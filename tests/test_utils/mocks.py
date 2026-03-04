import asyncio
import time
from typing import Any, AsyncGenerator
from utils.engine.contract import NodeImplementation, IOType

async def execute_mock_stt(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Mocks STT by returning a static string."""
    text = config.get('mock_text', "This is a mock transcription.")
    # Consume inputs to avoid hanging
    for stream in input_streams.values():
        async for _ in stream: pass
    
    await output_queue.put({"type": "text_final", "content": text, "ts": time.perf_counter()})

async def execute_mock_llm(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Mocks LLM by returning a static string."""
    text = config.get('mock_text', "This is a mock AI response.")
    # Consume inputs
    for stream in input_streams.values():
        async for _ in stream: pass
        
    await output_queue.put({"type": "text_final", "content": text, "ts": time.perf_counter()})

def get_mock_implementation(impl_id: str, role: str, mock_text: str = None) -> NodeImplementation:
    if role == 'stt':
        fn = execute_mock_stt
        it, ot = [IOType.AUDIO_FILE], [IOType.TEXT_FINAL]
    elif role == 'llm':
        fn = execute_mock_llm
        it, ot = [IOType.TEXT_STREAM], [IOType.TEXT_FINAL]
    else:
        fn = None; it = ot = []

    return NodeImplementation(
        id=impl_id,
        input_types=it,
        output_types=ot,
        execute_fn=fn,
        config={"mock_text": mock_text} if mock_text else {}
    )
