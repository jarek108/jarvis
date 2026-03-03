from enum import Enum

class Capability(Enum):
    """Formalized model capabilities for autonomous binding."""
    TEXT_IN = "text_in"
    TEXT_OUT = "text_out"
    IMAGE_IN = "image_in"
    IMAGE_OUT = "image_out"
    VIDEO_IN = "video_in"
    VIDEO_OUT = "video_out"
    AUDIO_IN = "audio_in"
    AUDIO_OUT = "audio_out"
    
    # High-level task capabilities (derived or explicit)
    LLM = "llm"
    VLM = "vlm"
    STT = "stt"
    TTS = "tts"
    VISION_ENCODER = "vision_encoder"

class MappingPreference(Enum):
    """User preference for automatic model selection."""
    PREFER_BIG = "prefer_big"
    PREFER_SMALL = "prefer_small"
