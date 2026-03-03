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
from utils.edge import AudioSensor
from manage_loadout import apply_loadout, kill_loadout, restart_service, kill_service

CHECKPOINT_PATH = os.path.join(script_dir, ".cache", "checkpoint-client.json")

class JarvisController:
    def __init__(self, ui_queue):
        self.ui_queue = ui_queue
        self.cfg = load_config()
        self.project_root = script_dir
        
        # 1. Redirect System Logs to UI
        def ui_sink(message):
            self.ui_queue.put({"type": "log", "msg": message.record["message"], "tag": "system"})
        logger.add(ui_sink, format="{message}", level="INFO")

        # 3. State
        self.current_session_id = f"CLIENT_{time.strftime('%Y%m%d_%H%M%S')}"
        self.session_dir = os.path.join(script_dir, "logs", "sessions", self.current_session_id)
        os.makedirs(self.session_dir, exist_ok=True)
        
        self.current_pipeline = "voice_to_voice"
        self.current_strategy = "fast_interaction"
        self.current_loadout = "NONE"
        self.node_positions = {} # Scoped per pipeline: { pid: { nid: [x,y] } }
        self.load_checkpoint()
        
        # Force system state to match UI "NONE" state
        def init_cleanup():
            self.ui_queue.put({"type": "log", "msg": "🧹 Cleaning up previous session state...", "tag": "system"})
            kill_loadout("all")
        threading.Thread(target=init_cleanup, daemon=True).start()
        
        self.is_recording = False
        self.is_polling = True
        self.health_state = {}
        self.runnability = {"runnable": False, "errors": ["Initializing..."], "map": {}}
        
        # 4. Embedded Flow Engine (Session Aware)
        self.resolver = PipelineResolver(self.project_root)
        self.executor = PipelineExecutor(self.project_root, session_dir=self.session_dir)
        
        # Edge Hardware
        self.audio_sensor = AudioSensor()
        
        threading.Thread(target=self._status_polling_loop, daemon=True).start()

    def load_checkpoint(self):
        if os.path.exists(CHECKPOINT_PATH):
            try:
                with open(CHECKPOINT_PATH, "r") as f:
                    data = json.load(f)
                    self.current_pipeline = data.get("pipeline", self.current_pipeline)
                    self.current_strategy = data.get("strategy", self.current_strategy)
                    self.node_positions = data.get("node_positions", {})
                    # Force NONE on startup
                    self.current_loadout = "NONE"
            except: pass

    def save_checkpoint(self):
        try:
            with open(CHECKPOINT_PATH, "w") as f:
                json.dump({
                    "pipeline": self.current_pipeline, 
                    "strategy": self.current_strategy,
                    "loadout": self.current_loadout,
                    "node_positions": self.node_positions
                }, f)
        except: pass

    def update_node_positions(self, pipeline_id, positions):
        """Updates and saves manual node positions for a specific pipeline."""
        self.node_positions[pipeline_id] = positions
        self.save_checkpoint()

    def _status_polling_loop(self):
        while self.is_polling:
            try:
                # 1. Get Physical Health for ACTIVE LOADOUT ONLY (Fast Path)
                registry_data = self.resolver.get_live_models()
                active_models = registry_data.get("models", [])
                system_external_vram = registry_data.get("external", 0.0)
                
                active_ports = [m['port'] for m in active_models if m.get('port')]
                
                # Map ports to log paths for error detection
                log_map = {m['port']: m['log_path'] for m in active_models if m.get('log_path') and m.get('port')}
                self.health_state = get_system_health(ports=active_ports, log_paths=log_map)
                
                # 2. Get Hardware Metrics
                vram_used = utils.get_gpu_vram_usage()
                vram_total = utils.get_gpu_total_vram()

                # 3. Check Logical Runnability (Passing existing health to avoid double-poll)
                self.runnability = self.resolver.check_runnability(self.current_pipeline, self.current_strategy, external_health=self.health_state)
                
                # 4. Update UI
                self.ui_queue.put({
                    "type": "health_update", 
                    "health": self.health_state, 
                    "runnability": self.runnability,
                    "active_models": active_models,
                    "vram": {"used": vram_used, "total": vram_total, "external": system_external_vram}
                })
            except Exception as e:
                logger.error(f"Status Polling Error: {e}")
            time.sleep(1.5)

    def trigger_loadout_change(self, loadout_id):
        # 1. Skip if same loadout already active (unless it's NONE, then we allow re-kill)
        if loadout_id != "NONE" and loadout_id == self.current_loadout:
            logger.info(f"Loadout '{loadout_id}' already active. Skipping application.")
            return

        self.current_loadout = loadout_id
        self.save_checkpoint()
        
        def task():
            if loadout_id == "NONE":
                self.ui_queue.put({"type": "log", "msg": "☢️ KILLING ALL SERVICES...", "tag": "system"})
                kill_loadout("all")
            else:
                self.ui_queue.put({"type": "log", "msg": f"⚙️ APPLYING LOADOUT: {loadout_id}", "tag": "system"})
                try:
                    # Apply loadout using existing logic (Soft apply to avoid full kill if possible)
                    apply_loadout(loadout_id, soft=True)
                    self.ui_queue.put({"type": "log", "msg": "✅ LOADOUT APPLIED", "tag": "system"})
                except Exception as e:
                    self.ui_queue.put({"type": "log", "msg": f"❌ LOADOUT ERROR: {e}", "tag": "system"})

        threading.Thread(target=task, daemon=True).start()

    def trigger_service_restart(self, sid):
        def task():
            self.ui_queue.put({"type": "log", "msg": f"🔄 RESTARTING SERVICE: {sid}", "tag": "system"})
            try:
                restart_service(sid, self.current_loadout)
                self.ui_queue.put({"type": "log", "msg": f"✅ RESTARTED: {sid}", "tag": "system"})
            except Exception as e:
                self.ui_queue.put({"type": "log", "msg": f"❌ RESTART ERROR [{sid}]: {e}", "tag": "system"})
        threading.Thread(target=task, daemon=True).start()

    def trigger_service_kill(self, sid):
        def task():
            self.ui_queue.put({"type": "log", "msg": f"🔪 CLOSING SERVICE: {sid}", "tag": "system"})
            try:
                kill_service(sid)
                self.ui_queue.put({"type": "log", "msg": f"✅ CLOSED: {sid}", "tag": "system"})
            except Exception as e:
                self.ui_queue.put({"type": "log", "msg": f"❌ CLOSE ERROR [{sid}]: {e}", "tag": "system"})
        threading.Thread(target=task, daemon=True).start()

    def start_recording(self):
        if not self.runnability.get('runnable'):
            self.ui_queue.put({"type": "log", "msg": f"❌ CANNOT RUN: {', '.join(self.runnability['errors'])}", "tag": "system"})
            return
        self.is_recording = True
        self.ui_queue.put({"type": "state", "recording": True})

    def stop_recording(self):
        if not self.is_recording: return
        self.is_recording = False
        self.ui_queue.put({"type": "state", "recording": False})
        audio_data = self.audio_sensor.capture_snapshot(duration=3.0)
        threading.Thread(target=self._run_pipeline_local, args=(audio_data,), daemon=True).start()

    def _run_pipeline_local(self, audio_data):
        temp_audio = os.path.join(self.session_dir, "user_voice.wav")
        os.makedirs(os.path.dirname(temp_audio), exist_ok=True)
        with open(temp_audio, "wb") as f: f.write(audio_data)

        try:
            bound_graph = self.resolver.resolve(self.current_pipeline, self.current_strategy)
        except Exception as e:
            self.ui_queue.put({"type": "log", "msg": f"Resolution Error: {e}", "tag": "system"})
            return

        inputs = {"input_mic": temp_audio}

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
