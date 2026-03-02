import re
import time
from loguru import logger

async def chunk_by_delimiter(input_packet_stream, delimiters=".?!", min_length=1):
    """
    Consumes an async generator of PipelinePackets (tokens) 
    and yields packets (sentences) based on delimiters.
    """
    buffer = ""
    pattern = f"([{re.escape(delimiters)}])"
    seq = 0
    
    async for packet in input_packet_stream:
        token = packet.get('content', '')
        if not token: continue
        buffer += token
        
        # Split but keep delimiters
        parts = re.split(pattern, buffer)
        
        # re.split with capture group keeps delimiters in the list
        while len(parts) > 2:
            chunk = (parts[0] + parts[1]).strip()
            if len(chunk) >= min_length:
                yield {
                    "type": "text_sentence",
                    "content": chunk,
                    "seq": seq,
                    "ts": time.perf_counter(),
                    "metadata": {"source_seq": packet.get('seq')}
                }
                seq += 1
            
            # Rebuild buffer with remaining parts
            buffer = "".join(parts[2:])
            parts = re.split(pattern, buffer)
            
    # Yield remaining buffer
    final_chunk = buffer.strip()
    if final_chunk:
        yield {
            "type": "text_sentence",
            "content": final_chunk,
            "seq": seq,
            "ts": time.perf_counter()
        }
