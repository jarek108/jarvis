"""
[Title] : Jarvis Universal Graph Host
[Section] : Description
The single entry point for the Jarvis production environment. 
This server is pipeline-agnostic; it loads a flow graph from YAML and executes it 
using the reactive PipelineExecutor.
"""

import os
import sys
import time
import argparse
import asyncio
import json
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse, JSONResponse
from contextlib import asynccontextmanager
from loguru import logger

# Project Setup
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

import utils
from utils.pipeline import PipelineResolver, PipelineExecutor

# --- CONFIGURATION ---
cfg = utils.load_config()
logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | <cyan>{message}</cyan>", colorize=True)

def get_args():
    parser = argparse.ArgumentParser(description="Jarvis Universal Host")
    parser.add_argument("--port", type=int, default=cfg['ports']['sts'], help="Main server port")
    parser.add_argument("--pipeline", type=str, default="voice_to_voice", help="Default pipeline to host")
    parser.add_argument("--mapping", type=str, help="Optional mapping override")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    return parser.parse_known_args()[0]

args = get_args()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"⚛️  Starting Jarvis Universal Host [Pipeline: {args.pipeline}]")
    app.state.resolver = PipelineResolver(project_root)
    app.state.executor = PipelineExecutor(project_root)
    
    # Resolve the hosted graph at startup
    try:
        app.state.bound_graph = app.state.resolver.resolve(args.pipeline, args.mapping)
        logger.info(f"✅ Resolved '{args.pipeline}' with active loadout")
    except Exception as e:
        logger.error(f"❌ Resolution Failed: {e}")
        app.state.bound_graph = None

    app.state.is_ready = True
    yield
    logger.info("Jarvis Host shutting down.")

app = FastAPI(lifespan=lifespan)
app.state.is_ready = False

@app.get("/health")
async def health():
    if not app.state.is_ready:
        return JSONResponse(status_code=503, content={"status": "STARTUP"})
    return {
        "status": "ON",
        "service": "jarvis_server",
        "hosted_pipeline": args.pipeline,
        "is_resolvable": app.state.bound_graph is not None
    }

@app.post("/process_stream")
async def process_stream(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    language: Optional[str] = Form("en")
):
    """Unified endpoint for multi-modal reactive execution."""
    if not app.state.bound_graph:
        raise HTTPException(status_code=503, detail="Server not correctly initialized or pipeline resolution failed.")

    # 1. Prepare Inputs
    scenario_inputs = {"language": language}
    if text:
        scenario_inputs["input_instruction"] = text
        scenario_inputs["input_text"] = text
    
    if file:
        audio_data = await file.read()
        temp_path = os.path.join(project_root, "buffers", "incoming_user_input.wav")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f: f.write(audio_data)
        scenario_inputs["input_mic"] = temp_path

    async def event_generator():
        # Standard Multi-Part Frame Protocol: [TypeChar (1)][Length (4)][Payload (N)]
        def frame(type_char, data):
            return type_char.encode() + len(data).to_bytes(4, 'little') + data

        # Start Execution Task
        exec_task = asyncio.create_task(app.state.executor.run(app.state.bound_graph, scenario_inputs))
        
        # 2. Yield Packets as they are produced (Reactive Monitoring)
        last_seen_idx = 0
        while not exec_task.done() or last_seen_idx < len(app.state.executor.trace):
            while last_seen_idx < len(app.state.executor.trace):
                packet = app.state.executor.trace[last_seen_idx]
                last_seen_idx += 1
                
                # Filter for OUT packets to stream to client
                if packet.get('dir') == 'OUT':
                    ptype = packet.get('type')
                    content = packet.get('content')
                    
                    # A: Audio Data (Fulfillment)
                    if ptype == "audio_path":
                        if content and os.path.exists(content):
                            with open(content, "rb") as f:
                                yield frame('A', f.read()[44:])
                    
                    # T: Text Content (Tokens/Sentences)
                    elif ptype in ["text_token", "text_sentence", "text_final"]:
                        if content:
                            msg = {"text": str(content), "type": ptype, "seq": packet.get('seq', 0)}
                            yield frame('T', json.dumps(msg).encode())

                    # S: State Metadata
                    elif ptype == "input_source":
                        yield frame('S', json.dumps({"state": "READY_FOR_Fulfillment", "source": packet.get('node')}).encode())

            await asyncio.sleep(0.01) # Yield to execution loop

        # 3. Final Metrics & Telemetry
        final_metrics = {
            "node_timings": app.state.executor.timings,
            "vram_peak": app.state.executor.vram_peak,
            "trace_len": len(app.state.executor.trace)
        }
        yield frame('M', json.dumps(final_metrics).encode())

    return StreamingResponse(event_generator(), media_type="application/octet-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)
