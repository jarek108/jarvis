from .stt import STTAdapter
from .llm import LLMAdapter
from .tts import TTSAdapter
from .utility import UtilityAdapter

def get_adapter(role, project_root):
    """Factory to return the correct adapter based on node role."""
    adapters = {
        "stt": STTAdapter,
        "llm": LLMAdapter,
        "tts": TTSAdapter,
        "utility": UtilityAdapter
    }
    
    adapter_class = adapters.get(role.lower())
    if not adapter_class:
        # Default to LLM if engine is recognized but role is generic
        if role.lower() in ["ollama", "vllm"]:
            adapter_class = LLMAdapter
        else:
            raise ValueError(f"No adapter found for role: {role}")
            
    return adapter_class(project_root)
