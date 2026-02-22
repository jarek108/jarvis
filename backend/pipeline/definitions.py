from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class PipelineConfig:
    name: str
    input_mode: str  # 'audio_stream', 'text_message', 'frame_stream'
    trigger: str     # 'vad', 'manual', 'continuous'
    models: List[str] # List of model IDs required
    description: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PipelineContext:
    session_id: str
    active_config: Optional[PipelineConfig] = None
    input_buffer: bytes = b""
    current_frame: Optional[bytes] = None
    state: str = "IDLE" # IDLE, LOADING, LISTENING, THINKING, SPEAKING
