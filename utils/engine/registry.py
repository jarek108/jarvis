from typing import Optional
from .contract import NodeImplementation, IOType, Capability
from .implementations import (
    execute_openai_chat, execute_whisper_stt, execute_chatterbox_tts,
    execute_speaker, execute_ptt_mic, execute_notification, execute_chunker,
    execute_memory_node
)

class ImplementationRegistry:
    """
    Central registry for all NodeImplementations.
    Contains static (hardcoded) and dynamic (loadout-based) implementations.
    """
    def __init__(self):
        self._implementations: dict[str, NodeImplementation] = {}
        self._load_static_implementations()

    def _load_static_implementations(self):
        # 1. Hardware / Edge Implementations
        self.register(NodeImplementation(
            id="PushToTalkMic",
            input_types=[],
            output_types=[IOType.AUDIO_FILE],
            execute_fn=execute_ptt_mic,
            capabilities=[Capability.AUDIO_OUT]
        ))
        
        self.register(NodeImplementation(
            id="SystemSpeaker",
            input_types=[IOType.AUDIO_FILE, IOType.AUDIO_STREAM],
            output_types=[],
            execute_fn=execute_speaker,
            capabilities=[Capability.AUDIO_IN]
        ))

        self.register(NodeImplementation(
            id="NotificationActuator",
            input_types=[IOType.TEXT_FINAL],
            output_types=[],
            execute_fn=execute_notification,
            capabilities=[Capability.TEXT_IN]
        ))

        # 2. Logical / Utility Implementations
        self.register(NodeImplementation(
            id="SentenceChunker",
            input_types=[IOType.TEXT_STREAM],
            output_types=[IOType.TEXT_STREAM],
            execute_fn=execute_chunker
        ))

        self.register(NodeImplementation(
            id="ConversationMemory",
            input_types=[IOType.TEXT_FINAL],
            output_types=[IOType.TEXT_FINAL],
            execute_fn=execute_memory_node
        ))

    def register(self, impl: NodeImplementation):
        self._implementations[impl.id] = impl

    def get(self, impl_id: str) -> Optional[NodeImplementation]:
        return self._implementations.get(impl_id)

    def find_by_capability(self, caps: list[Capability]) -> list[NodeImplementation]:
        """Finds implementations that satisfy ALL required capabilities."""
        return [
            impl for impl in self._implementations.values()
            if all(c in impl.capabilities for c in caps)
        ]

    def find_by_io(self, inputs: list[IOType], outputs: list[IOType]) -> list[NodeImplementation]:
        """Finds implementations that match requested IO signatures."""
        return [
            impl for impl in self._implementations.values()
            if all(i in impl.input_types for i in inputs) and all(o in impl.output_types for o in outputs)
        ]

    def get_all(self) -> list[NodeImplementation]:
        return list(self._implementations.values())
