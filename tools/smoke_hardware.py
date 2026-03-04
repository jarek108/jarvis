import os
import time
import wave
import threading
import asyncio
from loguru import logger

# --- Core Dependencies ---
import utils
from utils.engine.contract import Capability
from utils.engine.implementations import (
    execute_ptt_mic, execute_speaker, execute_screen_capture, 
    execute_camera_capture, execute_keyboard_typer, execute_clipboard_sensor,
    execute_clipboard_writer
)

async def smoke_mic():
    """Human-in-the-loop mic check."""
    logger.info("🎤 SMOKE TEST: Microphone (Hold-to-Talk)")
    logger.info("Please hold the SPACE BAR and speak for 2 seconds...")
    
    ptt_signal = threading.Event()
    
    def key_listener():
        try:
            import keyboard
            keyboard.wait('space')
            ptt_signal.set()
            time.sleep(2)
            ptt_signal.clear()
        except ImportError:
            # Fallback if keyboard lib not installed/accessible
            time.sleep(1)
            ptt_signal.set()
            time.sleep(2)
            ptt_signal.clear()
        
    listener = threading.Thread(target=key_listener, daemon=True)
    listener.start()
    
    config = {
        "scenario_inputs": {"ptt_active": ptt_signal},
        "session_dir": "logs/smoke_test"
    }
    
    out_q = asyncio.Queue()
    await execute_ptt_mic("smoke_mic", {}, config, out_q, None)
    
    result = await out_q.get()
    if result and result.get('content'):
        path = result['content']
        logger.info(f"✅ Mic Capture Saved: {path}")
        return path
    else:
        logger.error("❌ Mic Capture Failed.")
        return None

async def smoke_speaker(audio_path=None):
    """Verifies audio output."""
    logger.info("🔊 SMOKE TEST: Speaker")
    
    # Create an async generator to simulate a stream
    async def audio_stream():
        if audio_path:
            yield {"type": "audio_path", "content": audio_path}
        else:
            # Generate a simple beep/tone if no file provided
            # (In reality, we just log and try to play if sounddevice works)
            logger.info("No audio path provided, skipping physical playback check.")
            return

    await execute_speaker("smoke_speaker", {"in": audio_stream()}, {}, asyncio.Queue(), None)
    logger.info("✅ Speaker execution finished.")

async def smoke_screen():
    """Validates screen capture logic."""
    logger.info("🖥️ SMOKE TEST: Screen Capture")
    config = {"session_dir": "logs/smoke_test"}
    out_q = asyncio.Queue()
    await execute_screen_capture("smoke_screen", {}, config, out_q, None)
    
    result = await out_q.get()
    if result and result.get('content'):
        path = result['content']
        logger.info(f"✅ Screen Capture Saved: {path}")
        if os.name == 'nt': os.startfile(path)
    else:
        logger.error("❌ Screen Capture Failed.")

async def smoke_camera():
    """Validates camera capture logic."""
    logger.info("📷 SMOKE TEST: Camera Capture")
    config = {"session_dir": "logs/smoke_test", "device_index": 0}
    out_q = asyncio.Queue()
    await execute_camera_capture("smoke_camera", {}, config, out_q, None)
    
    result = await out_q.get()
    if result and result.get('content'):
        path = result['content']
        logger.info(f"✅ Camera Capture Saved: {path}")
        if os.name == 'nt': os.startfile(path)
    else:
        logger.error("❌ Camera Capture Failed. (Check if webcam is plugged in)")

async def smoke_clipboard():
    """Verifies clipboard read/write functionality."""
    logger.info("📋 SMOKE TEST: Clipboard")
    token = f"JARVIS-TEST-{int(time.time())}"
    
    # 1. WRITE
    async def text_stream():
        yield {"type": "text_final", "content": token}
        
    await execute_clipboard_writer("smoke_clip_write", {"in": text_stream()}, {}, asyncio.Queue(), None)
    
    # 2. READ
    out_q = asyncio.Queue()
    await execute_clipboard_sensor("smoke_clip_read", {}, {}, out_q, None)
    result = await out_q.get()
    
    if result and result.get('content') == token:
        logger.info(f"✅ Clipboard verified: {token}")
    else:
        logger.error(f"❌ Clipboard mismatch. Expected {token}, got {result.get('content')}")

async def smoke_keyboard():
    """Verifies keyboard emulation."""
    logger.info("⌨️  SMOKE TEST: Keyboard Typer")
    logger.info("Opening a Notepad and typing in 3 seconds... (Switch focus!)")
    
    if os.name == 'nt':
        os.system("start notepad.exe")
        time.sleep(3)
        
        async def text_stream():
            yield {"type": "text_final", "content": "Hello from Jarvis Hardware Smoke Test!"}
            
        await execute_keyboard_typer("smoke_kb", {"in": text_stream()}, {}, asyncio.Queue(), None)
        logger.info("✅ Keyboard typing finished.")
    else:
        logger.warning("Keyboard smoke test skipped (Non-Windows platform).")

def smoke_vram():
    """Validates GPU/5090 presence."""
    logger.info("🏎️ SMOKE TEST: GPU / VRAM")
    vram = utils.get_gpu_vram_usage()
    total = utils.get_gpu_total_vram()
    logger.info(f"✅ GPU detected. VRAM: {vram:.1f} / {total:.1f} GB")

async def main():
    os.makedirs("logs/smoke_test", exist_ok=True)
    print("\n--- JARVIS HARDWARE SMOKE SUITE ---\n")
    
    smoke_vram()
    await smoke_clipboard()
    await smoke_screen()
    await smoke_camera()
    
    # Interaction tests last
    mic_path = await smoke_mic()
    if mic_path:
        await smoke_speaker(mic_path)
    
    # Keyboard test is intrusive, do it very last
    await smoke_keyboard()
    
    print("\n--- SMOKE SUITE COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(main())
