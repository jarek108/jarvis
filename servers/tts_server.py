from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from contextlib import asynccontextmanager
import torch
import io
import os
import sys
import time
import argparse
import soundfile as sf
from loguru import logger

# --- EMERGENCY HOTFIX: Monkey-patch perth ---
try:
    class DummyWatermarker:
        def __init__(self, *args, **kwargs): pass
        def apply(self, *args, **kwargs): return args[0]
        def apply_watermark(self, wav, *args, **kwargs): return wav
    import perth
    perth.PerthImplicitWatermarker = DummyWatermarker
    logger.warning("💉 EMERGENCY: Monkey-patched perth.PerthImplicitWatermarker")
except Exception as e:
    logger.error(f"💉 Patch failed: {e}")
# -----------------------------------------------------

from chatterbox.tts import ChatterboxTTS
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from chatterbox.tts_turbo import ChatterboxTurboTTS

# Force HF_TOKEN to False if not set
if "HF_TOKEN" not in os.environ:
    os.environ["HF_TOKEN"] = "False"

# 1. Parse CLI arguments
parser = argparse.ArgumentParser(description="Chatterbox TTS Server")
parser.add_argument("--port", type=int, default=8200, help="Port to run on")
parser.add_argument("--variant", type=str, default="chatterbox-eng", help="chatterbox-eng, chatterbox-multilingual, or chatterbox-turbo")
parser.add_argument("--benchmark-mode", action="store_true", help="Enable deterministic output for benchmarking")
args, unknown = parser.parse_known_args()

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.utils import load_config

cfg = load_config()
VARIANT_ID = args.variant
device = cfg['device'] if torch.cuda.is_available() else "cpu"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info(f"🚀 Loading TTS Variant: {VARIANT_ID} on {device} (Benchmark Mode: {args.benchmark_mode})...")

    # Strip prefix and map 'eng' to 'vanilla' internal logic
    internal_variant = VARIANT_ID.replace("chatterbox-", "")
    if internal_variant == "eng": internal_variant = "vanilla"

    try:
        if internal_variant == "multilingual":
            model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        elif internal_variant == "turbo":
            model = ChatterboxTurboTTS.from_pretrained(device=device)
        else:
            # Default to vanilla (eng)
            model = ChatterboxTTS.from_pretrained(device=device)
        
        # Store model in app state for request handlers
        app.state.model = model
        app.state.internal_variant = internal_variant
        app.state.benchmark_mode = args.benchmark_mode
        
        # --- WARMUP ---
        logger.info(f"🔥 Warming up TTS [{VARIANT_ID}] (CUDA spin-up)...")
        start_warm = time.perf_counter()
        
        if args.benchmark_mode:
            torch.manual_seed(42)

        if internal_variant == "multilingual":
            model.generate("warm", "en")
        else:
            model.generate("warm")
        
        app.state.is_ready = True
        logger.info(f"✅ Model {VARIANT_ID} loaded and WARM on port {args.port} ({time.perf_counter() - start_warm:.1f}s).")
    except Exception as e:
        logger.critical(f"❌ CRITICAL ERROR: Failed to load model {VARIANT_ID}: {e}")
        sys.exit(1)
    
    yield

app = FastAPI(lifespan=lifespan)
app.state.is_ready = False

@app.get("/health")
async def health():
    if not app.state.is_ready:
        return JSONResponse(status_code=503, content={"status": "STARTUP", "variant": VARIANT_ID})
    return {"status": "ON", "variant": VARIANT_ID, "port": args.port, "benchmark_mode": app.state.benchmark_mode}

@app.post("/tts")
async def tts(request: Request):
    try:
        data = await request.json()
        text = data.get("text", "")
        language_id = data.get("language_id", "en") 
        
        if not text:
            return Response(status_code=400, content="No text provided")
        
        model = app.state.model
        internal_variant = app.state.internal_variant
        
        logger.debug(f"Generating [{VARIANT_ID}] TTS for: [{text[:50]}...]")
        
        start_time = time.perf_counter()
        
        if app.state.benchmark_mode:
            torch.manual_seed(42)

        if internal_variant == "multilingual":
            wav = model.generate(text, language_id)
        else:
            wav = model.generate(text)
        processing_time = time.perf_counter() - start_time
        
        wav_numpy = wav.squeeze().cpu().numpy()
        out = io.BytesIO()
        sf.write(out, wav_numpy, model.sr, format="WAV")
        
        return Response(
            content=out.getvalue(), 
            media_type="audio/wav",
            headers={"X-Inference-Time": str(processing_time)}
        )
    except Exception as e:
        logger.error(f"Error generating TTS: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port)
