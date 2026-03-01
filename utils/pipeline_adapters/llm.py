import json
import os
from .base import NodeAdapter

class LLMAdapter(NodeAdapter):
    async def run(self, node_id, node_config, input_streams, output_queue, session):
        binding = node_config.get('binding')
        if not binding: return
        
        port = binding['port']
        model_id = binding['id'].split('#')[0]
        
        # vLLM requires the full canonical ID (e.g. Qwen/Qwen2-VL-...)
        if binding['engine'] == "vllm":
            from utils.config import resolve_canonical_id
            model_id = resolve_canonical_id(model_id, engine="vllm")
        else:
            # Ollama/Stubs cleanup
            model_id = model_id.replace("OL_", "").replace("VL_", "")
            if binding['engine'] == "ollama": model_id = model_id.lower()
        
        # 1. Collect inputs from all streams
        resolved_inputs = {}
        for in_id, stream in input_streams.items():
            content = ""
            async for packet in stream:
                # Accumulate content (LLM currently needs full prompt to start)
                val = packet.get('content', '')
                if val:
                    if isinstance(val, str) and os.path.exists(val):
                        # If it's a file path (like system prompt), read it
                        with open(val, 'r', encoding='utf-8', errors='ignore') as f:
                            content += f.read()
                    else:
                        content += str(val)
            resolved_inputs[in_id] = content

        # 2. Build Prompt
        layout = node_config.get('context_layout')
        if layout:
            prompt = layout
            for in_id, val in resolved_inputs.items():
                prompt = prompt.replace("{{" + in_id + "}}", val)
        else:
            # Default: Merge all non-empty inputs
            prompt = "\n".join([v for v in resolved_inputs.values() if v]) or "Hello"

        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": node_config.get('output_streaming', False)
        }
        
        url = f"http://127.0.0.1:{port}/v1/chat/completions"
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                raise RuntimeError(f"LLM Server Error ({resp.status}): {err_text}")
            
            if payload['stream']:
                seq = 0
                async for line in resp.content:
                    if not line: continue
                    line_text = line.decode('utf-8').strip()
                    if line_text.startswith("data: ") and "[DONE]" not in line_text:
                        try:
                            token = json.loads(line_text[6:])['choices'][0]['delta'].get('content', '')
                            if token:
                                await output_queue.put(self.create_packet("text_token", token, seq))
                                seq += 1
                        except: pass
            else:
                text = (await resp.json())['choices'][0]['message']['content']
                await output_queue.put(self.create_packet("text_final", text))
