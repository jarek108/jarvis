import os
import time
import io
import wave
import threading
import numpy as np
import pyaudio
from .registry import EdgeImplementation
from utils.engine.contract import Capability

try:
    import mss
    import PIL.Image
except ImportError:
    mss = None
try:
    import pyperclip
except ImportError:
    pyperclip = None

class PushToTalkMic(EdgeImplementation):
    """
    Captures audio from the local microphone while a signal is active.
    Fulfills the [AUDIO_OUT] capability.
    """
    def __init__(self, rate=16000, chunk=1024):
        self.rate = rate
        self.chunk = chunk
        self.p = pyaudio.PyAudio()
        self._is_recording = False
        self._frames = []

    def get_capabilities(self):
        return [Capability.AUDIO_OUT]

    async def capture(self, node_id, scenario_inputs, session_dir):
        """
        Active capture loop. 
        Expects scenario_inputs['ptt_active'] to be a threading.Event or similar signal.
        """
        ptt_signal = scenario_inputs.get('ptt_active')
        if not ptt_signal:
            raise ValueError(f"PushToTalkMic requires a 'ptt_active' signal in scenario_inputs.")

        # 1. Wait for PTT Press
        while not ptt_signal.is_set():
            time.sleep(0.05)

        # 2. Start Recording
        self._frames = []
        stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=self.rate, input=True, frames_per_buffer=self.chunk)
        self._is_recording = True
        
        while ptt_signal.is_set():
            data = stream.read(self.chunk)
            self._frames.append(data)
        
        # 3. Finalize
        stream.stop_stream()
        stream.close()
        self._is_recording = False

        # Save to session-scoped file
        out_path = os.path.join(session_dir, f"{node_id}_capture.wav")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        
        with wave.open(out_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(self._frames))
            
        return out_path

class WavFileReader(EdgeImplementation):
    """Mocks a microphone by reading a local .wav file."""
    def get_capabilities(self):
        return [Capability.AUDIO_OUT]

    async def capture(self, node_id, scenario_inputs, session_dir):
        # Simply returns the path provided in scenario_inputs or node config
        path = scenario_inputs.get(node_id)
        if not path:
            raise ValueError(f"WavFileReader requires a file path in scenario_inputs['{node_id}'].")
        return path

class ScreenSensor(EdgeImplementation):
    """Captures snapshots of the local desktop."""
    def get_capabilities(self):
        return [Capability.IMAGE_OUT]

    def capture_snapshot(self):
        if not mss: return None
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()

class ClipboardSensor(EdgeImplementation):
    """Reads the local clipboard."""
    def get_capabilities(self):
        return [Capability.TEXT_OUT]

    def capture_snapshot(self):
        if not pyperclip: return ""
        return pyperclip.paste()
