import time
import abc

class NodeAdapter(abc.ABC):
    """
    Standard interface for all Jarvis Pipeline Nodes.
    Adapters are modality-specific but follow a uniform execution pattern.
    """
    def __init__(self, project_root, session_dir=None):
        self.project_root = project_root
        self.session_dir = session_dir

    def resolve_path(self, path, default_filename=None):
        """Resolves a path relative to session_dir if available, otherwise project_root."""
        if not path and not default_filename: return None
        p = path if path else default_filename
        
        # If absolute, return as is
        if os.path.isabs(p): return p
        
        # If session_dir is provided, use it as base
        base = self.session_dir if self.session_dir else self.project_root
        return os.path.normpath(os.path.join(base, p))

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
