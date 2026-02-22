from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class OperationMode:
    name: str
    input_modalities: List[str] # text, image, audio
    trigger: str                # manual, vad, continuous
    output_format: str          # text, audio, event
    requirements: List[str]     # stt, tts, llm, vlm
    history_limit: int = 5
    system_prompt: str = ""
    description: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PipelineConfig:
    name: str
    mode: OperationMode
    models: List[str] # Specific model loadout fulfilling mode requirements
    description: str = ""

@dataclass
class PipelineContext:
    session_id: str
    active_config: Optional[PipelineConfig] = None
    input_buffer: bytes = b""
    current_frame: Optional[bytes] = None
    state: str = "IDLE" # IDLE, LOADING, LISTENING, THINKING, SPEAKING
