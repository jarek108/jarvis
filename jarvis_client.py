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

from manage_loadout import apply_loadout, kill_loadout

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
        
        # 1. Embedded Flow Engine
        self.resolver = PipelineResolver(self.project_root)
        self.executor = PipelineExecutor(self.project_root)
        
        # 2. Edge Hardware Adapters
        self.audio_sensor = AudioSensor()
        
        # 3. State
        self.current_pipeline = "voice_to_voice"
        self.current_strategy = "fast_interaction"
        self.current_loadout = "NONE"
        self.load_checkpoint()
        
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
                    self.current_loadout = data.get("loadout", self.current_loadout)
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
                active_models = self.resolver.get_live_models()
                active_ports = [m['port'] for m in active_models]
                self.health_state = get_system_health(ports=active_ports)
                
                # 2. Check Logical Runnability (Passing existing health to avoid double-poll)
                self.runnability = self.resolver.check_runnability(self.current_pipeline, self.current_strategy, external_health=self.health_state)
                
                # 3. Update UI
                self.ui_queue.put({
                    "type": "health_update", 
                    "health": self.health_state, 
                    "runnability": self.runnability,
                    "active_models": active_models
                })
            except Exception as e:
                logger.error(f"Status Polling Error: {e}")
            time.sleep(1.5)

    def trigger_loadout_change(self, loadout_id):
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

class JarvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("JARVIS CORE CONSOLE")
        self.geometry("1200x850")
        self.configure(fg_color=BG_COLOR)
        self.queue = queue.Queue()
        self.controller = JarvisController(self.queue)
        self.setup_ui()
        self.poll_queue()

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
        self.loadout_opt.pack(pady=(0, 20), padx=10)

        ctk.CTkLabel(self.sidebar, text="ACTIVE MODELS", font=("Impact", 16), text_color=GRAY_COLOR).pack(pady=(10, 5))
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

        # --- MAIN ---
        self.terminal = ctk.CTkTextbox(self, font=("Consolas", 13), fg_color=BG_COLOR, text_color=TEXT_COLOR)
        self.terminal.grid(row=1, column=1, sticky="nsew", padx=15, pady=15)
        
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

    def on_loadout_change(self, val):
        self.controller.trigger_loadout_change(val)
        # Clear health frame on change to force a fresh rebuild
        for widget in self.health_frame.winfo_children():
            widget.destroy()
        self.service_widgets = {}

    def update_health_ui(self, health, runnability, active_models=None):
        # 1. Update Service Sidebar (Precise Model List)
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
                f = ctk.CTkFrame(self.health_frame, fg_color="#12161E", corner_radius=6)
                f.pack(fill="x", pady=4, padx=5)
                
                # Header: Lamp + ID
                header = ctk.CTkFrame(f, fg_color="transparent")
                header.pack(fill="x", padx=5, pady=(5, 0))
                lamp = ctk.CTkLabel(header, text="●", font=("Arial", 18))
                lamp.pack(side="left", padx=2)
                name = ctk.CTkLabel(header, text=mid, font=("Consolas", 12, "bold"), anchor="w", justify="left")
                name.pack(side="left", fill="x", expand=True)
                
                # Subtext: Engine + Caps
                caps_str = " | ".join(m.get('capabilities', []))
                subtext = ctk.CTkLabel(f, text=f"{m['engine'].upper()} • {caps_str}", font=("Consolas", 10), text_color=GRAY_COLOR, anchor="w")
                subtext.pack(fill="x", padx=25, pady=(0, 2))
                
                # Params: num_ctx, etc.
                if m.get('params'):
                    p_str = " ".join([f"{k}:{v}" for k, v in m['params'].items()])
                    params = ctk.CTkLabel(f, text=p_str, font=("Consolas", 9), text_color="#5A6070", anchor="w", wraplength=180)
                    params.pack(fill="x", padx=25, pady=(0, 5))
                
                self.service_widgets[mid] = {"lamp": lamp, "frame": f}
            
            color = GRAY_COLOR
            if info['status'] == "ON": color = SUCCESS_COLOR
            elif info['status'] == "OFF": color = ERROR_COLOR
            elif info['status'] == "STARTUP": color = WARNING_COLOR
            elif info['status'] == "BUSY": color = ACCENT_COLOR
            
            self.service_widgets[mid]['lamp'].configure(text_color=color)

        # 2. Update Loadout Dropdown Color
        if self.controller.current_loadout == "NONE":
            self.loadout_opt.configure(fg_color=GRAY_COLOR)
        elif all(s['status'] == "ON" or s['status'] == "BUSY" for s in health.values()):
            self.loadout_opt.configure(fg_color=SUCCESS_COLOR)
        elif any(s['status'] == "STARTUP" for s in health.values()):
            self.loadout_opt.configure(fg_color=WARNING_COLOR)
        else:
            self.loadout_opt.configure(fg_color=ACCENT_COLOR)

        # 3. Update Record Button
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
                self.update_health_ui(msg['health'], msg['runnability'], active_models=msg.get('active_models'))
        self.after(100, self.poll_queue)

if __name__ == "__main__":
    app = JarvisApp()
    app.mainloop()
