import os
import time
import wave
import asyncio
import threading
from typing import Any, AsyncGenerator
from loguru import logger

# --- Optional Dependencies ---
try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
except ImportError:
    sd = sf = np = None

try:
    import pyaudio
except ImportError:
    pyaudio = None

async def execute_speaker(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Local audio playback implementation."""
    if not sd or not sf: 
        logger.warning(f"[{node_id}] sounddevice or soundfile missing. Skipping playback.")
        return
        
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            content = packet.get('content')
            if isinstance(content, str) and os.path.exists(content):
                samples, fs = sf.read(content)
                sd.play(samples, samplerate=fs)
                sd.wait()
            elif isinstance(content, (bytes, bytearray)):
                samples = np.frombuffer(content, dtype=np.int16)
                sd.play(samples, samplerate=24000)
                sd.wait()
            await output_queue.put(packet) # Propagate for tracing

async def execute_ptt_mic(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Push-to-Talk microphone implementation."""
    if not pyaudio: 
        logger.warning(f"[{node_id}] pyaudio missing. Skipping capture.")
        return
        
    scenario_inputs = config.get('scenario_inputs', {})
    
    # 0. Check for direct file override FIRST
    path = scenario_inputs.get(node_id) or scenario_inputs.get('input_mic')
    if path and os.path.exists(path):
        await output_queue.put({"type": "audio_path", "content": path, "ts": time.perf_counter()})
        return

    ptt_signal = scenario_inputs.get('ptt_active')
    session_dir = config.get('session_dir', '.')
    
    if not ptt_signal:
        raise ValueError(f"{node_id} requires a 'ptt_active' signal or direct file override.")

    # 1. Wait for PTT
    wait_start = time.perf_counter()
    is_test = 'input_mic' in scenario_inputs or 'input_text' in scenario_inputs
    timeout = config.get('wait_timeout', 15.0 if is_test else 300.0) 
    
    while not ptt_signal.is_set():
        if time.perf_counter() - wait_start > timeout:
            logger.warning(f"[{node_id}] PTT wait timed out after {timeout}s")
            return
        await asyncio.sleep(0.05)
    
    # 2. Record
    pa = pyaudio.PyAudio()
    frames = []
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
    while ptt_signal.is_set():
        data = stream.read(1024)
        frames.append(data)
    stream.stop_stream(); stream.close(); pa.terminate()
    
    # 3. Save
    out_path = os.path.join(session_dir, f"{node_id}_capture.wav")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with wave.open(out_path, 'wb') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
        wf.writeframes(b''.join(frames))
    
    await output_queue.put({"type": "audio_path", "content": out_path, "ts": time.perf_counter()})

def validate_ptt_mic(node_id: str, config: dict, scenario_inputs: dict) -> tuple[bool, str]:
    """Ensures PTT Mic has a way to get data."""
    if scenario_inputs.get(node_id) or scenario_inputs.get('input_mic'):
        return True, ""
    
    if scenario_inputs.get('ptt_active'):
        return True, ""
        
    return False, f"Node '{node_id}' requires a 'ptt_active' signal or file input (input_mic), but neither was found."
