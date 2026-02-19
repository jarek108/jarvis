import requests
import json
import time
import argparse
import os

def probe_video(url, model, video_url, prompt="Describe what is happening in this video."):
    """
    Sends a Chat Completion request to vLLM using the 'video_url' content type.
    """
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "video_url",
                        "video_url": {"url": video_url}
                    }
                ]
            }
        ],
        "max_tokens": 512,
        "temperature": 0
    }

    print(f"🚀 Sending probe to {url}...")
    print(f"📦 Payload snippet: {json.dumps(payload['messages'][0]['content'][1])}")
    
    start_time = time.perf_counter()
    try:
        response = requests.post(f"{url}/v1/chat/completions", json=payload, timeout=120)
        duration = time.perf_counter() - start_time
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            print(f"✅ Success ({duration:.2f}s)!")
            print(f"📝 Response: {content}")
            return True
        else:
            print(f"❌ Failed (HTTP {response.status_code})")
            print(f"Detail: {response.text}")
            return False
    except Exception as e:
        print(f"💥 Error: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="vLLM Native Video API Probe")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8300", help="vLLM server URL")
    parser.add_argument("--model", type=str, required=True, help="Model ID (e.g. Qwen/Qwen2-VL-2B-Instruct)")
    parser.add_argument("--video", type=str, required=True, help="Video URL or in-container local path")
    parser.add_argument("--prompt", type=str, default="Describe the main actions in this video.")
    
    args = parser.parse_args()
    
    probe_video(args.url, args.model, args.video, args.prompt)
