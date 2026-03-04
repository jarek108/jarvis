import os
import io
import time
import wave
import sounddevice as sd
import numpy as np
import soundfile as sf
from .registry import EdgeImplementation
from utils.engine.contract import Capability

try:
    import pyautogui
except ImportError:
    pyautogui = None
try:
    from win10toast import ToastNotifier
except ImportError:
    ToastNotifier = None

class SystemSpeaker(EdgeImplementation):
    """Plays audio through the local speakers."""
    def get_capabilities(self):
        return [Capability.AUDIO_IN]

    async def deliver(self, node_id, content, scenario_inputs, session_dir):
        # content can be raw PCM or a file path
        if isinstance(content, str) and os.path.exists(content):
            samples, fs = sf.read(content)
            sd.play(samples, samplerate=fs)
            sd.wait()
        else:
            samples = np.frombuffer(content, dtype=np.int16)
            sd.play(samples, samplerate=24000)
            sd.wait()

class KeyboardActuator(EdgeImplementation):
    """Emulates keyboard typing."""
    def get_capabilities(self):
        return [Capability.TEXT_IN]

    async def deliver(self, node_id, content, scenario_inputs, session_dir):
        if not pyautogui: return
        pyautogui.write(str(content), interval=0.01)

class NotificationActuator(EdgeImplementation):
    """Displays OS-level notifications."""
    def get_capabilities(self):
        return [Capability.TEXT_IN]

    async def deliver(self, node_id, content, scenario_inputs, session_dir):
        if ToastNotifier:
            toaster = ToastNotifier()
            toaster.show_toast("Jarvis", str(content), duration=5, threaded=True)
        else:
            print(f"🔔 NOTIFICATION: Jarvis - {content}")
