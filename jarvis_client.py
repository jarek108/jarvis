import os
import sys
import time
import json
import threading
import subprocess
import wave
import numpy as np
import sounddevice as sd
import customtkinter as ctk
from PIL import Image
import io
import re
import queue
import yaml
import asyncio
from loguru import logger

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

import utils
from utils import load_config, list_all_loadouts, get_system_health, get_loaded_ollama_models, kill_all_jarvis_services, kill_process_on_port
from utils.pipeline import PipelineResolver, PipelineExecutor
from utils.edge_sensors import AudioSensor, ScreenSensor, ClipboardSensor
from utils.edge_actuators import AudioActuator, KeyboardActuator, NotificationActuator

# --- UI CONSTANTS ---
BG_COLOR = "#0B0F19"
ACCENT_COLOR = "#00D1FF"
TEXT_COLOR = "#E0E0E0"
GRAY_COLOR = "#2A2F3E"
SUCCESS_COLOR = "#00FF94"
ERROR_COLOR = "#FF4B4B"
YELLOW_COLOR = "#FFD700"

ctk.set_appearance_mode("dark")

class JarvisController:
    def __init__(self, ui_queue):
        self.ui_queue = ui_queue
        self.cfg = load_config()
        self.project_root = os.path.dirname(os.path.abspath(__file__))
        
        # 1. Embedded Flow Engine
        self.resolver = PipelineResolver(self.project_root)
        self.executor = PipelineExecutor(self.project_root)
        
        # 2. Edge Hardware Adapters
        self.audio_sensor = AudioSensor()
        self.screen_sensor = ScreenSensor()
        self.clipboard_sensor = ClipboardSensor()
        
        self.current_loadout = "base-qwen30-multi"
        self.current_pipeline = "voice_to_voice"
        self.selected_lang = "None"
        self.interaction_mode = "HOLD"
        self.is_recording = False
        self.is_playing = False
        self.interrupt_request = False
        
        # Debounce / Slip protection
        self._stop_timer = None
        
        # State sharing
        self.health_state = {}
        self.loaded_ollama_models = []
        self.is_polling = True
        
        # Logs dir
        self.log_dir = os.path.join(self.project_root, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        threading.Thread(target=self._status_polling_loop, daemon=True).start()

    def _status_polling_loop(self):
        interval = self.cfg.get('system', {}).get('health_check_interval', 2.0)
        while self.is_polling:
            try:
                self.health_state = get_system_health()
                self.loaded_ollama_models = get_loaded_ollama_models()
            except Exception as e:
                logger.error(f"Status Polling Error: {e}")
            time.sleep(interval)

    def kill_service(self, port, label):
        self.ui_queue.put({"type": "log", "msg": f"💀 Killing service: {label} (Port {port})", "tag": "system"})
        threading.Thread(target=kill_process_on_port, args=(port,), daemon=True).start()

    def purge_system(self):
        self.ui_queue.put({"type": "log", "msg": "☢️ PURGING SYSTEM: Killing all workers and clearing VRAM...", "tag": "system"})
        threading.Thread(target=kill_all_jarvis_services, daemon=True).start()

    def start_recording(self):
        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None
            return
        if self.is_recording: return
        self.is_recording = True
        # NOTE: Real streaming audio capture logic would go here
        # For Phase 1 of embedded, we just signal the state
        self.ui_queue.put({"type": "state", "recording": True})

    def stop_recording(self):
        if not self.is_recording or self._stop_timer: return
        if self.interaction_mode == "HOLD":
            self._stop_timer = threading.Timer(0.3, self._finalize_recording)
            self._stop_timer.start()
        else:
            self._finalize_recording()

    def _finalize_recording(self):
        self._stop_timer = None
        self.is_recording = False
        self.ui_queue.put({"type": "state", "recording": False})
        
        # 1. Physical Capture
        self.ui_queue.put({"type": "log", "msg": "Capturing audio...", "tag": "system"})
        audio_data = self.audio_sensor.capture_snapshot(duration=3.0) # Placeholder duration
        
        # 2. Local Execution
        self.ui_queue.put({"type": "log", "msg": "Thinking...", "tag": "system"})
        threading.Thread(target=self._run_pipeline_local, args=(audio_data,), daemon=True).start()

    def _run_pipeline_local(self, audio_data):
        # Create temp file for the engine (until we support raw bytes in sensors)
        temp_audio = os.path.join(self.project_root, "buffers", "user_voice.wav")
        os.makedirs(os.path.dirname(temp_audio), exist_ok=True)
        with open(temp_audio, "wb") as f: f.write(audio_data)

        # 1. Resolve Graph
        try:
            # Note: We assume the loadout is already applied via manage_loadout.py
            bound_graph = self.resolver.resolve(self.current_pipeline)
        except Exception as e:
            self.ui_queue.put({"type": "log", "msg": f"Resolution Error: {e}", "tag": "system"})
            return

        # 2. Prepare Inputs
        inputs = {
            "input_mic": temp_audio,
            "input_instruction": "",
            "language": self.selected_lang if self.selected_lang != "None" else "en"
        }

        # 3. Monitor Execution (via Trace)
        async def run_and_monitor():
            # Run the engine
            exec_task = asyncio.create_task(self.executor.run(bound_graph, inputs))
            
            # Watch the trace and push to UI
            last_idx = 0
            while not exec_task.done() or last_idx < len(self.executor.trace):
                while last_idx < len(self.executor.trace):
                    packet = self.executor.trace[last_idx]
                    last_idx += 1
                    if packet.get('dir') == 'OUT':
                        ptype = packet.get('type')
                        content = packet.get('content')
                        if ptype in ["text_token", "text_sentence", "text_final"]:
                            self.ui_queue.put({"type": "log", "msg": str(content), "tag": "assistant"})
                await asyncio.sleep(0.05)
            
            self.ui_queue.put({"type": "log", "msg": "Processing complete.", "tag": "system"})

        asyncio.run(run_and_monitor())

    def interrupt(self):
        # In embedded mode, we can directly stop the executor/adapters
        self.interrupt_request = True
        self.ui_queue.put({"type": "log", "msg": "Interrupting...", "tag": "system"})

# --- UI LAYER (Remains largely the same, but simplified) ---

class JarvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("JARVIS EMBEDDED CONSOLE")
        self.geometry("1100x800")
        self.configure(fg_color=BG_COLOR)
        self.queue = queue.Queue()
        self.controller = JarvisController(self.queue)
        self.setup_ui()
        self.poll_queue()
        self.poll_status()

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color="#080C14")
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        
        # Header
        self.header = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color="#0D1117")
        self.header.grid(row=0, column=1, sticky="ew")
        
        # Terminal / Log View
        self.terminal = ctk.CTkTextbox(self, font=("Consolas", 13), fg_color=BG_COLOR, text_color=TEXT_COLOR)
        self.terminal.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
        
        # Controls
        self.controls = ctk.CTkFrame(self, height=100, fg_color="#0D1117")
        self.controls.grid(row=2, column=1, sticky="ew")
        
        self.record_btn = ctk.CTkButton(self.controls, text="HOLD TO TALK", fg_color=ACCENT_COLOR, text_color="black")
        self.record_btn.pack(pady=20, padx=20, side="left")
        self.record_btn.bind("<Button-1>", lambda e: self.controller.start_recording())
        self.record_btn.bind("<ButtonRelease-1>", lambda e: self.controller.stop_recording())

    def poll_queue(self):
        while not self.queue.empty():
            msg = self.queue.get()
            if msg['type'] == "log":
                self.terminal.insert("end", f"{msg['msg']}\n")
                self.terminal.see("end")
            elif msg['type'] == "state":
                if msg.get('recording'): self.record_btn.configure(fg_color=ERROR_COLOR, text="RECORDING...")
                else: self.record_btn.configure(fg_color=ACCENT_COLOR, text="HOLD TO TALK")
        self.after(100, self.poll_queue)

    def poll_status(self):
        # Update sidebar with health info
        self.after(2000, self.poll_status)

if __name__ == "__main__":
    app = JarvisApp()
    app.mainloop()
