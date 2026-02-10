import requests
import time
import json
import os
import sys
import re

# Allow importing utils from parent
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import report_llm_result, ensure_utf8_output

ensure_utf8_output()

def run_test(model_name="gpt-oss:20b"):
    url = "http://127.0.0.1:11434/api/chat"
    
    scenarios = [
        {"name": "english_std", "text": "Hello, this is a test of Tatterbox TTS."},
        {"name": "polish_explicit", "text": "Cześć, nazywam się Jarbis, jed mogę ci dzisiaj pomóc."},
        {"name": "short2long", "text": "Tell me a four to five sentences story about a dog."},
        {"name": "long2short", "text": "It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in want of a wife. However little known the feelings or views of such a man may be on his first entering a neighbourhood, this truth is so well fixed in the minds of the surrounding families, that he is considered the rightful property of some one or other of their daughters. What is the title of this book? Respond with title only."}
    ]

    for s in scenarios:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": s['text']}],
            "stream": True,
            "options": {"temperature": 0, "seed": 42}
        }

        try:
            start_time = time.perf_counter()
            first_token_time = None
            first_response_time = None
            full_text = ""
            thought_text = ""
            chunks = []
            sentence_buffer = ""
            total_tokens = 0
            is_thinking = False

            with requests.post(url, json=payload, stream=True) as resp:
                if resp.status_code != 200:
                    report_llm_result({"name": s['name'], "status": "FAILED", "text": f"HTTP {resp.status_code}"})
                    continue

                for line in resp.iter_lines():
                    if line:
                        data = json.loads(line.decode())
                        token = data.get("message", {}).get("content", "")
                        
                        if first_token_time is None:
                            first_token_time = time.perf_counter()

                        # Logic to handle <thought> tags if present
                        if "<thought>" in token: 
                            is_thinking = True
                            continue
                        if "</thought>" in token: 
                            is_thinking = False
                            continue
                        
                        if is_thinking:
                            thought_text += token
                        else:
                            full_text += token
                            sentence_buffer += token
                            if first_response_time is None and token.strip():
                                first_response_time = time.perf_counter()

                            # Detect sentence end in the actual response
                            if any(c in token for c in ".!?"):
                                chunks.append({
                                    "text": sentence_buffer.strip(),
                                    "end": time.perf_counter() - start_time
                                })
                                sentence_buffer = ""

                        total_tokens += 1

                if sentence_buffer.strip():
                    chunks.append({
                        "text": sentence_buffer.strip(),
                        "end": time.perf_counter() - start_time
                    })

            total_dur = time.perf_counter() - start_time
            ttft = first_token_time - start_time if first_token_time else 0
            ttfr = (first_response_time - start_time) if first_response_time else ttft
            tps = total_tokens / total_dur if total_dur > 0 else 0

            res_obj = {
                "name": s['name'],
                "status": "PASSED",
                "ttft": ttft,
                "ttfr": ttfr,
                "tps": tps,
                "raw_text": full_text,
                "thought": thought_text.strip(),
                "chunks": chunks,
                "duration": total_dur
            }
            report_llm_result(res_obj)

        except Exception as e:
            report_llm_result({"name": s['name'], "status": "FAILED", "text": str(e)})

if __name__ == "__main__":
    run_test()