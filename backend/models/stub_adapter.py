import asyncio
import logging
from typing import Any, Optional, List, Dict
from .interface import ModelInterface

logger = logging.getLogger("jarvis.models.stub")

class StubAdapter(ModelInterface):
    """Fake model adapter for E2E logic verification."""
    def __init__(self, m_type: str):
        self._type = m_type
        self._model_id: Optional[str] = None

    async def load(self, model_id: str, **kwargs) -> bool:
        self._model_id = model_id
        logger.info(f"STUB: Loaded {self._type} model {model_id}")
        return True

    async def unload(self) -> bool:
        logger.info(f"STUB: Unloaded {self._type}")
        return True

    async def infer(self, data: Any, **kwargs) -> Any:
        if self._type == "stt":
            # Return fixed transcription
            return "This is a stub transcription."
        elif self._type == "tts":
            # Return 100 bytes of silence
            return b"\x00" * 100
        elif self._type == "llm":
            # Echo input or fixed response
            return "This is a stub LLM response."
        return None

    @property
    def model_type(self) -> str:
        return self._type
