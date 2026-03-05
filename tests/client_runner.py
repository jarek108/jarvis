import os
import sys
import time
import asyncio
import argparse
import threading
import yaml
from loguru import logger
from typing import Any, Optional, Dict, List

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

from ui import JarvisApp
import utils

# --- Optional Dependencies ---
try:
    import mss
    import PIL.Image
except ImportError:
    mss = PIL = None

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
        return {
            "loadout": ctrl.current_loadout,
            "pipeline": ctrl.current_pipeline,
            "runnable": ctrl.runnability.get("runnable", False),
            "health_summary": {p: s['status'] for p, s in ctrl.health_state.items()}
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
    def __init__(self, app: JarvisApp):
        self.app = app

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
            
            os.makedirs("logs/visual_tests", exist_ok=True)
            out_path = os.path.join("logs/visual_tests", filename)
            img.save(out_path, quality=85)
            logger.info(f"📸 Screenshot saved: {out_path}")

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
    def __init__(self, args):
        self.args = args
        self.app = None
        self.automation = None
        self.dumper = None
        self.visual = None
        self.is_running = True
        self.start_time = 0
        self.results = []

    async def run_scenario(self, scenario_data: Dict[str, Any]):
        logger.info(f"🎬 Starting Scenario: {scenario_data.get('name', 'Unnamed')}")
        self.is_running = True
        
        self.app = JarvisApp()
        self.automation = AutomationController(self.app)
        self.dumper = StatusDumper(self.app)
        self.visual = VisualVerifier(self.app)
        self.start_time = time.perf_counter()
        
        timeline = scenario_data.get('timeline', [])
        # Normalize timestamps
        for step in timeline:
            if isinstance(step['t'], str): step['t'] = float(step['t'].replace('s', ''))
            
        step_idx = 0
        
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
                        await self.execute_action(step)
                        step_idx += 1
                elif elapsed > (timeline[-1]['t'] if timeline else 0) + 1.0:
                    self.is_running = False
                
                await asyncio.sleep(0.01)
        finally:
            self.cleanup()

    async def execute_action(self, step: Dict[str, Any]):
        action = step.get('action')
        target = step.get('target')
        value = step.get('value')
        
        if action == "select_dropdown":
            self.automation.select_dropdown(target, value)
        elif action == "click_element":
            self.automation.click(target)
        elif action == "take_screenshot":
            self.visual.capture_window(step.get('file', 'test_snap.jpg'))
        elif action == "assert_ui_text":
            actual = self.dumper.get_ui_text(target)
            contains = step.get('contains', '')
            if contains in actual:
                logger.info(f"✅ Assertion Passed: '{target}' contains '{contains}'")
            else:
                display_actual = f"'{actual}'" if actual else "EMPTY"
                logger.error(f"❌ Assertion Failed: '{target}' (Actual: {display_actual}) does not contain '{contains}'")
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

            if success: logger.info(f"✅ System State: {cond}")
            else: logger.error(f"❌ System State: Condition '{cond}' failed. Health: {h}")

    def cleanup(self):
        logger.info("🧹 Cleaning up client test session...")
        if self.app:
            try: self.app.destroy()
            except: pass

async def main():
    parser = argparse.ArgumentParser(description="Jarvis Client UI Test Runner")
    parser.add_argument("file", type=str, help="Path to scenario YAML or Plan YAML.")
    parser.add_argument("--mock-all", action="store_true")
    args = parser.parse_args()

    # Pre-test backend cleanup
    from manage_loadout import kill_loadout
    kill_loadout("all")
    
    if args.mock_all: os.environ['JARVIS_MOCK_ALL'] = "1"

    with open(args.file, 'r') as f:
        data = yaml.safe_load(f)

    runner = ClientTestRunner(args)
    
    if "timeline" in data:
        await runner.run_scenario(data)
    elif "scenarios" in data:
        # Load from plan
        scenario_file = os.path.join(project_root, "tests", "scenarios", "client_ui.yaml")
        with open(scenario_file, 'r') as sf:
            all_scenarios = yaml.safe_load(sf)
        
        for item in data['scenarios']:
            sid = item['id']
            if sid in all_scenarios:
                sdata = all_scenarios[sid]
                sdata['name'] = sdata.get('name', sid)
                await runner.run_scenario(sdata)
    else:
        for sid, sdata in data.items():
            if isinstance(sdata, dict) and "timeline" in sdata:
                await runner.run_scenario(sdata)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
