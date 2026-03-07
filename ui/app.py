import os
import sys
import queue
import yaml
import time
from loguru import logger
import customtkinter as ctk

from .controller import JarvisController
from .graph_widget import PipelineGraphWidget
from .sidebar_widgets import VramMonitor, ModelHealthCard, LoadingSpinner

import utils

# Add project root to sys.path
script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if script_dir not in sys.path:
    sys.path.append(script_dir)

class JarvisApp(ctk.CTk):
    def __init__(self):
        self._boot_time = time.perf_counter()
        
        super().__init__()
        self.title("JARVIS CORE CONSOLE")
        self._ui_log("APP_BOOT", "Initializing JarvisApp")
        
        self.queue = queue.Queue()
        self.controller = JarvisController(self.queue)

        # 1. Set restored geometry first if it exists
        if self.controller.geometry:
            self.geometry(self.controller.geometry)
        else:
            self.geometry("1200x850")

        # 2. Apply maximization state last (if it was maximized, this overrides geometry)
        if self.controller.is_maximized or self.controller.geometry is None:
            self.state("zoomed")
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Load UI Config dynamically
        self.ui_cfg = self.controller.cfg.get('ui', {})
        self.colors = self.ui_cfg.get('colors', {})
        
        self.configure(fg_color=self.colors.get('bg', '#0B0F19'))
        
        # State for Log Viewing and Transitions
        self.selected_mid = None
        self.last_log_content = ""
        self.transition_lock = False
        self.initial_scan_pending = True
        self._last_vram_str = ""
        
        self.setup_ui()
        self.update_graph_view()
        
        # Start initial scan spinner
        self.loading_spinner.start()
        self._ui_log("SPINNER_STATE", "start")
        
        self.poll_queue()
        self._update_log_viewer_loop()
        
        # Deferred restoration to ensure OS mapping is complete
        self.after(500, self._restore_window_state)

    def _ui_log(self, event: str, details: str = ""):
        delta = time.perf_counter() - self._boot_time
        logger.bind(domain="UI").debug(f"[+{delta:.3f}s] [{event}] {details}")

    def _restore_window_state(self):
        """Final window state application after initial layout stabilization."""
        try:
            # 1. Apply saved geometry first
            if self.controller.geometry:
                self.geometry(self.controller.geometry)
            else:
                self.geometry("1200x850")

            # 2. If maximized, force a 'Double-Pump' transition to wake up Windows DWM
            if self.controller.is_maximized or self.controller.geometry is None:
                self.state("normal")
                self.update_idletasks()
                self.state("zoomed")
        except Exception as e:
            logger.error(f"Failed to restore window state: {e}")

    def setup_ui(self):
        self._ui_log("UI_READY", "Starting UI widget packing")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color="#080C14")
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        
        # Loadout Selection at the Top
        ctk.CTkLabel(self.sidebar, text="LOADOUT", font=("Impact", 18), text_color=self.colors.get('accent')).pack(pady=(20, 5))
        from utils import list_all_loadouts
        loadouts = ["NONE"] + list_all_loadouts()
        self.loadout_var = ctk.StringVar(value=self.controller.current_loadout)
        self.loadout_opt = ctk.CTkOptionMenu(self.sidebar, values=loadouts, variable=self.loadout_var, command=self.on_loadout_change, width=200)
        self.loadout_opt.pack(pady=(0, 10), padx=10)

        # VRAM Monitor Container (with Spinner)
        self.vram_container = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.vram_container.pack(fill="x", padx=10)
        
        self.loading_spinner = LoadingSpinner(self.vram_container, self.colors, size=20)
        self.loading_spinner.pack(side="right", padx=(0, 5), pady=(5, 0))

        self.vram_monitor = VramMonitor(self.vram_container, self.colors)
        try:
            # Fast initial update (no breakdown)
            self.vram_monitor.update(utils.get_gpu_vram_usage(), utils.get_gpu_total_vram(), None)
        except: pass

        ctk.CTkLabel(self.sidebar, text="ACTIVE MODELS", font=("Impact", 16), text_color="#E0E0E0").pack(pady=(10, 5))
        self.health_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.health_frame.pack(fill="both", expand=True, padx=10)
        self.service_widgets = {} # mid -> ModelHealthCard

        # --- HEADER ---
        self.header = ctk.CTkFrame(self, height=80, corner_radius=0, fg_color="#0D1117")
        self.header.grid(row=0, column=1, sticky="ew")
        
        # Pipeline
        ctk.CTkLabel(self.header, text="Pipeline:", font=("Consolas", 12, "bold")).pack(side="left", padx=(10, 5))
        pipes = [f.replace(".yaml", "") for f in os.listdir(os.path.join(script_dir, "system_config", "pipelines")) if f.endswith(".yaml")]
        self.pipe_var = ctk.StringVar(value=self.controller.current_pipeline)
        self.pipe_opt = ctk.CTkOptionMenu(self.header, values=pipes, variable=self.pipe_var, command=self.on_config_change)
        self.pipe_opt.pack(side="left", padx=10)

        # Auto Layout
        self.auto_btn = ctk.CTkButton(self.header, text="AUTO LAYOUT", width=100, height=24, fg_color=self.colors.get('gray'), text_color="white", command=self.on_auto_layout)
        self.auto_btn.pack(side="left", padx=20)

        # Mode Indicator
        self.mode_label = ctk.CTkLabel(self.header, text="MODE: TERMINAL", font=("Consolas", 12, "bold"), text_color=self.colors.get('accent'))
        self.mode_label.pack(side="right", padx=20)

        # --- MAIN DISPLAY AREA ---
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.grid(row=1, column=1, sticky="nsew", padx=15, pady=15)
        self.main_area.grid_columnconfigure(0, weight=1) # Graph
        self.main_area.grid_columnconfigure(1, weight=1) # Console
        self.main_area.grid_rowconfigure(0, weight=1)

        # 1. Pipeline Graph
        self.graph_widget = PipelineGraphWidget(self.main_area, self.ui_cfg)
        self.graph_widget.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.graph_widget.on_positions_changed_callback = lambda p: self.controller.update_node_positions(self.controller.current_pipeline, p)

        # 2. Console Container (Terminal or Log Viewer)
        self.console_container = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.console_container.grid(row=0, column=1, sticky="nsew")
        self.console_container.grid_columnconfigure(0, weight=1)
        self.console_container.grid_rowconfigure(0, weight=1)

        self.terminal = ctk.CTkTextbox(self.console_container, font=("Consolas", 13), fg_color=self.colors.get('bg'), text_color=self.colors.get('text'))
        self.terminal.grid(row=0, column=0, sticky="nsew")
        
        self.log_viewer = ctk.CTkTextbox(self.console_container, font=("Consolas", 11), fg_color="#05080F", text_color="#A0A0A0")
        
        # --- FOOTER ---
        self.footer = ctk.CTkFrame(self, height=120, fg_color="#0D1117")
        self.footer.grid(row=2, column=1, sticky="ew")
        self.record_btn = ctk.CTkButton(self.footer, text="HOLD TO TALK", font=("Impact", 24), height=60, fg_color=self.colors.get('accent'), text_color="black")
        self.record_btn.pack(pady=20, padx=20, fill="x")
        self.record_btn.bind("<Button-1>", lambda e: self.controller.start_recording())
        self.record_btn.bind("<ButtonRelease-1>", lambda e: self.controller.stop_recording())

    def on_config_change(self, _=None):
        self.controller.current_pipeline = self.pipe_var.get()
        self.controller.save_checkpoint()
        self.update_graph_view()

    def on_auto_layout(self):
        self.graph_widget.apply_auto_layout()

    def on_closing(self):
        self.controller.geometry = self.geometry()
        self.controller.is_maximized = (self.state() == "zoomed")
        self.controller.save_checkpoint()
        self.destroy()

    def on_loadout_change(self, val):
        self._ui_log("USER_ACTION", f"Requested loadout: {val}")
        if val != "NONE" and val == self.controller.current_loadout: return
        self.transition_lock = True; self.selected_mid = None; self.switch_to_terminal()
        for widget in self.health_frame.winfo_children(): widget.destroy()

        try:
            registry_data = self.controller.resolver.get_live_models()
            vram_snap = {"used": utils.get_gpu_vram_usage(), "total": utils.get_gpu_total_vram(), "external": registry_data.get("external", 0.0)}
        except: vram_snap = None
        if val != "NONE":
            try:
                loadouts_path = os.path.join(self.controller.project_root, "system_config", "loadouts.yaml")
                with open(loadouts_path, "r") as f: all_loadouts = yaml.safe_load(f)
                target = all_loadouts.get(val)
                if target:
                    model_strings = target.get('models', []) if isinstance(target, dict) else target
                    instant_models = []
                    instant_health = {}
                    from utils.config import parse_model_string
                    for i, m_str in enumerate(model_strings):
                        m_data = parse_model_string(m_str)
                        if m_data:
                            mock_port = -1 - i
                            instant_models.append({"id": m_data['id'], "engine": m_data['engine'], "params": m_data['params'], "port": mock_port, "capabilities": self.controller.resolver.get_model_capabilities(m_data['id'], m_data['engine'])})
                            instant_health[mock_port] = {"status": "STARTUP", "info": "Initializing..."}
                    
                    self.controller.health_state = instant_health
                    self.update_health_ui(instant_health, {"runnable": False, "errors": ["Loading..."]}, active_models=instant_models, vram=vram_snap)
            except Exception as e: logger.error(f"Instant UI refresh failed: {e}")
        else:
            self.transition_lock = False
            self.controller.health_state = {}
            self.update_health_ui({}, {"runnable": False, "errors": ["Offline"]}, active_models=[], vram=vram_snap)
        def execute_backend_changes():
            self.controller.trigger_loadout_change(val)
            self.update_graph_view()
        self.after(100, execute_backend_changes)

    def update_graph_view(self):
        health = self.controller.health_state
        try:
            bound_graph = self.controller.resolver.resolve(self.controller.current_pipeline, self.controller.current_strategy)
            manual_pos = self.controller.node_positions.get(self.controller.current_pipeline)
            self.graph_widget.set_graph_data(bound_graph, manual_positions=manual_pos, health_data=health)
        except:
            try:
                raw_pipeline = self.controller.resolver.load_yaml(self.controller.current_pipeline)
                unbound_graph = {n['id']: n.copy() for n in raw_pipeline.get('nodes', [])}
                manual_pos = self.controller.node_positions.get(self.controller.current_pipeline)
                self.graph_widget.set_graph_data(unbound_graph, manual_positions=manual_pos, health_data=health)
            except: self.graph_widget.set_graph_data(None)

    def switch_to_terminal(self):
        self.log_viewer.grid_remove(); self.terminal.grid()
        self.mode_label.configure(text="MODE: TERMINAL", text_color=self.colors.get('accent'))

    def switch_to_log(self, mid):
        self.terminal.grid_remove(); self.log_viewer.grid(row=0, column=0, sticky="nsew")
        self.mode_label.configure(text=f"LOG: {mid}", text_color=self.colors.get('success'))
        self.log_viewer.delete("1.0", "end"); self.last_log_content = ""

    def _update_log_viewer_loop(self):
        if not self.winfo_exists(): return
        if self.selected_mid:
            registry_data = self.controller.resolver.get_live_models()
            active_models = registry_data.get("models", [])
            m = next((m for m in active_models if m['id'] == self.selected_mid), None)
            if m and m.get('log_path') and os.path.exists(m['log_path']):
                try:
                    with open(m['log_path'], "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(0, os.SEEK_END); size = f.tell(); f.seek(max(0, size - 10000))
                        content = f.read()
                        if content != self.last_log_content:
                            self.log_viewer.configure(state="normal"); self.log_viewer.delete("1.0", "end")
                            self.log_viewer.insert("1.0", content); self.log_viewer.see("end")
                            self.log_viewer.configure(state="disabled"); self.last_log_content = content
                except: pass
        if self.winfo_exists():
            self.after(1000, self._update_log_viewer_loop)

    def on_model_click(self, mid):
        if self.selected_mid == mid: self.selected_mid = None; self.switch_to_terminal()
        else: self.selected_mid = mid; self.switch_to_log(mid)
        self._update_selection_ui()

    def _update_selection_ui(self):
        for mid, card in self.service_widgets.items():
            card.set_selected(mid == self.selected_mid)

    def on_right_click(self, event, m):
        menu = ctk.CTkFrame(self, fg_color="#1A1E26", border_width=1, border_color=self.colors.get('accent'))
        def close_menu(e=None): menu.place_forget()
        menu.place(x=event.x_root - self.winfo_rootx(), y=event.y_root - self.winfo_rooty())
        ctk.CTkButton(menu, text="Open Log", fg_color="transparent", anchor="w", height=30, hover_color="#2A2F3E", command=lambda: [self.switch_to_log(m['id']), close_menu()]).pack(fill="x", padx=2, pady=2)
        ctk.CTkButton(menu, text="Restart", fg_color="transparent", anchor="w", height=30, hover_color="#2A2F3E", command=lambda: [self.controller.trigger_service_restart(m['id']), close_menu()]).pack(fill="x", padx=2, pady=2)
        ctk.CTkButton(menu, text="Close", fg_color="transparent", anchor="w", height=30, hover_color="#2A2F3E", text_color=self.colors.get('error'), command=lambda: [self.controller.trigger_service_kill(m['id']), close_menu()]).pack(fill="x", padx=2, pady=2)
        menu.bind("<Leave>", close_menu); self.bind("<Button-1>", close_menu, add="+")

    def update_health_ui(self, health, runnability, active_models=None, vram=None):
        if vram:
            vram_str = f"used={vram['used']:.1f}, ext={vram['external']:.1f}"
            if vram_str != self._last_vram_str:
                self._ui_log("VRAM_RENDER", vram_str)
                self._last_vram_str = vram_str
            self.vram_monitor.update(vram['used'], vram['total'], vram['external'])

        if self.transition_lock and active_models is not None and not active_models: return
        if active_models: self.transition_lock = False
        
        models_to_render = active_models if active_models else []
        current_mids = [m['id'] for m in models_to_render]
        
        # Prune dead widgets
        for mid in list(self.service_widgets.keys()):
            if mid not in current_mids: 
                self.service_widgets[mid].destroy()
                del self.service_widgets[mid]

        # 1. Determine which models are bound to the current pipeline
        bound_mids = set()
        try:
            # We use the current view_mode's bound graph
            bound_graph = self.controller.resolver.resolve(self.controller.current_pipeline)
            for node in bound_graph.values():
                binding = node.get('binding')
                if binding: bound_mids.add(binding['id'])
        except: pass

        # Update or Create widgets
        for m in models_to_render:
            mid = m['id']
            port = m['port']
            info = health.get(port, {"status": "OFF", "info": None})
            
            if mid not in self.service_widgets:
                card = ModelHealthCard(self.health_frame, m, self.colors, self.on_model_click, self.on_right_click)
                self.service_widgets[mid] = card
            
            self.service_widgets[mid].set_status(info['status'])
            self.service_widgets[mid].set_orphan(mid not in bound_mids)
            
        self._update_selection_ui()
        
        # Refresh Graph with new health data
        self.update_graph_view()

        # Loadout Opt color coding
        if self.controller.current_loadout == "NONE": self.loadout_opt.configure(fg_color=self.colors.get('gray'))
        elif all(s['status'] == "ON" or s['status'] == "BUSY" for s in health.values()): self.loadout_opt.configure(fg_color=self.colors.get('success'), text_color="black")
        elif any(s['status'] == "STARTUP" for s in health.values()): self.loadout_opt.configure(fg_color="#CCAA00", text_color="white")
        else: self.loadout_opt.configure(fg_color=self.colors.get('accent'), text_color="black")
        
        if runnability.get('runnable'): self.record_btn.configure(state="normal", fg_color=self.colors.get('accent'), text="HOLD TO TALK")
        else:
            errors = runnability.get('errors', []); err_msg = errors[0] if len(errors) == 1 else ("Arch Mismatch / Unbound Nodes" if any("Resolution Error" in e or "ARCH_MISMATCH" in e for e in errors) else f"{len(errors)} Services Failed") if errors else "Offline"
            self.record_btn.configure(state="disabled", fg_color=self.colors.get('gray'), text=f"OFFLINE: {err_msg}")

    def poll_queue(self):
        if not self.winfo_exists(): return
        while not self.queue.empty():
            msg = self.queue.get()
            if msg['type'] == "log": self.terminal.insert("end", f"{msg['msg']}\n"); self.terminal.see("end")
            elif msg['type'] == "state":
                if msg.get('recording'): self.record_btn.configure(fg_color=self.colors.get('error'), text="RECORDING...")
            elif msg['type'] == "health_update":
                # Retirement trigger: first valid VRAM update stops the initial boot spinner forever
                if self.initial_scan_pending and msg.get('vram'):
                    self.loading_spinner.stop()
                    self._ui_log("SPINNER_STATE", "stop (first health report arrived)")
                    self.initial_scan_pending = False
                self.update_health_ui(msg['health'], msg['runnability'], active_models=msg.get('active_models'), vram=msg.get('vram'))
        self.after(100, self.poll_queue)
