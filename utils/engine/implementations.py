import json
import os
import aiohttp
import asyncio
import time
import wave
import io
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

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import mss
    import PIL.Image
except ImportError:
    mss = PIL = None

try:
    from win10toast import ToastNotifier
except ImportError:
    ToastNotifier = None

# --- Core Utilities ---

async def resolve_inputs(input_streams: dict[str, AsyncGenerator]) -> dict[str, str]:
    """Standard utility to accumulate data from input streams."""
    resolved = {}
    for in_id, stream in input_streams.items():
        content = ""
        async for packet in stream:
            if packet is None: break
            val = packet.get('content', '')
            if val:
                if isinstance(val, str) and os.path.exists(val):
                    try:
                        with open(val, 'r', encoding='utf-8', errors='ignore') as f:
                            content += f.read()
                    except: content += val
                else:
                    content += str(val)
        resolved[in_id] = content
    return resolved

# --- MODEL IMPLEMENTATIONS ---

async def execute_openai_chat(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Standard implementation for OpenAI-compatible Chat APIs (Ollama, vLLM)."""
    resolved = await resolve_inputs(input_streams)
    
    layout = config.get('context_layout')
    sys_prompt_id = config.get('system_prompt')
    sys_prompt_content = resolved.get(sys_prompt_id) if sys_prompt_id else None
    other_inputs = {k: v for k, v in resolved.items() if k != sys_prompt_id}
    
    if layout:
        prompt = layout
        for in_id, val in other_inputs.items():
            prompt = prompt.replace("{{" + in_id + "}}", val)
    else:
        prompt = "\n".join([v for v in other_inputs.values() if v]) or "Hello"

    messages = []
    if sys_prompt_content:
        messages.append({"role": "system", "content": sys_prompt_content})
    messages.append({"role": "user", "content": prompt})

    binding = config.get('binding', {})
    port = binding.get('port')
    model_id = binding.get('id', 'unknown').split('#')[0]
    
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": config.get('output_streaming', False)
    }
    
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    
    async with session.post(url, json=payload) as resp:
        if resp.status != 200:
            err_text = await resp.text()
            raise RuntimeError(f"LLM Server Error ({resp.status}): {err_text}")
        
        if payload['stream']:
            seq = 0
            async for line in resp.content:
                if not line: continue
                line_text = line.decode('utf-8').strip()
                if line_text.startswith("data: ") and "[DONE]" not in line_text:
                    try:
                        token = json.loads(line_text[6:])['choices'][0]['delta'].get('content', '')
                        if token:
                            await output_queue.put({"type": "text_token", "content": token, "seq": seq, "ts": time.perf_counter()})
                            seq += 1
                    except: pass
        else:
            text = (await resp.json())['choices'][0]['message']['content']
            await output_queue.put({"type": "text_final", "content": text, "ts": time.perf_counter()})

async def execute_whisper_stt(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Standard implementation for Whisper STT servers."""
    audio_path = None
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            audio_path = packet.get('content')
            if audio_path: break
        if audio_path: break
        
    if not audio_path: raise ValueError(f"{node_id} missing audio path.")

    binding = config.get('binding', {})
    url = f"http://127.0.0.1:{binding.get('port')}/transcribe"
    
    data = aiohttp.FormData()
    data.add_field('file', open(audio_path, 'rb'))
    
    async with session.post(url, data=data) as resp:
        if resp.status != 200:
            err_text = await resp.text()
            raise RuntimeError(f"STT Server Error ({resp.status}): {err_text}")
        text = (await resp.json()).get('text', '')
        await output_queue.put({"type": "text_final", "content": text, "ts": time.perf_counter()})

async def execute_chatterbox_tts(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Standard implementation for Chatterbox TTS servers."""
    text = None
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            text = packet.get('content')
            if text: break
        if text: break
        
    if not text: return

    binding = config.get('binding', {})
    url = f"http://127.0.0.1:{binding.get('port')}/synthesize"
    
    payload = {"text": text}
    async with session.post(url, json=payload) as resp:
        if resp.status != 200:
            err_text = await resp.text()
            raise RuntimeError(f"TTS Server Error ({resp.status}): {err_text}")
        
        result = await resp.json()
        audio_path = result.get('audio_path')
        await output_queue.put({"type": "audio_path", "content": audio_path, "ts": time.perf_counter()})

# --- HARDWARE IMPLEMENTATIONS ---

async def execute_speaker(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Local audio playback implementation."""
    if not sd or not sf: return
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

async def execute_ptt_mic(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Push-to-Talk microphone implementation."""
    if not pyaudio: return
    scenario_inputs = config.get('scenario_inputs', {})
    ptt_signal = scenario_inputs.get('ptt_active')
    session_dir = config.get('session_dir', '.')
    
    if not ptt_signal:
        # If no signal, attempt fallback to direct file if provided in scenario_inputs
        path = scenario_inputs.get(node_id)
        if path:
            await output_queue.put({"type": "audio_path", "content": path, "ts": time.perf_counter()})
            return
        raise ValueError(f"{node_id} requires a 'ptt_active' signal or direct file override.")

    # 1. Wait for PTT
    while not ptt_signal.is_set(): await asyncio.sleep(0.05)
    
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

async def execute_notification(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """OS notification actuator."""
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            content = str(packet.get('content', ''))
            if ToastNotifier:
                ToastNotifier().show_toast("Jarvis", content, duration=5, threaded=True)
            else:
                logger.info(f"🔔 NOTIFICATION: {content}")
            await output_queue.put(packet)

async def execute_screen_capture(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Captures desktop screenshots."""
    if not mss or not PIL: return
    session_dir = config.get('session_dir', '.')
    out_path = os.path.join(session_dir, f"{node_id}_capture.jpg")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        img.save(out_path, format="JPEG", quality=85)
        
    await output_queue.put({"type": "image_path", "content": out_path, "ts": time.perf_counter()})

async def execute_keyboard_typer(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Emulates keyboard typing."""
    if not pyautogui: return
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            content = str(packet.get('content', ''))
            pyautogui.write(content, interval=0.01)
            await output_queue.put(packet)

async def execute_clipboard_sensor(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Reads local clipboard content."""
    if not pyperclip: return
    text = pyperclip.paste()
    await output_queue.put({"type": "text_final", "content": text, "ts": time.perf_counter()})

# --- UTILITY IMPLEMENTATIONS ---

async def execute_chunker(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Logical chunking implementation."""
    from utils.engine import chunk_by_delimiter
    delimiters = config.get('delimiters', '.?!')
    stream = next(iter(input_streams.values())) if input_streams else None
    if not stream: return
    async for out_packet in chunk_by_delimiter(stream, delimiters=delimiters):
        await output_queue.put(out_packet)

async def execute_memory_node(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Handles session history and conversation context."""
    session_dir = config.get('session_dir', '.')
    storage_path = config.get('path', 'session_history.txt')
    if not os.path.isabs(storage_path):
        storage_path = os.path.join(session_dir, storage_path)
    
    os.makedirs(os.path.dirname(storage_path), exist_ok=True)
    
    # 1. READ
    history_content = ""
    if os.path.exists(storage_path):
        with open(storage_path, "r", encoding="utf-8", errors='ignore') as f:
            history_content = f.read()
    
    # 2. APPEND
    new_data = ""
    for in_id, stream in input_streams.items():
        async for packet in stream:
            if packet is None: break
            content = packet.get('content')
            if content:
                new_data += f"\n{in_id.upper()}: {content}"
    
    if new_data:
        with open(storage_path, "a", encoding="utf-8") as f:
            f.write(new_data)
        with open(storage_path, "r", encoding="utf-8") as f:
            history_content = f.read()

    await output_queue.put({"type": "text_final", "content": history_content, "ts": time.perf_counter()})
