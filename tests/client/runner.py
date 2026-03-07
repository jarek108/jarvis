import os
import sys
import time
import asyncio
import argparse
import threading
import yaml
import json
from loguru import logger
from typing import Any, Optional, Dict, List
from dataclasses import dataclass, asdict

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

from ui import JarvisApp
import utils
from test_utils import init_session, BOLD, GREEN, RED, YELLOW, RESET, LINE_LEN
from test_utils.scenarios import load_scenarios_from_sources

# --- Optional Dependencies ---
try:
    import mss
    import PIL.Image
except ImportError:
    mss = PIL = None

@dataclass
class TestResult:
    id: str
    name: str
    status: str
    duration: float
    error: Optional[str] = None

class StatusDumper:
    """Extracts shallow state snapshots from the UI and Backend Controller."""
    def __init__(self, app: JarvisApp):
        self.app = app

    def get_ui_text(self, target_path: str) -> str:
        """Extracts text from a specific widget path."""
        start_t = time.perf_counter()
        widget = self._resolve_widget(target_path)
        if not widget: return "WIDGET_NOT_FOUND"
        
        text = ""
        try:
            if hasattr(widget, "get") and hasattr(widget, "index"): # Textbox
                text = widget.get("1.0", "end-1c").strip()
            elif hasattr(widget, "cget"): # Label / Button / Frame
                text = str(widget.cget("text"))
            
            # Expanded fallback for CustomTkinter widgets with variables
            if not text:
                for var_attr in ["_variable", "variable", "_var"]:
                    if hasattr(widget, var_attr):
                        var = getattr(widget, var_attr)
                        if hasattr(var, "get"):
                            text = str(var.get())
                            break
        except: pass
        
        latency = (time.perf_counter() - start_t) * 1000
        if latency > 5.0:
            logger.warning(f"⚠️ Slow UI Dump: {latency:.2f}ms for '{target_path}'")
        return text

    def get_system_snapshot(self) -> Dict[str, Any]:
        """Captures the controller's internal health and runnability state."""
        ctrl = self.app.controller
        self.app.update_idletasks()
        self.app.update()
        return {
            "loadout": ctrl.current_loadout,
            "pipeline": ctrl.current_pipeline,
            "runnable": ctrl.runnability.get("runnable", False),
            "health_summary": {p: s['status'] for p, s in ctrl.health_state.items()},
            "is_maximized": self.app.state() == "zoomed",
            "spinner_active": self.app.loading_spinner.is_running,
            "geometry": self.app.geometry(),
            "state": self.app.state(),
            "x": self.app.winfo_x(),
            "y": self.app.winfo_y(),
            "vram_breakdown_visible": self.app.vram_monitor.v_lbl_ext_part.winfo_viewable()
        }

    def _resolve_widget(self, path: str) -> Optional[Any]:
        """Maps a string path like 'loadout_opt' to an actual object."""
        mapping = {
            "loadout_opt": self.app.loadout_opt,
            "pipe_opt": self.app.pipe_opt,
            "record_btn": self.app.record_btn,
            "terminal": self.app.terminal,
            "mode_label": self.app.mode_label
        }
        return mapping.get(path)

class VisualVerifier:
    """Handles window-specific screenshot captures."""
    def __init__(self, app: JarvisApp, session_dir: str):
        self.app = app
        self.session_dir = session_dir
        self.current_scenario_id = "unknown"

    def capture_window(self, filename: str):
        """Captures the exact bounding box of the app window."""
        if not mss or not PIL: return

        self.app.update_idletasks()
        self.app.update()

        x, y = self.app.winfo_rootx(), self.app.winfo_rooty()
        w, h = self.app.winfo_width(), self.app.winfo_height()

        with mss.mss() as sct:
            monitor = {"top": y, "left": x, "width": w, "height": h}
            sct_img = sct.grab(monitor)
            img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            img_dir = os.path.join(self.session_dir, "images")
            os.makedirs(img_dir, exist_ok=True)
            
            # Prefix with scenario ID to prevent collisions
            prefixed_name = f"{self.current_scenario_id}_{filename}"
            out_path = os.path.join(img_dir, prefixed_name)
            img.save(out_path, quality=85)
            logger.info(f"📸 Screenshot saved: {out_path}")

    def capture_desktop(self, filename: str):
        """Captures the entire primary monitor."""
        if not mss or not PIL: return

        with mss.mss() as sct:
            # monitors[0] is all monitors, monitors[1] is the primary
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            img_dir = os.path.join(self.session_dir, "images")
            os.makedirs(img_dir, exist_ok=True)
            
            prefixed_name = f"{self.current_scenario_id}_desktop_{filename}"
            out_path = os.path.join(img_dir, prefixed_name)
            img.save(out_path, quality=85)
            logger.info(f"🖥️  Desktop Screenshot saved: {out_path}")

class AutomationController:
    """Simulates deterministic human actions against UI widgets."""
    def __init__(self, app: JarvisApp):
        self.app = app

    def click(self, target_path: str):
        widget = self._resolve_widget(target_path)
        if hasattr(widget, "invoke"):
            logger.info(f"🖱️  Invoking click on '{target_path}'")
            widget.invoke()
        else:
            logger.error(f"❌ Cannot click non-invocable widget '{target_path}'")

    def maximize(self):
        logger.info("🔲 Maximizing window")
        self.app.state("zoomed")
        self.app.update_idletasks()
        self.app.update()

    def select_dropdown(self, target_path: str, value: str):
        if target_path == "loadout_opt":
            logger.info(f"🔽 Selecting Loadout: '{value}'")
            self.app.loadout_var.set(value)
            self.app.on_loadout_change(value)
        elif target_path == "pipe_opt":
            logger.info(f"🔽 Selecting Pipeline: '{value}'")
            self.app.pipe_var.set(value)
            self.app.on_config_change(value)

    def _resolve_widget(self, path: str) -> Optional[Any]:
        return StatusDumper(self.app)._resolve_widget(path)

class ClientTestRunner:
    def __init__(self, args, session_dir: str):
        self.args = args
        self.session_dir = session_dir
        self.app = None
        self.automation = None
        self.dumper = None
        self.visual = None
        self.is_running = True
        self.start_time = 0
        self.results: List[TestResult] = []

    async def run_scenario(self, scenario_id: str, scenario_data: Dict[str, Any]) -> bool:
        logger.info(f"🎬 Starting Scenario: {scenario_data.get('name', scenario_id)}")
        self.is_running = True
        
        self.app = JarvisApp()
        self.automation = AutomationController(self.app)
        self.dumper = StatusDumper(self.app)
        self.visual = VisualVerifier(self.app, self.session_dir)
        self.visual.current_scenario_id = scenario_id
        
        self.start_time = time.perf_counter()
        
        timeline = scenario_data.get('timeline', [])
        # Normalize timestamps
        for step in timeline:
            if isinstance(step['t'], str): step['t'] = float(step['t'].replace('s', ''))
            
        step_idx = 0
        scenario_success = True
        error_msg = None
        
        try:
            while self.is_running:
                try:
                    self.app.update_idletasks()
                    self.app.update()
                except:
                    logger.info("👋 Window closed. Terminating scenario.")
                    break
                
                elapsed = time.perf_counter() - self.start_time
                
                if step_idx < len(timeline):
                    step = timeline[step_idx]
                    if elapsed >= step['t']:
                        step_success, step_error = await self.execute_action(step)
                        if not step_success:
                            scenario_success = False
                            error_msg = step_error
                            if self.args.fail_fast:
                                self.is_running = False
                                break
                        step_idx += 1
                elif elapsed > (timeline[-1]['t'] if timeline else 0) + 1.0:
                    self.is_running = False
                
                await asyncio.sleep(0.01)
        except Exception as e:
            scenario_success = False
            error_msg = str(e)
            logger.error(f"💥 Scenario execution failed: {e}")
        finally:
            duration = time.perf_counter() - self.start_time
            self.results.append(TestResult(
                id=scenario_id,
                name=scenario_data.get('name', scenario_id),
                status="PASSED" if scenario_success else "FAILED",
                duration=duration,
                error=error_msg
            ))
            self.cleanup()
            
        return scenario_success

    async def execute_action(self, step: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        action = step.get('action')
        target = step.get('target')
        value = step.get('value')
        
        try:
            if action == "select_dropdown":
                self.automation.select_dropdown(target, value)
            elif action == "click_element":
                self.automation.click(target)
            elif action == "maximize_window":
                self.automation.maximize()
            elif action == "take_screenshot":
                self.visual.capture_window(step.get('file', 'test_snap.jpg'))
            elif action == "take_desktop_screenshot":
                self.visual.capture_desktop(step.get('file', 'desktop_snap.jpg'))
            elif action == "assert_ui_text":
                actual = self.dumper.get_ui_text(target)
                contains = step.get('contains', '')
                if contains in actual:
                    logger.info(f"✅ Assertion Passed: '{target}' contains '{contains}'")
                else:
                    err = f"Assertion Failed: '{target}' (Actual: {actual or 'EMPTY'}) does not contain '{contains}'"
                    logger.error(f"❌ {err}")
                    return False, err
            elif action == "assert_system_state":
                snap = self.dumper.get_system_snapshot()
                cond = step.get('condition')
                h = snap['health_summary']
                
                success = False
                if cond == "all_models_active":
                    success = all(s == "ON" or s == "BUSY" for s in h.values()) and len(h) > 0
                elif cond == "no_models_active":
                    success = len(h) == 0
                elif cond == "models_loading":
                    success = any(s == "STARTUP" for s in h.values())
                elif cond == "any_models_active":
                    success = len(h) > 0

                if success: 
                    logger.info(f"✅ System State: {cond}")
                else:
                    err = f"System State Condition '{cond}' failed. Health: {h}"
                    logger.error(f"❌ {err}")
                    return False, err
            elif action == "assert_ux_state":
                snap = self.dumper.get_system_snapshot()
                cond = step.get('condition')
                
                success = False
                if cond == "spinner_active":
                    success = snap['spinner_active']
                elif cond == "spinner_inactive":
                    success = not snap['spinner_active']
                elif cond == "maximized":
                    success = snap['is_maximized']
                elif cond == "stable_maximized":
                    # Maximized on Windows usually means state is zoomed AND top-left is at (0,0) or slightly negative
                    success = snap['is_maximized'] and snap['x'] <= 0 and snap['y'] <= 0
                elif cond == "not_maximized":
                    success = not snap['is_maximized']
                elif cond == "vram_breakdown_visible":
                    success = snap['vram_breakdown_visible']
                elif cond == "vram_breakdown_hidden":
                    success = not snap['vram_breakdown_visible']

                if success: 
                    logger.info(f"✅ UX State: {cond}")
                else:
                    err = f"UX State Condition '{cond}' failed. Snapshot: {snap}"
                    logger.error(f"❌ {err}")
                    return False, err
            return True, None
        except Exception as e:
            return False, str(e)

    def cleanup(self):
        if self.app:
            try:
                if hasattr(self.app, "on_closing"):
                    self.app.on_closing()
                else:
                    self.app.destroy()
            except: pass

    def print_summary(self):
        print(f"\n{BOLD}JARVIS CLIENT TEST SUMMARY{RESET}")
        print("-" * LINE_LEN)
        print(f"{'Scenario ID':<40} | {'Status':<10} | {'Time':<8}")
        print("-" * LINE_LEN)
        
        total_passed = 0
        for r in self.results:
            color = GREEN if r.status == "PASSED" else RED
            if r.status == "PASSED": total_passed += 1
            print(f"{r.id:<40} | {color}{r.status:<10}{RESET} | {r.duration:>6.1f}s")
            if r.error:
                print(f"   {YELLOW}↳ Error: {r.error}{RESET}")

        print("-" * LINE_LEN)
        final_color = GREEN if total_passed == len(self.results) else RED
        print(f"OVERALL: {final_color}{total_passed}/{len(self.results)} PASSED{RESET} | Session: {os.path.basename(self.session_dir)}")
        
        # Save JSON report
        report_path = os.path.join(self.session_dir, "client_report.json")
        with open(report_path, "w") as f:
            json.dump([asdict(r) for r in self.results], f, indent=2)

async def main():
    parser = argparse.ArgumentParser(description="Jarvis Client UI Test Runner")
    parser.add_argument("plan", type=str, help="Path to a Plan YAML.")
    parser.add_argument("--mock-all", action="store_true", help="Alias for --mock-models and --mock-edge")
    parser.add_argument("--mock-models", action="store_true", help="Use fast stub models")
    parser.add_argument("--mock-edge", action="store_true", help="Bypass physical hardware")
    parser.add_argument("--fail-fast", action="store_true", help="Stop execution on first failure.")
    parser.add_argument("--keep-alive", action="store_true", help="Skip initial backend cleanup.")
    args = parser.parse_args()

    if args.mock_all:
        args.mock_models = True
        args.mock_edge = True

    plan_path = utils.resolve_path(args.plan)
    with open(plan_path, 'r') as f:
        plan_data = yaml.safe_load(f)

    if 'scenarios' not in plan_data:
        raise ValueError(f"Invalid Client Plan: '{plan_path}' missing 'scenarios' block.")

    # Initialize Session
    session_dir, session_id = init_session(plan_path, prefix="CLIENT_RUN_")
    
    # Pre-test backend cleanup
    if not args.keep_alive:
        from manage_loadout import kill_loadout
        kill_loadout("all")
    
    if args.mock_all: os.environ['JARVIS_MOCK_ALL'] = "1"
    if args.mock_models: os.environ['JARVIS_MOCK_MODELS'] = "1"
    if args.mock_edge: os.environ['JARVIS_MOCK_EDGE'] = "1"

    runner = ClientTestRunner(args, session_dir)
    
    # Resolve Scenarios from sources
    sources = plan_data.get('scenario_sources', ["client_ui.yaml"])
    all_scenarios = load_scenarios_from_sources(project_root, "client", sources)

    # Execute
    for item in plan_data['scenarios']:
        sid = item['id']
        if sid in all_scenarios:
            sdata = all_scenarios[sid]
            success = await runner.run_scenario(sid, sdata)
            if not success and args.fail_fast:
                break
        else:
            logger.error(f"Scenario '{sid}' not found in sources {sources}")

    runner.print_summary()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
