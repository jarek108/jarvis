from .stt import STTAdapter
from .llm import LLMAdapter
from .tts import TTSAdapter
from .utility import UtilityAdapter
from .memory import MemoryAdapter
from .sink import SinkAdapter

def get_adapter(role, project_root, session_dir=None):
    """Factory to return the correct adapter based on node role."""
    adapters = {
        "stt": STTAdapter,
        "llm": LLMAdapter,
        "tts": TTSAdapter,
        "utility": UtilityAdapter,
        "memory": MemoryAdapter,
        "sink": SinkAdapter
    }
    
    adapter_class = adapters.get(role.lower())
    if not adapter_class:
        # 1. Hardware/Edge Roles -> SinkAdapter
        sink_roles = ["audio_playback", "keyboard_typer", "system_notification", "chat_box"]
        if role.lower() in sink_roles:
            adapter_class = SinkAdapter
        # 2. Default to LLM if engine is recognized but role is generic
        elif role.lower() in ["ollama", "vllm"]:
            adapter_class = LLMAdapter
        else:
            raise ValueError(f"No adapter found for role: {role}")
            
    return adapter_class(project_root, session_dir=session_dir)
