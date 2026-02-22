import aiohttp
import logging
from typing import Any, Optional
from .interface import ModelInterface

logger = logging.getLogger("jarvis.models.tts")

class TTSAdapter(ModelInterface):
    def __init__(self, port: int):
        self.port = port
        self.url = f"http://127.0.0.1:{port}/tts"
        self._model_id: Optional[str] = None

    async def load(self, model_id: str, **kwargs) -> bool:
        self._model_id = model_id
        return True

    async def unload(self) -> bool:
        self._model_id = None
        return True

    async def infer(self, text: str, **kwargs) -> bytes:
        """Sends text to TTS server and returns audio bytes."""
        payload = {
            "text": text,
            "language_id": kwargs.get("language", "en"),
            "voice": kwargs.get("voice", "default")
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.url, json=payload) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"❌ TTS Error: {response.status}")
                        return b""
            except Exception as e:
                logger.error(f"❌ TTS Exception: {e}")
                return b""

    @property
    def model_type(self) -> str:
        return "tts"
