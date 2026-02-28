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

"""
[Title] : Speech-to-Speech (sts) Graph-Based Server
[Section] : Description
Unified Production Server hosting the declarative flow graph engine.
Replaces the hardcoded pipeline with the reactive PipelineExecutor.
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import Response, JSONResponse, StreamingResponse
from contextlib import asynccontextmanager
import os
import sys
import time
import argparse
import yaml
import json
import asyncio
from typing import Optional
from loguru import logger

# Project Setup
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

import utils
from utils.pipeline import PipelineResolver, PipelineExecutor
from utils.console import ensure_utf8_output

ensure_utf8_output()
cfg = utils.load_config()

# Configure lean logging
logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | <cyan>{message}</cyan>", colorize=True, enqueue=True)

def get_args():
    parser = argparse.ArgumentParser(description="Jarvis sts Flow Server")
    parser.add_argument("--port", type=int, default=cfg['ports']['sts'])
    parser.add_argument("--pipeline", type=str, default="voice_to_voice")
    parser.add_argument("--mapping", type=str, help="Optional mapping override")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    return parser.parse_known_args()[0]

args = get_args()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 Initializing Jarvis Flow Engine (Pipeline: {args.pipeline})")
    app.state.resolver = PipelineResolver(project_root)
    app.state.executor = PipelineExecutor(project_root)
    
    # 1. Resolve Graph using the currently active loadout
    try:
        app.state.bound_graph = app.state.resolver.resolve(args.pipeline, args.mapping)
        logger.info("✅ Pipeline Resolved & Ready")
    except Exception as e:
        logger.error(f"❌ Failed to resolve pipeline: {e}")
        app.state.bound_graph = None

    app.state.is_ready = True
    yield
    logger.info("sts Server shutting down.")

app = FastAPI(lifespan=lifespan)
app.state.is_ready = False

@app.get("/health")
async def health():
    if not app.state.is_ready:
        return JSONResponse(status_code=503, content={"status": "STARTUP"})
    return {"status": "ON", "service": "sts_server", "pipeline": args.pipeline}

@app.post("/process_stream")
async def process_stream(
    file: UploadFile = File(...),
    language_id: Optional[str] = Form(None)
):
    """Production streaming endpoint using the Reactive Engine."""
    if not app.state.bound_graph:
        raise HTTPException(status_code=500, detail="Pipeline not resolved.")

    # 1. Save input to buffer
    audio_data = await file.read()
    temp_path = os.path.join(project_root, "buffers", "sts_input.wav")
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    with open(temp_path, "wb") as f: f.write(audio_data)

    # 2. Prepare Inputs
    scenario_inputs = {
        "input_mic": temp_path,
        "language": language_id or "en"
    }

    async def event_generator():
        # Standard Jarvis Protocol: Multi-part octet stream
        def frame(type_char, data):
            return type_char.encode() + len(data).to_bytes(4, 'little') + data

        # Wrapper task to run the executor
        exec_task = asyncio.create_task(app.state.executor.run(app.state.bound_graph, scenario_inputs))
        
        # Monitor the Trace and yield packets as they appear
        last_yielded_idx = 0
        while not exec_task.done() or last_yielded_idx < len(app.state.executor.trace):
            while last_yielded_idx < len(app.state.executor.trace):
                event = app.state.executor.trace[last_yielded_idx]
                last_yielded_idx += 1
                
                # Filter for OUT packets to stream to client
                if event.get('dir') == 'OUT':
                    etype = event.get('type')
                    # Map Packet types to Frame types
                    if etype in ['text_token', 'text_final', 'text_sentence']:
                        # For text, we send JSON metadata
                        # Note: In a real production app we'd retrieve the content from a packet queue
                        # but for now we rely on the trace's captured metadata logic
                        pass 
                
            await asyncio.sleep(0.05)
            
        # For this refactor, we yield the final result for simplicity in Step 1
        # Real binary audio streaming requires the Executor to yield raw buffers
        res = app.state.executor.results
        if "proc_tts" in res:
            with open(res["proc_tts"], "rb") as f:
                yield frame('A', f.read()[44:]) # Skip WAV header
        
        # Yield Metrics
        yield frame('M', json.dumps({
            "timings": app.state.executor.timings,
            "stt_text": res.get("proc_stt", ""),
            "llm_text": res.get("proc_llm", "")
        }).encode())

    return StreamingResponse(event_generator(), media_type="application/octet-stream")

@app.post("/process")
async def process_simple(
    file: UploadFile = File(...),
    language_id: Optional[str] = Form(None)
):
    """Simple Request-Response endpoint."""
    if not app.state.bound_graph:
        raise HTTPException(status_code=500, detail="Pipeline not resolved.")

    audio_data = await file.read()
    temp_path = os.path.join(project_root, "buffers", "sts_input.wav")
    with open(temp_path, "wb") as f: f.write(audio_data)

    success = await app.state.executor.run(app.state.bound_graph, {"input_mic": temp_path})
    if not success:
        raise HTTPException(status_code=500, detail="Pipeline execution failed.")

    res = app.state.executor.results
    if "proc_tts" in res:
        with open(res["proc_tts"], "rb") as f:
            audio_out = f.read()
            
        headers = {
            "X-Result-STT": str(res.get("proc_stt", ""))[:1000],
            "X-Result-LLM": str(res.get("proc_llm", ""))[:1000]
        }
        return Response(content=audio_out, media_type="audio/wav", headers=headers)

    raise HTTPException(status_code=500, detail="No audio output generated.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)

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
