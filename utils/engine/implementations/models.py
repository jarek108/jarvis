import json
import os
import aiohttp
import asyncio
import time
from typing import Any, AsyncGenerator

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

def validate_stt(node_id: str, config: dict, scenario_inputs: dict) -> tuple[bool, str]:
    """STT usually depends on upstream audio, so we don't strictly validate scenario_inputs here."""
    return True, ""
