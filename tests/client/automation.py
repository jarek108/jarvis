import os
import time
import json
from loguru import logger
from typing import Any, Optional, Dict

# Conditional imports for UI components to avoid absolute dependency in the Orchestrator
try:
    from ui import JarvisApp
except ImportError:
    JarvisApp = Any

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
            logger.bind(domain="ORCHESTRATOR").warning(f"⚠️ Slow UI Dump: {latency:.2f}ms for '{target_path}'")
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
    """Handles window-specific screenshot captures within scenario folders."""
    def __init__(self, app: JarvisApp, scenario_dir: str):
        self.app = app
        self.scenario_dir = scenario_dir

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
            
            os.makedirs(self.scenario_dir, exist_ok=True)
            out_path = os.path.join(self.scenario_dir, filename)
            img.save(out_path, quality=85)
            logger.bind(domain="ORCHESTRATOR").info(f"📸 Screenshot saved: {out_path}")

    def capture_desktop(self, filename: str):
        """Captures the entire primary monitor."""
        if not mss or not PIL: return

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            os.makedirs(self.scenario_dir, exist_ok=True)
            out_path = os.path.join(self.scenario_dir, f"desktop_{filename}")
            img.save(out_path, quality=85)
            logger.bind(domain="ORCHESTRATOR").info(f"🖥️ Desktop Screenshot saved: {out_path}")

class AutomationController:
    """Simulates deterministic human actions against UI widgets."""
    def __init__(self, app: JarvisApp):
        self.app = app

    def click(self, target_path: str):
        widget = self._resolve_widget(target_path)
        if hasattr(widget, "invoke"):
            logger.bind(domain="ORCHESTRATOR").info(f"🖱️ Invoking click on '{target_path}'")
            widget.invoke()
        else:
            logger.bind(domain="ORCHESTRATOR").error(f"❌ Cannot click non-invocable widget '{target_path}'")

    def maximize(self):
        logger.bind(domain="ORCHESTRATOR").info("🔲 Maximizing window")
        self.app.state("zoomed")
        self.app.update_idletasks()
        self.app.update()

    def select_dropdown(self, target_path: str, value: str):
        if target_path == "loadout_opt":
            logger.bind(domain="ORCHESTRATOR").info(f"🔽 Selecting Loadout: '{value}'")
            self.app.loadout_var.set(value)
            self.app.on_loadout_change(value)
        elif target_path == "pipe_opt":
            logger.bind(domain="ORCHESTRATOR").info(f"🔽 Selecting Pipeline: '{value}'")
            self.app.pipe_var.set(value)
            self.app.on_config_change(value)

    def _resolve_widget(self, path: str) -> Optional[Any]:
        return StatusDumper(self.app)._resolve_widget(path)
