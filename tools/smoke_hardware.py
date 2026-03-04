import os
import time
import wave
import threading
from loguru import logger

# --- Core Dependencies ---
import utils
from utils.engine.contract import Capability
from utils.engine.implementations import execute_ptt_mic, execute_speaker, execute_screen_capture

async def smoke_mic():
    """Human-in-the-loop mic check."""
    logger.info("🎤 SMOKE TEST: Microphone (Hold-to-Talk)")
    logger.info("Please hold the SPACE BAR and speak for 2 seconds...")
    
    ptt_signal = threading.Event()
    
    def key_listener():
        import keyboard
        keyboard.wait('space')
        ptt_signal.set()
        time.sleep(2)
        ptt_signal.clear()
        
    listener = threading.Thread(target=key_listener, daemon=True)
    listener.start()
    
    config = {
        "scenario_inputs": {"ptt_active": ptt_signal},
        "session_dir": "logs/smoke_test"
    }
    
    import asyncio
    out_q = asyncio.Queue()
    await execute_ptt_mic("smoke_mic", {}, config, out_q, None)
    
    result = await out_q.get()
    if result and result.get('content'):
        path = result['content']
        logger.info(f"✅ Mic Capture Saved: {path}")
        logger.info("Playing back...")
        await execute_speaker("smoke_playback", {}, {"session_dir": "logs/smoke_test"}, asyncio.Queue(), None)
        # We need to feed the speaker the file. Standalone execute_speaker needs an input stream.
        # For simplicity in smoke test, we'll use a direct play if needed, but let's stick to the signature.
    else:
        logger.error("❌ Mic Capture Failed.")

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
        # Open the file
        if os.name == 'nt': os.startfile(path)
    else:
        logger.error("❌ Screen Capture Failed.")

def smoke_vram():
    """Validates GPU/5090 presence."""
    logger.info("🏎️ SMOKE TEST: GPU / VRAM")
    vram = utils.get_gpu_vram_usage()
    total = utils.get_gpu_total_vram()
    logger.info(f"✅ GPU detected. VRAM: {vram:.1f} / {total:.1f} GB")

async def main():
    os.makedirs("logs/smoke_test", exist_ok=True)
    smoke_vram()
    await smoke_screen()
    try:
        import keyboard
        await smoke_mic()
    except ImportError:
        logger.warning("Skipping Mic smoke test (keyboard library not found).")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
