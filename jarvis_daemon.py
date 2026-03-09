import os
import sys
import time
import asyncio
from fastapi import FastAPI, BackgroundTasks, Request
from pydantic import BaseModel
import uvicorn
from loguru import logger

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

from utils.infra.status import get_system_health_async
from manage_loadout import apply_loadout, kill_loadout, kill_service, restart_service
from utils import get_gpu_vram_usage, get_gpu_total_vram
from utils.engine import PipelineResolver

app = FastAPI(title="Jarvis Loadout Daemon")

class StateManager:
    def __init__(self):
        self.loadout_id = "NONE"
        self.global_state = "IDLE"
        self.models = []
        self.external_vram = 0.0
        self.is_polling = False
        self.poll_task = None

    async def start_polling(self):
        if self.is_polling: return
        self.is_polling = True
        self.poll_task = asyncio.create_task(self._poll_loop())

    async def stop_polling(self):
        self.is_polling = False
        if self.poll_task:
            self.poll_task.cancel()
            self.poll_task = None

    async def _poll_loop(self):
        cfg = load_config()
        poll_interval = cfg.get('system', {}).get('health_check_interval', 1.0)
        
        while self.is_polling:
            if self.models:
                active_ports = [m['port'] for m in self.models if m.get('port')]
                log_map = {m['port']: m['log_path'] for m in self.models if m.get('log_path') and m.get('port')}
                health = await get_system_health_async(ports=active_ports, log_paths=log_map)
                
                all_on = True
                any_error = False
                for mdata in self.models:
                    port = mdata.get('port')
                    old_state = mdata.get('state', 'STARTING')
                    
                    if port in health:
                        st = health[port]['status']
                        mdata['state'] = st
                        mdata['info'] = health[port]['info']
                        if st not in ["ON", "BUSY"]: all_on = False
                        if st in ["ERROR", "UNHEALTHY"]: any_error = True
                    else:
                        st = "OFF"
                        mdata['state'] = st
                        all_on = False
                    
                    if st != old_state and old_state != "OFF":
                        logger.info(f"[State Transition] {mdata['id']} changed from {old_state} to {st}")
                
                old_global = self.global_state
                if any_error: self.global_state = "ERROR"
                elif all_on: self.global_state = "READY"
                else: self.global_state = "STARTING"
                
                if old_global != self.global_state:
                    logger.info(f"==> Global Loadout State: {self.global_state}")
                
                from manage_loadout import save_runtime_registry
                save_runtime_registry(self.models, project_root=script_dir, external_vram=self.external_vram, loadout_id=self.loadout_id)
            else:
                self.global_state = "IDLE"
                # Call with empty ports to ensure mock state trackers are cleared
                await get_system_health_async(ports=[])
            
            await asyncio.sleep(poll_interval)

state = StateManager()

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Jarvis Daemon Poller")
    await state.start_polling()

@app.on_event("shutdown")
async def shutdown_event():
    await state.stop_polling()

@app.get("/status")
async def get_status():
    return {
        "loadout_id": state.loadout_id,
        "global_state": state.global_state,
        "models": state.models,
        "vram": {
            "used": get_gpu_vram_usage(),
            "total": get_gpu_total_vram(),
            "external": state.external_vram
        }
    }

class WatchRequest(BaseModel):
    loadout_id: str
    external_vram: float
    models: list

@app.post("/watch")
async def watch_models(req: WatchRequest):
    state.loadout_id = req.loadout_id
    state.external_vram = req.external_vram
    
    new_models = []
    for m in req.models:
        if 'state' not in m: m['state'] = 'STARTING'
        new_models.append(m)
        
    state.models = new_models
    state.global_state = "STARTING"
    return {"status": "watching", "count": len(state.models)}

class LoadoutRequest(BaseModel):
    name: str
    soft: bool = True

@app.post("/loadout")
async def apply_loadout_endpoint(req: LoadoutRequest, background_tasks: BackgroundTasks):
    if req.name == "NONE":
        kill_loadout("all")
        state.loadout_id = "NONE"
        state.models = []
        state.global_state = "IDLE"
        return {"status": "cleared"}
    
    try:
        # Pre-populate state instantly so UI immediately sees STARTUP
        import yaml
        loadouts_file = os.path.join(script_dir, "system_config", "loadouts.yaml")
        with open(loadouts_file, "r") as f:
            all_loadouts = yaml.safe_load(f)
        target = all_loadouts.get(req.name, {})
        raw_models = target.get('models', []) if isinstance(target, dict) else target
        
        from utils.config import parse_model_string, load_config
        cfg = load_config()
        
        pre_models = []
        for m_str in raw_models:
            m_data = parse_model_string(m_str)
            if not m_data: continue
            sid = m_data['id']
            engine = m_data['engine']
            role = "stt" if "whisper" in sid.lower() else "tts" if "chatterbox" in sid.lower() or "piper" in sid.lower() else "llm"
            port = cfg.get(f"{role}_loadout", {}).get(sid) or cfg.get("ports", {}).get(engine)
            if port:
                pre_models.append({"id": sid, "port": port, "state": "STARTING", "engine": engine})
        
        state.loadout_id = req.name
        state.models = pre_models
        state.global_state = "STARTING"
    except Exception as e:
        logger.error(f"Failed to pre-parse loadout: {e}")

    def task():
        try:
            # apply_loadout is synchronous and writes to runtime_registry.json
            apply_loadout(req.name, soft=req.soft)
            
            # Read the generated registry to get accurate log paths and final metadata
            resolver = PipelineResolver(script_dir)
            res = resolver.get_live_models()
            state.external_vram = res.get('external', 0.0)
            
            new_models = []
            for m in res.get('models', []):
                m['state'] = 'STARTING'
                new_models.append(m)
                
            state.models = new_models
            
        except Exception as e:
            logger.error(f"Failed to apply loadout: {e}")
            state.global_state = "ERROR"
            
    background_tasks.add_task(task)
    return {"status": "starting", "loadout": req.name}

@app.delete("/loadout")
async def clear_loadout(background_tasks: BackgroundTasks):
    def task(): kill_loadout("all")
    background_tasks.add_task(task)
    state.loadout_id = "NONE"
    state.models = []
    state.global_state = "IDLE"
    return {"status": "clearing"}

@app.post("/service/{sid}/restart")
async def restart_svc(sid: str, background_tasks: BackgroundTasks):
    def task(): restart_service(sid, state.loadout_id)
    background_tasks.add_task(task)
    return {"status": "restarting"}

@app.delete("/service/{sid}")
async def kill_svc(sid: str, background_tasks: BackgroundTasks):
    def task(): kill_service(sid)
    background_tasks.add_task(task)
    state.models = [m for m in state.models if m['id'] != sid]
    return {"status": "killing"}

if __name__ == "__main__":
    from utils import load_config
    cfg = load_config()
    daemon_port = cfg.get('ports', {}).get('daemon', 5555)
    uvicorn.run(app, host="127.0.0.1", port=daemon_port)
