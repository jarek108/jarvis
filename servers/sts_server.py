"""
[Title] : Speech-to-Speech (sts) Pipeline Server
[Section] : Description
This server orchestrates the full STT -> LLM -> TTS pipeline. It acts as the 
central entry point for Jarvis, managing its own dependencies (STT, TTS, Ollama)
if they are not already running.

[Section] : Usage Examples
[Subsection] : Default (uses default.yaml)
python servers/sts_server.py

[Subsection] : Custom Loadout
python servers/sts_server.py --loadout eng_turbo

[Subsection] : Manual Overrides
python servers/sts_server.py --stt faster-whisper-tiny --tts chatterbox-turbo
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

from utils import load_config, is_port_in_use, kill_process_on_port, start_server, get_service_status
from utils.console import ensure_utf8_output

# Ensure UTF-8 output for Windows console
ensure_utf8_output()

# Global config and state
cfg = load_config()
owned_ports = []
DEFAULT_LOADOUT = "base-qwen30-multi"

# Configure lean logging
logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | <cyan>{message}</cyan>", colorize=True, enqueue=True)

def get_args():
    parser = argparse.ArgumentParser(description="Jarvis sts Server")
    parser.add_argument("--port", type=int, default=cfg['ports']['sts'], help="Port to run the sts server on")
    parser.add_argument("--loadout", type=str, help="Name of a loadout preset (e.g., eng_turbo)")
    parser.add_argument("--stt", type=str, help="STT model override")
    parser.add_argument("--tts", type=str, help="TTS variant override")
    parser.add_argument("--llm", type=str, help="LLM model override")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output for benchmarking")
    parser.add_argument("--stub", action="store_true", help="Run in stub mode (skip warmup)")
    parser.add_argument("--trust-deps", action="store_true", help="Skip internal dependency health checks and warmup (assumes runner manages infra)")
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
            await asyncio.sleep(0.5)
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
    logger.info("Initializing Jarvis sts Cluster...")
    
    # 1. Determine active models
    active_stt = args.stt
    active_tts = args.tts
    active_llm = args.llm
    
    selected_loadout = args.loadout or DEFAULT_LOADOUT
    loadout_path = os.path.join(project_root, "loadouts", f"{selected_loadout}.yaml")
    
    if os.path.exists(loadout_path):
        with open(loadout_path, "r") as f:
            l_data = yaml.safe_load(f)
            if not active_stt:
                stt_val = l_data.get("stt")
                if stt_val:
                    active_stt = stt_val[0] if isinstance(stt_val, list) else stt_val
            if not active_tts:
                tts_val = l_data.get("tts")
                if tts_val:
                    active_tts = tts_val[0] if isinstance(tts_val, list) else tts_val
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
    
    # 3. Executables
    python_exe = sys.executable

    # Determine LLM engine and port
    llm_engine = "ollama"
    llm_model_name = active_llm
    if isinstance(active_llm, dict):
        llm_engine = active_llm.get("engine", "ollama")
        llm_model_name = active_llm.get("model")
    elif isinstance(active_llm, str) and active_llm.startswith("vllm:"):
        llm_engine = "vllm"
        llm_model_name = active_llm[5:]
    elif isinstance(active_llm, str) and active_llm.startswith("VL_"):
        llm_engine = "vllm"
        llm_model_name = active_llm[3:]
    elif isinstance(active_llm, str) and active_llm.startswith("OL_"):
        llm_engine = "ollama"
        llm_model_name = active_llm[3:]

    if llm_engine == "vllm":
        llm_port = cfg['ports'].get('vllm', 8300)
        llm_service_name = "vLLM Core"
        llm_cmd = [python_exe, "-m", "vllm.entrypoints.openai.api_server", "--model", llm_model_name, "--port", str(llm_port)]
        llm_health = f"http://127.0.0.1:{llm_port}/v1/models"
        app.state.llm_model_prefixed = f"vl_{llm_model_name}"
    else:
        llm_port = cfg['ports']['ollama']
        llm_service_name = "Ollama Core"
        llm_cmd = ["ollama", "serve"]
        llm_health = f"http://127.0.0.1:{llm_port}/api/tags"
        app.state.llm_model_prefixed = f"ol_{llm_model_name}"

    app.state.llm_port = llm_port
    app.state.llm_engine = llm_engine
    app.state.llm_model = llm_model_name

    stt_script = os.path.join(project_root, "servers", "stt_server.py")
    tts_script = os.path.join(project_root, "servers", "tts_server.py")

    services = [
        {
            "name": "STT Server", 
            "port": stt_port, 
            "cmd": [python_exe, stt_script, "--port", str(stt_port), "--model", active_stt] + (["--benchmark-mode"] if args.benchmark_mode else []), 
            "health": f"http://127.0.0.1:{stt_port}/health"
        },
        {
            "name": "TTS Server", 
            "port": tts_port, 
            "cmd": [python_exe, tts_script, "--port", str(tts_port), "--variant", active_tts] + (["--benchmark-mode"] if args.benchmark_mode else []), 
            "health": f"http://127.0.0.1:{tts_port}/health"
        },
        {
            "name": llm_service_name, 
            "port": llm_port, 
            "cmd": llm_cmd, 
            "health": llm_health
        }
    ]

    if not args.trust_deps:
        logger.info("📡 Checking Infrastructure...")
        for s in services:
            if not is_port_in_use(s["port"]):
                logger.info(f"  ✨ Spawning {s['name']} (Port {s['port']})")
                start_server(s["cmd"], loud=False)
                owned_ports.append(s["port"])
            else:
                logger.info(f"  ℹ️  {s['name']} is already running.")

        # Wait for all
        wait_timeout = 5 if args.stub else 120
        ready_tasks = [wait_for_service_ready(s['name'], s['health'], timeout=wait_timeout) for s in services]
        results = await asyncio.gather(*ready_tasks)
        
        if not all(results):
            logger.critical("🚨 DEPENDENCY FAILURE: Pipeline entry blocked.")

        # 4. LLM Warmup (External)
        if llm_engine == "ollama" and not args.stub:
            await warmup_ollama(f"http://127.0.0.1:{llm_port}", llm_model_name)
    else:
        logger.info("🚀 Trusting Dependencies (Skipping internal checks/warmup)")

    app.state.is_ready = True
    logger.info("✨ JARVIS PIPELINE READY")
    yield
    
    # --- SHUTDOWN ---
    logger.info(f"sts Server shutting down. Cleaning up {len(owned_ports)} owned services...")
    for port in owned_ports:
        kill_process_on_port(port)
    logger.info("Cleanup complete.")

app = FastAPI(lifespan=lifespan)
app.state.is_ready = False

@app.get("/health")
async def health_check():
    if not app.state.is_ready:
        return JSONResponse(status_code=503, content={"status": "STARTUP"})
    return {"status": "ON", "service": "sts_server"}

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
    llm_port = app.state.llm_port

    try:
        audio_data = await file.read()
        
        timeout = aiohttp.ClientTimeout(total=300)
        # 1. STT (Buffered)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            stt_url = f"http://127.0.0.1:{stt_port}/transcribe"
            form = aiohttp.FormData()
            form.add_field('file', audio_data, filename='input.wav', content_type='audio/wav')
            if language_id:
                form.add_field('language', language_id)
            async with session.post(stt_url, data=form) as resp:
                stt_result = await resp.json()
                input_text = stt_result.get("text", "")

        if not input_text:
            return Response(status_code=400, content="No speech detected")

        async def audio_generator():
            def frame(type_char, data):
                return type_char.encode() + len(data).to_bytes(4, 'little') + data

            # Pipelined metrics (relative to total_start)
            m = {
                "stt": [0, 0],
                "llm": [0, 0],
                "tts": [0, 0],
                "stt_text": input_text,
                "llm_text": "",
                "llm_chunks": [], # [{text, end}]
                "tts_chunks": []  # [{text, end}]
            }
            
            # 1. Send STT text immediately
            stt_ready_time = round(time.perf_counter() - total_start, 2)
            yield frame('T', json.dumps({
                "role": "user", 
                "text": input_text,
                "start": 0.0,
                "end": stt_ready_time
            }).encode())

            m["stt"] = [stt_ready_time, stt_ready_time]
            
            queue = asyncio.Queue()
            
            async def llm_producer():
                """Reads tokens from LLM as fast as possible and pushes sentences to queue."""
                sentence_buffer = ""
                full_llm_text = ""
                first_token_time = None
                
                try:
                    async with aiohttp.ClientSession() as session:
                        llm_url = f"http://127.0.0.1:{llm_port}/v1/chat/completions"
                        llm_payload = {
                            "model": active_llm,
                            "messages": [{"role": "user", "content": input_text}],
                            "stream": True,
                            "temperature": 0.7
                        }
                        if args.benchmark_mode:
                            llm_payload["temperature"] = 0
                            llm_payload["seed"] = 42

                        async with session.post(llm_url, json=llm_payload) as resp:
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
                                            full_llm_text += token
                                            
                                            if any(c in sentence_buffer for c in ".!?"):
                                                parts = re.split(r'(?<=[.!?])\s+', sentence_buffer)
                                                for i in range(len(parts) - 1):
                                                    sentence = parts[i].strip()
                                                    if sentence:
                                                        # TRUTHFUL TIMESTAMP: Mark LLM chunk end the moment it's generated
                                                        m["llm_chunks"].append({"text": sentence, "end": round(time.perf_counter() - total_start, 2)})
                                                        await queue.put(sentence)
                                                sentence_buffer = parts[-1]
                                        except:
                                            continue
                    
                    if sentence_buffer.strip():
                        sentence = sentence_buffer.strip()
                        m["llm_chunks"].append({"text": sentence, "end": round(time.perf_counter() - total_start, 2)})
                        await queue.put(sentence)
                
                finally:
                    m["llm_text"] = full_llm_text
                    await queue.put(None) # Sentinel

            # Start producer in background
            producer_task = asyncio.create_task(llm_producer())
            
            first_audio_time = None
            last_audio_time = None
            
            try:
                async with aiohttp.ClientSession() as session:
                    while True:
                        sentence = await queue.get()
                        if sentence is None: break
                        
                        # 3. TTS for sentence
                        sentence_start = round(time.perf_counter() - total_start, 2)
                        tts_url = f"http://127.0.0.1:{tts_port}/tts"
                        tts_payload = {"text": sentence, "voice": "default", "language_id": language_id or "en"}
                        async with session.post(tts_url, json=tts_payload) as tts_resp:
                            if tts_resp.status == 200:
                                if first_audio_time is None:
                                    first_audio_time = time.perf_counter()
                                    m["tts"][0] = round(first_audio_time - total_start, 2)
                                
                                audio_chunk = await tts_resp.read()
                                last_audio_time = time.perf_counter()
                                sentence_end = round(last_audio_time - total_start, 2)
                                
                                # Mark TTS chunk delivery
                                m["tts_chunks"].append({"text": sentence, "end": sentence_end})
                                
                                # 2. Yield LLM text chunk with timestamps
                                yield frame('T', json.dumps({
                                    "role": "jarvis", 
                                    "text": sentence,
                                    "start": sentence_start,
                                    "end": sentence_end
                                }).encode())

                                # 4. Yield Audio frame (skipping 44-byte WAV header)
                                yield frame('A', audio_chunk[44:])
            finally:
                # End of stream metrics
                m["tts"][1] = round((last_audio_time or time.perf_counter()) - total_start, 2)
                await producer_task
                # 5. Yield Metrics frame
                yield frame('M', json.dumps(m).encode())

        # Measure STT duration before stream starts
        stt_dur = time.perf_counter() - total_start
        
        custom_headers = {
            "X-Model-STT": safe_header(active_stt),
            "X-Model-LLM": safe_header(app.state.llm_model_prefixed),
            "X-Model-TTS": safe_header(active_tts)
        }
        
        return StreamingResponse(audio_generator(), media_type="application/octet-stream", headers=custom_headers)

    except Exception as e:
        logger.error(f"sts Streaming Error: {e}")
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
    llm_port = app.state.llm_port

    try:
        audio_data = await file.read()
        
        timeout = aiohttp.ClientTimeout(total=300) # 5 minutes
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 1. STT
            stt_url = f"http://127.0.0.1:{stt_port}/transcribe"
            form = aiohttp.FormData()
            form.add_field('file', audio_data, filename='input.wav', content_type='audio/wav')
            if language_id:
                form.add_field('language', language_id)
            
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
            # Override for determinism in benchmark mode
            if args.benchmark_mode:
                llm_payload["temperature"] = 0
                llm_payload["seed"] = 42

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
        custom_headers["X-Model-LLM"] = safe_header(app.state.llm_model_prefixed)
        custom_headers["X-Model-TTS"] = safe_header(active_tts)
        
        return Response(content=output_audio, media_type="audio/wav", headers=custom_headers)

    except Exception as e:
        logger.error(f"sts Pipeline Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    
    # Pre-flight check: is the port already held by a healthy Jarvis?
    status = get_service_status(args.port)
    if status == "ON":
        logger.info(f"✅ sts Server is already running and HEALTHY on port {args.port}. Exiting.")
        sys.exit(0)
    elif status != "OFF":
        logger.warning(f"⚠️ Port {args.port} is {status}. Cleaning up before start...")
        kill_process_on_port(args.port)

    # Use global args for uvicorn config
    uvicorn.run(app, host=args.host, port=args.port)
