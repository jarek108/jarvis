import asyncio
import aiohttp
import requests
from ..config import load_config
from .ports import is_port_in_use, get_jarvis_ports, is_port_in_use_async
from .logs import check_log_for_errors

async def get_service_status_async(session, port: int):
    """Asynchronous version of get_service_status."""
    if not await is_port_in_use_async(port): return port, "OFF", None
    cfg = load_config()
    url = f"http://127.0.0.1:{port}/health"
    if port == cfg['ports']['ollama']: url = f"http://127.0.0.1:{port}/api/tags"
    elif port == cfg['ports'].get('vllm'): url = f"http://127.0.0.1:{port}/v1/models"

    try:
        async with session.get(url, timeout=1.0) as response:
            if response.status == 200:
                data = await response.json()
                is_stub = "stub" in str(data.get("service", "")).lower() or data.get("stub") is True
                
                if port == cfg['ports']['ollama']: 
                    return port, "ON", ("Stub" if is_stub else "Ollama")
                if port == cfg['ports'].get('vllm'): 
                    if is_stub: return port, "ON", "Stub"
                    models = data.get("data", [])
                    return port, "ON", (models[0]["id"] if models else "vLLM")
                
                raw_name = data.get("model") or data.get("variant") or data.get("service") or "Ready"
                name = f"{raw_name} (Stub)" if is_stub and "stub" not in raw_name.lower() else raw_name
                return port, ("BUSY" if data.get("status") == "busy" else "ON"), name
            elif response.status == 503:
                data = await response.json()
                if data.get("status") == "STARTUP": return port, "STARTUP", "Loading..."
            return port, "UNHEALTHY", None
    except:
        return port, "OFF", None

def get_service_status(port: int):
    """Synchronous check of a single service status."""
    if not is_port_in_use(port): return "OFF", None
    cfg = load_config()
    try:
        url = f"http://127.0.0.1:{port}/health"
        if port == cfg['ports']['ollama']: url = f"http://127.0.0.1:{port}/api/tags"
        elif port == cfg['ports'].get('vllm'): url = f"http://127.0.0.1:{port}/v1/models"
        
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            data = response.json()
            is_stub = "stub" in str(data.get("service", "")).lower() or data.get("stub") is True
            if port == cfg['ports']['ollama']: return "ON", ("Stub" if is_stub else "Ollama")
            if port == cfg['ports'].get('vllm'):
                if is_stub: return "ON", "Stub"
                models = data.get("data", [])
                return "ON", (models[0]["id"] if models else "vLLM")
            raw_name = data.get("model") or data.get("variant") or data.get("service") or "Ready"
            name = f"{raw_name} (Stub)" if is_stub and "stub" not in raw_name.lower() else raw_name
            return ("BUSY" if data.get("status") == "busy" else "ON"), name
        elif response.status_code == 503 and response.json().get("status") == "STARTUP":
            return "STARTUP", "Loading..."
        return "UNHEALTHY", None
    except: return "OFF", None

async def get_system_health_async(ports=None, log_paths=None):
    """Polls specified or all Jarvis services in parallel, including log error checks."""
    import os
    import time
    
    is_mock = os.environ.get('JARVIS_MOCK_ALL') == "1" or os.environ.get('JARVIS_UI_TEST') == "1"
    if is_mock:
        global _mock_state_tracker
        target_ports = ports if ports is not None else get_jarvis_ports()
        
        now = time.time()
        for p in target_ports:
            if p not in _mock_state_tracker:
                _mock_state_tracker[p] = now

        cfg = load_config()
        delay_range = cfg.get('system', {}).get('mock_startup_range', [1.5, 3.0])

        result = {}
        for p in target_ports:
            elapsed = now - _mock_state_tracker[p]
            target_delay = (p % (delay_range[1] - delay_range[0])) + delay_range[0]
            status = "STARTUP" if elapsed < target_delay else "ON"
            result[p] = {"status": status, "info": "MOCKED"}
        return result

    # Explicitly check for None so that empty list [] is honored (idle scan avoidance)
    target_ports = ports if ports is not None else get_jarvis_ports()
    if not target_ports: return {} # Handle empty scan immediately
    
    async with aiohttp.ClientSession() as session:
        tasks = [get_service_status_async(session, p) for p in target_ports]
        results = await asyncio.gather(*tasks)
    
    health = {r[0]: {"status": r[1], "info": r[2]} for r in results}
    if log_paths:
        for port, path in log_paths.items():
            if port in health and health[port]['status'] != "ON":
                if check_log_for_errors(path):
                    health[port]['status'] = "ERROR"
                    health[port]['info'] = "Fatal Error (Check Logs)"
    return health

_mock_state_tracker = {}

def get_system_health(ports=None, log_paths=None):
    """Consolidated synchronous health check for all or specific services."""
    import os
    import time

    is_mock = os.environ.get('JARVIS_MOCK_ALL') == "1" or os.environ.get('JARVIS_UI_TEST') == "1"
    if is_mock:
        global _mock_state_tracker
        
        target_ports = ports if ports is not None else get_jarvis_ports()

        # Update tracker for any new ports seen
        now = time.time()
        for p in target_ports:
            if p not in _mock_state_tracker:
                _mock_state_tracker[p] = now

        cfg = load_config()
        delay_range = cfg.get('system', {}).get('mock_startup_range', [1.5, 3.0])

        # Pre-build port metadata map for mock info
        port_meta = {}
        if 'ollama' in cfg['ports']: port_meta[cfg['ports']['ollama']] = {"label": "Ollama", "type": "llm"}
        if 'vllm' in cfg['ports']: port_meta[cfg['ports']['vllm']] = {"label": "vLLM", "type": "llm"}
        for name, port in cfg['stt_loadout'].items(): port_meta[port] = {"label": name, "type": "stt"}
        for name, port in cfg['tts_loadout'].items(): port_meta[port] = {"label": name, "type": "tts"}

        result = {}
        for p in target_ports:
            elapsed = now - _mock_state_tracker[p]
            # Use deterministic delay based on port number to avoid flicker
            target_delay = (p % (delay_range[1] - delay_range[0])) + delay_range[0]

            status = "STARTUP" if elapsed < target_delay else "ON"
            meta = port_meta.get(p, {"label": f"MOCK_{p}", "type": "unknown"})
            result[p] = {
                "status": status, 
                "info": "MOCKED", 
                "label": meta['label'], 
                "type": meta['type']
            }

        return result

    health_raw = asyncio.run(get_system_health_async(ports=ports, log_paths=log_paths))

    health = {}
    port_map = {cfg['ports']['ollama']: {"label": "Ollama", "type": "llm"}}
    if 'vllm' in cfg['ports']: port_map[cfg['ports']['vllm']] = {"label": "vLLM", "type": "llm"}
    for name, port in cfg['stt_loadout'].items(): port_map[port] = {"label": name, "type": "stt"}
    for name, port in cfg['tts_loadout'].items(): port_map[port] = {"label": name, "type": "tts"}

    if ports: port_map = {p: meta for p, meta in port_map.items() if p in ports}
    for port, meta in port_map.items():
        res = health_raw.get(port, {"status": "OFF", "info": None})
        status = res['status']
        if ports and port in ports and status == "OFF": status = "STARTUP"
        health[port] = {"status": status, "info": res['info'], "label": meta['label'], "type": meta['type']}
    return health

async def wait_for_ports_parallel(ports, timeout, require_stub=False):
    if not ports: return True
    start_time = asyncio.get_event_loop().time()
    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() - start_time < timeout:
            tasks = [get_service_status_async(session, p) for p in ports]
            results = await asyncio.gather(*tasks)
            all_on = True
            for r in results:
                p_port, status, info = r
                if status != "ON": all_on = False; break
                if require_stub and "stub" not in str(info).lower(): all_on = False; break
            if all_on: return True
            await asyncio.sleep(0.5)
    return False
