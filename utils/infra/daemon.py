import time
import asyncio
import requests
from utils import load_config

def wait_for_daemon_ready(timeout=30.0, require_models=False, polling_interval=0.5):
    """
    Synchronous waiter for the Jarvis Daemon.
    Returns True if settled, False on timeout.
    """
    cfg = load_config()
    daemon_port = cfg.get('ports', {}).get('daemon', 5555)
    url = f"http://127.0.0.1:{daemon_port}/status"
    
    start_t = time.perf_counter()
    while time.perf_counter() - start_t < timeout:
        try:
            r = requests.get(url, timeout=1.0)
            if r.status_code == 200:
                data = r.json()
                if data.get('ready'):
                    if not require_models or (require_models and data.get('models')):
                        return True
        except:
            pass
        time.sleep(polling_interval)
    return False

async def wait_for_daemon_ready_async(timeout=30.0, require_models=False, polling_interval=0.5):
    """
    Asynchronous waiter for the Jarvis Daemon.
    Returns True if settled, False on timeout.
    """
    cfg = load_config()
    daemon_port = cfg.get('ports', {}).get('daemon', 5555)
    url = f"http://127.0.0.1:{daemon_port}/status"
    
    start_t = time.perf_counter()
    while time.perf_counter() - start_t < timeout:
        try:
            # We still use requests but in a non-blocking loop with await sleep
            r = requests.get(url, timeout=1.0)
            if r.status_code == 200:
                data = r.json()
                if data.get('ready'):
                    if not require_models or (require_models and data.get('models')):
                        return True
        except:
            pass
        await asyncio.sleep(polling_interval)
    return False
