import os
import yaml
import sys

_config_cache = None

def get_project_root():
    """Returns the absolute path to the project root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_config():
    global _config_cache
    if _config_cache is not None:
        return _config_cache
        
    config_path = os.path.join(get_project_root(), "config.yaml")
    with open(config_path, "r") as f:
        _config_cache = yaml.safe_load(f)
    return _config_cache

def list_all_loadouts(include_experimental=False):
    """Lists all available loadout names from the loadouts.yaml file."""
    loadouts_file = os.path.join(get_project_root(), "loadouts.yaml")
    if not os.path.exists(loadouts_file):
        return []
    
    with open(loadouts_file, "r") as f:
        data = yaml.safe_load(f)
        return sorted(list(data.keys())) if data else []

def safe_filename(canonical_id):
    """
    Deterministically sanitizes a canonical model ID for use in the local filesystem.
    Rules: lowercase, replace slashes and colons with double dashes.
    """
    if not canonical_id: return ""
    return canonical_id.lower().replace(" ", "-").replace("/", "--").replace(":", "--")

def parse_model_string(entry, stt_registry=None, tts_registry=None):
    """
    Parses a strict URI-style model definition string: engine://canonical_id#param1=val1#param2
    Returns a dictionary with the engine, original canonical id, and parameters.
    """
    if not isinstance(entry, str): return None
    
    if "://" not in entry:
        raise ValueError(f"Invalid model string '{entry}'. Must use format 'engine://canonical_id#params'")

    engine, rest = entry.split("://", 1)
    parts = rest.split("#")
    canonical_id = parts[0]
    
    flags = {}
    for f in parts[1:]:
        if "=" in f:
            k, v = f.split("=", 1)
            try:
                v = int(v) if v.isdigit() else (float(v) if '.' in v else v)
            except: pass
            if v == "true": v = True
            elif v == "false": v = False
            flags[k.lower()] = v
        else:
            flags[f.lower()] = True

    # Map 'ctx' flag back to 'num_ctx' for system compatibility
    if 'ctx' in flags:
        flags['num_ctx'] = flags.pop('ctx')

    return {
        "id": canonical_id,
        "engine": engine.lower(),
        "params": flags
    }

def get_model_calibration(model_id, engine="vllm"):
    """
    Retrieves physics constants for a specific model from model_calibrations/.
    Returns (base_vram, kv_cost_per_10k) or None.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cal_dir = os.path.join(project_root, "model_calibrations")
    
    # Use standard safe filename generator
    safe_id = safe_filename(model_id)
    cal_path = os.path.join(cal_dir, f"{engine}_{safe_id}.yaml")
    
    if os.path.exists(cal_path):
        with open(cal_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            constants = data.get("constants", {})
            return constants.get("base_vram_gb"), constants.get("kv_cache_gb_per_10k")
    
    return None, None

def resolve_path(path_str):
    """Expands ~ and resolves relative paths against project root."""
    if not path_str: return None
    expanded = os.path.expanduser(path_str)
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.normpath(os.path.join(project_root, expanded))

def get_hf_home(silent=False):
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
    if not silent:
        print(f"  ↳ ✅ System Integrity: HF_HOME detected -> {path}")
    return path

def get_ollama_models(silent=False):
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
    if not silent:
        print(f"  ↳ ✅ System Integrity: OLLAMA_MODELS detected -> {path}")
    return path
