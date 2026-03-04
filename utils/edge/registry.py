from loguru import logger
from utils.engine.contract import Capability

class EdgeImplementation:
    """Base class for all physical edge (hardware/script) interactions."""
    def get_capabilities(self):
        """Returns a list of Capability enums provided by this edge device."""
        return []

    def get_id(self):
        return self.__class__.__name__

    async def capture(self, node_id, scenario_inputs, session_dir):
        """Called by SourceAdapter. Returns data to be injected into the pipeline."""
        return None

    async def deliver(self, node_id, content, scenario_inputs, session_dir):
        """Called by SinkAdapter. Executes the physical action."""
        pass

class EdgeRegistry:
    """Registry of all available Edge Implementations."""
    def __init__(self):
        self._implementations = {}
        self._load_defaults()

    def _load_defaults(self):
        # Lazy load to avoid immediate hardware binding
        from .sensors import PushToTalkMic, WavFileReader, ScreenSensor
        from .actuators import SystemSpeaker, NotificationActuator, KeyboardActuator
        
        self.register(PushToTalkMic())
        self.register(WavFileReader())
        self.register(ScreenSensor())
        
        self.register(SystemSpeaker())
        self.register(NotificationActuator())
        self.register(KeyboardActuator())

    def register(self, impl: EdgeImplementation):
        self._implementations[impl.get_id()] = impl

    def get_all(self):
        return list(self._implementations.values())

    def get_by_id(self, impl_id):
        return self._implementations.get(impl_id)
