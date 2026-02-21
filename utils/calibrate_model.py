import os
import sys
import re
import yaml
import time
import shutil
import argparse

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

# Local imports from the same folder
from vram import get_gpu_total_vram

# --- SHARED UTILITIES ---

def parse_size_gb(size_str):
    """Converts sizes like '18.1 GiB', '876.0 MiB', '0.93 GB' to float GB."""
    if not size_str: return 0.0
    size_str = size_str.strip().replace('"', '').replace('(', '').replace(')', '')
    m = re.match(r"([\d\.]+)\s*([a-zA-Z]+)", size_str)
    if not m: return 0.0
    val, unit = float(m.group(1)), m.group(2).upper()
    if unit.startswith('M'): return val / 1024.0
    if unit.startswith('K'): return val / (1024.0 * 1024.0)
    if unit.startswith('T'): return val * 1024.0
    return val

def save_calibration(model_id, engine, base_vram, gb_per_10k, source_tokens, source_cache_gb, log_source):
    """Unified artifact saving and archiving."""
    cal_dir = os.path.join(project_root, "model_calibrations")
    logs_dir = os.path.join(cal_dir, "source_logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    prefix = "ol_" if engine == "ollama" else "vl_"
    clean_id = model_id.lower().replace(" ", "-").replace("/", "--").replace(":", "-").split('#')[0]
    safe_name = prefix + clean_id
    
    yaml_path = os.path.join(cal_dir, f"{safe_name}.yaml")
    dest_log_path = os.path.join(logs_dir, f"{safe_name}.log")
    
    output_data = {
        "id": model_id.split('#')[0],
        "engine": engine,
        "constants": {"base_vram_gb": round(base_vram, 4), "kv_cache_gb_per_10k": round(gb_per_10k, 6)},
        "metadata": {
            "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu_vram_total_gb": round(get_gpu_total_vram(), 2),
            "source_tokens": source_tokens, "source_cache_gb": round(source_cache_gb, 4)
        }
    }
    
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, sort_keys=False)
    
    if log_source and os.path.exists(log_source):
        if os.path.abspath(log_source) != os.path.abspath(dest_log_path):
            shutil.copy(log_source, dest_log_path)
        
    print(f"✅ Specification saved: {os.path.relpath(yaml_path, project_root)}")
    return output_data

# --- ENGINE PARSERS ---

def extract_vllm_metrics(content):
    """Parses vLLM log content for memory metrics and model ID."""
    re_base = re.compile(r"Model loading took ([\d\.]+) GiB memory")
    re_cache_gb = re.compile(r"Available KV cache memory: ([\d\.]+) GiB")
    re_tokens = re.compile(r"GPU KV cache size: ([\d,]+) tokens")
    re_model = re.compile(r"model\s+([\w\-/.-]+)")

    base_vram, cache_gb, tokens, model_id = None, None, None, None
    m = re_base.search(content); base_vram = float(m.group(1)) if m else None
    m = re_cache_gb.search(content); cache_gb = float(m.group(1)) if m else None
    m = re_tokens.search(content); tokens = int(m.group(1).replace(",", "")) if m else None
    m = re_model.search(content); model_id = m.group(1) if m else None
    return base_vram, cache_gb, tokens, model_id

def extract_ollama_metrics(content, default_id=None):
    """Parses Ollama log content for memory metrics and model ID."""
    re_total = re.compile(r'msg="total memory".*?size="?([^"]+)"?', re.DOTALL)
    re_kv_msg = re.compile(r'msg="kv cache".*?size="?([^"]+)"?', re.DOTALL)
    re_weight_msg = re.compile(r'msg="model weights".*?size="?([^"]+)"?', re.DOTALL)
    re_compute_msg = re.compile(r'msg="compute graph".*?size="?([^"]+)"?', re.DOTALL)
    re_model_msg = re.compile(r'msg="loading model".*?model=([^ ]+)')
    re_kv_low = re.compile(r'(?:llama_kv_cache:.*?size|KV buffer size)\s*=\s*([\d\.]+)\s*(\w+)i?B')
    re_tokens = re.compile(r'(?:llama_kv_cache: size|KV self size)\s*=\s*.*?\(\s*(\d+)\s*cells')
    re_weight_low = re.compile(r'(?:model size:|model buffer size)\s*[:=]\s*([\d\.]+)\s*(\w+)i?B')
    re_compute_low = re.compile(r'compute buffer size\s*[:=]\s*([\d\.]+)\s*(\w+)i?B')
    re_model_low = re.compile(r'general.name\s+=\s+(.*)')
    re_model_v3 = re.compile(r'general.name\s+\w+\s+=\s+(.*)')
    re_tokens_fb = re.compile(r'KvSize:(\d+)')

    total_gb, kv_gb, cells, model_id = None, None, None, None
    weight_gb, compute_gb = 0.0, 0.0

    m = re_total.search(content); total_gb = parse_size_gb(m.group(1)) if m else None
    m = re_kv_msg.search(content)
    if m: kv_gb = parse_size_gb(m.group(1))
    else:
        m = re_kv_low.search(content)
        if m: kv_gb = parse_size_gb(f"{m.group(1)} {m.group(2)}")
    
    m = re_tokens.search(content); cells = int(m.group(1)) if m else None
    if not cells: 
        m = re_tokens_fb.search(content); cells = int(m.group(1)) if m else None
    
    m = re_weight_msg.search(content)
    if m: weight_gb = parse_size_gb(m.group(1))
    else:
        for wm in re_weight_low.finditer(content): weight_gb += parse_size_gb(f"{wm.group(1)} {wm.group(2)}")
    
    for cm in re_compute_low.finditer(content): compute_gb += parse_size_gb(f"{cm.group(1)} {cm.group(2)}")

    m = re_model_msg.search(content); model_id = m.group(1) if m else None
    if not model_id:
        m = re_model_low.search(content); model_id = m.group(1).strip() if m else None
    if not model_id:
        m = re_model_v3.search(content); model_id = m.group(1).strip() if m else None
    
    model_id = model_id or default_id
    if not total_gb and (weight_gb > 0 and kv_gb is not None):
        total_gb = weight_gb + kv_gb + compute_gb
    return total_gb, kv_gb, cells, model_id

# --- CORE LOGIC ---

def process_file(log_path, model_override=None, engine_override=None):
    """Processes a single log file."""
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        # Detection
        engine = engine_override
        if not engine:
            if "source=server.go" in content or 'msg="' in content or "llama_kv_cache:" in content: engine = "ollama"
            elif "(APIServer" in content or "Model loading took" in content: engine = "vllm"
        
        if not engine: return 1 # Skipped

        if engine == "ollama":
            # Filename-based fallback ID
            fname = os.path.basename(log_path)
            default_id = None
            if fname.startswith("svc_llm_OL_"):
                m = re.search(r"svc_llm_OL_(.*?)_\d{8}_\d{6}", fname)
                if m: default_id = m.group(1)
            elif fname.startswith("ol_"): default_id = fname[3:].replace(".log", "")
            
            total, kv, cells, ext_id = extract_ollama_metrics(content, default_id)
            target_id = model_override or ext_id
            if not (total and kv and cells and target_id): return 2
            save_calibration(target_id, "ollama", total-kv, (kv/cells)*10000, cells, kv, log_path)
        else:
            base, kv, tokens, ext_id = extract_vllm_metrics(content)
            target_id = model_override or ext_id
            if not target_id and os.path.basename(log_path).startswith("svc_llm_VL_"):
                m = re.search(r"svc_llm_VL_(.*?)_\d{8}_\d{6}", os.path.basename(log_path))
                if m: target_id = m.group(1)
            if not (base and kv and tokens and target_id): return 2
            save_calibration(target_id, "vllm", base, (kv/tokens)*10000, tokens, kv, log_path)
        return 0
    except Exception as e:
        print(f"💥 Error in {os.path.basename(log_path)}: {e}"); return 2

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Model Calibration from Logs")
    parser.add_argument("path", type=str, help="File or folder path")
    parser.add_argument("--model", type=str, help="Model ID override")
    parser.add_argument("--engine", type=str, choices=["vllm", "ollama"])
    args = parser.parse_args()

    if not os.path.exists(args.path): print(f"❌ Not found: {args.path}"); sys.exit(1)

    if os.path.isdir(args.path):
        files = [os.path.join(args.path, f) for f in os.listdir(args.path) if os.path.isfile(os.path.join(args.path, f))]
        stats = {0: 0, 1: 0, 2: 0}
        for f_path in files:
            if os.path.basename(f_path).startswith('.') or f_path.endswith(('.yaml', '.xlsx', '.json', '.wav')):
                stats[1] += 1; continue
            stats[process_file(f_path, engine_override=args.engine)] += 1
        print(f"\n✨ Batch complete. Success: {stats[0]}, Skipped: {stats[1]}, Failed: {stats[2]}")
    else:
        process_file(args.path, model_override=args.model, engine_override=args.engine)
