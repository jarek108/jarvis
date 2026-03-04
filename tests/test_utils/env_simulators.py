import os
import time
import threading
import tkinter as tk
from typing import Optional
from loguru import logger

# --- Optional Dependencies ---
try:
    import sounddevice as sd
    import soundfile as sf
except ImportError:
    sd = sf = None

class AudioFeeder:
    """Plays audio files into a specific system output device (e.g., Virtual Cable)."""
    def __init__(self, device_name: str = "CABLE Input"):
        self.device_name = device_name
        self.device_id = self._find_device_id(device_name)
        
    def _find_device_id(self, name: str) -> Optional[int]:
        if not sd: return None
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if name in d['name'] and d['max_output_channels'] > 0:
                return i
        return None

    def play(self, file_path: str, blocking: bool = False):
        if not sd or self.device_id is None:
            logger.error(f"AudioFeeder: Cannot play. Device '{self.device_name}' not found or sounddevice missing.")
            return

        def _play():
            try:
                data, fs = sf.read(file_path)
                sd.play(data, samplerate=fs, device=self.device_id)
                sd.wait()
            except Exception as e:
                logger.error(f"AudioFeeder error: {e}")

        if blocking: _play()
        else: threading.Thread(target=_play, daemon=True).start()

class ScreenFeeder:
    """Opens a top-most GUI window displaying a test image to simulate a desktop state."""
    def __init__(self):
        self.root: Optional[tk.Tk] = None
        self.thread: Optional[threading.Thread] = None

    def start(self, image_path: str):
        def _run():
            self.root = tk.Tk()
            self.root.overrideredirect(True) # Borderless
            self.root.attributes("-topmost", True)
            
            # Load Image
            from PIL import Image, ImageTk
            img = Image.open(image_path)
            photo = ImageTk.PhotoImage(img)
            
            label = tk.Label(self.root, image=photo)
            label.pack()
            
            # Position centered
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            self.root.geometry(f"{img.width}x{img.height}+{(screen_w-img.width)//2}+{(screen_h-img.height)//2}")
            
            self.root.mainloop()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.root:
            self.root.after(0, self.root.destroy)

class KeyboardSandbox:
    """Opens a GUI window that captures and logs incoming keystrokes for verification."""
    def __init__(self):
        self.root: Optional[tk.Tk] = None
        self.log = []
        self.thread: Optional[threading.Thread] = None

    def start(self):
        def _run():
            self.root = tk.Tk()
            self.root.title("Jarvis Keyboard Sandbox")
            self.root.attributes("-topmost", True)
            
            text_area = tk.Text(self.root)
            text_area.pack()
            
            def on_key(event):
                self.log.append({"char": event.char, "keysym": event.keysym, "t": time.perf_counter()})
            
            text_area.bind("<Key>", on_key)
            text_area.focus_set()
            
            self.root.mainloop()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.root:
            self.root.after(0, self.root.destroy)

    def get_full_text(self) -> str:
        return "".join([e['char'] for e in self.log if e['char']])
