from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class ModelInterface(ABC):
    """Universal interface for all cognitive models (STT, TTS, LLM, VLM)."""
    
    @abstractmethod
    async def load(self, model_id: str, **kwargs) -> bool:
        """Loads the model into VRAM/Memory."""
        pass

    @abstractmethod
    async def unload(self) -> bool:
        """Frees resources."""
        pass

    @abstractmethod
    async def infer(self, data: Any, **kwargs) -> Any:
        """Performs primary inference task."""
        pass

    @property
    @abstractmethod
    def model_type(self) -> str:
        """Returns 'stt', 'tts', 'llm', or 'vlm'."""
        pass
