from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

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

class IOType(Enum):
    """Strict data types for node input/output validation."""
    TEXT_STREAM = "text_stream"
    TEXT_FINAL = "text_final"
    AUDIO_FILE = "audio_file"
    AUDIO_STREAM = "audio_stream"
    IMAGE_FILE = "image_file"
    IMAGE_RAW = "image_raw"
    VIDEO_FILE = "video_file"
    SIGNAL = "signal"  # For PTT events, etc.
    DATA_PATH = "data_path" # Generic fallback

@dataclass
class NodeImplementation:
    """
    Standardized execution unit for all Jarvis nodes.
    Unifies models, hardware, and logical operations.
    """
    id: str
    input_types: list[IOType]
    output_types: list[IOType]
    
    # The actual execution logic (standalone function)
    execute_fn: Callable
    
    # Static configuration (ports, model IDs, delimiters, etc.)
    config: dict[str, Any] = field(default_factory=dict)
    
    # Metadata for the AutoBinder
    capabilities: list[Capability] = field(default_factory=list)
    physics_weight: float = 0.0 # VRAM or Param count proxy
