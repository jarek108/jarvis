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

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_dir)

from tests.utils import get_service_status, kill_process_on_port, load_config

# --- UI CONSTANTS ---
BG_COLOR = "#0B0F19"
ACCENT_COLOR = "#00D1FF"
TEXT_COLOR = "#E0E0E0"
GRAY_COLOR = "#2A2F3E"
SUCCESS_COLOR = "#00FF94"
ERROR_COLOR = "#FF4B4B"

ctk.set_appearance_mode("dark")

class JarvisClient(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("JARVIS SYSTEM CONSOLE")
        self.geometry("900x700")
        self.configure(fg_color=BG_COLOR)

        # State
        self.server_process = None
        self.is_recording = False
        self.audio_frames = []
        self.stream = None
        self.p = pyaudio.PyAudio()
        self.cfg = load_config()
        self.s2s_port = self.cfg['ports']['s2s']
        self.s2s_url = f"http://127.0.0.1:{self.s2s_port}"

        self.setup_ui()
        self.update_status_loop()

    def setup_ui(self):
        # Grid layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Sidebar (Infrastructure) ---
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color="#080C14")
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="⚛️ JARVIS", font=ctk.CTkFont(size=24, weight="bold"), text_color=ACCENT_COLOR)
        self.logo_label.pack(pady=(20, 10))
        
        self.sub_label = ctk.CTkLabel(self.sidebar, text="BLACKWELL CORE V1", font=ctk.CTkFont(size=10), text_color=GRAY_COLOR)
        self.sub_label.pack(pady=(0, 20))

        self.init_btn = ctk.CTkButton(self.sidebar, text="INITIALIZE SYSTEM", command=self.toggle_server, 
                                     fg_color=GRAY_COLOR, hover_color=ACCENT_COLOR, text_color=TEXT_COLOR)
        self.init_btn.pack(pady=10, padx=20, fill="x")

        # Status Panel
        self.status_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.status_frame.pack(pady=20, padx=20, fill="x")
        
        self.stt_status = self.create_status_row("🎙️ STT ENGINE")
        self.tts_status = self.create_status_row("🔊 TTS ENGINE")
        self.llm_status = self.create_status_row("🧠 OLLAMA CORE")
        self.s2s_status = self.create_status_row("✨ S2S PIPELINE")

        # --- Main Area ---
        # Top Telemetry
        self.telemetry_frame = ctk.CTkFrame(self, fg_color="#0D121F", height=60, corner_radius=10)
        self.telemetry_frame.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="nsew")
        
        self.tel_stt = self.create_tel_item(self.telemetry_frame, "STT", "0.00s")
        self.tel_llm = self.create_tel_item(self.telemetry_frame, "LLM", "0.00s")
        self.tel_tts = self.create_tel_item(self.telemetry_frame, "TTS", "0.00s")
        self.tel_tot = self.create_tel_item(self.telemetry_frame, "TOTAL", "0.00s", last=True)

        # Chat/Terminal Area
        self.chat_display = ctk.CTkTextbox(self, fg_color="#080C14", border_color=GRAY_COLOR, border_width=1, corner_radius=10, font=ctk.CTkFont(family="Consolas", size=13))
        self.chat_display.grid(row=1, column=1, padx=20, pady=10, sticky="nsew")
        self.chat_display.tag_config("user", foreground=ACCENT_COLOR)
        self.chat_display.tag_config("jarvis", foreground=SUCCESS_COLOR)
        self.chat_display.tag_config("system", foreground=GRAY_COLOR)

        # Bottom Interaction
        self.input_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.input_frame.grid(row=2, column=1, padx=20, pady=20, sticky="nsew")
        
        self.talk_btn = ctk.CTkButton(self.input_frame, text="HOLD TO TALK", height=60, corner_radius=30,
                                     fg_color=GRAY_COLOR, hover_color="#1E2433", 
                                     font=ctk.CTkFont(size=16, weight="bold"))
        self.talk_btn.pack(side="left", expand=True, fill="x", padx=(0, 10))
        self.talk_btn.bind("<Button-1>", self.start_recording)
        self.talk_btn.bind("<ButtonRelease-1>", self.stop_recording)
        
        # Add spacebar support
        self.bind("<KeyPress-space>", self.start_recording)
        self.bind("<KeyRelease-space>", self.stop_recording)

    def create_status_row(self, label):
        row = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        row.pack(fill="x", pady=5)
        lbl = ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=11), text_color=TEXT_COLOR)
        lbl.pack(side="left")
        dot = ctk.CTkLabel(row, text="●", text_color=GRAY_COLOR, font=ctk.CTkFont(size=14))
        dot.pack(side="right")
        return dot

    def create_tel_item(self, parent, label, val, last=False):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(side="left", expand=True)
        l1 = ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=10, weight="bold"), text_color=GRAY_COLOR)
        l1.pack()
        l2 = ctk.CTkLabel(f, text=val, font=ctk.CTkFont(family="Consolas", size=14), text_color=ACCENT_COLOR)
        l2.pack()
        return l2

    def log(self, msg, tag="system"):
        self.chat_display.insert("end", f"[{time.strftime('%H:%M:%S')}] ", "system")
        prefix = "YOU > " if tag == "user" else "JARVIS > " if tag == "jarvis" else "SYS  > "
        self.chat_display.insert("end", f"{prefix}{msg}\n", tag)
        self.chat_display.see("end")

    def toggle_server(self):
        if self.server_process:
            self.log("Shutting down system...")
            kill_process_on_port(self.s2s_port)
            self.server_process = None
            self.init_btn.configure(text="INITIALIZE SYSTEM", fg_color=GRAY_COLOR)
        else:
            self.log("Starting Blackwell Core...")
            self.init_btn.configure(text="STOP SYSTEM", fg_color=ERROR_COLOR)
            threading.Thread(target=self.run_server, daemon=True).start()

    def run_server(self):
        project_root = os.path.dirname(os.path.abspath(__file__))
        python_exe = os.path.join(project_root, "jarvis-venv", "Scripts", "python.exe")
        server_script = os.path.join(project_root, "servers", "s2s_server.py")
        
        cmd = [python_exe, server_script, "--loadout", "default"]
        self.server_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, encoding='utf-8', bufsize=1,
            creationflags=0x08000000 if os.name == 'nt' else 0
        )
        
        log_pattern = re.compile(r".*?[A-Z]+\s+\| (.*)$")
        ansi_escape = re.compile(r'\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])')

        for line in iter(self.server_process.stdout.readline, ''):
            if line:
                clean = ansi_escape.sub('', line.strip())
                match = log_pattern.match(clean)
                msg = match.group(1) if match else clean
                if "INFO:" in msg: continue
                self.log(msg, "system")
        self.server_process.stdout.close()

    def update_status_loop(self):
        health = {}
        try:
            # Quick check of ports from config
            status_map = {
                self.s2s_port: self.s2s_status,
                8011: self.stt_status, # base
                8021: self.tts_status, # mtl
                11434: self.llm_status
            }
            
            for port, dot in status_map.items():
                s = get_service_status(port)
                color = SUCCESS_COLOR if s == "ON" else YELLOW_COLOR if s == "STARTUP" else ERROR_COLOR if s == "UNHEALTHY" else GRAY_COLOR
                dot.configure(text_color=color)
        except:
            pass
        
        # Update UI state
        if self.is_recording:
            self.talk_btn.configure(fg_color=ERROR_COLOR, text="LISTENING...")
        else:
            can_talk = get_service_status(self.s2s_port) == "ON"
            self.talk_btn.configure(fg_color=ACCENT_COLOR if can_talk else GRAY_COLOR, 
                                   text="HOLD TO TALK" if can_talk else "SYSTEM OFFLINE")

        self.after(2000, self.update_status_loop)

    def start_recording(self, event=None):
        if self.is_recording or get_service_status(self.s2s_port) != "ON": return
        self.is_recording = True
        self.audio_frames = []
        self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=16000, 
                                 input=True, frames_per_buffer=1024)
        threading.Thread(target=self.record_loop, daemon=True).start()

    def record_loop(self):
        while self.is_recording:
            data = self.stream.read(1024)
            self.audio_frames.append(data)

    def stop_recording(self, event=None):
        if not self.is_recording: return
        self.is_recording = False
        self.stream.stop_stream()
        self.stream.close()
        
        # Save to temp buffer
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
            wf.setframerate(16000)
            wf.writeframes(b''.join(self.audio_frames))
        
        self.log("Sending to Jarvis...", "system")
        threading.Thread(target=self.send_request, args=(buf.getvalue(),), daemon=True).start()

    def send_request(self, audio_data):
        try:
            files = {'file': ('input.wav', audio_data, 'audio/wav')}
            start_time = time.perf_counter()
            resp = requests.post(f"{self.s2s_url}/process", files=files)
            duration = time.perf_counter() - start_time
            
            if resp.status_code == 200:
                # Metrics
                self.tel_stt.configure(text=f"{resp.headers.get('X-Metric-STT-Inference', '0.00')}s")
                self.tel_llm.configure(text=f"{resp.headers.get('X-Metric-LLM-Total', '0.00')}s")
                self.tel_tts.configure(text=f"{resp.headers.get('X-Metric-TTS-Inference', '0.00')}s")
                self.tel_tot.configure(text=f"{duration:.2f}s")
                
                # Transcripts
                self.log(resp.headers.get('X-Result-STT', '...'), "user")
                self.log(resp.headers.get('X-Result-LLM', '...'), "jarvis")
                
                # Play audio
                threading.Thread(target=self.play_audio, args=(resp.content,), daemon=True).start()
            else:
                self.log(f"Error: {resp.status_code}", "system")
        except Exception as e:
            self.log(f"Pipeline Error: {e}", "system")

    def play_audio(self, data):
        with io.BytesIO(data) as f:
            with wave.open(f, 'rb') as wf:
                # Use sounddevice for high quality playback
                samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                sd.play(samples, wf.getframerate())
                sd.wait()

YELLOW_COLOR = "#FFD700"

if __name__ == "__main__":
    app = JarvisClient()
    app.mainloop()
