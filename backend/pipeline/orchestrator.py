import asyncio
import logging
import time
from typing import Optional, Dict, Any, List
from .definitions import PipelineConfig, PipelineContext, OperationMode
from backend.session.manager import SessionManager, Session
from backend.models.resource import ResourceManager
from backend.models.stt_adapter import STTAdapter
from backend.models.tts_adapter import TTSAdapter
from backend.models.llm_adapter import LLMAdapter

logger = logging.getLogger("jarvis.pipeline")

class PipelineManager:
    def __init__(self, session_manager: SessionManager, resource_manager: ResourceManager, stubs: bool = False):
        self.session_manager = session_manager
        self.resource_manager = resource_manager
        self.context: Optional[PipelineContext] = None
        self.active_session: Optional[Session] = None
        self.operation_modes: Dict[str, OperationMode] = {}
        self.active_pipelines: Dict[str, PipelineConfig] = {}
        self.output_queue: Optional[asyncio.Queue] = None
        self.stubs = stubs
        
        # Initialize Adapters (Lazy load or stub)
        if stubs:
            from backend.models.stub_adapter import StubAdapter
            self.stt = StubAdapter("stt")
            self.tts = StubAdapter("tts")
            self.llm = StubAdapter("llm")
        else:
            self.stt = STTAdapter(port=8101) 
            self.tts = TTSAdapter(port=8201) 
            self.llm = LLMAdapter()

    def register_operation_mode(self, mode: OperationMode):
        self.operation_modes[mode.name] = mode
        logger.info(f"🛠️ Registered Operation Mode: {mode.name}")

    async def initialize_session(self, session_id: str, output_queue: asyncio.Queue):
        self.active_session = self.session_manager.get_session(session_id)
        self.context = PipelineContext(session_id=session_id)
        self.output_queue = output_queue
        logger.info(f"🧠 Initialized PipelineManager for session: {session_id}")

    async def switch_mode(self, mode_name: str, loadout: List[str]):
        """Configures the backend to run a specific OperationMode using a specific Loadout."""
        if mode_name not in self.operation_modes:
            logger.error(f"❌ Unknown operation mode: {mode_name}")
            return False
        
        mode = self.operation_modes[mode_name]
        
        # 1. Validation: Does loadout satisfy mode requirements?
        # (Simplified: check if required types are in model strings)
        loadout_types = self.resource_manager._identify_model_types(loadout)
        for req in mode.requirements:
            if req not in loadout_types and not self.stubs:
                logger.error(f"❌ Loadout does not satisfy requirement: {req}")
                return False

        logger.info(f"🔄 Activating Mode '{mode_name}' with Loadout {loadout}...")
        self.context.state = "LOADING"
        await self.emit_event("status", {"state": "LOADING", "mode": mode_name})
        
        # 2. Resource management
        await self.resource_manager.ensure_loadout(loadout)
        
        # 3. Build Pipeline Config
        self.context.active_config = PipelineConfig(name=mode_name, mode=mode, models=loadout)
        self.active_session.active_mode = mode_name
        
        self.context.state = "IDLE"
        await self.emit_event("status", {"state": "READY", "mode": mode_name})
        return True

    async def handle_input(self, msg_type: str, data: Any):
        if not self.context or not self.context.active_config:
            return

        mode = self.context.active_config.mode
        
        if msg_type == "binary":
            if "audio" in mode.input_modalities:
                self.context.input_buffer += data
                # Simple VAD trigger for prototype
                if len(self.context.input_buffer) > 32000: 
                    await self.process_turn(input_type="audio", payload=self.context.input_buffer)
                    self.context.input_buffer = b""
        
        elif msg_type == "text":
            if not isinstance(data, dict): return
            if data.get("type") == "message" and "text" in mode.input_modalities:
                await self.process_turn(input_type="text", payload=data.get("content"))

    async def process_turn(self, input_type: str, payload: Any):
        """Universal execution logic driven by OperationMode settings."""
        if self.context.state != "IDLE": return
        self.context.state = "THINKING"
        await self.emit_event("status", {"state": "THINKING"})
        
        mode = self.context.active_config.mode
        user_text = ""

        # 1. Input Processing
        if input_type == "audio":
            user_text = await self.stt.infer(payload)
            if not user_text: 
                self.context.state = "IDLE"
                await self.emit_event("status", {"state": "READY"})
                return
        else:
            user_text = payload

        await self.emit_event("log", {"role": "user", "content": user_text})
        
        # 2. History & Prompting
        messages = [{"role": "system", "content": mode.system_prompt}]
        
        if mode.history_limit > 0:
            hist = self.active_session.history[-mode.history_limit:]
            for turn in hist:
                messages.append({"role": turn["role"], "content": turn["content"]})
        
        messages.append({"role": "user", "content": user_text})

        # 3. LLM Inference
        response_text = await self.llm.infer(messages)
        await self.emit_event("log", {"role": "assistant", "content": response_text})
        
        # Record Turn
        self.active_session.add_turn("user", user_text)
        self.active_session.add_turn("assistant", response_text)

        # 4. Output Routing
        if mode.output_format == "audio":
            audio_out = await self.tts.infer(response_text)
            if audio_out:
                await self.push_binary(audio_out)
        
        # 5. Cleanup / State Reset
        self.context.state = "IDLE"
        await self.emit_event("status", {"state": "READY"})

    async def emit_event(self, event_type: str, payload: Dict[str, Any]):
        if self.output_queue:
            payload["type"] = event_type
            await self.output_queue.put(("text", payload))

    async def push_binary(self, data: bytes):
        if self.output_queue:
            await self.output_queue.put(("binary", data))
