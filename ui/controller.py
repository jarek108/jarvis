import os
import sys
import time
import json
import threading
import queue
import asyncio
from loguru import logger

# Add project root to sys.path
script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if script_dir not in sys.path:
    sys.path.append(script_dir)

import utils
from utils import load_config, get_system_health
from utils.engine import PipelineResolver, PipelineExecutor
from manage_loadout import apply_loadout, kill_loadout, restart_service, kill_service

CHECKPOINT_PATH = os.path.join(script_dir, ".cache", "checkpoint-client.json")

class JarvisController:
    def __init__(self, ui_queue, initial_state_path=None):
        self.ui_queue = ui_queue
        self.cfg = load_config()
        self.project_root = script_dir
        
        # 1. Redirect System Logs to UI
        # Legacy UI sink - only routes to visual terminal, does not log to disk
        def ui_sink(message):
            self.ui_queue.put({"type": "log", "msg": message.record["message"], "tag": "system"})
        # Allow logs that have no domain (Global logs), even if they have other extra metadata
        logger.add(ui_sink, format="{message}", level="INFO", filter=lambda r: not r["extra"].get("domain"))

        # 3. State
        self.current_session_id = f"CLIENT_{time.strftime('%Y%m%d_%H%M%S')}"
        self.session_dir = os.path.join(script_dir, "logs", "sessions", self.current_session_id)
        os.makedirs(self.session_dir, exist_ok=True)
        
        self.current_pipeline = "speech_to_speech"
        self.current_strategy = "fast_interaction"
        self.current_loadout = "NONE"
        self.node_positions = {} # Scoped per pipeline: { pid: { nid: [x,y] } }
        self.geometry = None
        self.is_maximized = False
        self.load_checkpoint()
        
        # 3.1 IMMEDIATE SYNC: Clear runtime registry only if we think we are starting fresh
        if self.current_loadout == "NONE":
            try:
                from manage_loadout import save_runtime_registry
                save_runtime_registry([], project_root=self.project_root, loadout_id="NONE")
            except: pass
        else:
            logger.info(f"🔄 Restoring session with active loadout: {self.current_loadout}")

        self.is_recording = False
        self.is_polling = True
        self.health_state = {}
        self.runnability = {"runnable": False, "errors": ["Initializing..."], "map": {}}
        self._last_daemon_state = "IDLE"
        
        # 4. Embedded Flow Engine (Session Aware)
        self.resolver = PipelineResolver(self.project_root)
        self.executor = PipelineExecutor(self.project_root, session_dir=self.session_dir)
        
        # Edge Hardware (bound via registry)
        self.ptt_signal = threading.Event()

        # 5. Fast-boot from initial state if provided
        if initial_state_path and os.path.exists(initial_state_path):
            try:
                with open(initial_state_path, "r") as f:
                    init_data = json.load(f)
                    self.health_state = init_data.get("health", {})
                    self.current_loadout = init_data.get("loadout", self.current_loadout)
                    active_models = init_data.get("models", [])
                    vram = init_data.get("vram", {"used": 0.0, "total": 0.0, "external": 0.0})
                    self.runnability = self.resolver.check_runnability(
                        self.current_pipeline, self.current_strategy, 
                        external_health=self.health_state, silent=True
                    )
                    self.ui_queue.put({
                        "type": "health_update",
                        "health": self.health_state,
                        "runnability": self.runnability,
                        "active_models": active_models,
                        "vram": vram
                    })
                    logger.info(f"🚀 FAST-BOOT: Loaded initial state from {initial_state_path}")
            except Exception as e:
                logger.error(f"Failed to load initial state: {e}")
        
        threading.Thread(target=self._status_polling_loop, daemon=True).start()

    def load_checkpoint(self):
        if os.path.exists(CHECKPOINT_PATH):
            try:
                with open(CHECKPOINT_PATH, "r") as f:
                    data = json.load(f)
                    self.current_pipeline = data.get("pipeline", self.current_pipeline)
                    self.current_strategy = data.get("strategy", self.current_strategy)
                    self.node_positions = data.get("node_positions", {})
                    self.geometry = data.get("geometry")
                    self.is_maximized = data.get("is_maximized", False)
                    # We EXPLICITLY do not restore the loadout here to ensure clean boot
                    self.current_loadout = "NONE"
            except: pass

    def save_checkpoint(self):
        try:
            with open(CHECKPOINT_PATH, "w") as f:
                json.dump({
                    "pipeline": self.current_pipeline, 
                    "strategy": self.current_strategy,
                    "loadout": self.current_loadout,
                    "node_positions": self.node_positions,
                    "geometry": self.geometry,
                    "is_maximized": self.is_maximized
                }, f)
        except: pass

    def update_node_positions(self, pipeline_id, positions):
        self.node_positions[pipeline_id] = positions
        self.save_checkpoint()

    def _status_polling_loop(self):
        import requests
        self._last_poll_state = None
        while self.is_polling:
            start_t = time.perf_counter()
            try:
                try:
                    r = requests.get("http://127.0.0.1:5555/status", timeout=1.0)
                    daemon_status = r.json()
                    active_models = daemon_status.get("models", [])
                    system_external_vram = daemon_status.get("vram", {}).get("external", 0.0)
                    # Convert the daemon's model list back to the health dict format the UI expects
                    self.health_state = {m['port']: {"status": m.get('state', 'OFF'), "info": m.get('info')} for m in active_models if m.get('port')}
                except:
                    # Fallback to local resolver if daemon is unreachable
                    registry_data = self.resolver.get_live_models()
                    active_models = registry_data.get("models", [])
                    system_external_vram = registry_data.get("external", 0.0)
                    active_ports = [m['port'] for m in active_models if m.get('port')]
                    log_map = {m['port']: m['log_path'] for m in active_models if m.get('log_path') and m.get('port')}
                    self.health_state = get_system_health(ports=active_ports, log_paths=log_map)
                
                vram_used = utils.get_gpu_vram_usage()
                vram_total = utils.get_gpu_total_vram()
                
                current_state = {
                    "pipeline": self.current_pipeline,
                    "strategy": self.current_strategy,
                    "health": self.health_state,
                    "models": active_models
                }
                
                if current_state != self._last_poll_state:
                    self.runnability = self.resolver.check_runnability(
                        self.current_pipeline, 
                        self.current_strategy, 
                        external_health=self.health_state, 
                        silent=True
                    )
                    self._last_poll_state = current_state
                
                # Logic for "LOADOUT APPLIED" detection
                try:
                    daemon_state = daemon_status.get("global_state")
                    if daemon_state == "READY" and self._last_daemon_state in ["STARTING", "IDLE"]:
                        msg = "✅ LOADOUT APPLIED"
                        logger.info(msg)
                        self.ui_queue.put({"type": "log", "msg": msg, "tag": "system"})
                    self._last_daemon_state = daemon_state
                except: pass

                self.ui_queue.put({
                    "type": "health_update", 
                    "health": self.health_state, 
                    "runnability": self.runnability,
                    "active_models": active_models,
                    "vram": {"used": vram_used, "total": vram_total, "external": system_external_vram}
                })
            except Exception as e:
                logger.error(f"Status Polling Error: {e}")
            
            poll_interval = self.cfg.get('system', {}).get('health_check_interval', 1.0)
            time.sleep(poll_interval)

    def trigger_loadout_change(self, loadout_id):
        if loadout_id != "NONE" and loadout_id == self.current_loadout:
            return
        self.current_loadout = loadout_id
        self.save_checkpoint()
        def task():
            import requests
            # Retry loop for 409 Conflict (Busy Daemon)
            max_retries = 15
            for attempt in range(max_retries):
                try:
                    if loadout_id == "NONE":
                        logger.info(f"☢️ KILLING ALL SERVICES (Attempt {attempt+1})...")
                        r = requests.delete("http://127.0.0.1:5555/loadout", timeout=20.0)
                    else:
                        logger.info(f"⚙️ APPLYING LOADOUT (Attempt {attempt+1}): {loadout_id}")
                        r = requests.post("http://127.0.0.1:5555/loadout", json={"name": loadout_id, "soft": True}, timeout=20.0)
                    
                    if r.status_code in [200, 202]:
                        logger.info("✅ LOADOUT DELEGATED TO DAEMON")
                        try:
                            data = r.json()
                            if 'models' in data:
                                self.health_state = {m['port']: {"status": "STARTING", "info": "Initiating..."} for m in data['models'] if m.get('port')}
                                logger.info(f"🚀 UI State updated instantly with {len(self.health_state)} models.")
                        except: pass
                        return # Success!
                    
                    if r.status_code == 409:
                        logger.warning(f"⚠️ SYSTEM BUSY (409): {r.text}. Retrying in 1s...")
                        time.sleep(1.0)
                        continue
                    
                    logger.error(f"❌ DAEMON ERROR {r.status_code}: {r.text}")
                    break # Fatal error
                except Exception as e:
                    logger.warning(f"Daemon communication attempt {attempt+1} failed: {e}")
                    time.sleep(1.0)
            
            logger.error("❌ Failed to change loadout after multiple retries.")
        threading.Thread(target=task, daemon=True).start()

    def start_recording(self):
        if not self.runnability.get('runnable'):
            logger.error(f"❌ CANNOT RUN: {', '.join(self.runnability['errors'])}")
            return
        self.is_recording = True
        self.ptt_signal.set()
        self.ui_queue.put({"type": "state", "recording": True})
        threading.Thread(target=self._run_pipeline_local, daemon=True).start()

    def stop_recording(self):
        if not self.is_recording: return
        self.is_recording = False
        self.ptt_signal.clear()
        self.ui_queue.put({"type": "state", "recording": False})

    def _run_pipeline_local(self):
        try:
            bound_graph = self.resolver.resolve(self.current_pipeline)
        except Exception as e:
            logger.error(f"Resolution Error: {e}")
            return
        inputs = {"ptt_active": self.ptt_signal}
        async def run_and_monitor():
            exec_task = asyncio.create_task(self.executor.run(bound_graph, inputs))
            last_idx = 0
            while not exec_task.done() or last_idx < len(self.executor.trace):
                while last_idx < len(self.executor.trace):
                    packet = self.executor.trace[last_idx]; last_idx += 1
                    if packet.get('dir') == 'OUT':
                        ptype = packet.get('type')
                        content = packet.get('content')
                        if ptype in ["text_token", "text_sentence", "text_final"]:
                            self.ui_queue.put({"type": "log", "msg": str(content), "tag": "assistant"})
                await asyncio.sleep(0.05)
        asyncio.run(run_and_monitor())
