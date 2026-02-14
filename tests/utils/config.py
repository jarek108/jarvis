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
        return os.path.normpath(expanded)
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.normpath(os.path.join(project_root, expanded))

import sys

def get_hf_home():
    """Strictly resolves HuggingFace cache path from system environment."""
    env = os.environ.get('HF_HOME')
    if not env:
        print("\n" + "!"*80)
        print("❌ CRITICAL ERROR: System environment variable 'HF_HOME' is not set.")
        print("Jarvis requires explicit pathing to prevent accidental system drive bloat.")
        print("Please set 'HF_HOME' to your model storage directory (e.g., D:\\Models\\HF).")
        print("!"*80 + "\n")
        sys.exit(1)
    
    path = os.path.normpath(env)
    print(f"  ↳ ✅ System Integrity: HF_HOME detected -> {path}")
    return path

def get_ollama_models():
    """Strictly resolves Ollama models path from system environment."""
    env = os.environ.get('OLLAMA_MODELS')
    if not env:
        print("\n" + "!"*80)
        print("❌ CRITICAL ERROR: System environment variable 'OLLAMA_MODELS' is not set.")
        print("Jarvis requires explicit pathing to prevent accidental system drive bloat.")
        print("Please set 'OLLAMA_MODELS' to your model storage directory (e.g., D:\\Models\\Ollama).")
        print("!"*80 + "\n")
        sys.exit(1)
    
    path = os.path.normpath(env)
    print(f"  ↳ ✅ System Integrity: OLLAMA_MODELS detected -> {path}")
    return path

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
