import json
import sys
import os
import time
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text
from rich.align import Align

from utils.console import (
    ensure_utf8_output,
    CYAN, GREEN, RED, YELLOW, GRAY, RESET, BOLD, LINE_LEN
)

from utils.infra.session import SESSION_START_TIME

def format_status(status):
    if status == "PASSED": return f"{GREEN}[PASS]{RESET}"
    return f"{RED}[FAIL]{RESET}"

def fmt_with_chunks(text, chunks):
    """Adds (timestamp) markers to text based on chunk data."""
    if not chunks: return text
    out = []
    for c in chunks:
        out.append(f"{c['text']}({c['end']:.2f}s)")
    return "".join(out)

def report_llm_result(res_obj):
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def report_scenario_result(res_obj):
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def save_artifact(domain, data, session_dir=None):
    if not session_dir:
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(utils_dir))
        artifacts_dir = os.path.join(project_root, "tests", "artifacts")
    else:
        artifacts_dir = session_dir

    os.makedirs(artifacts_dir, exist_ok=True)
    file_path = os.path.join(artifacts_dir, f"{domain}.json")
    
    existing_data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except:
            existing_data = []
    
    new_loadouts = [d['loadout'] for d in data]
    combined_data = [d for d in existing_data if d['loadout'] not in new_loadouts]
    combined_data.extend(data)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, indent=4, ensure_ascii=False)

def trigger_report_generation(upload=True, session_dir=None):
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tests_dir = os.path.join(project_root, "tests")
        if tests_dir not in sys.path: sys.path.append(tests_dir)
        import generate_report
        return generate_report.generate_and_upload_report(
            session_dir=session_dir,
            upload_report=upload,
            upload_outputs=False,
            open_browser=True
        )
    except Exception as e:
        sys.stderr.write(f"⚠️ Auto-report failed: {e}\n"); return None

class LiveFilter(io.StringIO):
    """Captures everything to a buffer. It's intended that the dashboard pulls the raw logs from files."""
    def __init__(self):
        super().__init__()
        # Use the raw OS stdout to ensure we always have a path to the terminal
        self.out = sys.__stdout__ or sys.stdout

    @property
    def buffer(self):
        # Some libraries (like requests) expect a buffer attribute on stdout
        return self

    def write(self, s):
        # Silence all output to the real stdout while the dashboard is active.
        if isinstance(s, bytes):
            s = s.decode('utf-8', errors='replace')
        return super().write(s)

class RichDashboard:
    def __init__(self, plan_name, session_id="PENDING", system_info=None):
        # Force console to use the original stdout to bypass any redirections in worker threads
        self.console = Console(file=sys.__stdout__ or sys.stdout)
        self.plan_name = plan_name
        self.session_id = session_id
        self.system_info = system_info or {"host": {"gpu": "Detecting..."}}
        self.test_data = {}
        
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._session_path = None
        self.active_log_path = None
        
        self.overall_progress = Progress(
            TextColumn("[bold blue]{task.description}", justify="right"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "•",
            TextColumn("[bold cyan]{task.completed}/{task.total}"),
            "•",
            TextColumn("{task.fields[extra]}"),
        )
        self.boot_task = self.overall_progress.add_task("Booting / Pre-flight", total=5, extra="")
        self.overall_task = self.overall_progress.add_task("Total Scenarios", total=100, extra="")
        
        self.current_loadout = None
        self.active_log_path = None
        self.vram_usage = 0.0
        self.vram_total = 1.0
        self.ram_usage = 0.0
        self.ram_total = 1.0
        self.cpu_info = "Detecting..."
        self.recent_logs = []
        
        self._snapshot_path = None
        self._stop_event = threading.Event()
        self._snapshot_thread = None
        self._boot_start = time.perf_counter()
        self.boot_duration = 0

        # Use screen=False to allow the final frame to persist in the scrollback buffer.
        self.live = Live(self, console=self.console, refresh_per_second=4, screen=False, redirect_stdout=False)

    @property
    def snapshot_path(self):
        return self._snapshot_path

    @snapshot_path.setter
    def snapshot_path(self, path):
        self._snapshot_path = path
        # If we are already running and just got a path, start the thread
        if self._snapshot_path and self.live.is_started and not self._snapshot_thread:
            import threading
            self._stop_event = threading.Event()
            self._snapshot_thread = threading.Thread(target=self._snapshot_loop, daemon=True)
            self._snapshot_thread.start()

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
            lines.append(Text(f"- {d_name.upper()} [{d_status}] - {d_dur:.1f}s ({d_data['models_done']}/{len(d_data['loadouts'])} models)"))
            
            for l_name, l_data in d_data['loadouts'].items():
                l_status = l_data['status'].upper()
                stp = self.get_phase_time(l_data, "setup")
                exe = self.get_phase_time(l_data, "execution")
                cln = self.get_phase_time(l_data, "cleanup")
                
                l_line = Text(f"  > {l_name} [{l_status}] ({l_data['done']}/{l_data['total']})")
                l_line.append(f" - stp: {stp:.1f}s, exec: {exe:.1f}s, cln: {cln:.1f}s")
                if l_data.get('error_message'):
                    l_line.append(f" ERROR: {l_data['error_message']}", style="bold")
                lines.append(l_line)

        # System
        vram_pct = (self.vram_usage / self.vram_total) * 100 if self.vram_total > 0 else 0
        ram_pct = (self.ram_usage / self.ram_total) * 100 if self.ram_total > 0 else 0
        session_path = self._session_path or ""
        
        lines.append(Text(f"\nSYSTEM STATUS:", style="bold underline"))
        lines.append(Text(f"CPU: {self.cpu_info}"))
        lines.append(Text(f"RAM: {self.ram_usage:.1f}/{self.ram_total:.1f} GB ({ram_pct:.1f}%)"))
        lines.append(Text(f"VRAM: {self.vram_usage:.1f}/{self.vram_total:.1f} GB ({vram_pct:.1f}%)"))
        
        env = self.system_info.get('environment', {})
        lines.append(Text(f"HF Path: {env.get('HF_HOME', 'N/A')}"))
        lines.append(Text(f"OL Path: {env.get('OLLAMA_MODELS', 'N/A')}"))

        d = self.system_info.get('host', {}).get('docker', {})
        lines.append(Text(f"Docker: [{d.get('status', 'Missing')}], {d.get('version', 'N/A')}"))
        if d.get('root_dir') and d.get('root_dir') != 'N/A':
            lines.append(Text(f"  ↳ VL Docker Location: {d['root_dir']}"))
        
        o = self.system_info.get('host', {}).get('ollama', {})
        lines.append(Text(f"Ollama: [{o.get('status', 'Missing')}], {o.get('version', 'N/A')}"))
        
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

        # Calculate and update totals for progress bars
        total_scenarios = sum(d['total'] for d in self.test_data.values())

        # Reset task completed states and set new totals
        self.overall_progress.update(self.overall_task, total=total_scenarios, completed=0, visible=True)

    def finalize_boot(self, session_id=None, system_info=None, session_dir=None):
        if session_id: 
            self.session_id = session_id
        if session_dir:
            self._session_path = session_dir
        
        if system_info: 
            self.system_info = system_info
            host = system_info.get('host', {})
            self.vram_total = host.get('vram_total_gb', self.vram_total)
            self.vram_usage = host.get('vram_used_gb', self.vram_usage)
            self.ram_total = host.get('ram_total_gb', self.ram_total)
            self.ram_usage = host.get('ram_used_gb', self.ram_usage)
            self.cpu_info = host.get('cpu', self.cpu_info)

        self.boot_duration = time.perf_counter() - self._boot_start
        self.overall_progress.update(self.boot_task, completed=5, extra=f"({self.boot_duration:.1f}s)")

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

    def update_scenario(self, domain, loadout, scenario_name, status, result="", duration=0.0, scenario_dir=None):
        d_data = self.test_data.get(domain.lower())
        if not d_data: return
        l_data = d_data['loadouts'].get(loadout)
        if not l_data: return
        
        if not d_data.get('start_time'): d_data['start_time'] = time.perf_counter()
        
        l_data['done'] += 1
        d_data['done'] += 1
        
        # Update the specific scenario entry
        if 'scenarios' not in l_data: l_data['scenarios'] = {}
        l_data['scenarios'][scenario_name] = {
            "status": status,
            "duration": duration,
            "error": result,
            "dir": scenario_dir
        }
        
        # Accumulate duration for flat UI suites that don't use strict phase timers
        if 'timers' not in l_data: l_data['timers'] = {"stp": 0, "exec": 0, "cln": 0}
        l_data['timers']['exec'] += duration
        
        if status != "PASSED":
            l_data['errors'] += 1
            l_data['status'] = "failed"
            d_data['status'] = "failed"
            
            if not l_data.get('error_message'):
                l_data['error_message'] = result
        elif l_data['status'] in ["pending", "wip"]:
            l_data['status'] = "wip"
            d_data['status'] = "wip"

        total_done = sum(d['done'] for d in self.test_data.values())
        total_all = sum(d['total'] for d in self.test_data.values())
        self.overall_progress.update(self.overall_task, completed=total_done, total=total_all)

    def finalize_loadout(self, domain, loadout, duration, status="passed", error_message=""):
        d_data = self.test_data.get(domain.lower())
        if not d_data: return
        l_data = d_data['loadouts'].get(loadout)
        if not l_data: return
        
        old_phase = l_data.get('phase')
        if old_phase and old_phase in l_data['phase_starts']:
            dur = time.perf_counter() - l_data['phase_starts'][old_phase]
            key = "stp" if old_phase == "setup" else ("exec" if old_phase == "execution" else "cln")
            l_data['timers'][key] = dur

        l_data['duration'] = duration
        if l_data['status'] in ["pending", "wip"]:
            l_data['status'] = status
        l_data['error_message'] = error_message
        l_data['phase'] = None

    def finalize_domain(self, domain):
        d_data = self.test_data.get(domain.lower())
        if not d_data: return
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
        session_path = self._session_path or ""

        for d_name, d_data in self.test_data.items():
            d_status = d_data['status'].lower()
            d_color = "green" if d_status == "passed" else ("red" if d_status == "failed" else ("blue" if d_status == "wip" else "bright_black"))
            
            d_dur = d_data['duration'] or (time.perf_counter() - d_data['start_time'] if d_data['start_time'] else 0)
            
            # Aggregate timers for domain
            d_stp, d_exe, d_cln = 0, 0, 0
            for l_data in d_data['loadouts'].values():
                d_stp += self.get_phase_time(l_data, "setup")
                d_exe += self.get_phase_time(l_data, "execution")
                d_cln += self.get_phase_time(l_data, "cleanup")

            # Domain Row: NAME - TIME, (C/D scenarios) - stp: Xs, exec: Ys, cln: Zs
            d_text = Text.assemble(
                (f"• {d_name.upper()}", f"bold {d_color}"),
                (f" - {d_dur:.1f}s", d_color)
            )
            
            d_text.append(f" ({d_data['done']}/{d_data['total']} scenarios)", "white")
            d_text.append(f" - stp: {d_stp:.1f}s, exec: {d_exe:.1f}s, cln: {d_cln:.1f}s", "gray50")
            table.add_row(d_text)
            
            for l_name, l_data in d_data['loadouts'].items():
                l_status = l_data['status'].lower()
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
                        m_type = "llm" if any(x in m_lower for x in ["ollama", "vllm", "ol_", "vl_"]) else \
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

                # Add ALL scenarios as sub-items
                if 'scenarios' in l_data:
                    for s_id, s_data in l_data['scenarios'].items():
                        s_status = s_data.get('status', 'pending').lower()
                        s_color = "green" if s_status == "passed" else ("red" if s_status == "failed" else ("blue" if s_status == "wip" else "bright_black"))
                        
                        scen_text = Text("      • ")
                        scen_url = f"file:///{s_data['dir'].replace(os.sep, '/')}" if s_data.get('dir') else session_path
                        
                        # Just show the scenario ID part
                        display_id = s_id.split("/")[-1] if "/" in s_id else s_id
                        
                        if s_status == "failed":
                            scen_text.append(display_id, style=f"{s_color} link {scen_url}")
                            scen_text.append(f": {s_data.get('error', 'FAILED')}", style="gray50")
                        else:
                            scen_text.append(display_id, style=s_color)
                            if s_status == "passed":
                                scen_text.append(f" ({s_data.get('duration', 0):.1f}s)", style="gray50")
                        
                        table.add_row(scen_text)
        return table

    def make_layout(self):
        from rich.console import Group
        
        # 1. Header (Simple)
        header_text = Text.assemble(
            (f" JARVIS: ", "bold white on blue"),
            (f" {self.plan_name} ", "bold green on blue"),
            (f" | SESSION: ", "white on blue"),
            (f" {self.session_id} ", "bold yellow on blue"),
        )
        header_panel = Panel(Align.center(header_text), style="blue")

        # 2. Specs Section
        vram_usage = self.vram_usage
        vram_total = self.vram_total
        vram_pct = (vram_usage / vram_total) * 100 if vram_total > 0 else 0
        ram_pct = (self.ram_usage / self.ram_total) * 100 if self.ram_total > 0 else 0
        
        host = self.system_info.get('host', {})
        gpu_name = host.get('gpu', 'Detecting...')

        def fmt_svc(name, info):
            status = info.get('status', 'Missing')
            color = "green" if status == "On" else ("red" if status == "Missing" else "yellow")
            return Text.assemble((f"{name} - ", "bold"), (f"[{status}]", f"bold {color}"), (f", {info.get('version', 'N/A')}"))

        specs_text = Text.assemble(
            (f"GPU: ", "bold cyan"), (f"{gpu_name} "), 
            (f"({vram_usage:.1f}/{vram_total:.1f} GB VRAM)", "cyan"), ("\n"),
            (f"CPU: ", "bold white"), (f"{self.cpu_info}\n"),
            (f"RAM: ", "bold green"), (f"{self.ram_usage:.1f}/{self.ram_total:.1f} GB ({ram_pct:.1f}%)\n")
        )
        
        env = self.system_info.get('environment', {})
        specs_text.append(f"HF Path: ", style="bold magenta")
        specs_text.append(f"{env.get('HF_HOME', 'N/A')}\n")
        specs_text.append(f"OL Path: ", style="bold magenta")
        specs_text.append(f"{env.get('OLLAMA_MODELS', 'N/A')}\n")

        specs_text.append(fmt_svc("Docker", host.get('docker', {})))
        if host.get('docker', {}).get('root_dir') and host.get('docker', {}).get('root_dir') != 'N/A':
            specs_text.append(f"\n   ↳ VL Docker Location: ", style="gray70")
            specs_text.append(f"{host['docker']['root_dir']}", style="gray50")
        
        specs_text.append("\n")
        specs_text.append(fmt_svc("Ollama", host.get('ollama', {})))

        specs_panel = Panel(specs_text, title="Starting system snapshot", border_style="blue")
        
        # 3. Overall Status
        overall_panel = Panel(self.overall_progress, title="Overall Status", border_style="blue")
        
        # 4. Hierarchy
        hierarchy_panel = Panel(
            self.make_progress_view(),
            title="Execution Hierarchy (Click models to open log)",
            border_style="blue"
        )
        
        # 5. System Status (Condensed)
        session_path = self._session_path or ""
        file_url = f"file:///{session_path.replace(os.sep, '/')}"

        status_text = Text.assemble(
            (f"Active Loadout: ", "bold"),
            (f"{str(self.current_loadout or 'Idle'):<30}", "cyan"),
            (f" | Path: ", "bold"),
            (f"{session_path}", f"bright_black link {file_url}")
        )
        
        if hasattr(self, 'report_url') and self.report_url:
            url = self.report_url
            if not url.startswith("http"): url = f"file:///{url.replace(os.sep, '/')}"
            status_text.append("\n")
            status_text.append("📊 REPORT: ", style="bold green")
            status_text.append(self.report_url, style=f"underline green link {url}")

        system_panel = Panel(Align.left(status_text), title="Session Info", border_style="cyan")
        
        # 6. Model Log Tail
        log_content = ""
        if self.active_log_path and os.path.exists(self.active_log_path):
            try:
                with open(self.active_log_path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    size = f.tell()
                    to_read = min(size, 4096)
                    f.seek(size - to_read)
                    chunk = f.read(to_read).decode('utf-8', errors='ignore')
                    lines = chunk.splitlines()
                    log_content = "\n".join(lines[-18:])
            except: pass
        
        footer_panel = Panel(Text(log_content, style="bright_black"), title=f"Model Log: {os.path.basename(self.active_log_path or 'None')}", border_style="bright_black")
        
        # Don't show the massive log tail for UI tests (which tail timeline.log)
        if self.active_log_path and "timeline.log" in self.active_log_path:
            return Group(header_panel, specs_panel, overall_panel, hierarchy_panel, system_panel)
            
        return Group(header_panel, specs_panel, overall_panel, hierarchy_panel, system_panel, footer_panel)

    def start(self, snapshot_path=None): 
        if snapshot_path: 
            self.snapshot_path = snapshot_path # Trigger property setter
        
        import sys
        sys.dashboard_active = True
        self.live.start()

    def stop(self):
        import sys
        sys.dashboard_active = False
        
        if self._stop_event:
            self._stop_event.set()
        self.live.stop()
        # Final snapshot
        self.save_snapshot()

class GDriveAssetManager:
    def __init__(self, service):
        self.service = service
        self.folders = {} # Path -> ID
        self.file_cache = {} # folder_id -> {filename: link}

    def get_folder_id(self, name, parent_id=None):
        """Creates or finds a folder by name under an optional parent."""
        cache_key = f"{parent_id or 'root'}/{name}"
        if cache_key in self.folders: return self.folders[cache_key]
        
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id: query += f" and '{parent_id}' in parents"
        else: query += " and 'root' in parents"
        
        results = self.service.files().list(q=query, fields='files(id, webViewLink)').execute()
        files = results.get('files', [])
        if not files:
            meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
            if parent_id: meta['parents'] = [parent_id]
            folder = self.service.files().create(body=meta, fields='id, webViewLink').execute()
            fid, link = folder.get('id'), folder.get('webViewLink')
        else:
            fid, link = files[0].get('id'), files[0].get('webViewLink')
        
        self.folders[cache_key] = fid
        self.folders[f"{cache_key}_link"] = link
        return fid

    def get_folder_link(self, name, parent_id=None):
        self.get_folder_id(name, parent_id)
        return self.folders.get(f"{parent_id or 'root'}/{name}_link")

    def preload_folder(self, folder_id):
        if folder_id in self.file_cache: return self.file_cache[folder_id]
        print(f"🔍 Pre-loading GDrive manifest for folder {folder_id}...")
        results = []
        page_token = None
        while True:
            res = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(name, webViewLink)",
                pageToken=page_token
            ).execute()
            results.extend(res.get('files', []))
            page_token = res.get('nextPageToken')
            if not page_token: break
        mapping = {f['name']: f['webViewLink'] for f in results}
        self.file_cache[folder_id] = mapping
        return mapping

    def sync_file(self, local_path, folder_id, overwrite=True):
        if not local_path or not os.path.exists(local_path): return None
        file_name = os.path.basename(local_path)
        cache = self.file_cache.get(folder_id, {})
        if file_name in cache and not overwrite: return cache[file_name]
        
        from googleapiclient.http import MediaFileUpload
        ext = os.path.splitext(file_name)[1].lower()
        mimetype = 'application/octet-stream'
        if ext in ['.wav', '.mp3']: mimetype = 'audio/mpeg' if ext == '.mp3' else 'audio/wav'
        elif ext in ['.png', '.jpg', '.jpeg']: mimetype = 'image/png' if ext == '.png' else 'image/jpeg'
        elif ext in ['.mp4']: mimetype = 'video/mp4'
        media = MediaFileUpload(local_path, mimetype=mimetype, resumable=True)
        
        import threading
        if not hasattr(self, '_api_lock'): self._api_lock = threading.Lock()
        
        with self._api_lock:
            meta = {'name': file_name, 'parents': [folder_id]}
            created = self.service.files().create(body=meta, media_body=media, fields='webViewLink').execute()
            link = created.get('webViewLink')
            if folder_id not in self.file_cache: self.file_cache[folder_id] = {}
            self.file_cache[folder_id][file_name] = link
            return link

    def batch_upload(self, local_paths, folder_id, label="artifacts", max_workers=10):
        if not local_paths: return {}
        cache = self.preload_folder(folder_id)
        to_upload = [p for p in local_paths if os.path.basename(p) not in cache]
        if not to_upload:
            print(f"✅ All {label} already exist on GDrive.")
            return cache
        print(f"🚀 Uploading {len(to_upload)} new {label} in parallel...")
        def upload_one(path):
            try: return path, self.sync_file(path, folder_id, overwrite=False)
            except Exception as e:
                print(f"  ❌ Failed to upload {os.path.basename(path)}: {e}"); return path, None
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(upload_one, to_upload))
        for path, link in results:
            if link: cache[os.path.basename(path)] = link
        return cache
