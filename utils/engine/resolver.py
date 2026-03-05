import os
import yaml
import json
from loguru import logger
from utils.config import get_project_root, load_config
from .binder import AutoBinder
from .contract import MappingPreference, NodeImplementation

class PipelineResolver:
    def __init__(self, project_root=None, search_paths=None):
        self.project_root = project_root if project_root else get_project_root()
        self.cfg = load_config()
        
        # ISOLATION: Define explicit directories for different graph artifacts
        if search_paths:
            self.search_paths = [os.path.join(self.project_root, p) if not os.path.isabs(p) else p for p in search_paths]
        else:
            self.search_paths = [os.path.join(self.project_root, "system_config", "pipelines")]

        self.strategies_dir = os.path.join(self.project_root, "system_config", "strategies")
        self.cal_dir = os.path.join(self.project_root, "system_config", "model_calibrations")
        self.registry_path = os.path.join(self.cal_dir, "runtime_registry.json")
        
        self.binder = AutoBinder(self.project_root)

    def load_yaml(self, name):
        """Searches for a YAML across the configured search paths."""
        clean_name = name.replace(".yaml", "")
        
        for base in self.search_paths:
            path = os.path.join(base, f"{clean_name}.yaml")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
        
        raise FileNotFoundError(f"YAML '{clean_name}.yaml' not found in search paths: {self.search_paths}")

    def get_live_models(self):
        if not os.path.exists(self.registry_path):
            return {"models": [], "external": 0.0, "loadout_id": "NONE"}
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content: return {"models": [], "external": 0.0, "loadout_id": "NONE"}
                data = json.loads(content)
                models = data.get("active_loadout", [])
                external = data.get("system_external_vram", 0.0)
                loadout_id = data.get("loadout_id", "unknown")
                for m in models:
                    try:
                        m['capabilities'] = self.get_model_capabilities(m['id'], m['engine'])
                    except Exception as e:
                        logger.error(f"Error getting caps for {m['id']}: {e}")
                        m['capabilities'] = []
                return {"models": models, "external": external, "loadout_id": loadout_id}
        except Exception as e:
            logger.error(f"Error reading registry: {e}")
            return {"models": [], "external": 0.0, "loadout_id": "NONE"}

    def get_model_capabilities(self, model_id, engine):
        """Looks up capabilities in the calibration registry."""
        from utils.config import safe_filename
        
        caps = []
        safe_id = safe_filename(model_id)
        
        # 1. Direct match using standard naming convention
        cal_path = os.path.join(self.cal_dir, f"{engine}_{safe_id}.yaml")
            
        if os.path.exists(cal_path):
            with open(cal_path, "r") as f:
                caps = yaml.safe_load(f).get("capabilities", [])

        # 2. Engine-based defaults (ENSURE IN/OUT are present)
        if engine == "ollama" or engine == "vllm":
            if not caps: caps = ["text_in", "text_out"]
            if "vl" in model_id.lower() and "image_in" not in caps:
                caps.append("image_in")
        
        return caps

    def resolve(self, pipeline_name, strategy_name=None, overrides=None):
        """
        Binds a pipeline to live models using the AutoBinder.
        Hierarchy: Manual Overrides > YAML Override > Persistent Cache > Physics Heuristic.
        """
        if os.environ.get('JARVIS_MOCK_ALL') == "1":
            if overrides is None: overrides = {}
            raw_p = self.load_yaml(pipeline_name)
            from .implementations.mocks import get_mock_implementation
            for node in raw_p['nodes']:
                nid = node['id']
                if nid not in overrides:
                    overrides[nid] = get_mock_implementation(f"mock_{nid}", node.get('role', 'unknown'))

        pipeline = self.load_yaml(pipeline_name)
        live_data = self.get_live_models()
        live_models = live_data.get("models", [])
        loadout_id = live_data.get("loadout_id", "unknown")
        
        # Determine Preference
        pref_str = self.cfg.get('mapping_preference', 'prefer_big')
        preference = MappingPreference.PREFER_BIG if pref_str == 'prefer_big' else MappingPreference.PREFER_SMALL
        
        # Generate Binding Manifest via AutoBinder
        manifest = self.binder.generate_manifest(
            pipeline_id=pipeline_name,
            nodes=pipeline['nodes'],
            active_models=live_models,
            preference=preference,
            loadout_id=loadout_id,
            overrides=overrides
        )
        
        bound_nodes = {}
        for node in pipeline['nodes']:
            nid = node['id']
            # EVERY node now looks into the manifest for its implementation
            bound_impl = manifest.get(nid)
            
            bn = node.copy()
            bn['binding'] = bound_impl
            bound_nodes[nid] = bn

            if not bound_impl:
                # Only log error for processing nodes that REQUIRE a model/logic
                if node.get('type') == 'processing' and node.get('role') not in ['utility', 'memory']:
                    logger.error(f"❌ ARCH_MISMATCH: No model found for {nid}")

        logger.info(f"✅ Resolved '{pipeline_name}' via AutoBinder [Pref: {pref_str}]")
        return bound_nodes

    def check_runnability(self, pipeline_name, strategy_name=None, external_health=None):
        """
        Proactively verifies if a pipeline is runnable based on live system health.
        Returns: {runnable: bool, errors: list, map: dict}
        """
        report = {"runnable": True, "errors": [], "map": {}}
        
        try:
            raw_pipeline = self.load_yaml(pipeline_name)
            for node in raw_pipeline['nodes']:
                report["map"][node['id']] = {"status": "UNRESOLVED", "model": "None"}
        except Exception as e:
            return {"runnable": False, "errors": [f"Pipeline Load Error: {e}"], "map": {}}

        try:
            bound_graph = self.resolve(pipeline_name, strategy_name)
        except Exception as e:
            report["runnable"] = False
            report["errors"].append(f"Resolution Error: {e}")
            return report

        if external_health:
            health = external_health
        else:
            from utils.infra import get_system_health
            health = get_system_health()
        
        for nid, node in bound_graph.items():
            binding = node.get('binding')
            if not binding:
                if node['type'] == 'processing':
                    report["runnable"] = False
                    report["errors"].append(f"Node '{nid}' is unbound.")
                report["map"][nid] = {"status": "UNBOUND", "model": "None"}
                continue
            
            # If implementation has a port (Model), check health
            # implementation.config['binding'] stores the model data
            m_data = binding.config.get('binding', {})
            port = m_data.get('port')
            
            if port:
                svc_info = health.get(port, {"status": "OFF", "info": None})
                report["map"][nid] = {
                    "status": svc_info['status'],
                    "model": binding.id,
                    "port": port
                }
                if svc_info['status'] != "ON":
                    report["runnable"] = False
                    report["errors"].append(f"Service for '{nid}' ({binding.id} on port {port}) is {svc_info['status']}.")
            else:
                report["map"][nid] = {"status": "LOCAL", "model": binding.id}

        return report
