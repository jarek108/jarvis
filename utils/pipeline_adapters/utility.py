from .base import NodeAdapter

class UtilityAdapter(NodeAdapter):
    async def run(self, node_id, node_config, input_streams, output_queue, session):
        op = node_config.get('operation')
        
        if op == 'chunk_by_delimiter':
            from utils.engine import chunk_by_delimiter
            delimiters = node_config.get('delimiters', '.?!')
            
            # Pick first input stream for chunking
            stream = next(iter(input_streams.values())) if input_streams else None
            if not stream: return

            async for out_packet in chunk_by_delimiter(stream, delimiters=delimiters):
                await output_queue.put(out_packet)
