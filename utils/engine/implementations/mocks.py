import asyncio
import time
from typing import Any, AsyncGenerator
from ..contract import NodeImplementation, IOType

async def execute_mock_stt(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Mocks STT by returning a static string."""
    text = config.get('mock_text', "This is a mock transcription.")
    for stream in input_streams.values():
        async for _ in stream: pass
    await output_queue.put({"type": "text_final", "content": text, "ts": time.perf_counter()})

async def execute_mock_llm(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Mocks LLM by returning a static string."""
    text = config.get('mock_text', "This is a mock AI response.")
    for stream in input_streams.values():
        async for _ in stream: pass
    await output_queue.put({"type": "text_final", "content": text, "ts": time.perf_counter()})

async def execute_mock_tts(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Mocks TTS by returning a static audio path."""
    for stream in input_streams.values():
        async for _ in stream: pass
    await output_queue.put({"type": "audio_path", "content": "tests/data/input.wav", "ts": time.perf_counter()})

async def execute_mock_source(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Mocks a sensor by returning the path from scenario_inputs or a default."""
    inputs = config.get('scenario_inputs', {})
    path = inputs.get(node_id) or inputs.get('input_mic') or inputs.get('input_media')
    if not path:
        # Fallbacks for manual mock mode
        if "mic" in node_id or "stt" in node_id: path = "tests/data/input.wav"
        elif "image" in node_id or "screen" in node_id: path = "tests/data/jarvis_logo.png"
    
    if path:
        await output_queue.put({"type": "data_path", "content": path, "ts": time.perf_counter()})

async def execute_mock_sink(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Mocks an actuator by doing nothing but propagating."""
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            await output_queue.put(packet)

def get_mock_implementation(impl_id: str, role: str, mock_text: str = None) -> NodeImplementation:
    role = role.lower()
    if role == 'stt':
        fn = execute_mock_stt
        it, ot = [IOType.AUDIO_FILE], [IOType.TEXT_FINAL]
    elif role == 'llm':
        fn = execute_mock_llm
        it, ot = [IOType.TEXT_STREAM], [IOType.TEXT_FINAL]
    elif role == 'tts':
        fn = execute_mock_tts
        it, ot = [IOType.TEXT_FINAL], [IOType.AUDIO_FILE]
    elif role in ['microphone', 'camera', 'screen_capture', 'clipboard_sensor', 'file_reader', 'source']:
        fn = execute_mock_source
        it, ot = [], [IOType.DATA_PATH]
    elif role in ['audio_playback', 'keyboard_typer', 'notification_actuator', 'sink', 'speaker']:
        fn = execute_mock_sink
        it, ot = [IOType.DATA_PATH, IOType.TEXT_FINAL], []
    else:
        fn = execute_mock_sink # Default sink-like
        it = [IOType.TEXT_FINAL, IOType.TEXT_STREAM, IOType.AUDIO_FILE, IOType.AUDIO_STREAM, IOType.IMAGE_FILE, IOType.IMAGE_RAW]
        ot = []

    return NodeImplementation(
        id=impl_id,
        input_types=it,
        output_types=ot,
        execute_fn=fn,
        config={"mock_text": mock_text} if mock_text else {}
    )
