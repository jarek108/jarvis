import aiohttp
import logging
from typing import Any, Optional
from .interface import ModelInterface

logger = logging.getLogger("jarvis.models.stt")

class STTAdapter(ModelInterface):
    def __init__(self, port: int):
        self.port = port
        self.url = f"http://127.0.0.1:{port}/transcribe"
        self._model_id: Optional[str] = None

    async def load(self, model_id: str, **kwargs) -> bool:
        self._model_id = model_id
        # In V1, we assume ResourceManager handled the process spawning
        return True

    async def unload(self) -> bool:
        self._model_id = None
        return True

    async def infer(self, audio_data: bytes, **kwargs) -> str:
        """Sends audio bytes to the STT server."""
        async with aiohttp.ClientSession() as session:
            # Use form-data for the file upload
            data = aiohttp.FormData()
            data.add_field('file', audio_data, filename='input.wav', content_type='audio/wav')
            
            if 'language' in kwargs:
                data.add_field('language', kwargs['language'])

            try:
                async with session.post(self.url, data=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("text", "").strip()
                    else:
                        logger.error(f"❌ STT Error: {response.status}")
                        return ""
            except Exception as e:
                logger.error(f"❌ STT Exception: {e}")
                return ""

    @property
    def model_type(self) -> str:
        return "stt"
