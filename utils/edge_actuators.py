import os
import io
import time
import wave
import sounddevice as sd
try:
    import pyautogui
except ImportError:
    pyautogui = None
try:
    from win10toast import ToastNotifier
except ImportError:
    ToastNotifier = None

class AudioActuator:
    """Plays audio through the local speakers."""
    def play(self, audio_data, rate=24000):
        # audio_data is expected to be raw PCM (without header)
        # as yielded by our jarvis_server
        samples = np.frombuffer(audio_data, dtype=np.int16)
        sd.play(samples, samplerate=rate)
        sd.wait()

class KeyboardActuator:
    """Emulates keyboard typing."""
    def type_text(self, text):
        if not pyautogui: return
        pyautogui.write(text, interval=0.01)

class NotificationActuator:
    """Displays OS-level notifications."""
    def notify(self, title, message):
        if ToastNotifier:
            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=5, threaded=True)
        else:
            print(f"🔔 NOTIFICATION: {title} - {message}")
