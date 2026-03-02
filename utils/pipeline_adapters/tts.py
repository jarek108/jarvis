import os
from .base import NodeAdapter

class TTSAdapter(NodeAdapter):
    async def run(self, node_id, node_config, input_streams, output_queue, session):
        binding = node_config.get('binding')
        if not binding: return
        
        full_audio = b""
        url = f"http://127.0.0.1:{binding['port']}/tts"
        
        # Pick the primary input stream (Reactive)
        stream = next(iter(input_streams.values())) if input_streams else None
        if not stream: return

        async for packet in stream:
            text = packet.get('content')
            if not text: continue
            
            async with session.post(url, json={'text': text}) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise RuntimeError(f"TTS Server Error ({resp.status}): {err_text}")
                full_audio += await resp.read()
        
        if full_audio:
            out_path = self.resolve_path(node_config.get('output'), f"{node_id}.wav")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, 'wb') as f: f.write(full_audio)
            await output_queue.put(self.create_packet("audio_path", out_path))
