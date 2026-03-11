import socket
import asyncio
from ..config import load_config

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

async def is_port_in_use_async(port: int) -> bool:
    """Asynchronous version of is_port_in_use."""
    try:
        # We only need to see if we can open a connection; we don't need to read/write
        conn = asyncio.open_connection('127.0.0.1', port)
        reader, writer = await asyncio.wait_for(conn, timeout=0.1)
        writer.close()
        await writer.wait_closed()
        return True
    except:
        return False

def get_jarvis_ports():
    """Returns a set of all ports defined in config.yaml for Jarvis services."""
    cfg = load_config()
    ports = {cfg['ports']['ollama']}
    if 'vllm' in cfg['ports']:
        ports.add(cfg['ports']['vllm'])
    ports.update(cfg['stt_loadout'].values())
    ports.update(cfg['tts_loadout'].values())
    return ports
