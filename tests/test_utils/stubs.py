import argparse
import time
import json
import asyncio
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

START_TIME = time.time()
DELAY = 0.0

def check_delay():
    if time.time() - START_TIME < DELAY:
        return JSONResponse(status_code=503, content={"status": "STARTUP"})
    return None

@app.get("/api/tags")
async def tags(request: Request):
    """Mimics Ollama model listing."""
    if d := check_delay(): return d
    return {"models": [{"name": "stub-model:latest"}], "service": "llm_stub"}

@app.get("/v1/models")
async def models(request: Request):
    """Mimics vLLM model listing."""
    if d := check_delay(): return d
    return {"data": [{"id": "stub-model:latest"}], "service": "llm_stub"}

@app.post("/api/chat")
@app.post("/v1/chat/completions")
async def chat(request: Request):
    """Mimics Ollama/vLLM chat API with streaming support."""
    if d := check_delay(): return d
    data = await request.json()
    model = data.get("model", "stub")
    stream = data.get("stream", False)
    
    # Extract prompt
    messages = data.get("messages", [])
    prompt = "hi"
    has_video = False
    if messages:
        content = messages[-1].get("content", [])
        if isinstance(content, list):
            prompt = next((p["text"] for p in content if p.get("type") == "text"), "image prompt")
            has_video = any(p.get("type") == "video_url" for p in content)
        else:
            prompt = content

    response_text = f"Stub response to: {prompt}"
    if has_video:
        response_text += " [Video Detected]"

    if stream:
        async def generate():
            # Mimic Ollama/vLLM chunking
            chunks = response_text.split()
            for i, word in enumerate(chunks):
                chunk_text = word + (" " if i < len(chunks)-1 else "")
                
                if "/v1/" in str(request.url): # vLLM / OpenAI format
                    payload = {
                        "choices": [{"delta": {"content": chunk_text}, "index": 0, "finish_reason": None}]
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                else: # Ollama format
                    payload = {
                        "model": model,
                        "message": {"role": "assistant", "content": chunk_text},
                        "done": False
                    }
                    yield json.dumps(payload) + "\n"
                await asyncio.sleep(0.05)
            
            if "/v1/" in str(request.url):
                yield "data: [DONE]\n\n"
            else:
                yield json.dumps({"done": True}) + "\n"

        return StreamingResponse(generate(), media_type="application/x-ndjson")
    else:
        if "/v1/" in str(request.url):
            return {
                "choices": [{"message": {"content": response_text}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": len(response_text.split()), "prompt_tokens": 10, "total_tokens": 10 + len(response_text.split())}
            }
        else:
            return {
                "model": model,
                "message": {"role": "assistant", "content": response_text},
                "done": True,
                "eval_count": len(response_text.split())
            }
    

@app.get("/health")
@app.get("/")
async def health(request: Request):
    if d := check_delay(): return d
    return {"status": "ON", "service": "stub", "port": request.url.port}

if __name__ == "__main__":
    import uvicorn
    import os
    import sys
    import random
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    if project_root not in sys.path:
        sys.path.append(project_root)
        
    try:
        from utils import load_config
        cfg = load_config()
        mock_range = cfg.get('system', {}).get('mock_startup_range', [1.5, 3.0])
        DELAY = round(random.uniform(mock_range[0], mock_range[1]), 2)
    except:
        DELAY = 0.0

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11434)
    args = parser.parse_args()
    
    uvicorn.run(app, host="127.0.0.1", port=args.port)
