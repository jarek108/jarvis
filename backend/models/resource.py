import asyncio
import logging
import os
import sys
import time
import json
from typing import List, Dict, Set, Optional

# Link to existing utils
import utils

logger = logging.getLogger("jarvis.resource")

class ResourceManager:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.cfg = utils.load_config()
        self.active_loadout: Dict[str, any] = {} # m_type -> {id, proc, port}
        self.python_exe = utils.resolve_path(self.cfg['paths']['venv_python'])
        
    async def ensure_loadout(self, required_models: List[str]):
        """
        Determines which models need to be swapped based on VRAM constraints.
        """
        if not required_models: return
        logger.info(f"⚖️ Balancing loadout for: {required_models}")
        
        # 1. Map IDs to Types
        target_map = self._identify_model_types(required_models)
        
        # 2. Check for LLM changes (forces full flush for isolation in V1)
        current_llm = self.active_loadout.get("llm", {}).get("id")
        target_llm = target_map.get("llm")
        
        if current_llm and target_llm and current_llm != target_llm:
            logger.info(f"🧹 Swapping LLM {current_llm} -> {target_llm}. Flushing services...")
            utils.kill_all_jarvis_services()
            self.active_loadout.clear()

        # 3. Start missing services
        for m_type, m_id in target_map.items():
            if m_type in self.active_loadout and self.active_loadout[m_type]["id"] == m_id:
                # Already running
                continue
            
            await self._spawn_model(m_type, m_id)

    def _identify_model_types(self, models: List[str]) -> Dict[str, str]:
        types = {}
        for m in models:
            m_lower = m.lower()
            if "whisper" in m_lower: types["stt"] = m
            elif "chatterbox" in m_lower: types["tts"] = m
            elif any(x in m_lower for x in ["ol_", "vl_", "vllm:"]): types["llm"] = m
        return types

    async def _spawn_model(self, m_type: str, m_id: str):
        logger.info(f"🚀 Spawning {m_type}: {m_id}")
        
        cmd = []
        port = 0
        is_docker = False

        if m_type == "stt":
            port = self.cfg['stt_loadout'].get(m_id, 8101)
            script = os.path.join(self.project_root, "servers", "stt_server.py")
            cmd = [self.python_exe, script, "--port", str(port), "--model", m_id, "--benchmark-mode"]
        
        elif m_type == "tts":
            port = self.cfg['tts_loadout'].get(m_id, 8201)
            script = os.path.join(self.project_root, "servers", "tts_server.py")
            cmd = [self.python_exe, script, "--port", str(port), "--variant", m_id, "--benchmark-mode"]
            
        elif m_type == "llm":
            if m_id.startswith("OL_"):
                port = self.cfg['ports']['ollama']
                cmd = ["ollama", "serve"]
            elif m_id.startswith("VL_"):
                is_docker = True
                port = self.cfg['ports'].get('vllm', 8300)
                await self._spawn_vllm_docker(m_id, port)

        if cmd:
            if not is_docker:
                proc = utils.start_server(cmd)
                self.active_loadout[m_type] = {"id": m_id, "proc": proc, "port": port}
            
            # Wait for port
            success = await asyncio.to_thread(utils.wait_for_port, port, timeout=120)
            if success:
                logger.info(f"✅ {m_type} is ready on port {port}")
                if m_type == "llm":
                    # Perform warmup
                    await asyncio.to_thread(utils.warmup_llm, m_id, visual=False, engine=("ollama" if m_id.startswith("OL_") else "vllm"))
            else:
                logger.error(f"❌ Failed to start {m_type} on port {port}")

    async def _spawn_vllm_docker(self, model_id: str, port: int):
        """Hardened vLLM Docker spawning logic."""
        # 1. Clean previous
        utils.stop_vllm_docker()
        
        # 2. Resolve Model Name and Utilization
        model_name = model_id[3:] # Strip VL_
        total_vram = utils.get_gpu_total_vram()
        
        # Calculate Utilization (Simplified version of LifecycleManager logic)
        base_gb, cost_10k = utils.get_model_calibration(model_name, engine="vllm")
        if base_gb:
            floor = self.cfg.get('vllm', {}).get('vram_static_floor', 1.0)
            buffer = self.cfg.get('vllm', {}).get('vram_safety_buffer', 0.15)
            # Use 4096 as default for E2E fast checks if not specified
            required_gb = base_gb + ((4096 / 10000.0) * cost_10k) + floor
            util = min(0.95, (required_gb / total_vram) + buffer)
        else:
            util = 0.5 # Conservative fallback
            
        hf_cache = os.getenv("HF_HOME")
        vlm_data = os.path.join(self.project_root, "tests", "vlm", "input_data")
        
        cmd = [
            "docker", "run", "--gpus", "all", "--rm", "--name", "vllm-server",
            "-p", f"{port}:8000", "-v", f"{hf_cache}:/root/.cache/huggingface",
            "-v", f"{vlm_data}:/data", "vllm/vllm-openai", model_name,
            "--gpu-memory-utilization", str(util), "--max-model-len", "4096",
            "--allowed-local-media-path", "/data"
        ]
        
        logger.info(f"🐳 Starting vLLM Docker: {model_name} (Util: {util:.2f})")
        utils.start_server(cmd)
        self.active_loadout["llm"] = {"id": model_id, "proc": None, "port": port}
