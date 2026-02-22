import asyncio
import logging
import os
import sys
import time
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
        health_url = ""

        if m_type == "stt":
            port = self.cfg['stt_loadout'].get(m_id, 8101)
            script = os.path.join(self.project_root, "servers", "stt_server.py")
            cmd = [self.python_exe, script, "--port", str(port), "--model", m_id]
            health_url = f"http://127.0.0.1:{port}/health"
        
        elif m_type == "tts":
            port = self.cfg['tts_loadout'].get(m_id, 8201)
            script = os.path.join(self.project_root, "servers", "tts_server.py")
            cmd = [self.python_exe, script, "--port", str(port), "--variant", m_id]
            health_url = f"http://127.0.0.1:{port}/health"
            
        elif m_type == "llm":
            if m_id.startswith("OL_"):
                # Ollama is handled as a singleton service
                port = self.cfg['ports']['ollama']
                cmd = ["ollama", "serve"]
                health_url = f"http://127.0.0.1:{port}/api/tags"
            else:
                # vLLM Docker spawning logic would go here
                # For V1, we assume Docker is already managed or use basic spawn
                logger.warning("⚠️ vLLM spawning not fully implemented in modular resource manager yet.")
                return

        if cmd:
            proc = utils.start_server(cmd)
            # Wait for port
            success = await asyncio.to_thread(utils.wait_for_port, port, timeout=60)
            if success:
                self.active_loadout[m_type] = {"id": m_id, "proc": proc, "port": port}
                logger.info(f"✅ {m_type} is ready on port {port}")
            else:
                logger.error(f"❌ Failed to start {m_type} on port {port}")
