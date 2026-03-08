import os
import yaml
import json
from loguru import logger
from .contract import Capability, MappingPreference, NodeImplementation, IOType
from .registry import ImplementationRegistry
from .implementations import execute_openai_chat, execute_whisper_stt, execute_chatterbox_tts
from utils.config import get_project_root, safe_filename

class AutoBinder:
    """
    Intelligent Model and Edge Binder for Jarvis Pipelines.
    Matches logical nodes to physical implementations (local functions or remote models).
    """
    def __init__(self, project_root=None):
        self.project_root = project_root if project_root else get_project_root()
        self.cal_dir = os.path.join(self.project_root, "system_config", "model_calibrations")
        self.cache_path = os.path.join(self.project_root, ".cache", "pipeline_bindings.json")
        self.registry = ImplementationRegistry()

    def _get_model_physics(self, model_id, engine):
        """Loads calibration data for a model to get its 'weight' (VRAM/Params)."""
        safe_id = safe_filename(model_id)
        path = os.path.join(self.cal_dir, f"{engine}_{safe_id}.yaml")
        if os.path.exists(path):
            with open(path, "r") as f:
                return yaml.safe_load(f)
        return {}

    def _model_to_implementation(self, m: dict) -> NodeImplementation:
        """Wraps a loadout model into a standard NodeImplementation object."""
        engine = m.get('engine', 'unknown')
        caps = [Capability(c) if isinstance(c, str) else c for c in m.get('capabilities', [])]
        
        # Determine protocol-specific execute_fn
        if engine in ['ollama', 'vllm']:
            fn = execute_openai_chat
            it, ot = [IOType.TEXT_STREAM], [IOType.TEXT_STREAM, IOType.TEXT_FINAL]
        elif engine == 'native':
            if any(c in [Capability.STT, "stt"] for c in caps):
                fn = execute_whisper_stt
                it, ot = [IOType.AUDIO_FILE], [IOType.TEXT_FINAL]
            elif any(c in [Capability.TTS, "tts"] for c in caps):
                fn = execute_chatterbox_tts
                it, ot = [IOType.TEXT_FINAL], [IOType.AUDIO_FILE]
            else:
                fn = None; it = ot = []
        else:
            fn = None; it = ot = []

        return NodeImplementation(
            id=m['id'],
            input_types=it,
            output_types=ot,
            execute_fn=fn,
            config={"binding": m},
            capabilities=caps,
            physics_weight=self._get_model_physics(m['id'], engine).get('constants', {}).get('base_vram_gb', 0.0)
        )

    def get_persisted_binding(self, pipeline_id, loadout_id, node_id):
        """Checks the local cache for a manual override."""
        if not os.path.exists(self.cache_path): return None
        try:
            with open(self.cache_path, "r") as f:
                data = json.load(f)
                key = f"{pipeline_id}::{loadout_id}"
                return data.get(key, {}).get(node_id)
        except: return None

    def generate_manifest(self, pipeline_id, nodes, active_models, preference=MappingPreference.PREFER_BIG, loadout_id="unknown", overrides=None, silent=False):
        """
        Creates a binding manifest for a list of nodes.
        Hierarchy: Manual Overrides > Fixed YAML Binding > Cache Override > Heuristic Discovery.
        """
        manifest = {}
        
        # 1. Prepare candidate implementations (Static + Dynamic Models)
        all_candidates = self.registry.get_all().copy()
        for m in active_models:
            all_candidates.append(self._model_to_implementation(m))

        for node in nodes:
            nid = node['id']
            
            # 0. Strategy 0: Manual Overrides (Injection for testing)
            if overrides and nid in overrides:
                manifest[nid] = overrides[nid]
                continue

            fixed_impl_id = node.get('implementation')
            required_caps = [Capability(c) if isinstance(c, str) else c for c in node.get('capabilities', [])]
            
            # A. Strategy 1: Fixed Binding (Direct implementation ID in YAML)
            if fixed_impl_id:
                bound = next((c for c in all_candidates if c.id == fixed_impl_id), None)
                if bound:
                    manifest[nid] = bound
                    continue
                else:
                    if not silent: logger.warning(f"Fixed implementation '{fixed_impl_id}' not found for node {nid}")

            # B. Strategy 2: Persistent Cache Override
            cache_override = self.get_persisted_binding(pipeline_id, loadout_id, nid)
            if cache_override:
                bound = next((c for c in all_candidates if c.id == cache_override), None)
                if bound:
                    manifest[nid] = bound
                    continue

            # C. Strategy 3: Discovery based on Capabilities
            if required_caps:
                candidates = [
                    c for c in all_candidates 
                    if all(rc in c.capabilities for rc in required_caps)
                ]
                
                if not candidates:
                    if not silent: logger.warning(f"No implementations satisfy capabilities {required_caps} for node {nid}")
                    manifest[nid] = None
                    continue

                # Sort by physics if multiple candidates exist
                reverse = (preference == MappingPreference.PREFER_BIG)
                candidates.sort(key=lambda x: x.physics_weight, reverse=reverse)
                manifest[nid] = candidates[0]
            else:
                # No capabilities and no fixed binding? Node is likely a passthrough or utility
                manifest[nid] = None

        return manifest
