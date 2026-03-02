import os
from .base import NodeAdapter
from loguru import logger

class MemoryAdapter(NodeAdapter):
    """
    Handles session history and conversation context using local file I/O.
    Fulfills the 'State-as-I/O' principle.
    """
    async def run(self, node_id, node_config, input_streams, output_queue, session):
        logger.info(f"🧠 Memory Node '{node_id}' executing.")
        
        # 1. Resolve storage path
        storage_path = self.resolve_path(node_config.get('path'), 'session_history.txt')
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        
        # 2. READ current state (if no input, we just yield the existing file)
        history_content = ""
        if os.path.exists(storage_path):
            with open(storage_path, "r", encoding="utf-8", errors='ignore') as f:
                history_content = f.read()
        
        # 3. APPEND new inputs (if provided)
        new_data = ""
        for in_id, stream in input_streams.items():
            async for packet in stream:
                content = packet.get('content')
                if content:
                    new_data += f"\n{in_id.upper()}: {content}"
        
        if new_data:
            with open(storage_path, "a", encoding="utf-8") as f:
                f.write(new_data)
            # Re-read to provide updated context
            with open(storage_path, "r", encoding="utf-8") as f:
                history_content = f.read()

        # 4. Yield the consolidated history
        p = self.create_packet("text_final", history_content)
        await output_queue.put(p)
