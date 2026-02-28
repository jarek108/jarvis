from .base import NodeAdapter
from loguru import logger

class MemoryAdapter(NodeAdapter):
    """
    STUB: Handles session history and conversation context.
    Currently a pass-through placeholder for Phase 2.
    """
    async def run(self, node_id, node_config, input_streams, output_queue, session):
        logger.info(f"🧠 Memory Node '{node_id}' reached (STUB)")
        
        # For now, it just yields what it receives (Pass-through)
        async for packet in input_streams.values():
            async for p in packet:
                await output_queue.put(p)
