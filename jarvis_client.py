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

from tests.utils import get_service_status, kill_process_on_port, load_config, list_all_loadouts

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
        self.ring_buffer = RingBuffer(10, rate) # 10s ring buffer
        self.is_running = True
        self.recording_frames = []
        self.is_capturing = False
        self.vu_level = 0
        
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk
        )
        
        threading.Thread(target=self._background_listen, daemon=True).start()

    def _background_listen(self):
        while self.is_running:
            try:
                data = self.stream.read(self.chunk, exception_on_overflow=False)
                samples = np.frombuffer(data, dtype=np.int16)
                self.ring_buffer.extend(samples)
                
                # Calculate VU level (RMS)
                rms = np.sqrt(np.mean(samples.astype(float)**2))
                self.vu_level = min(1.0, rms / 3000.0) # Normalized 0-1
                
                if self.is_capturing:
                    self.recording_frames.append(data)
            except:
                time.sleep(0.1)

    def start_capture(self):
        # Grab 0.5s pre-roll
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
        self.selected_lang = "en"
        self.interaction_mode = "HOLD" # "HOLD" or "TOGGLE"
        self.is_recording = False
        self.server_process = None

    def toggle_system(self):
        if self.server_process:
            self.ui_queue.put({"type": "log", "msg": "Shutting down system...", "tag": "system"})
            kill_process_on_port(self.s2s_port)
            self.server_process = None
            return False
        else:
            self.ui_queue.put({"type": "log", "msg": f"Starting Loadout: {self.current_loadout}", "tag": "system"})
            threading.Thread(target=self._run_server, daemon=True).start()
            return True

    def _run_server(self):
        python_exe = sys.executable
        server_script = os.path.join(self.project_root, "servers", "s2s_server.py")
        cmd = [python_exe, server_script, "--loadout", self.current_loadout]
        
        self.server_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, encoding='utf-8', bufsize=1,
            creationflags=0x08000000 if os.name == 'nt' else 0
        )
        
        for line in iter(self.server_process.stdout.readline, ''):
            if line:
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
        
        # Dispatch request
        self.ui_queue.put({"type": "log", "msg": "Thinking...", "tag": "system"})
        threading.Thread(target=self._send_request, args=(audio_data,), daemon=True).start()

    def _send_request(self, audio_data):
        # Convert to WAV
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2) # 16-bit
            wf.setframerate(16000)
            wf.writeframes(audio_data)
        
        try:
            files = {'file': ('input.wav', buf.getvalue(), 'audio/wav')}
            data = {'language_id': self.selected_lang}
            
            start_time = time.perf_counter()
            with requests.post(f"{self.s2s_url}/process_stream", files=files, data=data, stream=True) as resp:
                if resp.status_code != 200:
                    self.ui_queue.put({"type": "log", "msg": f"Error {resp.status_code}", "tag": "system"})
                    return

                # Setup audio playback
                sample_rate = 24000
                audio_stream = sd.RawOutputStream(samplerate=sample_rate, blocksize=1024, channels=1, dtype='int16')
                audio_stream.start()

                # PROTOCOL PARSER
                # [TYPE(1b)][LEN(4b)][DATA(LENb)]
                stream = resp.raw
                while True:
                    header = stream.read(5)
                    if not header or len(header) < 5:
                        break
                    
                    type_char = chr(header[0])
                    length = int.from_bytes(header[1:], 'little')
                    payload = stream.read(length)
                    
                    if type_char == 'T': # Text Frame
                        data = json.loads(payload.decode())
                        self.ui_queue.put({"type": "log", "msg": data['text'], "tag": data['role']})
                    elif type_char == 'A': # Audio Frame
                        audio_stream.write(payload)
                    elif type_char == 'M': # Metrics Frame
                        m = json.loads(payload.decode())
                        self.ui_queue.put({"type": "telemetry", "metrics": m, "total": time.perf_counter() - start_time})
                        break
                
                audio_stream.stop()
                audio_stream.close()
        except Exception as e:
            self.ui_queue.put({"type": "log", "msg": f"Pipeline Error: {e}", "tag": "system"})

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
        self.logo.pack(pady=(20, 5))
        self.sub_logo = ctk.CTkLabel(self.sidebar, text="BLACKWELL ENGINE V2", font=ctk.CTkFont(size=10), text_color=GRAY_COLOR)
        self.sub_logo.pack(pady=(0, 20))

        self.tabs = ctk.CTkTabview(self.sidebar, fg_color="transparent", segmented_button_selected_color=ACCENT_COLOR)
        self.tabs.pack(fill="both", expand=True, padx=10)
        
        self.tab_status = self.tabs.add("SYSTEM")
        self.tab_config = self.tabs.add("CONFIG")

        # --- System Tab ---
        self.init_btn = ctk.CTkButton(self.tab_status, text="INITIALIZE SYSTEM", command=self.on_toggle_system, 
                                     fg_color=GRAY_COLOR, hover_color=ACCENT_COLOR)
        self.init_btn.pack(pady=10, fill="x")

        self.status_frame = ctk.CTkFrame(self.tab_status, fg_color="transparent")
        self.status_frame.pack(pady=10, fill="x")
        
        self.status_indicators = {}
        for key in ["S2S", "LLM", "STT", "TTS"]:
            row = ctk.CTkFrame(self.status_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            lbl = ctk.CTkLabel(row, text=key, font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_COLOR)
            lbl.pack(side="left")
            val = ctk.CTkLabel(row, text="OFFLINE", font=ctk.CTkFont(size=10), text_color=GRAY_COLOR)
            val.pack(side="left", padx=10)
            dot = ctk.CTkLabel(row, text="●", text_color=GRAY_COLOR, font=ctk.CTkFont(size=14))
            dot.pack(side="right")
            self.status_indicators[key] = {"dot": dot, "val": val}

        # --- Config Tab ---
        ctk.CTkLabel(self.tab_config, text="LOADOUT", font=ctk.CTkFont(size=11, weight="bold")).pack(pady=(10,0), anchor="w", padx=20)
        self.loadout_var = ctk.StringVar(value=self.controller.current_loadout)
        self.loadout_drop = ctk.CTkOptionMenu(self.tab_config, values=list_all_loadouts(), variable=self.loadout_var, 
                                             command=self.on_loadout_change, fg_color=GRAY_COLOR, button_color=GRAY_COLOR, dropdown_fg_color=GRAY_COLOR)
        self.loadout_drop.pack(pady=5, padx=20, fill="x")

        self.edit_btn = ctk.CTkButton(self.tab_config, text="EDIT YAML", width=80, height=24, fg_color=GRAY_COLOR, command=self.on_edit_yaml)
        self.edit_btn.pack(pady=5, padx=20, anchor="e")

        ctk.CTkLabel(self.tab_config, text="TTS LANGUAGE", font=ctk.CTkFont(size=11, weight="bold")).pack(pady=(10,0), anchor="w", padx=20)
        self.lang_var = ctk.StringVar(value="en")
        self.lang_drop = ctk.CTkOptionMenu(self.tab_config, values=["en", "pl", "fr", "zh"], variable=self.lang_var,
                                          command=lambda v: setattr(self.controller, 'selected_lang', v))
        self.lang_drop.pack(pady=5, padx=20, fill="x")

        ctk.CTkLabel(self.tab_config, text="INTERACTION", font=ctk.CTkFont(size=11, weight="bold")).pack(pady=(10,0), anchor="w", padx=20)
        self.mode_var = ctk.StringVar(value="HOLD TO TALK")
        self.mode_seg = ctk.CTkSegmentedButton(self.tab_config, values=["HOLD", "TOGGLE"], 
                                              command=lambda v: setattr(self.controller, 'interaction_mode', v))
        self.mode_seg.set("HOLD")
        self.mode_seg.pack(pady=5, padx=20, fill="x")

        # --- Main View ---
        self.telemetry = ctk.CTkFrame(self, fg_color="#0D121F", height=60)
        self.telemetry.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="nsew")
        
        self.tel_labels = {}
        for i, key in enumerate(["STT", "LLM", "TTS", "TOTAL"]):
            f = ctk.CTkFrame(self.telemetry, fg_color="transparent")
            f.pack(side="left", expand=True)
            ctk.CTkLabel(f, text=key, font=ctk.CTkFont(size=9, weight="bold"), text_color=GRAY_COLOR).pack()
            l = ctk.CTkLabel(f, text="0.00s", font=ctk.CTkFont(family="Consolas", size=14), text_color=ACCENT_COLOR)
            l.pack()
            self.tel_labels[key] = l

        self.console = ctk.CTkTextbox(self, fg_color="#080C14", border_color=GRAY_COLOR, border_width=1, font=ctk.CTkFont(family="Consolas", size=13))
        self.console.grid(row=1, column=1, padx=20, pady=10, sticky="nsew")
        self.console.tag_config("user", foreground=ACCENT_COLOR)
        self.console.tag_config("jarvis", foreground=SUCCESS_COLOR)
        self.console.tag_config("system", foreground=GRAY_COLOR)

        self.interaction_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.interaction_frame.grid(row=2, column=1, padx=20, pady=20, sticky="nsew")
        
        self.talk_btn = ctk.CTkButton(self.interaction_frame, text="HOLD TO TALK", height=80, corner_radius=40,
                                     fg_color=GRAY_COLOR, font=ctk.CTkFont(size=18, weight="bold"))
        self.talk_btn.pack(side="left", expand=True, fill="both", padx=(0, 10))
        
        # Bindings
        self.talk_btn.bind("<Button-1>", self.on_press)
        self.talk_btn.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<KeyPress-space>", self.on_press)
        self.bind("<KeyRelease-space>", self.on_release)

        # VU Meter
        self.vu_canvas = ctk.CTkCanvas(self.interaction_frame, width=20, height=80, bg="#080C14", highlightthickness=0)
        self.vu_canvas.pack(side="right")
        self.vu_bar = self.vu_canvas.create_rectangle(0, 80, 20, 80, fill=ACCENT_COLOR, outline="")

    def on_toggle_system(self):
        is_starting = self.controller.toggle_system()
        if is_starting:
            self.init_btn.configure(text="STOP SYSTEM", fg_color=ERROR_COLOR)
        else:
            self.init_btn.configure(text="INITIALIZE SYSTEM", fg_color=GRAY_COLOR)

    def on_loadout_change(self, val):
        self.controller.current_loadout = val
        if self.controller.server_process:
            self.on_toggle_system() # Stop
            self.on_toggle_system() # Start with new

    def on_edit_yaml(self):
        # Simple top-level editor
        top = ctk.CTkToplevel(self)
        top.title(f"Editor: {self.loadout_var.get()}")
        top.geometry("600x400")
        
        path = os.path.join(self.controller.project_root, "tests", "loadouts", f"{self.loadout_var.get()}.yaml")
        with open(path, "r") as f: content = f.read()
        
        txt = ctk.CTkTextbox(top, font=ctk.CTkFont(family="Consolas", size=12))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", content)
        
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
        if self.controller.interaction_mode == "HOLD":
            self.controller.stop_recording()

    def poll_queue(self):
        while not self.queue.empty():
            item = self.queue.get()
            if item['type'] == "log":
                self.console.insert("end", f"[{time.strftime('%H:%M:%S')}] ", "system")
                prefix = "YOU > " if item['tag'] == "user" else "JARVIS > " if item['tag'] == "jarvis" else "SYS  > "
                self.console.insert("end", f"{prefix}{item['msg']}\n", item['tag'])
                self.console.see("end")
            elif item['type'] == "state":
                if item.get('recording'):
                    self.talk_btn.configure(fg_color=ERROR_COLOR, text="LISTENING...")
                else:
                    self.talk_btn.configure(fg_color=ACCENT_COLOR, text=self.mode_var.get())
            elif item['type'] == "telemetry":
                m = item['metrics']
                self.tel_labels["STT"].configure(text=f"{m.get('stt',[0,0])[1]:.2f}s")
                self.tel_labels["LLM"].configure(text=f"{m.get('llm',[0,0])[1]-m.get('llm',[0,0])[0]:.2f}s")
                self.tel_labels["TTS"].configure(text=f"{m.get('tts',[0,0])[1]-m.get('tts',[0,0])[0]:.2f}s")
                self.tel_labels["TOTAL"].configure(text=f"{item['total']:.2f}s")
        
        # Update VU Meter
        level = self.controller.audio.vu_level
        self.vu_canvas.coords(self.vu_bar, 0, 80 - (level * 80), 20, 80)
        
        self.after(50, self.poll_queue)

    def poll_status(self):
        cfg = self.controller.cfg
        # We only check ports relevant to active loadout to be clean
        ports = {
            "S2S": cfg['ports']['s2s'],
            "LLM": cfg['ports']['llm']
        }
        # Get active models from loadout
        path = os.path.join(self.controller.project_root, "tests", "loadouts", f"{self.controller.current_loadout}.yaml")
        if os.path.exists(path):
            with open(path, "r") as f:
                l = yaml.safe_load(f)
                if l.get('stt'): ports["STT"] = cfg['stt_loadout'][l['stt'][0]]
                if l.get('tts'): ports["TTS"] = cfg['tts_loadout'][l['tts'][0]]

        for key, port in ports.items():
            status, info = get_service_status(port)
            color = SUCCESS_COLOR if status == "ON" else YELLOW_COLOR if status == "STARTUP" else ERROR_COLOR if status == "UNHEALTHY" else GRAY_COLOR
            self.status_indicators[key]["dot"].configure(text_color=color)
            self.status_indicators[key]["val"].configure(text=info or "OFFLINE", text_color=color if status != "OFF" else GRAY_COLOR)
        
        # Update button availability
        s2s_on = get_service_status(cfg['ports']['s2s'])[0] == "ON"
        if not self.controller.is_recording:
            self.talk_btn.configure(state="normal" if s2s_on else "disabled", 
                                   fg_color=ACCENT_COLOR if s2s_on else GRAY_COLOR,
                                   text=f"{self.controller.interaction_mode} TO TALK" if s2s_on else "SYSTEM OFFLINE")

        self.after(2000, self.poll_status)

if __name__ == "__main__":
    app = JarvisApp()
    try:
        app.mainloop()
    finally:
        app.controller.audio.shutdown()
