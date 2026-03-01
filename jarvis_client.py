import os
import sys
import time
import json
import threading
import queue
import asyncio
import subprocess
from loguru import logger
import customtkinter as ctk
from PIL import Image

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

import utils
from utils import load_config, list_all_loadouts, get_system_health, kill_all_jarvis_services, kill_process_on_port
from utils.pipeline import PipelineResolver, PipelineExecutor
from utils.edge_sensors import AudioSensor

from manage_loadout import apply_loadout, kill_loadout, restart_service, kill_service

# --- UI CONSTANTS ---
BG_COLOR = "#0B0F19"
ACCENT_COLOR = "#00D1FF"
TEXT_COLOR = "#E0E0E0"
GRAY_COLOR = "#2A2F3E"
SUCCESS_COLOR = "#00FF94"
ERROR_COLOR = "#FF4B4B"
WARNING_COLOR = "#FFD700"

CHECKPOINT_PATH = os.path.join(script_dir, "checkpoint-client.json")

ctk.set_appearance_mode("dark")

class JarvisController:
    def __init__(self, ui_queue):
        self.ui_queue = ui_queue
        self.cfg = load_config()
        self.project_root = script_dir
        
        # 1. Redirect System Logs to UI
        def ui_sink(message):
            self.ui_queue.put({"type": "log", "msg": message.record["message"], "tag": "system"})
        logger.add(ui_sink, format="{message}", level="INFO")

        # 2. Embedded Flow Engine
        self.resolver = PipelineResolver(self.project_root)
        self.executor = PipelineExecutor(self.project_root)
        
        # 2. Edge Hardware Adapters
        self.audio_sensor = AudioSensor()
        
        # 3. State
        self.current_pipeline = "voice_to_voice"
        self.current_strategy = "fast_interaction"
        self.current_loadout = "NONE"
        self.load_checkpoint()
        
        # Force system state to match UI "NONE" state
        # Synchronously delete registry to prevent UI flashing old models
        registry_path = os.path.join(self.project_root, "model_calibrations", "runtime_registry.json")
        if os.path.exists(registry_path):
            try: os.remove(registry_path)
            except: pass
            
        def init_cleanup():
            self.ui_queue.put({"type": "log", "msg": "🧹 Cleaning up previous session state...", "tag": "system"})
            kill_loadout("all")
        threading.Thread(target=init_cleanup, daemon=True).start()
        
        self.is_recording = False
        self.is_polling = True
        self.health_state = {}
        self.runnability = {"runnable": False, "errors": ["Initializing..."], "map": {}}
        
        # Logs dir
        self.log_dir = os.path.join(self.project_root, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        threading.Thread(target=self._status_polling_loop, daemon=True).start()

    def load_checkpoint(self):
        if os.path.exists(CHECKPOINT_PATH):
            try:
                with open(CHECKPOINT_PATH, "r") as f:
                    data = json.load(f)
                    self.current_pipeline = data.get("pipeline", self.current_pipeline)
                    self.current_strategy = data.get("strategy", self.current_strategy)
                    # Force NONE on startup
                    self.current_loadout = "NONE"
            except: pass

    def save_checkpoint(self):
        try:
            with open(CHECKPOINT_PATH, "w") as f:
                json.dump({
                    "pipeline": self.current_pipeline, 
                    "strategy": self.current_strategy,
                    "loadout": self.current_loadout
                }, f)
        except: pass

    def _status_polling_loop(self):
        while self.is_polling:
            try:
                # 1. Get Physical Health for ACTIVE LOADOUT ONLY (Fast Path)
                registry_data = self.resolver.get_live_models()
                active_models = registry_data.get("models", [])
                external_vram = registry_data.get("baseline", 0.0)
                
                active_ports = [m['port'] for m in active_models if m.get('port')]
                
                # Map ports to log paths for error detection
                log_map = {m['port']: m['log_path'] for m in active_models if m.get('log_path') and m.get('port')}
                self.health_state = get_system_health(ports=active_ports, log_paths=log_map)
                
                # 2. Get Hardware Metrics
                vram_used = utils.get_gpu_vram_usage()
                vram_total = utils.get_gpu_total_vram()

                # 3. Check Logical Runnability (Passing existing health to avoid double-poll)
                self.runnability = self.resolver.check_runnability(self.current_pipeline, self.current_strategy, external_health=self.health_state)
                
                # 4. Update UI
                self.ui_queue.put({
                    "type": "health_update", 
                    "health": self.health_state, 
                    "runnability": self.runnability,
                    "active_models": active_models,
                    "vram": {"used": vram_used, "total": vram_total, "external": external_vram}
                })
            except Exception as e:
                logger.error(f"Status Polling Error: {e}")
            time.sleep(1.5)

    def trigger_loadout_change(self, loadout_id):
        # 1. Skip if same loadout already active (unless it's NONE, then we allow re-kill)
        if loadout_id != "NONE" and loadout_id == self.current_loadout:
            logger.info(f"Loadout '{loadout_id}' already active. Skipping application.")
            return

        self.current_loadout = loadout_id
        self.save_checkpoint()
        
        def task():
            if loadout_id == "NONE":
                self.ui_queue.put({"type": "log", "msg": "☢️ KILLING ALL SERVICES...", "tag": "system"})
                kill_loadout("all")
            else:
                self.ui_queue.put({"type": "log", "msg": f"⚙️ APPLYING LOADOUT: {loadout_id}", "tag": "system"})
                try:
                    # Apply loadout using existing logic (Soft apply to avoid full kill if possible)
                    apply_loadout(loadout_id, soft=True)
                    self.ui_queue.put({"type": "log", "msg": "✅ LOADOUT APPLIED", "tag": "system"})
                except Exception as e:
                    self.ui_queue.put({"type": "log", "msg": f"❌ LOADOUT ERROR: {e}", "tag": "system"})

        threading.Thread(target=task, daemon=True).start()

    def trigger_service_restart(self, sid):
        def task():
            self.ui_queue.put({"type": "log", "msg": f"🔄 RESTARTING SERVICE: {sid}", "tag": "system"})
            try:
                restart_service(sid, self.current_loadout)
                self.ui_queue.put({"type": "log", "msg": f"✅ RESTARTED: {sid}", "tag": "system"})
            except Exception as e:
                self.ui_queue.put({"type": "log", "msg": f"❌ RESTART ERROR [{sid}]: {e}", "tag": "system"})
        threading.Thread(target=task, daemon=True).start()

    def trigger_service_kill(self, sid):
        def task():
            self.ui_queue.put({"type": "log", "msg": f"🔪 CLOSING SERVICE: {sid}", "tag": "system"})
            try:
                kill_service(sid)
                self.ui_queue.put({"type": "log", "msg": f"✅ CLOSED: {sid}", "tag": "system"})
            except Exception as e:
                self.ui_queue.put({"type": "log", "msg": f"❌ CLOSE ERROR [{sid}]: {e}", "tag": "system"})
        threading.Thread(target=task, daemon=True).start()

    def start_recording(self):
        if not self.runnability.get('runnable'):
            self.ui_queue.put({"type": "log", "msg": f"❌ CANNOT RUN: {', '.join(self.runnability['errors'])}", "tag": "system"})
            return
        self.is_recording = True
        self.ui_queue.put({"type": "state", "recording": True})

    def stop_recording(self):
        if not self.is_recording: return
        self.is_recording = False
        self.ui_queue.put({"type": "state", "recording": False})
        audio_data = self.audio_sensor.capture_snapshot(duration=3.0)
        threading.Thread(target=self._run_pipeline_local, args=(audio_data,), daemon=True).start()

    def _run_pipeline_local(self, audio_data):
        temp_audio = os.path.join(self.project_root, "buffers", "user_voice.wav")
        os.makedirs(os.path.dirname(temp_audio), exist_ok=True)
        with open(temp_audio, "wb") as f: f.write(audio_data)

        try:
            bound_graph = self.resolver.resolve(self.current_pipeline, self.current_strategy)
        except Exception as e:
            self.ui_queue.put({"type": "log", "msg": f"Resolution Error: {e}", "tag": "system"})
            return

        inputs = {"input_mic": temp_audio}

        async def run_and_monitor():
            exec_task = asyncio.create_task(self.executor.run(bound_graph, inputs))
            last_idx = 0
            while not exec_task.done() or last_idx < len(self.executor.trace):
                while last_idx < len(self.executor.trace):
                    packet = self.executor.trace[last_idx]; last_idx += 1
                    if packet.get('dir') == 'OUT':
                        ptype = packet.get('type')
                        content = packet.get('content')
                        if ptype in ["text_token", "text_sentence", "text_final"]:
                            self.ui_queue.put({"type": "log", "msg": str(content), "tag": "assistant"})
                await asyncio.sleep(0.05)
        
        asyncio.run(run_and_monitor())

class PipelineGraphWidget(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = ctk.CTkCanvas(self, bg="#080C14", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.nodes = {}
        self.edges = []
        self.canvas.bind("<Configure>", self.on_resize)
        self.canvas.bind("<Button-1>", self.on_click)
        self.on_node_click_callback = None
        self.selected_node_id = None

    def on_resize(self, event):
        self.draw_graph()

    def set_graph_data(self, bound_graph):
        self.bound_graph = bound_graph
        self.draw_graph()

    def on_click(self, event):
        x, y = event.x, event.y
        clicked_id = None
        for nid, data in self.nodes.items():
            bx1, by1, bx2, by2 = data['bbox']
            if bx1 <= x <= bx2 and by1 <= y <= by2:
                clicked_id = nid
                break
                
        if clicked_id:
            if self.selected_node_id == clicked_id:
                self.selected_node_id = None
            else:
                self.selected_node_id = clicked_id
            self.draw_graph()
            if self.on_node_click_callback:
                self.on_node_click_callback(self.selected_node_id)

    def draw_rounded_rect(self, x, y, w, h, r, color, outline_color="", outline_width=0):
        # Create a rounded rectangle using lines and arcs
        points = [
            x+r, y,
            x+w-r, y,
            x+w, y,
            x+w, y+r,
            x+w, y+h-r,
            x+w, y+h,
            x+w-r, y+h,
            x+r, y+h,
            x, y+h,
            x, y+h-r,
            x, y+r,
            x, y
        ]
        return self.canvas.create_polygon(points, fill=color, outline=outline_color, width=outline_width, smooth=True)

    def draw_edge(self, x1, y1, x2, y2, color="#2A2F3E", style=None):
        # Draw an angled or curved line with an arrowhead
        ctrl_x = (x1 + x2) / 2
        return self.canvas.create_line(x1, y1, ctrl_x, y1, ctrl_x, y2, x2, y2, fill=color, width=2, arrow=ctk.LAST, smooth=True, dash=style)

    def draw_graph(self):
        self.canvas.delete("all")
        if not hasattr(self, 'bound_graph') or not self.bound_graph:
            self.canvas.create_text(self.winfo_width()/2, self.winfo_height()/2, text="No Pipeline Loaded", fill=GRAY_COLOR, font=("Consolas", 14))
            return

        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1: return

        # 1. Layout Engine (Simple Tiered Grid based on implicit roles)
        tiers = {0: [], 1: [], 2: [], 3: []}
        
        # Categorize nodes by role/type to assign tiers
        for nid, node in self.bound_graph.items():
            ntype = node.get('type')
            role = node.get('role', '')
            if ntype in ['source', 'input']: tiers[0].append(nid)
            elif role == 'utility': tiers[1].append(nid)
            elif ntype == 'processing' and role != 'utility': tiers[2].append(nid)
            elif ntype == 'sink': tiers[3].append(nid)
            else: tiers[1].append(nid) # Fallback

        # Calculate coordinates
        node_w, node_h = 160, 60
        margin_x = w / 5
        self.nodes = {}

        for tier_idx, nodes_in_tier in tiers.items():
            if not nodes_in_tier: continue
            cx = margin_x * (tier_idx + 1)
            spacing_y = h / (len(nodes_in_tier) + 1)
            
            for i, nid in enumerate(nodes_in_tier):
                cy = spacing_y * (i + 1)
                self.nodes[nid] = {
                    'x': cx, 'y': cy,
                    'bbox': (cx - node_w/2, cy - node_h/2, cx + node_w/2, cy + node_h/2),
                    'data': self.bound_graph[nid]
                }

        # 2. Draw Edges
        for nid, ndata in self.nodes.items():
            node = ndata['data']
            inputs = node.get('inputs', [])
            for src_id in inputs:
                if src_id in self.nodes:
                    src = self.nodes[src_id]
                    # Arrow from right edge of source to left edge of target
                    dash = (4, 4) if node.get('role') == 'memory' else None
                    self.draw_edge(src['bbox'][2], src['y'], ndata['bbox'][0], ndata['y'], style=dash)

        # 3. Draw Nodes
        for nid, ndata in self.nodes.items():
            node = ndata['data']
            cx, cy = ndata['x'], ndata['y']
            bx1, by1, bx2, by2 = ndata['bbox']
            
            # Styling based on state and selection
            is_selected = (nid == self.selected_node_id)
            bg_color = "#12161E"
            outline_color = SUCCESS_COLOR if is_selected else "#2A2F3E"
            outline_w = 2 if is_selected else 1
            
            ntype = node.get('type')
            role = node.get('role', ntype)
            binding = node.get('binding')
            
            if ntype == 'source': outline_color = ACCENT_COLOR
            elif ntype == 'sink': outline_color = WARNING_COLOR
            elif ntype == 'processing' and role != 'utility' and not binding:
                # Flag unbound required models
                outline_color = ERROR_COLOR
                outline_w = 2

            self.draw_rounded_rect(bx1, by1, node_w, node_h, 8, bg_color, outline_color, outline_w)
            
            # Text Content
            self.canvas.create_text(cx, cy - 10, text=nid[:20], fill="#FFFFFF", font=("Consolas", 10, "bold"))
            
            if binding:
                subtext = binding.get('id', 'Unknown')
                self.canvas.create_text(cx, cy + 10, text=subtext[:22], fill=SUCCESS_COLOR, font=("Consolas", 8))
            elif ntype == 'processing' and role != 'utility':
                self.canvas.create_text(cx, cy + 10, text="[UNBOUND]", fill=ERROR_COLOR, font=("Consolas", 8, "bold"))
            else:
                self.canvas.create_text(cx, cy + 10, text=f"[{role.upper()}]", fill=GRAY_COLOR, font=("Consolas", 8))

class JarvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("JARVIS CORE CONSOLE")
        self.geometry("1200x850")
        self.configure(fg_color=BG_COLOR)
        self.queue = queue.Queue()
        self.controller = JarvisController(self.queue)
        
        # State for Log Viewing
        self.selected_mid = None
        self.last_log_content = ""
        
        self.setup_ui()
        self.update_graph_view()
        self.poll_queue()
        self._update_log_viewer_loop()

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color="#080C14")
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        
        # Loadout Selection at the Top
        ctk.CTkLabel(self.sidebar, text="LOADOUT", font=("Impact", 18), text_color=ACCENT_COLOR).pack(pady=(20, 5))
        loadouts = ["NONE"] + list_all_loadouts()
        self.loadout_var = ctk.StringVar(value=self.controller.current_loadout)
        self.loadout_opt = ctk.CTkOptionMenu(self.sidebar, values=loadouts, variable=self.loadout_var, command=self.on_loadout_change, width=200)
        self.loadout_opt.pack(pady=(0, 10), padx=10)

        # VRAM Monitor
        self.vram_container = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.vram_container.pack(pady=(5, 0))
        
        self.vram_lbl_prefix = ctk.CTkLabel(self.vram_container, text="VRAM: ", font=("Consolas", 11), text_color="#D0D0D0")
        self.vram_lbl_prefix.pack(side="left")
        self.vram_lbl_model = ctk.CTkLabel(self.vram_container, text="0.0", font=("Consolas", 11, "bold"), text_color="#FFFFFF")
        self.vram_lbl_model.pack(side="left")
        self.vram_lbl_plus = ctk.CTkLabel(self.vram_container, text=" + ", font=("Consolas", 11), text_color="#D0D0D0")
        self.vram_lbl_plus.pack(side="left")
        self.vram_lbl_ext = ctk.CTkLabel(self.vram_container, text="0.0", font=("Consolas", 11, "bold"), text_color=WARNING_COLOR)
        self.vram_lbl_ext.pack(side="left")
        self.vram_lbl_ext_tag = ctk.CTkLabel(self.vram_container, text="(ext)", font=("Consolas", 9), text_color="#B0B0B0")
        self.vram_lbl_ext_tag.pack(side="left")
        self.vram_lbl_total = ctk.CTkLabel(self.vram_container, text=" / 0.0 GB", font=("Consolas", 11), text_color="#D0D0D0")
        self.vram_lbl_total.pack(side="left")

        self.vram_bar = ctk.CTkProgressBar(self.sidebar, width=200, height=8, fg_color="#10141B", progress_color=ACCENT_COLOR)
        self.vram_bar.pack(pady=(2, 20))
        self.vram_bar.set(0)

        ctk.CTkLabel(self.sidebar, text="ACTIVE MODELS", font=("Impact", 16), text_color="#E0E0E0").pack(pady=(10, 5))
        self.health_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.health_frame.pack(fill="both", expand=True, padx=10)
        self.service_widgets = {}

        # --- HEADER ---
        self.header = ctk.CTkFrame(self, height=80, corner_radius=0, fg_color="#0D1117")
        self.header.grid(row=0, column=1, sticky="ew")
        
        # Pipeline
        ctk.CTkLabel(self.header, text="Pipeline:").pack(side="left", padx=(20, 5))
        pipes = [f.replace(".yaml", "") for f in os.listdir(os.path.join(script_dir, "pipelines")) if f.endswith(".yaml")]
        self.pipe_var = ctk.StringVar(value=self.controller.current_pipeline)
        self.pipe_opt = ctk.CTkOptionMenu(self.header, values=pipes, variable=self.pipe_var, command=self.on_config_change)
        self.pipe_opt.pack(side="left", padx=10)

        # Strategy
        ctk.CTkLabel(self.header, text="Strategy:").pack(side="left", padx=(20, 5))
        strategies = [f.replace(".yaml", "") for f in os.listdir(os.path.join(script_dir, "strategies")) if f.endswith(".yaml")]
        self.strategy_var = ctk.StringVar(value=self.controller.current_strategy)
        self.strategy_opt = ctk.CTkOptionMenu(self.header, values=strategies, variable=self.strategy_var, command=self.on_config_change)
        self.strategy_opt.pack(side="left", padx=10)

        # Mode Indicator
        self.mode_label = ctk.CTkLabel(self.header, text="MODE: TERMINAL", font=("Consolas", 12, "bold"), text_color=ACCENT_COLOR)
        self.mode_label.pack(side="right", padx=20)

        # --- MAIN DISPLAY AREA ---
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.grid(row=1, column=1, sticky="nsew", padx=15, pady=15)
        self.main_area.grid_columnconfigure(0, weight=1) # Graph
        self.main_area.grid_columnconfigure(1, weight=1) # Console
        self.main_area.grid_rowconfigure(0, weight=1)

        # 1. Pipeline Graph
        self.graph_widget = PipelineGraphWidget(self.main_area)
        self.graph_widget.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # 2. Console Container (Terminal or Log Viewer)
        self.console_container = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.console_container.grid(row=0, column=1, sticky="nsew")
        self.console_container.grid_columnconfigure(0, weight=1)
        self.console_container.grid_rowconfigure(0, weight=1)

        self.terminal = ctk.CTkTextbox(self.console_container, font=("Consolas", 13), fg_color=BG_COLOR, text_color=TEXT_COLOR)
        self.terminal.grid(row=0, column=0, sticky="nsew")
        
        self.log_viewer = ctk.CTkTextbox(self.console_container, font=("Consolas", 11), fg_color="#05080F", text_color="#A0A0A0")
        # Hide log viewer initially
        
        # --- FOOTER ---
        self.footer = ctk.CTkFrame(self, height=120, fg_color="#0D1117")
        self.footer.grid(row=2, column=1, sticky="ew")
        self.record_btn = ctk.CTkButton(self.footer, text="HOLD TO TALK", font=("Impact", 24), height=60, fg_color=ACCENT_COLOR, text_color="black")
        self.record_btn.pack(pady=20, padx=20, fill="x")
        self.record_btn.bind("<Button-1>", lambda e: self.controller.start_recording())
        self.record_btn.bind("<ButtonRelease-1>", lambda e: self.controller.stop_recording())

    def on_config_change(self, _=None):
        self.controller.current_pipeline = self.pipe_var.get()
        self.controller.current_strategy = self.strategy_var.get()
        self.controller.save_checkpoint()
        self.update_graph_view()

    def on_loadout_change(self, val):
        # 1. Guard against redundant re-selection
        if val != "NONE" and val == self.controller.current_loadout:
            logger.info(f"Loadout '{val}' is already active. No action taken.")
            return

        self.controller.trigger_loadout_change(val)
        self.selected_mid = None # Reset selection
        self.switch_to_terminal()
        
        # 2. Instant UI Refresh: Populate models in STARTUP state immediately
        # Clear existing widgets
        for widget in self.health_frame.winfo_children():
            widget.destroy()
        self.service_widgets = {}

        if val != "NONE":
            try:
                # Load and parse the selected loadout immediately for the UI
                loadouts_path = os.path.join(self.project_root, "loadouts.yaml")
                with open(loadouts_path, "r") as f:
                    all_loadouts = yaml.safe_load(f)
                
                target = all_loadouts.get(val)
                if target:
                    model_strings = target.get('models', []) if isinstance(target, dict) else target
                    instant_models = []
                    instant_health = {}
                    
                    from utils.config import parse_model_string
                    for m_str in model_strings:
                        m_data = parse_model_string(m_str)
                        if m_data:
                            # We don't have ports yet, but we want to show the NAMES
                            # Use a mock port for the UI keying
                            mock_port = 0
                            instant_models.append({
                                "id": m_data['id'],
                                "engine": m_data['engine'],
                                "params": m_data['params'],
                                "port": mock_port,
                                "capabilities": self.controller.resolver.get_model_capabilities(m_data['id'], m_data['engine'])
                            })
                            instant_health[mock_port] = {"status": "STARTUP", "info": "Initializing..."}
                    
                    # Push an immediate health update to the local queue
                    self.update_health_ui(instant_health, {"runnable": False, "errors": ["Loading..."]}, active_models=instant_models)
            except Exception as e:
                logger.error(f"Instant UI refresh failed: {e}")

        self.update_graph_view()

    def update_graph_view(self):
        try:
            # Try to get the fully bound graph (with live models)
            bound_graph = self.controller.resolver.resolve(self.controller.current_pipeline, self.controller.current_strategy)
            self.graph_widget.set_graph_data(bound_graph)
        except Exception as e:
            # Fallback: Load raw pipeline to show structure even if unbound
            try:
                raw_pipeline = self.controller.resolver.load_yaml(self.controller.current_pipeline)
                unbound_graph = {n['id']: n.copy() for n in raw_pipeline.get('nodes', [])}
                self.graph_widget.set_graph_data(unbound_graph)
            except Exception as e2:
                logger.error(f"Failed to load raw pipeline for graph: {e2}")
                self.graph_widget.set_graph_data(None)

    def switch_to_terminal(self):
        self.log_viewer.grid_remove()
        self.terminal.grid()
        self.mode_label.configure(text="MODE: TERMINAL", text_color=ACCENT_COLOR)

    def switch_to_log(self, mid):
        self.terminal.grid_remove()
        self.log_viewer.grid(row=0, column=0, sticky="nsew")
        self.mode_label.configure(text=f"LOG: {mid}", text_color=SUCCESS_COLOR)
        self.log_viewer.delete("1.0", "end")
        self.last_log_content = ""

    def _update_log_viewer_loop(self):
        if self.selected_mid:
            # Find the model info in controller's resolver
            active_models = self.controller.resolver.get_live_models()
            m = next((m for m in active_models if m['id'] == self.selected_mid), None)
            if m and m.get('log_path') and os.path.exists(m['log_path']):
                try:
                    with open(m['log_path'], "r", encoding="utf-8", errors="ignore") as f:
                        # Read last 5000 chars for performance
                        f.seek(0, os.SEEK_END)
                        size = f.tell()
                        f.seek(max(0, size - 10000))
                        content = f.read()
                        if content != self.last_log_content:
                            self.log_viewer.configure(state="normal")
                            self.log_viewer.delete("1.0", "end")
                            self.log_viewer.insert("1.0", content)
                            self.log_viewer.see("end")
                            self.log_viewer.configure(state="disabled")
                            self.last_log_content = content
                except: pass
        self.after(1000, self._update_log_viewer_loop)

    def on_model_click(self, mid):
        if self.selected_mid == mid:
            self.selected_mid = None
            self.switch_to_terminal()
        else:
            self.selected_mid = mid
            self.switch_to_log(mid)
        self._update_selection_ui()

    def _update_selection_ui(self):
        """Immediately updates the visual state (borders/colors) of model cards based on selection."""
        for mid, widgets in self.service_widgets.items():
            if mid == self.selected_mid:
                widgets['frame'].configure(border_width=2, border_color=SUCCESS_COLOR, fg_color="#1A202C")
            else:
                widgets['frame'].configure(border_width=0, fg_color="#12161E")

    def on_right_click(self, event, m):
        menu = ctk.CTkFrame(self, fg_color="#1A1E26", border_width=1, border_color=ACCENT_COLOR)
        
        def close_menu(e=None): menu.place_forget()
        
        # Position menu at mouse
        menu.place(x=event.x_root - self.winfo_rootx(), y=event.y_root - self.winfo_rooty())
        
        # --- Options ---
        ctk.CTkButton(menu, text="Open Log", fg_color="transparent", anchor="w", height=30, hover_color="#2A2F3E", 
                      command=lambda: [self.open_service_log(m), close_menu()]).pack(fill="x", padx=2, pady=2)
        
        ctk.CTkButton(menu, text="Restart", fg_color="transparent", anchor="w", height=30, hover_color="#2A2F3E",
                      command=lambda: [self.controller.trigger_service_restart(m['id']), close_menu()]).pack(fill="x", padx=2, pady=2)
        
        ctk.CTkButton(menu, text="Close", fg_color="transparent", anchor="w", height=30, hover_color="#2A2F3E", text_color=ERROR_COLOR,
                      command=lambda: [self.controller.trigger_service_kill(m['id']), close_menu()]).pack(fill="x", padx=2, pady=2)

        # Close menu when mouse leaves or clicks elsewhere
        menu.bind("<Leave>", close_menu)
        self.bind("<Button-1>", close_menu, add="+")

    def update_health_ui(self, health, runnability, active_models=None, vram=None):
        # 1. Update VRAM Monitor
        if vram:
            used, total, external = vram['used'], vram['total'], vram.get('external', 0.0)
            model_vram = max(0, used - external)
            pct = used / total if total > 0 else 0
            
            self.vram_lbl_model.configure(text=f"{model_vram:.1f}")
            self.vram_lbl_ext.configure(text=f"{external:.1f}")
            self.vram_lbl_total.configure(text=f" / {total:.1f} GB ({int(pct*100)}%)")
            
            self.vram_bar.set(pct)
            # Dynamic bar color
            if pct > 0.9: self.vram_bar.configure(progress_color=ERROR_COLOR)
            elif pct > 0.75: self.vram_bar.configure(progress_color=WARNING_COLOR)
            else: self.vram_bar.configure(progress_color=ACCENT_COLOR)

        # 2. Update Service Sidebar (Precise Model List)
        models_to_render = active_models if active_models else []
        
        # Determine if we need to purge widgets for models no longer in loadout
        current_mids = [m['id'] for m in models_to_render]
        for mid in list(self.service_widgets.keys()):
            if mid not in current_mids:
                self.service_widgets[mid]['frame'].destroy()
                del self.service_widgets[mid]

        for m in models_to_render:
            mid = m['id']
            port = m['port']
            info = health.get(port, {"status": "OFF", "info": None})
            
            if mid not in self.service_widgets:
                # Selection/Hover handlers
                def on_click(event, m_id=mid): self.on_model_click(m_id)
                def on_rclick(event, model=m): self.on_right_click(event, model)
                def on_enter(event, f=None, m_id=mid): 
                    if self.selected_mid != m_id: f.configure(fg_color="#1A202C")
                def on_leave(event, f=None, m_id=mid): 
                    if self.selected_mid != m_id: f.configure(fg_color="#12161E")

                f = ctk.CTkFrame(self.health_frame, fg_color="#12161E", corner_radius=6, cursor="hand2", border_width=0)
                f.pack(fill="x", pady=6, padx=5)
                f.bind("<Button-1>", on_click)
                f.bind("<Button-3>", on_rclick)
                f.bind("<Enter>", lambda e, frame=f, m_id=mid: on_enter(e, frame, m_id))
                f.bind("<Leave>", lambda e, frame=f, m_id=mid: on_leave(e, frame, m_id))
                
                # Header: Lamp + ID
                header = ctk.CTkFrame(f, fg_color="transparent")
                header.pack(fill="x", padx=8, pady=(8, 0))
                header.bind("<Button-1>", on_click)
                header.bind("<Button-3>", on_rclick)
                
                lamp = ctk.CTkLabel(header, text="●", font=("Arial", 18))
                lamp.pack(side="left", padx=(0, 5))
                lamp.bind("<Button-1>", on_click)
                lamp.bind("<Button-3>", on_rclick)
                
                # Selectable Model Name
                name_box = ctk.CTkTextbox(header, font=("Consolas", 12, "bold"), height=25, fg_color="transparent", text_color="#FFFFFF", border_width=0, activate_scrollbars=False)
                name_box.insert("1.0", mid)
                name_box.configure(state="disabled")
                name_box.pack(side="left", fill="x", expand=True)
                name_box.bind("<Button-1>", on_click)
                name_box.bind("<Button-3>", on_rclick)
                
                # Capabilities: IN: ... | OUT: ...
                caps = m.get('capabilities', [])
                inputs = [c.replace("_in", "") for c in caps if c.endswith("_in")]
                outputs = [c.replace("_out", "") for c in caps if c.endswith("_out")]
                
                cap_text = f"IN: {', '.join(inputs)} | OUT: {', '.join(outputs)}"
                subtext = ctk.CTkLabel(f, text=cap_text, font=("Consolas", 10), text_color="#D0D0D0", anchor="w")
                subtext.pack(fill="x", padx=28, pady=(0, 2))
                subtext.bind("<Button-1>", on_click)
                subtext.bind("<Button-3>", on_rclick)
                
                # Streaming Indicator: Output-Stream ●
                stream_frame = ctk.CTkFrame(f, fg_color="transparent")
                stream_frame.pack(fill="x", padx=28, pady=(0, 2))
                stream_frame.bind("<Button-1>", on_click)
                stream_frame.bind("<Button-3>", on_rclick)
                
                is_llm = m['engine'] in ['ollama', 'vllm']
                streaming = m.get('params', {}).get('stream', True if is_llm else False)
                stream_color = SUCCESS_COLOR if streaming else ERROR_COLOR
                
                engine_str = m['engine'].upper()
                if m.get('required_gb'): engine_str += f" ({m['required_gb']} GB)"
                
                e_lbl = ctk.CTkLabel(stream_frame, text=f"{engine_str} • Out-Stream: ", font=("Consolas", 10), text_color="#B0B0B0")
                e_lbl.pack(side="left")
                e_lbl.bind("<Button-1>", on_click)
                e_lbl.bind("<Button-3>", on_rclick)
                
                s_lamp = ctk.CTkLabel(stream_frame, text="●", font=("Arial", 12), text_color=stream_color)
                s_lamp.pack(side="left")
                s_lamp.bind("<Button-1>", on_click)
                s_lamp.bind("<Button-3>", on_rclick)

                # Params (Filtered & Selectable)
                params_dict = m.get('params', {}).copy()
                params_dict.pop('device', None)
                params_dict.pop('stream', None)
                
                if params_dict:
                    p_str = " ".join([f"{k}:{v}" for k, v in params_dict.items()])
                    params_box = ctk.CTkTextbox(f, font=("Consolas", 9), height=35, fg_color="transparent", text_color="#A0A0A0", border_width=0, activate_scrollbars=False)
                    params_box.insert("1.0", p_str)
                    params_box.configure(state="disabled")
                    params_box.pack(fill="x", padx=28, pady=(0, 8))
                    params_box.bind("<Button-1>", on_click)
                    params_box.bind("<Button-3>", on_rclick)
                else:
                    ctk.CTkLabel(f, text="", height=4).pack() # Spacer
                
                self.service_widgets[mid] = {"lamp": lamp, "frame": f}

            
            # Update Status Lamp
            color = GRAY_COLOR
            if info['status'] == "ON": color = SUCCESS_COLOR
            elif info['status'] == "OFF": color = ERROR_COLOR
            elif info['status'] == "STARTUP": color = WARNING_COLOR
            elif info['status'] == "BUSY": color = ACCENT_COLOR
            self.service_widgets[mid]['lamp'].configure(text_color=color)

        # 3. Apply Selection Styling
        self._update_selection_ui()

        # 4. Update Loadout Dropdown Color
        if self.controller.current_loadout == "NONE":
            self.loadout_opt.configure(fg_color=GRAY_COLOR)
        elif all(s['status'] == "ON" or s['status'] == "BUSY" for s in health.values()):
            self.loadout_opt.configure(fg_color=SUCCESS_COLOR, text_color="black")
        elif any(s['status'] == "STARTUP" for s in health.values()):
            self.loadout_opt.configure(fg_color="#CCAA00", text_color="white")
        else:
            self.loadout_opt.configure(fg_color=ACCENT_COLOR, text_color="black")

        # 5. Update Record Button
        if runnability.get('runnable'):
            self.record_btn.configure(state="normal", fg_color=ACCENT_COLOR, text="HOLD TO TALK")
        else:
            err = runnability['errors'][0] if runnability['errors'] else "Offline"
            self.record_btn.configure(state="disabled", fg_color=GRAY_COLOR, text=f"OFFLINE: {err}")

    def poll_queue(self):
        while not self.queue.empty():
            msg = self.queue.get()
            if msg['type'] == "log":
                self.terminal.insert("end", f"{msg['msg']}\n"); self.terminal.see("end")
            elif msg['type'] == "state":
                if msg.get('recording'): self.record_btn.configure(fg_color=ERROR_COLOR, text="RECORDING...")
            elif msg['type'] == "health_update":
                self.update_health_ui(
                    msg['health'], 
                    msg['runnability'], 
                    active_models=msg.get('active_models'),
                    vram=msg.get('vram')
                )
        self.after(100, self.poll_queue)

if __name__ == "__main__":
    app = JarvisApp()
    app.mainloop()
