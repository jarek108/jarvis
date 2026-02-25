import os
import yaml
import json
from loguru import logger

class PipelineResolver:
    def __init__(self, project_root):
        self.project_root = project_root
        self.cal_dir = os.path.join(project_root, "model_calibrations")
        self.registry_path = os.path.join(self.cal_dir, "runtime_registry.json")

    def load_yaml(self, folder, name):
        path = os.path.join(self.project_root, folder, f"{name}.yaml")
        if not os.path.exists(path):
            raise FileNotFoundError(f"YAML not found: {path}")
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def get_live_models(self):
        if not os.path.exists(self.registry_path):
            return []
        with open(self.registry_path, "r") as f:
            data = json.load(f)
            return data.get("active_loadout", [])

    def get_model_capabilities(self, model_id, engine):
        """Looks up capabilities in the calibration registry."""
        prefix = ""
        if engine == "vllm": prefix = "vl_"
        elif engine == "ollama": prefix = "ol_"
        elif engine == "native":
            if "whisper" in model_id.lower(): prefix = "stt_"
            elif "chatterbox" in model_id.lower(): prefix = "tts_"
        
        # Sanitize ID
        clean_id = model_id.lower().replace(" ", "-").replace("/", "--").replace(":", "-").split('#')[0]
        cal_path = os.path.join(self.cal_dir, f"{prefix}{clean_id}.yaml")
        
        if os.path.exists(cal_path):
            with open(cal_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("capabilities", [])
        return []

    def resolve(self, pipeline_name, mapping_name=None):
        """
        Binds a pipeline to live models. If mapping_name is None, attempts auto-mapping.
        """
        pipeline = self.load_yaml("pipelines", pipeline_name)
        mapping = self.load_yaml("mappings", mapping_name) if mapping_name else None
        live_models = self.get_live_models()
        
        bound_nodes = {}
        for nid in [n['id'] for n in pipeline['nodes'] if n['type'] == 'input']:
            bound_nodes[nid] = next(n for n in pipeline['nodes'] if n['id'] == nid)

        for node in [n for n in pipeline['nodes'] if n['type'] == 'processing']:
            node_id = node['id']
            required_caps = node.get('capabilities', [])
            bound_model = None

            if mapping:
                # STRATEGY BINDING
                candidates = mapping['bindings'].get(node_id, {}).get('candidates', [])
                for cid in candidates:
                    match = next((m for m in live_models if m['id'] == cid), None)
                    if match and all(c in self.get_model_capabilities(match['id'], match['engine']) for c in required_caps):
                        bound_model = match; break
            else:
                # AUTO-MAPPING (Frictionless)
                matches = []
                for m in live_models:
                    actual_caps = self.get_model_capabilities(m['id'], m['engine'])
                    if all(c in actual_caps for c in required_caps):
                        matches.append(m)
                
                if len(matches) == 1:
                    bound_model = matches[0]
                elif len(matches) > 1:
                    raise ValueError(f"Ambiguity for node '{node_id}': Multiple live models { [m['id'] for m in matches] } satisfy capabilities {required_caps}. Please provide a mapping strategy.")
                else:
                    raise ValueError(f"Could not fulfill node '{node_id}': No live model satisfies capabilities {required_caps}.")

            if not bound_model:
                raise ValueError(f"Resolution failed for node '{node_id}'.")
            
            bn = node.copy()
            bn['binding'] = bound_model
            bound_nodes[node_id] = bn

        logger.info(f"✅ Resolved '{pipeline_name}' ({'AUTO' if not mapping else mapping_name})")
        return bound_nodes
