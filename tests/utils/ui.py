import sys
import io
import time
import os
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text
from rich.align import Align

# --- SHARED UI CONSTANTS ---
CYAN = "\033[96m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
LINE_LEN = 120

def ensure_utf8_output():
    """Forces UTF-8 for console output on Windows to prevent UnicodeEncodeErrors."""
    if sys.platform == "win32":
        if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        if not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8':
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class LiveFilter(io.StringIO):
    """Captures everything to a buffer. It's intended that the dashboard pulls the raw logs from files."""
    def __init__(self):
        super().__init__()
        ensure_utf8_output()
        self.out = sys.stdout # The original stdout

    def write(self, s):
        # We don't write anything to self.out here, as it's intended to be completely silent.
        # The dashboard reads from the log files.
        return super().write(s)

def fmt_with_chunks(text, chunks):
    """Adds (timestamp) markers to text based on chunk data."""
    if not chunks: return text
    out = []
    for c in chunks:
        out.append(f"{c['text']}({c['end']:.2f}s)")
    return "".join(out)

class RichDashboard:
    def __init__(self, plan_name, session_id, system_info):
        self.console = Console()
        self.plan_name = plan_name
        self.session_id = session_id
        self.system_info = system_info
        self.test_data = {}
        
        self.overall_progress = Progress(
            TextColumn("[bold blue]{task.description}", justify="right"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "•",
            TextColumn("[bold cyan]{task.completed}/{task.total}"),
            "•",
            TimeElapsedColumn(),
        )
        self.overall_task = self.overall_progress.add_task("Total Scenarios", total=100)
        self.models_task = self.overall_progress.add_task("Total Models   ", total=100)
        
        self.current_loadout = None
        self.active_log_path = None
        self.vram_usage = 0.0
        self.vram_total = 1.0
        self.recent_logs = []
        
        self.snapshot_path = None
        self._stop_event = None
        self._snapshot_thread = None

        # Use screen=False to allow the final frame to persist in the scrollback buffer
        self.live = Live(self, console=self.console, refresh_per_second=4, screen=False)

    def __rich__(self) -> Layout:
        return self.make_layout()

    def make_clean_layout(self):
        """Pure text hierarchical view for progression.log (human readable)."""
        from rich.console import Group
        lines = [Text(f"JARVIS TEST SESSION: {self.session_id}", style="bold")]
        lines.append(Text(f"PLAN: {self.plan_name}\n"))
        
        lines.append(Text("EXECUTION HIERARCHY:", style="bold underline"))
        for d_name, d_data in self.test_data.items():
            d_status = d_data['status'].upper()
            d_dur = d_data['duration'] or (time.perf_counter() - d_data['start_time'] if d_data['start_time'] else 0)
            lines.append(Text(f"â€¢ {d_name.upper()} [{d_status}] - {d_dur:.1f}s ({d_data['models_done']}/{len(d_data['loadouts'])} models)"))
            
            for l_name, l_data in d_data['loadouts'].items():
                l_status = l_data['status'].upper()
                stp = self.get_phase_time(l_data, "setup")
                exe = self.get_phase_time(l_data, "execution")
                cln = self.get_phase_time(l_data, "cleanup")
                
                l_line = Text(f"  âž¤ {l_name} [{l_status}] ({l_data['done']}/{l_data['total']})")
                l_line.append(f" - stp: {stp:.1f}s, exec: {exe:.1f}s, cln: {cln:.1f}s")
                if l_data.get('error_message'):
                    l_line.append(f" ERROR: {l_data['error_message']}", style="bold")
                lines.append(l_line)

        # System
        vram_pct = (self.vram_usage / self.vram_total) * 100 if self.vram_total > 0 else 0
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        session_path = os.path.join(project_root, "tests", "logs", self.session_id)
        
        lines.append(Text(f"\nSYSTEM STATUS:", style="bold underline"))
        lines.append(Text(f"VRAM: {self.vram_usage:.1f}/{self.vram_total:.1f} GB ({vram_pct:.1f}%)"))
        lines.append(Text(f"Path: {session_path}"))
        
        if hasattr(self, 'report_url') and self.report_url:
            lines.append(Text(f"REPORT: {self.report_url}"))

        return Group(*lines)

    def save_snapshot(self, path=None):
        """Dumps current dashboard state to a file (Truly clean text)."""
        target = path or self.snapshot_path
        if not target: return

        # Use a console with color_system=None to strip ANSI but KEEP the structure
        capture_console = Console(width=LINE_LEN, force_terminal=False, color_system=None)
        with capture_console.capture() as capture:
            capture_console.print(self.make_clean_layout())
        
        content = capture.get()
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
        except: pass

    def _snapshot_loop(self):
        import time
        while not self._stop_event.is_set():
            self.save_snapshot()
            time.sleep(2.0)

    def init_plan_structure(self, structure):
        self.test_data = structure

    def update_phase(self, domain, loadout, phase, status="wip"):
        d_data = self.test_data.get(domain.lower())
        if not d_data: return
        l_data = d_data['loadouts'].get(loadout)
        if not l_data: return
        
        # Special signal for log file paths: log_path:type:path
        if phase.startswith("log_path:"):
            parts = phase.split(":", 2)
            if len(parts) == 3:
                svc_type, path = parts[1], parts[2]
                if 'log_paths' not in l_data: l_data['log_paths'] = {}
                l_data['log_paths'][svc_type] = path
                self.active_log_path = path
            return

        if 'timers' not in l_data:
            l_data['timers'] = {"stp": 0, "exec": 0, "cln": 0}
            l_data['phase_starts'] = {}

        if l_data.get('phase') == phase and status == "wip":
            return

        old_phase = l_data.get('phase')
        if old_phase and old_phase in l_data['phase_starts']:
            dur = time.perf_counter() - l_data['phase_starts'][old_phase]
            key = "stp" if old_phase == "setup" else ("exec" if old_phase == "execution" else "cln")
            l_data['timers'][key] = dur

        l_data['phase'] = phase
        l_data['phase_starts'][phase] = time.perf_counter()

        if l_data['status'] != "failed":
            l_data['status'] = status
        if status == "wip" and not d_data['start_time']:
            d_data['start_time'] = time.perf_counter()
        if d_data['status'] != "failed":
            d_data['status'] = status

    def update_scenario(self, domain, loadout, scenario_name, status):
        d_data = self.test_data.get(domain.lower())
        l_data = d_data['loadouts'].get(loadout)
        l_data['done'] += 1
        d_data['done'] += 1
        if status != "PASSED":
            l_data['errors'] += 1
            l_data['status'] = "failed"
            d_data['status'] = "failed"
        
        total_done = sum(d['done'] for d in self.test_data.values())
        total_all = sum(d['total'] for d in self.test_data.values())
        self.overall_progress.update(self.overall_task, completed=total_done, total=total_all)

    def finalize_loadout(self, domain, loadout, duration, status="passed", error_message=""):
        d_data = self.test_data.get(domain.lower())
        l_data = d_data['loadouts'].get(loadout)
        
        old_phase = l_data.get('phase')
        if old_phase and old_phase in l_data['phase_starts']:
            dur = time.perf_counter() - l_data['phase_starts'][old_phase]
            key = "stp" if old_phase == "setup" else ("exec" if old_phase == "execution" else "cln")
            l_data['timers'][key] = dur

        l_data['duration'] = duration
        if l_data['status'] == "wip": # Only update if not already failed
            l_data['status'] = status
        l_data['error_message'] = error_message
        l_data['phase'] = None
        d_data['models_done'] += 1
        
        total_models_done = sum(d['models_done'] for d in self.test_data.values())
        total_models_all = sum(len(d['loadouts']) for d in self.test_data.values())
        self.overall_progress.update(self.models_task, completed=total_models_done, total=total_models_all)

    def finalize_domain(self, domain):
        d_data = self.test_data.get(domain.lower())
        if d_data['start_time']:
            d_data['duration'] = time.perf_counter() - d_data['start_time']
        if d_data['status'] == "wip":
            d_data['status'] = "passed"

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.recent_logs.append(f"[{timestamp}] {message}")
        if len(self.recent_logs) > 8:
            self.recent_logs.pop(0)

    def get_phase_time(self, l_data, phase):
        if 'timers' not in l_data: return 0
        current_phase = l_data.get('phase')
        # If it's the active phase, return live time + already recorded time
        if current_phase == phase:
            return l_data['timers'].get(phase == "setup" and "stp" or (phase == "execution" and "exec" or "cln"), 0) + (time.perf_counter() - l_data['phase_starts'][phase])
        key = "stp" if phase == "setup" else ("exec" if phase == "execution" else "cln")
        return l_data['timers'].get(key, 0)

    def make_progress_view(self):
        """Renders the hierarchical domain/model list with clickable log links."""
        table = Table.grid(padding=(0, 1), expand=True)
        
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        session_path = os.path.join(project_root, "tests", "logs", self.session_id)

        for d_name, d_data in self.test_data.items():
            d_status = d_data['status']
            d_color = "green" if d_status == "passed" else ("red" if d_status == "failed" else ("blue" if d_status == "wip" else "bright_black"))
            d_dur = d_data['duration'] or (time.perf_counter() - d_data['start_time'] if d_data['start_time'] else 0)
            
            # Aggregate timers for domain
            d_stp, d_exe, d_cln = 0, 0, 0
            for l_data in d_data['loadouts'].values():
                d_stp += self.get_phase_time(l_data, "setup")
                d_exe += self.get_phase_time(l_data, "execution")
                d_cln += self.get_phase_time(l_data, "cleanup")

            # Domain Row: NAME - TIME, (A/B models) (C/D scenarios) - stp: Xs, exec: Ys, cln: Zs
            models_total = len(d_data['loadouts'])
            d_text = Text.assemble(
                (f"• {d_name.upper()}", f"bold {d_color}"),
                (f" - {d_dur:.1f}s", d_color),
                (f" ({d_data['models_done']}/{models_total} models)", "white"),
                (f" ({d_data['done']}/{d_data['total']} scenarios)", "white"),
                (f" - stp: {d_stp:.1f}s, exec: {d_exe:.1f}s, cln: {d_cln:.1f}s", "gray50")
            )
            table.add_row(d_text)
            
            for l_name, l_data in d_data['loadouts'].items():
                l_status = l_data['status']
                l_color = "green" if l_status == "passed" else ("red" if l_status == "failed" else ("blue" if l_status == "wip" else "bright_black"))
                stp = self.get_phase_time(l_data, "setup")
                exe = self.get_phase_time(l_data, "execution")
                cln = self.get_phase_time(l_data, "cleanup")
                
                # Model Row: Indented
                l_text = Text("   ➤ ")
                
                # Split multi-model names (e.g., STT + LLM + TTS)
                models = l_data.get('models', [l_name])
                log_paths = l_data.get('log_paths', {})
                
                for i, m in enumerate(models):
                    if i > 0: l_text.append(" + ", style="white")
                    
                    if l_status == "pending":
                        l_text.append(m, style=l_color)
                    else:
                        m_lower = m.lower()
                        m_type = "llm" if any(x in m_lower for x in ["ol_", "vl_", "vllm:"]) else \
                                 ("stt" if "whisper" in m_lower else \
                                 ("tts" if "chatterbox" in m_lower else None))
                        
                        target_path = log_paths.get(m_type) or log_paths.get("sts") or session_path
                        url = f"file:///{target_path.replace(os.sep, '/')}"
                        l_text.append(m, style=f"{l_color} link {url}")

                l_text.append(f" ({l_data['done']}/{l_data['total']})", style="white")
                l_text.append(f" - stp: {stp:.1f}s, exec: {exe:.1f}s, cln: {cln:.1f}s", style="gray70")
                
                if l_status == "passed":
                    l_text.append(" [PASSED]", style="bold green")
                elif l_data.get('error_message'):
                    l_text.append(f" [{l_data['error_message']}]", style="bold red")
                elif l_status == "failed" or l_data.get('errors', 0) > 0:
                    l_text.append(f" [{l_data['errors']} FAILED]", style="bold red")
                table.add_row(l_text)
        return table

    def make_layout(self):
        from rich.console import Group
        
        # 1. Header
        host = self.system_info['host']
        header_text = Text.assemble(
            (f" JARVIS: ", "bold white on blue"),
            (f" {self.plan_name} ", "bold green on blue"),
            (f" | SESSION: ", "white on blue"),
            (f" {self.session_id} ", "bold yellow on blue"),
            (f" | GPU: ", "white on blue"),
            (f" {host['gpu']} ", "bold cyan on blue"),
        )
        header_panel = Panel(Align.center(header_text), style="blue")
        
        # 2. Overall Status
        overall_panel = Panel(self.overall_progress, title="Overall Status", border_style="blue")
        
        # 3. Hierarchy
        hierarchy_panel = Panel(
            self.make_progress_view(),
            title="Execution Hierarchy (Click models to open log)",
            border_style="blue"
        )
        
        # 4. System Status
        vram_pct = (self.vram_usage / self.vram_total) * 100 if self.vram_total > 0 else 0
        vram_color = "green" if vram_pct < 70 else ("yellow" if vram_pct < 90 else "red")
        
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        session_path = os.path.join(project_root, "tests", "logs", self.session_id)
        file_url = f"file:///{session_path.replace(os.sep, '/')}"

        vram_text = Text.assemble(
            (f"VRAM: ", "bold"),
            (f"{self.vram_usage:.1f}/{self.vram_total:.1f} GB ({vram_pct:.1f}%) ", vram_color),
            (f" | Active: ", "bold"),
            (f"{str(self.current_loadout or 'Idle'):<30}", "cyan"),
            (f" | Path: ", "bold"),
            (f"{session_path}", f"bright_black link {file_url}")
        )
        
        if hasattr(self, 'report_url') and self.report_url:
            url = self.report_url
            if not url.startswith("http"): url = f"file:///{url.replace(os.sep, '/')}"
            vram_text.append("\n")
            vram_text.append("📊 REPORT: ", style="bold green")
            vram_text.append(self.report_url, style=f"underline green link {url}")

        system_panel = Panel(Align.left(vram_text), title="System Status", border_style="cyan")
        
        # 5. Model Log Tail
        log_content = ""
        if self.active_log_path and os.path.exists(self.active_log_path):
            try:
                with open(self.active_log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    log_content = "".join(lines[-18:])
            except: pass
        
        footer_panel = Panel(Text(log_content, style="bright_black"), title=f"Model Log: {os.path.basename(self.active_log_path or 'None')}", border_style="bright_black")
        
        return Group(header_panel, overall_panel, hierarchy_panel, system_panel, footer_panel)

    def start(self, snapshot_path=None): 
        self.snapshot_path = snapshot_path
        if self.snapshot_path:
            import threading
            self._stop_event = threading.Event()
            self._snapshot_thread = threading.Thread(target=self._snapshot_loop, daemon=True)
            self._snapshot_thread.start()

        # self.console.clear() # Removed to prevent scrollback corruption
        self.live.start()

    def stop(self):
        if self._stop_event:
            self._stop_event.set()
        self.live.stop()
        # Final snapshot
        self.save_snapshot()
