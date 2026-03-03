import os
import yaml
import json
from loguru import logger
from utils.config import get_project_root, load_config
from .binder import AutoBinder
from .contract import MappingPreference

class PipelineResolver:
    def __init__(self, project_root=None, base_dir=None):
        self.project_root = project_root if project_root else get_project_root()
        self.cfg = load_config()
        
        # ISOLATION: Define explicit directories for different graph artifacts
        if base_dir:
            self.pipelines_dir = base_dir if os.path.isabs(base_dir) else os.path.join(self.project_root, base_dir)
        else:
            self.pipelines_dir = os.path.join(self.project_root, "system_config", "pipelines")

        self.strategies_dir = os.path.join(self.project_root, "system_config", "strategies")
        self.cal_dir = os.path.join(self.project_root, "system_config", "model_calibrations")
        self.registry_path = os.path.join(self.cal_dir, "runtime_registry.json")
        
        self.binder = AutoBinder(self.project_root)

    def load_yaml(self, name, folder=None):
        """Loads a YAML from the configured absolute base_dir or a specified folder."""
        clean_name = name.replace(".yaml", "")
        base = folder if folder else self.pipelines_dir
        path = os.path.join(base, f"{clean_name}.yaml")
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"YAML not found at: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

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

    def resolve(self, pipeline_name, strategy_name=None):
        """
        Binds a pipeline to live models using the AutoBinder.
        Hierarchy: YAML Override > Persistent Cache > Physics Heuristic.
        """
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
            loadout_id=loadout_id
        )
        
        bound_nodes = {}
        # 1. Populate Entry/Utility Nodes (No model binding needed)
        for node in pipeline['nodes']:
            nid = node['id']
            if node.get('type') in ['input', 'source', 'sink'] or node.get('role') in ['utility', 'memory']:
                bound_nodes[nid] = node.copy()
            else:
                # Processing Node - Apply Binding
                bound_model = manifest.get(nid)
                if not bound_model:
                    # Critical Error: No model could satisfy requirements
                    logger.error(f"❌ ARCH_MISMATCH: No model found for {nid}")
                    bn = node.copy()
                    bn['binding'] = None
                    bound_nodes[nid] = bn
                else:
                    bn = node.copy()
                    bn['binding'] = bound_model
                    bound_nodes[nid] = bn

        logger.info(f"✅ Resolved '{pipeline_name}' via AutoBinder [Pref: {pref_str}]")
        return bound_nodes

    def check_runnability(self, pipeline_name, strategy_name=None, external_health=None):
        """
        Proactively verifies if a pipeline is runnable based on live system health.
        Returns: {runnable: bool, errors: list, map: dict}
        """
        report = {"runnable": True, "errors": [], "map": {}}
        
        # 1. Load the raw pipeline first to populate the map even if resolution fails
        try:
            raw_pipeline = self.load_yaml(pipeline_name)
            for node in raw_pipeline['nodes']:
                report["map"][node['id']] = {"status": "UNRESOLVED", "model": "None"}
        except Exception as e:
            return {"runnable": False, "errors": [f"Pipeline Load Error: {e}"], "map": {}}

        # 2. Try to Resolve the graph (Detects ARCH_MISMATCH or strategy errors)
        try:
            bound_graph = self.resolve(pipeline_name, strategy_name)
        except Exception as e:
            report["runnable"] = False
            report["errors"].append(f"Resolution Error: {e}")
            return report

        # 3. Check Live Health for all bound ports
        if external_health:
            health = external_health
        else:
            from utils.infra import get_system_health
            health = get_system_health()
        
        for nid, node in bound_graph.items():
            role = node.get('role', '').lower()
            if node['type'] == 'processing' and role not in ['utility', 'memory']:
                binding = node.get('binding')
                if not binding:
                    report["runnable"] = False
                    report["errors"].append(f"Node '{nid}' is unbound.")
                    continue
                
                port = binding.get('port')
                svc_info = health.get(port, {"status": "OFF", "info": None})
                
                report["map"][nid] = {
                    "status": svc_info['status'],
                    "model": binding['id'],
                    "port": port
                }
                
                if svc_info['status'] != "ON":
                    report["runnable"] = False
                    report["errors"].append(f"Service for '{nid}' ({binding['id']} on port {port}) is {svc_info['status']}.")
            
            else:
                # Utility, Memory, or Sink nodes
                report["map"][nid] = {"status": "LOCAL", "role": role or node['type']}

        return report
