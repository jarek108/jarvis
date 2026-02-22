import asyncio
import logging
import time
import io
import wave
from typing import Optional, Dict, Any, List
from .definitions import PipelineConfig, PipelineContext
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
        self.pipelines: Dict[str, PipelineConfig] = {}
        self.output_queue: Optional[asyncio.Queue] = None
        
        if stubs:
            from backend.models.stub_adapter import StubAdapter
            self.stt = StubAdapter("stt")
            self.tts = StubAdapter("tts")
            self.llm = StubAdapter("llm")
            logger.info("🧪 Pipeline initialized with STUB adapters.")
        else:
            # Initialize Real Adapters
            self.stt = STTAdapter(port=8101) 
            self.tts = TTSAdapter(port=8201) 
            self.llm = LLMAdapter()

    def register_pipeline(self, config: PipelineConfig):
        self.pipelines[config.name] = config
        logger.info(f"📜 Registered pipeline: {config.name}")

    async def initialize_session(self, session_id: str, output_queue: asyncio.Queue):
        self.active_session = self.session_manager.get_session(session_id)
        self.context = PipelineContext(session_id=session_id)
        self.output_queue = output_queue
        logger.info(f"🧠 Initialized PipelineManager for session: {session_id}")

    async def switch_mode(self, mode_name: str):
        if mode_name not in self.pipelines:
            logger.error(f"❌ Unknown pipeline mode: {mode_name}")
            return False
        
        config = self.pipelines[mode_name]
        logger.info(f"🔄 Switching to mode: {mode_name}...")
        
        self.context.state = "LOADING"
        await self.emit_event("status", {"state": "LOADING", "mode": mode_name})
        
        # 1. Ensure Loadout
        await self.resource_manager.ensure_loadout(config.models)
        
        # 2. Update Context
        self.context.active_config = config
        self.active_session.active_mode = mode_name
        
        self.context.state = "IDLE"
        await self.emit_event("status", {"state": "READY", "mode": mode_name})
        return True

    async def handle_input(self, msg_type: str, data: Any):
        if not self.context or not self.context.active_config:
            return

        if msg_type == "binary":
            await self._process_binary_input(data)
        elif msg_type == "text":
            await self._process_text_input(data)

    async def _process_binary_input(self, data: bytes):
        mode = self.context.active_config.input_mode
        if mode == "audio_stream":
            # Very basic VAD: if we receive audio and we are IDLE, start accumulating
            # In V1, we'll assume the client handles VAD or sends explicit "start/stop"
            # For now, let's treat every binary chunk as potential audio to transcribe
            self.context.input_buffer += data
            
            # Simple threshold for transcription (e.g. 1 second of audio at 16kHz)
            if len(self.context.input_buffer) > 32000: 
                await self.execute_sts_pipeline()

    async def _process_text_input(self, data: Any):
        if not isinstance(data, dict): return
        cmd = data.get("type")
        if cmd == "message":
            text = data.get("content")
            await self.run_text_pipeline(text)

    async def execute_sts_pipeline(self):
        """Full Speech-to-Speech Flow."""
        if self.context.state != "IDLE": return
        
        self.context.state = "THINKING"
        await self.emit_event("status", {"state": "THINKING"})
        
        audio_data = self.context.input_buffer
        self.context.input_buffer = b"" # Clear buffer
        
        # 1. STT
        logger.info("⚙️ Step 1: STT")
        text = await self.stt.infer(audio_data)
        if not text:
            self.context.state = "IDLE"
            await self.emit_event("status", {"state": "READY"})
            return

        await self.emit_event("log", {"role": "user", "content": text})
        self.active_session.add_turn("user", text)

        # 2. LLM
        logger.info("⚙️ Step 2: LLM")
        messages = [{"role": "user", "content": text}]
        # Include history if needed
        response_text = await self.llm.infer(messages)
        
        await self.emit_event("log", {"role": "assistant", "content": response_text})
        self.active_session.add_turn("assistant", response_text)

        # 3. TTS
        logger.info("⚙️ Step 3: TTS")
        audio_out = await self.tts.infer(response_text)
        if audio_out:
            await self.push_binary(audio_out)

        self.context.state = "IDLE"
        await self.emit_event("status", {"state": "READY"})

    async def run_text_pipeline(self, text: str):
        """Text-to-Speech/Text Flow."""
        self.context.state = "THINKING"
        await self.emit_event("status", {"state": "THINKING"})
        
        await self.emit_event("log", {"role": "user", "content": text})
        self.active_session.add_turn("user", text)

        response_text = await self.llm.infer([{"role": "user", "content": text}])
        
        await self.emit_event("log", {"role": "assistant", "content": response_text})
        self.active_session.add_turn("assistant", response_text)

        # Optional TTS for text input
        if "tts" in [m.lower() for m in self.context.active_config.models]:
            audio_out = await self.tts.infer(response_text)
            if audio_out:
                await self.push_binary(audio_out)

        self.context.state = "IDLE"
        await self.emit_event("status", {"state": "READY"})

    async def emit_event(self, event_type: str, payload: Dict[str, Any]):
        if self.output_queue:
            payload["type"] = event_type
            await self.output_queue.put(("text", payload))

    async def push_binary(self, data: bytes):
        if self.output_queue:
            await self.output_queue.put(("binary", data))
