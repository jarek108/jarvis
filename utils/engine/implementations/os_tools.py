import os
import time
import asyncio
import aiohttp
from typing import Any, AsyncGenerator
from loguru import logger

# --- Optional Dependencies ---
try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    from win10toast import ToastNotifier
except ImportError:
    ToastNotifier = None

async def execute_notification(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """OS notification actuator."""
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            content = str(packet.get('content', ''))
            if ToastNotifier:
                try:
                    ToastNotifier().show_toast("Jarvis", content, duration=5, threaded=True)
                except: logger.info(f"🔔 NOTIFICATION: {content}")
            else:
                logger.info(f"🔔 NOTIFICATION: {content}")
            await output_queue.put(packet)

async def execute_keyboard_typer(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Emulates keyboard typing."""
    if not pyautogui: 
        logger.warning(f"[{node_id}] pyautogui missing. Skipping keyboard emulation.")
        return
        
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            content = str(packet.get('content', ''))
            pyautogui.write(content, interval=0.01)
            await output_queue.put(packet)

async def execute_clipboard_sensor(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Reads local clipboard content."""
    if not pyperclip: 
        logger.warning(f"[{node_id}] pyperclip missing. Skipping clipboard read.")
        return
    text = pyperclip.paste()
    await output_queue.put({"type": "text_final", "content": text, "ts": time.perf_counter()})

async def execute_clipboard_writer(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Writes text to the local clipboard."""
    if not pyperclip: 
        logger.warning(f"[{node_id}] pyperclip missing. Skipping clipboard write.")
        return
        
    for stream in input_streams.values():
        async for packet in stream:
            if packet is None: break
            content = str(packet.get('content', ''))
            pyperclip.copy(content)
            await output_queue.put({"type": "signal", "content": "SUCCESS", "ts": time.perf_counter()})

async def execute_chunker(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Logical chunking implementation."""
    from utils.engine import chunk_by_delimiter
    delimiters = config.get('delimiters', '.?!')
    stream = next(iter(input_streams.values())) if input_streams else None
    if not stream: return
    async for out_packet in chunk_by_delimiter(stream, delimiters=delimiters):
        await output_queue.put(out_packet)

async def execute_memory_node(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Handles session history and conversation context."""
    session_dir = config.get('session_dir', '.')
    storage_path = config.get('path', 'session_history.txt')
    if not os.path.isabs(storage_path):
        storage_path = os.path.join(session_dir, storage_path)
    
    os.makedirs(os.path.dirname(storage_path), exist_ok=True)
    
    # 1. READ
    history_content = ""
    if os.path.exists(storage_path):
        with open(storage_path, "r", encoding="utf-8", errors='ignore') as f:
            history_content = f.read()
    
    # 2. APPEND
    new_data = ""
    for in_id, stream in input_streams.items():
        async for packet in stream:
            if packet is None: break
            content = packet.get('content')
            if content:
                new_data += f"\n{in_id.upper()}: {content}"
    
    if new_data:
        with open(storage_path, "a", encoding="utf-8") as f:
            f.write(new_data)
        with open(storage_path, "r", encoding="utf-8") as f:
            history_content = f.read()

    await output_queue.put({"type": "text_final", "content": history_content, "ts": time.perf_counter()})

async def execute_file_reader(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Reads a text file from disk."""
    path = config.get('path')
    scenario_inputs = config.get('scenario_inputs', {})
    if not path:
        path = scenario_inputs.get(node_id) or scenario_inputs.get('input_text')
    
    if not path: return

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if not os.path.isabs(path):
        alt_path = os.path.join(project_root, "system_config", path)
        if os.path.exists(alt_path): path = alt_path
        else: path = os.path.join(project_root, path)

    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            await output_queue.put({"type": "text_final", "content": content, "ts": time.perf_counter()})

def validate_keyboard_typer(node_id: str, config: dict, scenario_inputs: dict) -> tuple[bool, str]:
    if not pyautogui: return False, "Missing 'pyautogui' library."
    return True, ""

def validate_file_reader(node_id: str, config: dict, scenario_inputs: dict) -> tuple[bool, str]:
    path = config.get('path') or scenario_inputs.get(node_id) or scenario_inputs.get('input_text')
    if not path: return False, f"Node '{node_id}' requires a file path."
    return True, ""
