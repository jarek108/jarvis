import argparse
import time
import json
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

@app.get("/api/tags")
async def tags():
    """Mimics Ollama model listing."""
    return {"models": [{"name": "stub-model:latest"}], "service": "llm_stub"}

@app.get("/v1/models")
async def models():
    """Mimics vLLM model listing."""
    return {"data": [{"id": "stub-model:latest"}], "service": "llm_stub"}

@app.post("/api/chat")
@app.post("/v1/chat/completions")
async def chat(request: Request):
    """Mimics Ollama/vLLM chat API with streaming support."""
    data = await request.json()
    model = data.get("model", "stub")
    stream = data.get("stream", False)
    
    # Extract prompt
    messages = data.get("messages", [])
    prompt = messages[-1]["content"] if messages else "hi"
    if isinstance(prompt, list): # VLM format
        prompt = next((p["text"] for p in prompt if p["type"] == "text"), "image prompt")

    response_text = f"Stub response to: {prompt}"

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
                "choices": [{"message": {"content": response_text}, "finish_reason": "stop"}]
            }
        else:
            return {
                "model": model,
                "message": {"role": "assistant", "content": response_text},
                "done": True
            }

@app.get("/health")
async def health():
    return {"status": "ON", "service": "llm_stub"}

if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11434)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
