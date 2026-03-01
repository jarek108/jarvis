import os
import yaml
import sys

_config_cache = None

def load_config():
    global _config_cache
    if _config_cache is not None:
        return _config_cache
        
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config.yaml")
    with open(config_path, "r") as f:
        _config_cache = yaml.safe_load(f)
    return _config_cache

def list_all_loadouts(include_experimental=False):
    """Lists all available loadout names from the loadouts.yaml file."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loadouts_file = os.path.join(project_root, "loadouts.yaml")
    if not os.path.exists(loadouts_file):
        return []
    
    with open(loadouts_file, "r") as f:
        data = yaml.safe_load(f)
        return sorted(list(data.keys())) if data else []

def parse_model_string(entry, stt_registry=None, tts_registry=None):
    """
    Parses a string like 'VL_model-id#ctx=8192#stream' into a structured dict.
    Returns: {"id": str, "engine": str, "params": dict}
    """
    if not isinstance(entry, str): return None
    
    # Fallback registry fetch if not provided
    if stt_registry is None or tts_registry is None:
        cfg = load_config()
        stt_registry = cfg.get('stt_loadout', {})
        tts_registry = cfg.get('tts_loadout', {})

    parts = entry.split('#')
    raw_id = parts[0]
    
    flags = {}
    for f in parts[1:]:
        if '=' in f:
            k, v = f.split('=', 1)
            try:
                v = int(v) if v.isdigit() else (float(v) if '.' in v else v)
            except: pass
            flags[k.lower()] = v
        else:
            flags[f.lower()] = True

    engine = "native"
    clean_id = raw_id
    
    if raw_id in stt_registry or raw_id in tts_registry:
        engine = "native"
    elif raw_id.startswith("OL_"):
        engine = "ollama"
        clean_id = raw_id[3:]
    elif raw_id.startswith("VL_"):
        engine = "vllm"
        clean_id = raw_id[3:]
    elif raw_id.startswith("vllm:"):
        engine = "vllm"
        clean_id = raw_id[5:]
        
    # Map 'ctx' flag back to 'num_ctx' for system compatibility
    if 'ctx' in flags:
        flags['num_ctx'] = flags.pop('ctx')

    return {
        "id": clean_id,
        "engine": engine,
        "params": flags
    }

def get_model_calibration(model_id, engine="vllm"):
    """
    Retrieves physics constants for a specific model from model_calibrations/.
    Returns (base_vram, kv_cost_per_10k) or None.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cal_dir = os.path.join(project_root, "model_calibrations")
    
    prefix = "vl_" if engine == "vllm" else "ol_"
    # Sanitize name to match our filenaming convention
    clean_id = model_id.lower().replace(" ", "-").replace("/", "--").replace(":", "-").split('#')[0]
    cal_path = os.path.join(cal_dir, f"{prefix}{clean_id}.yaml")
    
    if os.path.exists(cal_path):
        with open(cal_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            constants = data.get("constants", {})
            return constants.get("base_vram_gb"), constants.get("kv_cache_gb_per_10k")
    
    return None, None

def resolve_canonical_id(model_id, engine):
    """
    Translates an internal sanitized model ID (e.g., qwen--2b) 
    into its canonical engine ID (e.g., Qwen/Qwen2-2B or qwen:2b).
    Source of truth: model_calibrations/*.yaml 'id' field.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cal_dir = os.path.join(project_root, "model_calibrations")
    
    prefix = "vl_" if engine == "vllm" else "ol_"
    # Sanitize incoming to find the calibration file
    lookup_id = model_id.lower().replace(" ", "-").replace("/", "--").replace(":", "-").split('#')[0]
    if lookup_id.startswith(prefix): lookup_id = lookup_id[len(prefix):]
    
    cal_path = os.path.join(cal_dir, f"{prefix}{lookup_id}.yaml")
    
    # 1. Metadata Lookup (Source of Truth)
    if os.path.exists(cal_path):
        with open(cal_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data.get("id"): return data["id"]

    # 2. Heuristic Fallback (For uncalibrated models)
    clean_id = model_id.split('#')[0]
    if clean_id.startswith(prefix): clean_id = clean_id[len(prefix):]
    
    if engine == "vllm":
        return clean_id.replace("--", "/") # Restore slashes
    elif engine == "ollama":
        return clean_id.replace("--", ":") # Restore colons
    return clean_id

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
