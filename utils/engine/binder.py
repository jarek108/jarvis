import os
import yaml
import json
from loguru import logger
from .contract import Capability, MappingPreference
from utils.config import get_project_root, safe_filename

class AutoBinder:
    """
    Intelligent Model Binder for Jarvis Pipelines.
    Matches logical nodes to physical models based on capabilities and physics.
    """
    def __init__(self, project_root=None):
        self.project_root = project_root if project_root else get_project_root()
        self.cal_dir = os.path.join(self.project_root, "system_config", "model_calibrations")
        self.cache_path = os.path.join(self.project_root, ".cache", "pipeline_bindings.json")

    def _get_model_physics(self, model_id, engine):
        """Loads calibration data for a model to get its 'weight' (VRAM/Params)."""
        safe_id = safe_filename(model_id)
        path = os.path.join(self.cal_dir, f"{engine}_{safe_id}.yaml")
        if os.path.exists(path):
            with open(path, "r") as f:
                return yaml.safe_load(f)
        return {}

    def find_candidates(self, required_caps, active_models):
        """Returns models that satisfy all required capabilities."""
        candidates = []
        for model in active_models:
            model_caps = model.get('capabilities', [])
            # Convert strings to set for intersection
            if all(cap in model_caps for cap in required_caps):
                candidates.append(model)
        return candidates

    def sort_by_physics(self, candidates, preference=MappingPreference.PREFER_BIG):
        """Sorts candidates based on their VRAM footprint or param count."""
        def get_weight(m):
            physics = self._get_model_physics(m['id'], m['engine'])
            # Priority 1: base_vram_gb
            # Priority 2: source_tokens (proxy for model size)
            weight = physics.get('constants', {}).get('base_vram_gb', 0.0)
            if weight == 0:
                weight = physics.get('metadata', {}).get('source_tokens', 0) / 1e9 # B params proxy
            return weight

        reverse = (preference == MappingPreference.PREFER_BIG)
        return sorted(candidates, key=get_weight, reverse=reverse)

    def get_persisted_binding(self, pipeline_id, loadout_id, node_id):
        """Checks the local cache for a manual override."""
        if not os.path.exists(self.cache_path): return None
        try:
            with open(self.cache_path, "r") as f:
                data = json.load(f)
                key = f"{pipeline_id}::{loadout_id}"
                return data.get(key, {}).get(node_id)
        except: return None

    def persist_binding(self, pipeline_id, loadout_id, node_id, model_uri):
        """Saves a manual override to the local cache."""
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        data = {}
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r") as f: data = json.load(f)
            except: pass
        
        key = f"{pipeline_id}::{loadout_id}"
        if key not in data: data[key] = {}
        data[key][node_id] = model_uri
        
        with open(self.cache_path, "w") as f:
            json.dump(data, f, indent=2)

    def generate_manifest(self, pipeline_id, nodes, active_models, preference=MappingPreference.PREFER_BIG, loadout_id="unknown"):
        """
        Creates a binding manifest for a list of nodes.
        Hierarchy: YAML Override > Cache Override > Physics Heuristic.
        """
        manifest = {}
        
        for node in nodes:
            nid = node['id']
            if node.get('type') in ['input', 'source', 'sink'] or node.get('role') in ['utility', 'memory']:
                continue

            required_caps = node.get('capabilities', [])
            if not required_caps: continue

            # 1. Check YAML Override (if we decide to put it there)
            yaml_override = node.get('model_hint') # Placeholder name
            
            # 2. Check Persisted Cache
            cache_override = self.get_persisted_binding(pipeline_id, loadout_id, nid)
            
            # 3. Find candidates
            candidates = self.find_candidates(required_caps, active_models)
            
            if not candidates:
                logger.warning(f"No candidates found for node {nid} with caps {required_caps}")
                manifest[nid] = None
                continue

            # Resolution logic
            bound_model = None
            
            # Try cache match
            if cache_override:
                bound_model = next((m for m in candidates if m['id'] == cache_override), None)
            
            # Try YAML hint match
            if not bound_model and yaml_override:
                bound_model = next((m for m in candidates if m['id'] == yaml_override), None)

            # Fallback to Physics
            if not bound_model:
                sorted_candidates = self.sort_by_physics(candidates, preference)
                bound_model = sorted_candidates[0]

            manifest[nid] = bound_model

        return manifest
