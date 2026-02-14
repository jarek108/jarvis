import os
import yaml

def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_path = os.path.join(base_dir, "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def resolve_path(path_str):
    """Expands ~ and resolves relative paths against project root."""
    if not path_str: return None
    expanded = os.path.expanduser(path_str)
    if os.path.isabs(expanded):
        return expanded
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.normpath(os.path.join(project_root, expanded))

def list_all_loadouts(include_experimental=False):
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    loadout_dir = os.path.join(project_root, "loadouts")
    if not os.path.exists(loadout_dir): return []
    return [f.replace(".yaml", "") for f in os.listdir(loadout_dir) if f.endswith(".yaml")]

def list_all_llm_models():
    loadouts = list_all_loadouts(include_experimental=True)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    models = set()
    for lid in loadouts:
        path = os.path.join(project_root, "loadouts", f"{lid}.yaml")
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
                if data.get('llm'): models.add(data['llm'])
        except: pass
    return sorted(list(models))

def list_all_stt_models():
    cfg = load_config()
    return sorted(list(cfg.get('stt_loadout', {}).keys()))

def list_all_tts_models():
    cfg = load_config()
    return sorted(list(cfg.get('tts_loadout', {}).keys()))
