import aiohttp
import os
from .base import NodeAdapter

class STTAdapter(NodeAdapter):
    async def run(self, node_id, node_config, input_streams, output_queue, session):
        binding = node_config.get('binding')
        if not binding: return
        
        # Identify first available audio path from any input
        audio_path = None
        for stream in input_streams.values():
            async for packet in stream:
                audio_path = packet.get('content')
                if audio_path: break
            if audio_path: break
            
        if not audio_path: 
            raise ValueError(f"{node_id} missing audio path.")

        # Robust Path Resolution
        if not os.path.exists(audio_path):
            abs_path = self.resolve_path(audio_path)
            if os.path.exists(abs_path):
                audio_path = abs_path
            else:
                raise FileNotFoundError(f"STT Audio not found: {audio_path}")

        data = aiohttp.FormData()
        data.add_field('file', open(audio_path, 'rb'))
        
        url = f"http://127.0.0.1:{binding['port']}/transcribe"
        async with session.post(url, data=data) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                raise RuntimeError(f"STT Server Error ({resp.status}): {err_text}")
            text = (await resp.json()).get('text', '')
            await output_queue.put(self.create_packet("text_final", text))
