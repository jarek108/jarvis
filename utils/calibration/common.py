import os
import re
import yaml
import time
import shutil
import sys

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

import utils

def parse_size_gb(size_str):
    """Converts sizes like '18.1 GiB', '876.0 MiB', '0.93 GB' to float GB."""
    if not size_str: return 0.0
    size_str = size_str.strip().replace('"', '').replace('(', '').replace(')', '')
    
    m = re.match(r"([\d\.]+)\s*([a-zA-Z]+)", size_str)
    if not m: return 0.0
    
    val = float(m.group(1))
    unit = m.group(2).upper()
    
    if unit.startswith('M'): return val / 1024.0
    if unit.startswith('G'): return val
    if unit.startswith('K'): return val / (1024.0 * 1024.0)
    if unit.startswith('T'): return val * 1024.0
    return val

def save_calibration(model_id, engine, base_vram, gb_per_10k, source_tokens, source_cache_gb, log_source, project_root):
    cal_dir = os.path.join(project_root, "model_calibrations")
    logs_dir = os.path.join(cal_dir, "source_logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    prefix = "ol_" if engine == "ollama" else "vl_"
    safe_name = prefix + model_id.replace("/", "--").replace(":", "-").lower()
    yaml_path = os.path.join(cal_dir, f"{safe_name}.yaml")
    dest_log_path = os.path.join(logs_dir, f"{safe_name}.log")
    
    output_data = {
        "id": model_id, "engine": engine,
        "constants": {"base_vram_gb": round(base_vram, 4), "kv_cache_gb_per_10k": round(gb_per_10k, 6)},
        "metadata": {
            "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu_vram_total_gb": round(utils.get_gpu_total_vram(), 2),
            "source_tokens": source_tokens, "source_cache_gb": round(source_cache_gb, 4)
        }
    }
    
    with open(yaml_path, "w", encoding="utf-8") as f: 
        yaml.dump(output_data, f, sort_keys=False)
    
    if log_source and os.path.exists(log_source):
        # Normalize paths to check if they are the same
        abs_src = os.path.abspath(log_source)
        abs_dest = os.path.abspath(dest_log_path)
        if abs_src != abs_dest:
            shutil.copy(log_source, dest_log_path)
            print(f"💾 Log archived to: {os.path.relpath(dest_log_path, project_root)}")
        
    print(f"✅ Specification saved: {os.path.relpath(yaml_path, project_root)}")
    return output_data
