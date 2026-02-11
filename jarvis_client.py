import os
import sys
import time
import json
import threading
import subprocess
import requests
import pyaudio
import wave
import numpy as np
import sounddevice as sd
import customtkinter as ctk
from PIL import Image
import io
import re
import queue
import yaml
from loguru import logger

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_dir)

from tests.utils import get_service_status, kill_process_on_port, load_config, list_all_loadouts, get_system_health, get_loaded_ollama_models

# --- UI CONSTANTS ---
BG_COLOR = "#0B0F19"
ACCENT_COLOR = "#00D1FF"
TEXT_COLOR = "#E0E0E0"
GRAY_COLOR = "#2A2F3E"
SUCCESS_COLOR = "#00FF94"
ERROR_COLOR = "#FF4B4B"
YELLOW_COLOR = "#FFD700"

ctk.set_appearance_mode("dark")

class RingBuffer:
    def __init__(self, size_seconds, rate=16000):
        self.size = size_seconds * rate
        self.buffer = np.zeros(self.size, dtype=np.int16)
        self.ptr = 0

    def extend(self, data):
        data_len = len(data)
        if data_len > self.size:
            data = data[-self.size:]
            data_len = self.size
        end_space = self.size - self.ptr
        if data_len <= end_space:
            self.buffer[self.ptr:self.ptr+data_len] = data
        else:
            self.buffer[self.ptr:] = data[:end_space]
            self.buffer[:data_len-end_space] = data[end_space:]
        self.ptr = (self.ptr + data_len) % self.size

    def get_last(self, seconds, rate=16000):
        length = int(seconds * rate)
        if length > self.size: length = self.size
        if self.ptr >= length:
            return self.buffer[self.ptr-length:self.ptr].copy()
        else:
            part1 = self.buffer[self.size-(length-self.ptr):]
            part2 = self.buffer[:self.ptr]
            return np.concatenate([part1, part2])

class AudioEngine:
    def __init__(self, rate=16000, chunk=1024):
        self.rate = rate
        self.chunk = chunk
        self.p = pyaudio.PyAudio()
        self.ring_buffer = RingBuffer(10, rate)
        self.is_running = True
        self.recording_frames = []
        self.is_capturing = False
        self.vu_level = 0
        self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=self.rate, input=True, frames_per_buffer=self.chunk)
        threading.Thread(target=self._background_listen, daemon=True).start()

    def _background_listen(self):
        while self.is_running:
            try:
                data = self.stream.read(self.chunk, exception_on_overflow=False)
                samples = np.frombuffer(data, dtype=np.int16)
                self.ring_buffer.extend(samples)
                rms = np.sqrt(np.mean(samples.astype(float)**2))
                self.vu_level = min(1.0, rms / 3000.0)
                if self.is_capturing:
                    self.recording_frames.append(data)
            except:
                time.sleep(0.1)

    def start_capture(self):
        pre_roll = self.ring_buffer.get_last(0.5)
        self.recording_frames = [pre_roll.tobytes()]
        self.is_capturing = True

    def stop_capture(self):
        self.is_capturing = False
        return b''.join(self.recording_frames)

    def shutdown(self):
        self.is_running = False
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()

class JarvisController:
    def __init__(self, ui_queue):
        self.ui_queue = ui_queue
        self.cfg = load_config()
        self.audio = AudioEngine()
        self.project_root = os.path.dirname(os.path.abspath(__file__))
        self.s2s_port = self.cfg['ports']['s2s']
        self.s2s_url = f"http://127.0.0.1:{self.s2s_port}"
        self.current_loadout = "base-qwen30-multi"
        self.selected_lang = "None"
        self.interaction_mode = "HOLD"
        self.is_recording = False
        self.server_process = None
        
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

    def toggle_system(self):
        if self.server_process:
            self.ui_queue.put({"type": "log", "msg": "Shutting down system...", "tag": "system"})
            threading.Thread(target=kill_process_on_port, args=(self.s2s_port,), daemon=True).start()
            self.server_process = None
            return False
        else:
            self.ui_queue.put({"type": "log", "msg": f"Starting Loadout: {self.current_loadout}", "tag": "system"})
            threading.Thread(target=self._run_server, daemon=True).start()
            return True

    def kill_service(self, port, label):
        self.ui_queue.put({"type": "log", "msg": f"💀 Killing service: {label} (Port {port})", "tag": "system"})
        threading.Thread(target=kill_process_on_port, args=(port,), daemon=True).start()

    def _run_server(self):
        python_exe = sys.executable
        server_script = os.path.join(self.project_root, "servers", "s2s_server.py")
        cmd = [python_exe, server_script, "--loadout", self.current_loadout]
        
        log_file_path = os.path.join(self.log_dir, "s2s_server.log")
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n--- SESSION START: {time.ctime()} ---\n")
            self.server_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                text=True, encoding='utf-8', bufsize=1, 
                creationflags=0x08000000 if os.name == 'nt' else 0
            )
            
            for line in iter(self.server_process.stdout.readline, ''):
                if line:
                    log_file.write(line)
                    log_file.flush()
                    # Only log critical errors or startup confirmations to the console
                    if "PIPELINE READY" in line or "CRITICAL" in line or "ERROR" in line:
                        self.ui_queue.put({"type": "log", "msg": line.strip(), "tag": "system"})
            
            self.server_process.stdout.close()

    def start_recording(self):
        if self.is_recording: return
        self.is_recording = True
        self.audio.start_capture()
        self.ui_queue.put({"type": "state", "recording": True})

    def stop_recording(self):
        if not self.is_recording: return
        self.is_recording = False
        audio_data = self.audio.stop_capture()
        self.ui_queue.put({"type": "state", "recording": False})
        threading.Thread(target=self._send_request, args=(audio_data,), daemon=True).start()

    def _send_request(self, audio_data):
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(audio_data)
        try:
            files = {'file': ('input.wav', buf.getvalue(), 'audio/wav')}
            data = {}
            if self.selected_lang != "None": data['language_id'] = self.selected_lang
            start_time = time.perf_counter()
            with requests.post(f"{self.s2s_url}/process_stream", files=files, data=data, stream=True) as resp:
                if resp.status_code != 200:
                    self.ui_queue.put({"type": "log", "msg": f"Error {resp.status_code}", "tag": "system"}); return
                audio_stream = sd.RawOutputStream(samplerate=24000, blocksize=1024, channels=1, dtype='int16')
                audio_stream.start()
                stream = resp.raw
                while True:
                    header = stream.read(5)
                    if not header or len(header) < 5: break
                    type_char = chr(header[0])
                    length = int.from_bytes(header[1:], 'little')
                    payload = stream.read(length)
                    if type_char == 'T':
                        data_json = json.loads(payload.decode())
                        # Format: (start s) Text (end s)
                        timestamped_msg = f"({data_json.get('start', 0.0):.2f}s) {data_json['text']} ({data_json.get('end', 0.0):.2f}s)"
                        self.ui_queue.put({"type": "log", "msg": timestamped_msg, "tag": data_json['role']})
                    elif type_char == 'A': audio_stream.write(payload)
                    elif type_char == 'M':
                        m = json.loads(payload.decode())
                        self.ui_queue.put({"type": "telemetry", "metrics": m, "total": time.perf_counter() - start_time}); break
                audio_stream.stop(); audio_stream.close()
        except Exception as e: self.ui_queue.put({"type": "log", "msg": f"Pipeline Error: {e}", "tag": "system"})

class JarvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("JARVIS SYSTEM CONSOLE")
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

        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color="#080C14")
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        
        self.logo = ctk.CTkLabel(self.sidebar, text="⚛️ JARVIS", font=ctk.CTkFont(size=24, weight="bold"), text_color=ACCENT_COLOR)
        self.logo.pack(pady=(20, 20))
        
        self.sidebar_content = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_content.pack(fill="both", expand=True, padx=10)

        # 1. Health Section
        self.status_container = ctk.CTkFrame(self.sidebar_content, fg_color="transparent")
        self.status_container.pack(fill="x", pady=5)
        ctk.CTkLabel(self.status_container, text="HEALTH STATUS", font=ctk.CTkFont(size=11, weight="bold"), text_color=GRAY_COLOR).pack(anchor="w")
        self.init_btn = ctk.CTkButton(self.status_container, text="INITIALIZE SYSTEM", command=self.on_toggle_system, fg_color=GRAY_COLOR, hover_color=ACCENT_COLOR)
        self.init_btn.pack(pady=5, fill="x")
        self.status_frame = ctk.CTkFrame(self.status_container, fg_color="transparent")
        self.status_frame.pack(fill="x", pady=5)
        self.status_rows = {}

        # 2. Config Section (Now directly under health)
        self.config_container = ctk.CTkFrame(self.sidebar_content, fg_color="transparent")
        self.config_container.pack(fill="x", pady=10)
        
        ctk.CTkLabel(self.config_container, text="LOADOUT", font=ctk.CTkFont(size=11, weight="bold"), text_color=GRAY_COLOR).pack(anchor="w")
        self.loadout_var = ctk.StringVar(value=self.controller.current_loadout)
        loadouts = ["None"] + list_all_loadouts()
        self.loadout_drop = ctk.CTkOptionMenu(self.config_container, values=loadouts, variable=self.loadout_var, command=self.on_loadout_change, fg_color=GRAY_COLOR, button_color=GRAY_COLOR)
        self.loadout_drop.pack(pady=5, fill="x")
        self.edit_btn = ctk.CTkButton(self.config_container, text="EDIT YAML", width=80, height=24, fg_color=GRAY_COLOR, command=self.on_edit_yaml)
        self.edit_btn.pack(pady=2, anchor="e")

        ctk.CTkLabel(self.config_container, text="TTS LANGUAGE", font=ctk.CTkFont(size=11, weight="bold"), text_color=GRAY_COLOR).pack(anchor="w", pady=(10,0))
        self.lang_var = ctk.StringVar(value="None")
        self.lang_drop = ctk.CTkOptionMenu(self.config_container, values=["None", "en", "pl", "fr", "zh"], variable=self.lang_var, command=lambda v: setattr(self.controller, 'selected_lang', v))
        self.lang_drop.pack(pady=5, fill="x")

        ctk.CTkLabel(self.config_container, text="INTERACTION", font=ctk.CTkFont(size=11, weight="bold"), text_color=GRAY_COLOR).pack(anchor="w", pady=(10,0))
        self.mode_seg = ctk.CTkSegmentedButton(self.config_container, values=["HOLD", "TOGGLE"], command=lambda v: setattr(self.controller, 'interaction_mode', v))
        self.mode_seg.set("HOLD"); self.mode_seg.pack(pady=5, fill="x")

        # --- Main View ---
        self.telemetry = ctk.CTkFrame(self, fg_color="#0D121F", height=60)
        self.telemetry.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="nsew")
        self.tel_labels = {}
        for key in ["STT", "LLM", "TTS", "TOTAL"]:
            f = ctk.CTkFrame(self.telemetry, fg_color="transparent"); f.pack(side="left", expand=True)
            ctk.CTkLabel(f, text=key, font=ctk.CTkFont(size=9, weight="bold"), text_color=GRAY_COLOR).pack()
            l = ctk.CTkLabel(f, text="0.00s", font=ctk.CTkFont(family="Consolas", size=14), text_color=ACCENT_COLOR); l.pack()
            self.tel_labels[key] = l

        self.console = ctk.CTkTextbox(self, fg_color="#080C14", border_color=GRAY_COLOR, border_width=1, font=ctk.CTkFont(family="Consolas", size=13))
        self.console.grid(row=1, column=1, padx=20, pady=10, sticky="nsew")
        self.console.tag_config("user", foreground=ACCENT_COLOR); self.console.tag_config("jarvis", foreground=SUCCESS_COLOR); self.console.tag_config("system", foreground=GRAY_COLOR)

        self.interaction_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.interaction_frame.grid(row=2, column=1, padx=20, pady=20, sticky="nsew")
        self.talk_btn = ctk.CTkButton(self.interaction_frame, text="HOLD TO TALK", height=80, corner_radius=40, fg_color=GRAY_COLOR, font=ctk.CTkFont(size=18, weight="bold"))
        self.talk_btn.pack(side="left", expand=True, fill="both", padx=(0, 10))
        self.talk_btn.bind("<Button-1>", self.on_press); self.talk_btn.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<KeyPress-space>", self.on_press); self.bind("<KeyRelease-space>", self.on_release)
        self.vu_canvas = ctk.CTkCanvas(self.interaction_frame, width=20, height=80, bg="#080C14", highlightthickness=0); self.vu_canvas.pack(side="right")
        self.vu_bar = self.vu_canvas.create_rectangle(0, 80, 20, 80, fill=ACCENT_COLOR, outline="")

    def on_toggle_system(self):
        if self.controller.toggle_system(): self.init_btn.configure(text="STOP SYSTEM", fg_color=ERROR_COLOR)
        else: self.init_btn.configure(text="INITIALIZE SYSTEM", fg_color=GRAY_COLOR)

    def on_loadout_change(self, val):
        self.controller.current_loadout = val
        if self.controller.server_process: self.on_toggle_system(); self.on_toggle_system()

    def on_edit_yaml(self):
        top = ctk.CTkToplevel(self); top.title(f"Editor: {self.loadout_var.get()}"); top.geometry("600x400")
        path = os.path.join(self.controller.project_root, "tests", "loadouts", f"{self.loadout_var.get()}.yaml")
        with open(path, "r") as f: content = f.read()
        txt = ctk.CTkTextbox(top, font=ctk.CTkFont(family="Consolas", size=12)); txt.pack(fill="both", expand=True, padx=10, pady=10); txt.insert("1.0", content)
        def save():
            with open(path, "w") as f: f.write(txt.get("1.0", "end"))
            top.destroy()
        ctk.CTkButton(top, text="SAVE", command=save, fg_color=SUCCESS_COLOR, text_color="black").pack(pady=10)

    def on_press(self, event=None):
        if self.controller.interaction_mode == "TOGGLE":
            if self.controller.is_recording: self.controller.stop_recording()
            else: self.controller.start_recording()
        else:
            self.controller.start_recording()

    def on_release(self, event=None):
        if self.controller.interaction_mode == "HOLD": self.controller.stop_recording()

    def poll_queue(self):
        while not self.queue.empty():
            item = self.queue.get()
            if item['type'] == "log":
                self.console.insert("end", f"[{time.strftime('%H:%M:%S')}] ", "system")
                prefix = "YOU > " if item['tag'] == "user" else "JARVIS > " if item['tag'] == "jarvis" else "SYS  > "
                self.console.insert("end", f"{prefix}{item['msg']}\n", item['tag']); self.console.see("end")
            elif item['type'] == "state":
                if item.get('recording'): self.talk_btn.configure(fg_color=ERROR_COLOR, text="LISTENING...")
                else: self.talk_btn.configure(fg_color=ACCENT_COLOR, text=f"{self.controller.interaction_mode} TO TALK")
            elif item['type'] == "telemetry":
                m = item['metrics']
                self.tel_labels["STT"].configure(text=f"{m.get('stt',[0,0])[1]:.2f}s")
                self.tel_labels["LLM"].configure(text=f"{m.get('llm',[0,0])[1]-m.get('llm',[0,0])[0]:.2f}s")
                self.tel_labels["TTS"].configure(text=f"{m.get('tts',[0,0])[1]-m.get('tts',[0,0])[0]:.2f}s")
                self.tel_labels["TOTAL"].configure(text=f"{item['total']:.2f}s")
        self.vu_canvas.coords(self.vu_bar, 0, 80 - (self.controller.audio.vu_level * 80), 20, 80)
        self.after(50, self.poll_queue)

    def poll_status(self):
        health = self.controller.health_state
        loaded_ollama = self.controller.loaded_ollama_models
        
        active_ports = set()
        active_llm = None
        
        if self.controller.current_loadout != "None":
            path = os.path.join(self.controller.project_root, "tests", "loadouts", f"{self.controller.current_loadout}.yaml")
            if os.path.exists(path):
                with open(path, "r") as f:
                    l = yaml.safe_load(f)
                    active_llm = l.get('llm')
                    active_ports.add(self.controller.cfg['ports']['s2s'])
                    active_ports.add(self.controller.cfg['ports']['llm'])
                    if l.get('stt'): active_ports.add(self.controller.cfg['stt_loadout'][l['stt'][0]])
                    if l.get('tts'): active_ports.add(self.controller.cfg['tts_loadout'][l['tts'][0]])

        # Create a sorted list of ports to maintain consistent UI order
        sorted_ports = sorted(health.keys())

        for port in sorted_ports:
            info = health[port]
            status = info['status']
            is_active = port in active_ports
            
            # Logic:
            # 1. If status is ON/STARTUP/BUSY, always show it.
            # 2. If status is OFF, only show it if it's in the active loadout.
            
            is_rogue = not is_active and status != "OFF"
            
            # Special Ollama Check: Model mismatch is always rogue (Yellow)
            if info['label'] == "LLM" and status == "ON":
                if active_llm and not any(active_llm in m for m in loaded_ollama):
                    is_rogue = True

            should_show = (status != "OFF") or is_active

            if should_show:
                if port not in self.status_rows:
                    row = ctk.CTkFrame(self.status_frame, fg_color="transparent"); row.pack(fill="x", pady=1)
                    lbl = ctk.CTkLabel(row, text=info['label'][:15], font=ctk.CTkFont(size=10, weight="bold"), text_color=TEXT_COLOR); lbl.pack(side="left")
                    val = ctk.CTkLabel(row, text="...", font=ctk.CTkFont(size=9), text_color=GRAY_COLOR); val.pack(side="left", padx=5)
                    
                    # Kill Button (Skull)
                    kill_btn = ctk.CTkButton(row, text="💀", width=20, height=20, fg_color="transparent", hover_color=ERROR_COLOR, 
                                            command=lambda p=port, l=info['label']: self.controller.kill_service(p, l))
                    kill_btn.pack(side="right", padx=2)
                    
                    dot = ctk.CTkLabel(row, text="●", font=ctk.CTkFont(size=12)); dot.pack(side="right")
                    self.status_rows[port] = {"frame": row, "val": val, "dot": dot, "kill_btn": kill_btn}
                
                color = YELLOW_COLOR if is_rogue else (SUCCESS_COLOR if status == "ON" else YELLOW_COLOR if status == "STARTUP" else ERROR_COLOR if status == "UNHEALTHY" else GRAY_COLOR)
                text = (info['info'] or "READY") if not is_rogue else f"ROGUE: {info['info'] or 'BUSY'}"
                if info['label'] == "LLM" and is_rogue: 
                    model_name = loaded_ollama[0] if loaded_ollama else "EMPTY"
                    text = f"WRONG MODEL: {model_name}"
                
                self.status_rows[port]["dot"].configure(text_color=color)
                self.status_rows[port]["val"].configure(text=text, text_color=color if status != "OFF" else GRAY_COLOR)
                
                # Only show skull if service is actually running (not OFF)
                if status == "OFF":
                    self.status_rows[port]["kill_btn"].configure(state="disabled", text="")
                else:
                    self.status_rows[port]["kill_btn"].configure(state="normal", text="💀")
            else:
                if port in self.status_rows:
                    self.status_rows[port]["frame"].destroy()
                    del self.status_rows[port]

        s2s_on = health.get(self.controller.cfg['ports']['s2s'], {}).get('status') == "ON"
        if not self.controller.is_recording:
            self.talk_btn.configure(state="normal" if s2s_on else "disabled", fg_color=ACCENT_COLOR if s2s_on else GRAY_COLOR, text=f"{self.controller.interaction_mode} TO TALK" if s2s_on else "SYSTEM OFFLINE")
        self.after(500, self.poll_status)

if __name__ == "__main__":
    app = JarvisApp()
    try: app.mainloop()
    finally:
        app.controller.is_polling = False
        app.controller.audio.shutdown()
