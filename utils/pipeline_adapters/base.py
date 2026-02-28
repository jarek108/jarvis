import time
import abc

class NodeAdapter(abc.ABC):
    """
    Standard interface for all Jarvis Pipeline Nodes.
    Adapters are modality-specific but follow a uniform execution pattern.
    """
    def __init__(self, project_root):
        self.project_root = project_root

    @abc.abstractmethod
    async def run(self, node_id, node_config, input_streams, output_queue, session):
        """
        Executes the node logic.
        :param node_id: Unique ID of the node
        :param node_config: Resolved YAML config (including bindings)
        :param input_streams: Dictionary of {node_id: async_generator}
        :param output_queue: Async queue to push results to
        :param session: Active aiohttp session for API calls
        """
        pass

    def create_packet(self, p_type, content, seq=0):
        """Helper to create a standard packet."""
        return {
            "type": p_type,
            "content": content,
            "seq": seq,
            "ts": time.perf_counter()
        }
