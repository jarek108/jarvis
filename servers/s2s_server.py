"""
[Title] : Speech-to-Speech (S2S) Pipeline Server
[Section] : Description
This server orchestrates the full STT -> LLM -> TTS pipeline. It acts as the 
central entry point for Jarvis, managing its own dependencies (STT, TTS, Ollama)
if they are not already running.

[Section] : Usage Examples
[Subsection] : Default (uses default.yaml)
python servers/s2s_server.py

[Subsection] : Custom Loadout
python servers/s2s_server.py --loadout turbo_ultra

[Subsection] : Manual Overrides
python servers/s2s_server.py --stt faster-whisper-tiny --tts chatterbox-turbo
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import Response, JSONResponse, StreamingResponse
from contextlib import asynccontextmanager
import aiohttp
import asyncio
import os
import sys
import time
import argparse
import yaml
import json
import re
from typing import Optional
from loguru import logger

# Allow importing from parent directory
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

from tests.utils import load_config, is_port_in_use, kill_process_on_port, start_server, get_service_status

# Global config and state
cfg = load_config()
owned_ports = []
DEFAULT_LOADOUT = "default"

# Configure lean logging
logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | <cyan>{message}</cyan>", colorize=True, enqueue=True)

def get_args():
    parser = argparse.ArgumentParser(description="Jarvis S2S Server")
    parser.add_argument("--port", type=int, default=cfg['ports']['s2s'], help="Port to run the S2S server on")
    parser.add_argument("--loadout", type=str, help="Name of a loadout preset (e.g., turbo_ultra)")
    parser.add_argument("--stt", type=str, help="STT model override")
    parser.add_argument("--tts", type=str, help="TTS variant override")
    parser.add_argument("--llm", type=str, help="LLM model override")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    return parser.parse_known_args()[0]

args = get_args()

def safe_header(text):
    """Aggressively sanitize text for HTTP headers (printable ASCII only)."""
    if not text: return ""
    # Replace newlines/tabs with spaces, then keep only printable ASCII (32-126)
    text = text.replace("\n", " ").replace("\t", " ")
    return "".join(c for c in text if 32 <= ord(c) <= 126)

async def wait_for_service_ready(name, url, timeout=120):
    """Polls a /health endpoint until it returns 200 OK."""
    start_time = time.perf_counter()
    logger.info(f"  ↳ ⌛ Checking {name}...")
    async with aiohttp.ClientSession() as session:
        while time.perf_counter() - start_time < timeout:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        logger.info(f"  ↳ ✅ {name} is ONLINE ({time.perf_counter() - start_time:.1f}s)")
                        return True
            except Exception:
                pass
            await asyncio.sleep(2)
    logger.error(f"  ↳ ❌ {name} TIMEOUT")
    return False

async def warmup_ollama(url, model_name):
    """Pokes Ollama with a tiny prompt to ensure it is hot in VRAM."""
    logger.info(f"🔥 Activating LLM ({model_name})...")
    start_time = time.perf_counter()
    async with aiohttp.ClientSession() as session:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5
        }
        try:
            async with session.post(f"{url}/v1/chat/completions", json=payload) as resp:
                if resp.status == 200:
                    await resp.json()
                    logger.info(f"✅ LLM is HOT ({time.perf_counter() - start_time:.1f}s)")
                else:
                    logger.error(f"⚠️ LLM Warmup Status: {resp.status}")
        except Exception as e:
            logger.error(f"⚠️ LLM Warmup Failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info("Initializing Jarvis S2S Cluster...")
    
    # 1. Determine active models
    active_stt = args.stt
    active_tts = args.tts
    active_llm = args.llm
    
    selected_loadout = args.loadout or DEFAULT_LOADOUT
    loadout_path = os.path.join(project_root, "tests", "loadouts", f"{selected_loadout}.yaml")
    
    if os.path.exists(loadout_path):
        with open(loadout_path, "r") as f:
            l_data = yaml.safe_load(f)
            if not active_stt: active_stt = l_data.get("stt", [None])[0]
            if not active_tts: active_tts = l_data.get("tts", [None])[0]
            if not active_llm: active_llm = l_data.get("llm")
            logger.info(f"📦 Loadout: {selected_loadout}")
    else:
        logger.error(f"❌ Preset {selected_loadout} missing at {loadout_path}")
        if not active_stt: active_stt = "faster-whisper-base"
        if not active_tts: active_tts = "chatterbox-multilingual"
        if not active_llm: active_llm = "gpt-oss:20b"

    app.state.stt_model = active_stt
    app.state.tts_model = active_tts
    app.state.llm_model = active_llm
    
    logger.info(f"🛠️  Pipeline: {active_stt} ➔ {active_llm} ➔ {active_tts}")

    # 2. Ports
    stt_port = cfg['stt_loadout'][active_stt]
    tts_port = cfg['tts_loadout'][active_tts]
    llm_port = cfg['ports']['llm']

    # 3. Executables
    python_exe = os.path.join(project_root, "jarvis-venv", "Scripts", "python.exe")
    stt_script = os.path.join(project_root, "servers", "stt_server.py")
    tts_script = os.path.join(project_root, "servers", "tts_server.py")

    services = [
        {
            "name": "STT Server", 
            "port": stt_port, 
            "cmd": [python_exe, stt_script, "--port", str(stt_port), "--model", active_stt], 
            "health": f"http://127.0.0.1:{stt_port}/health"
        },
        {
            "name": "TTS Server", 
            "port": tts_port, 
            "cmd": [python_exe, tts_script, "--port", str(tts_port), "--variant", active_tts], 
            "health": f"http://127.0.0.1:{tts_port}/health"
        },
        {
            "name": "Ollama Core", 
            "port": llm_port, 
            "cmd": ["ollama", "serve"], 
            "health": f"http://127.0.0.1:{llm_port}/api/tags"
        }
    ]

    logger.info("📡 Checking Infrastructure...")
    for s in services:
        if not is_port_in_use(s["port"]):
            logger.info(f"  ✨ Spawning {s['name']} (Port {s['port']})")
            start_server(s["cmd"], loud=False)
            owned_ports.append(s["port"])
        else:
            logger.info(f"  ℹ️  {s['name']} is already running.")

    # Wait for all
    ready_tasks = [wait_for_service_ready(s['name'], s['health']) for s in services]
    results = await asyncio.gather(*ready_tasks)
    
    if not all(results):
        logger.critical("🚨 DEPENDENCY FAILURE: Pipeline entry blocked.")

    # 4. LLM Warmup (External)
    await warmup_ollama(f"http://127.0.0.1:{llm_port}", active_llm)
    
    app.state.is_ready = True
    logger.info("✨ JARVIS PIPELINE READY")
    yield
    
    # --- SHUTDOWN ---
    logger.info(f"S2S Server shutting down. Cleaning up {len(owned_ports)} owned services...")
    for port in owned_ports:
        kill_process_on_port(port)
    logger.info("Cleanup complete.")

app = FastAPI(lifespan=lifespan)
app.state.is_ready = False

@app.get("/health")
async def health_check():
    if not app.state.is_ready:
        return JSONResponse(status_code=503, content={"status": "STARTUP"})
    return {"status": "ON", "service": "s2s_server"}

@app.post("/process_stream")
async def process_stream(
    file: UploadFile = File(...),
    language_id: Optional[str] = Form(None)
):
    total_start = time.perf_counter()
    active_stt = app.state.stt_model
    active_tts = app.state.tts_model
    active_llm = app.state.llm_model
    
    stt_port = cfg['stt_loadout'][active_stt]
    tts_port = cfg['tts_loadout'][active_tts]
    llm_port = cfg['ports']['llm']

    try:
        audio_data = await file.read()
        
        # 1. STT (Buffered)
        async with aiohttp.ClientSession() as session:
            stt_url = f"http://127.0.0.1:{stt_port}/transcribe"
            form = aiohttp.FormData()
            form.add_field('file', audio_data, filename='input.wav', content_type='audio/wav')
            async with session.post(stt_url, data=form) as resp:
                stt_result = await resp.json()
                input_text = stt_result.get("text", "")

        if not input_text:
            return Response(status_code=400, content="No speech detected")

        async def audio_generator():
            sentence_buffer = ""
            # Pipelined metrics (relative to total_start)
            m = {
                "stt": [0, 0],
                "llm": [0, 0],
                "tts": [0, 0]
            }
            
            # STT is buffered, so first/last output is the same timestamp
            stt_ready_time = round(time.perf_counter() - total_start, 2)
            m["stt"] = [stt_ready_time, stt_ready_time]
            
            first_token_time = None
            first_audio_time = None
            last_audio_time = None
            
            async with aiohttp.ClientSession() as session:
                # 2. LLM Streaming
                llm_url = f"http://127.0.0.1:{llm_port}/v1/chat/completions"
                payload = {
                    "model": active_llm,
                    "messages": [{"role": "user", "content": input_text}],
                    "stream": True
                }
                
                async with session.post(llm_url, json=payload) as resp:
                    async for line in resp.content:
                        if line:
                            line_text = line.decode('utf-8').strip()
                            if line_text.startswith("data: "):
                                data_str = line_text[6:]
                                if data_str == "[DONE]": 
                                    m["llm"][1] = round(time.perf_counter() - total_start, 2)
                                    break
                                try:
                                    if first_token_time is None:
                                        first_token_time = time.perf_counter()
                                        m["llm"][0] = round(first_token_time - total_start, 2)

                                    chunk = json.loads(data_str)
                                    token = chunk['choices'][0]['delta'].get('content', '')
                                    sentence_buffer += token
                                    
                                    # Check for sentence completion (Assume .!? as breakpoints)
                                    if any(c in sentence_buffer for c in ".!?"):
                                        parts = re.split(r'(?<=[.!?])\s+', sentence_buffer)
                                        for i in range(len(parts) - 1):
                                            sentence = parts[i].strip()
                                            if sentence:
                                                # 3. TTS for sentence
                                                tts_url = f"http://127.0.0.1:{tts_port}/tts"
                                                tts_payload = {"text": sentence, "voice": "default", "language_id": language_id or "en"}
                                                async with session.post(tts_url, json=tts_payload) as tts_resp:
                                                    if tts_resp.status == 200:
                                                        if first_audio_time is None:
                                                            first_audio_time = time.perf_counter()
                                                            m["tts"][0] = round(first_audio_time - total_start, 2)
                                                        
                                                        audio_chunk = await tts_resp.read()
                                                        last_audio_time = time.perf_counter()
                                                        yield audio_chunk[44:]
                                        sentence_buffer = parts[-1]
                                except:
                                    continue

                # Final flush
                if sentence_buffer.strip():
                    tts_url = f"http://127.0.0.1:{tts_port}/tts"
                    tts_payload = {"text": sentence_buffer.strip(), "voice": "default", "language_id": language_id or "en"}
                    async with session.post(tts_url, json=tts_payload) as tts_resp:
                        if tts_resp.status == 200:
                            if first_audio_time is None:
                                first_audio_time = time.perf_counter()
                                m["tts"][0] = round(first_audio_time - total_start, 2)
                            audio_chunk = await tts_resp.read()
                            last_audio_time = time.perf_counter()
                            yield audio_chunk[44:]
            
            # End of stream metrics
            m["tts"][1] = round((last_audio_time or time.perf_counter()) - total_start, 2)
            # Add a clear boundary and metrics JSON
            yield b"\nMETRICS_JSON:" + json.dumps(m).encode()

        return StreamingResponse(audio_generator(), media_type="application/octet-stream")

    except Exception as e:
        logger.error(f"S2S Streaming Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process")
async def process_audio(
    file: UploadFile = File(...),
    language_id: Optional[str] = Form(None)
):
    total_start = time.perf_counter()
    metrics = {}
    
    active_stt = app.state.stt_model
    active_tts = app.state.tts_model
    active_llm = app.state.llm_model

    stt_port = cfg['stt_loadout'][active_stt]
    tts_port = cfg['tts_loadout'][active_tts]
    llm_port = cfg['ports']['llm']

    try:
        audio_data = await file.read()
        
        async with aiohttp.ClientSession() as session:
            # 1. STT
            stt_url = f"http://127.0.0.1:{stt_port}/transcribe"
            form = aiohttp.FormData()
            form.add_field('file', audio_data, filename='input.wav', content_type='audio/wav')
            
            async with session.post(stt_url, data=form) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=500, detail="STT Server Error")
                stt_result = await resp.json()
                input_text = stt_result.get("text", "")
                metrics['STT-Inference'] = float(resp.headers.get("X-Inference-Time", 0))

            if not input_text:
                return Response(status_code=400, content="No speech detected")
            
            # 2. LLM
            llm_url = f"http://127.0.0.1:{llm_port}/v1/chat/completions"
            llm_payload = {
                "model": active_llm,
                "messages": [{"role": "user", "content": input_text}],
                "temperature": 0.7
            }
            llm_start = time.perf_counter()
            async with session.post(llm_url, json=llm_payload) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=500, detail="LLM Server Error")
                llm_result = await resp.json()
                llm_text = llm_result['choices'][0]['message']['content'].strip()
                metrics['LLM-Total'] = time.perf_counter() - llm_start

            # 3. TTS
            tts_url = f"http://127.0.0.1:{tts_port}/tts"
            tts_payload = {
                "text": llm_text, 
                "voice": "default",
                "language_id": language_id or "en"
            }
            async with session.post(tts_url, json=tts_payload) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=500, detail="TTS Server Error")
                output_audio = await resp.read()
                metrics['TTS-Inference'] = float(resp.headers.get("X-Inference-Time", 0))

        total_duration = time.perf_counter() - total_start
        custom_headers = {f"X-Metric-{k.replace(' ', '-')}": str(v) for k, v in metrics.items()}
        
        custom_headers["X-Result-STT"] = safe_header(input_text)
        custom_headers["X-Result-LLM"] = safe_header(llm_text)
        custom_headers["X-Model-STT"] = safe_header(active_stt)
        custom_headers["X-Model-LLM"] = safe_header(active_llm)
        custom_headers["X-Model-TTS"] = safe_header(active_tts)
        
        return Response(content=output_audio, media_type="audio/wav", headers=custom_headers)

    except Exception as e:
        logger.error(f"S2S Pipeline Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    
    # Pre-flight check: is the port already held by a healthy Jarvis?
    status = get_service_status(args.port)
    if status == "ON":
        logger.info(f"✅ S2S Server is already running and HEALTHY on port {args.port}. Exiting.")
        sys.exit(0)
    elif status != "OFF":
        logger.warning(f"⚠️ Port {args.port} is {status}. Cleaning up before start...")
        kill_process_on_port(args.port)

    # Use global args for uvicorn config
    uvicorn.run(app, host=args.host, port=args.port)