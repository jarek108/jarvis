import aiohttp
import json
import logging
from typing import Any, List, Dict, Optional
from .interface import ModelInterface

logger = logging.getLogger("jarvis.models.llm")

class LLMAdapter(ModelInterface):
    def __init__(self, vllm_port: int = 8300, ollama_port: int = 11434):
        self.vllm_url = f"http://127.0.0.1:{vllm_port}/v1/chat/completions"
        self.ollama_url = f"http://127.0.0.1:{ollama_port}/api/chat"
        self._model_id: Optional[str] = None
        self._engine: str = "vllm"

    async def load(self, model_id: str, **kwargs) -> bool:
        self._model_id = model_id
        if model_id.startswith("OL_"):
            self._engine = "ollama"
            self._model_id = model_id[3:].lower() # Strip OL_
        else:
            self._engine = "vllm"
            # vLLM might need the full name or a tag, assuming it's already running the right model
        return True

    async def unload(self) -> bool:
        return True

    async def infer(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Sends chat messages to the active LLM engine."""
        if self._engine == "ollama":
            return await self._infer_ollama(messages, **kwargs)
        else:
            return await self._infer_vllm(messages, **kwargs)

    async def _infer_ollama(self, messages: List[Dict[str, str]], **kwargs) -> str:
        payload = {
            "model": self._model_id,
            "messages": messages,
            "stream": False
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.ollama_url, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("message", {}).get("content", "")
                    else:
                        return f"Error: {response.status}"
            except Exception as e:
                return f"Exception: {e}"

    async def _infer_vllm(self, messages: List[Dict[str, str]], **kwargs) -> str:
        # For vLLM, model name doesn't usually matter in the request if only one is loaded
        payload = {
            "model": "default", 
            "messages": messages,
            "stream": False,
            "max_tokens": kwargs.get("max_tokens", 512)
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.vllm_url, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result["choices"][0]["message"]["content"]
                    else:
                        return f"Error: {response.status}"
            except Exception as e:
                return f"Exception: {e}"

    @property
    def model_type(self) -> str:
        return "llm"
