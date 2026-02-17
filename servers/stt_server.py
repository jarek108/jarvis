from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
import torch
from faster_whisper import WhisperModel
import io
import os
import sys
import time
import argparse
from typing import Optional
import numpy as np

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.utils import load_config, ensure_utf8_output

# Ensure UTF-8 output for Windows console
ensure_utf8_output()

# 1. Parse CLI arguments
parser = argparse.ArgumentParser(description="Faster Whisper STT Server")
parser.add_argument("--port", type=int, default=8100, help="Port to run on")
parser.add_argument("--model", type=str, default="faster-whisper-base", help="Model size (faster-whisper-tiny, etc)")
parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output for benchmarking")
args, unknown = parser.parse_known_args()

app = FastAPI()
cfg = load_config()

# 2. Load model based on CLI args
device = cfg['device'] if torch.cuda.is_available() else "cpu"
model_id = args.model

# Strip prefix if present for faster-whisper loading
actual_model = model_id.replace("faster-whisper-", "")
if actual_model == "large": actual_model = "large-v3"

print(f"Loading Whisper STT ({actual_model}) on {device}...")
model = WhisperModel(actual_model, device=device, compute_type="float16" if device == "cuda" else "int8")

# --- WARMUP ---
print(f"Warming up STT [{model_id}] (First-time kernel spin-up)...")
warmup_audio = np.zeros(16000, dtype=np.float32) # 1s of silence at 16kHz
# Use deterministic settings for warmup if in benchmark mode
warmup_beam = 1 if args.benchmark_mode else 5
list(model.transcribe(warmup_audio, beam_size=warmup_beam)) # Force evaluation
print(f"STT {model_id} loaded and WARM on port {args.port} (Benchmark Mode: {args.benchmark_mode}).")

@app.get("/health")
async def health():
    return {"status": "ready", "model": model_id, "port": args.port, "benchmark_mode": args.benchmark_mode}

@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None)
):
    try:
        audio_bytes = await file.read()
        audio_file = io.BytesIO(audio_bytes)
        
        start_time = time.perf_counter()
        # Deterministic settings for benchmarking
        beam_size = 1 if args.benchmark_mode else 5
        
        segments, info = model.transcribe(audio_file, beam_size=beam_size, language=language if language else None)
        text = "".join([segment.text for segment in segments]).strip()
        processing_time = time.perf_counter() - start_time
        
        print(f"STT [{model_id}] Result: [{text}] (Took {processing_time:.3f}s)")
        
        return JSONResponse(
            content={"text": text, "language": info.language, "detected_language": info.language},
            headers={"X-Inference-Time": str(processing_time)}
        )
    except Exception as e:
        print(f"STT Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port)
