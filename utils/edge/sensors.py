import os
import time
import io
import wave
import numpy as np
import pyaudio
try:
    import mss
    import PIL.Image
except ImportError:
    mss = None
try:
    import pyperclip
except ImportError:
    pyperclip = None

class AudioSensor:
    """Captures audio from the local microphone."""
    def __init__(self, rate=16000, chunk=1024):
        self.rate = rate
        self.chunk = chunk
        self.p = pyaudio.PyAudio()
        self.stream = None

    def capture_snapshot(self, duration=2.0):
        """Records a fixed-length audio clip."""
        self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=self.rate, input=True, frames_per_buffer=self.chunk)
        frames = []
        for _ in range(0, int(self.rate / self.chunk * duration)):
            data = self.stream.read(self.chunk)
            frames.append(data)
        
        self.stream.stop_stream()
        self.stream.close()
        
        # Save to temporary buffer
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(frames))
        return buf.getvalue()

class ScreenSensor:
    """Captures snapshots of the local desktop."""
    def capture_snapshot(self):
        if not mss: return None
        with mss.mss() as sct:
            # Capture primary monitor
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()

class ClipboardSensor:
    """Reads the local clipboard."""
    def capture_snapshot(self):
        if not pyperclip: return ""
        return pyperclip.paste()
