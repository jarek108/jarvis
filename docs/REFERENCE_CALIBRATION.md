# Reference: Calibration & Physics Database

Technical specifications for the Jarvis Model Physics system.

## 1. CLI: `utils/calibrate_models.py`

The primary tool for extracting physical constants from engine logs.

### Usage
```powershell
python utils/calibrate_models.py [PATH] [OPTIONS]
```

### Positional Arguments
*   **`PATH`**: Can be a path to a single `.log` file or a directory containing multiple logs. If a directory is provided, the script runs in **Batch Mode**.

### Options
*   **`--engine [vllm|ollama]`**: Force a specific engine parser. By default, the script auto-detects the engine using content fingerprints.
*   **`--model [ID]`**: Override the Model ID for the output filename. By default, the script extracts the ID from the log content or filename.

---

## 2. Datasheet Schema: `model_calibrations/*.yaml`

Each calibrated model has a YAML datasheet stored in the `model_calibrations/` root folder.

### Schema Example
```yaml
id: Qwen/Qwen2.5-0.5B-Instruct  # The internal model identifier
engine: vllm                    # vllm or ollama
constants:
  base_vram_gb: 0.93            # Fixed cost (Weights + Compute Buffer)
  kv_cache_gb_per_10k: 0.114031 # Variable cost (GB per 10,000 tokens)
metadata:
  calibrated_at: '2026-02-21'   # Timestamp
  gpu_vram_total_gb: 31.84      # VRAM of the hardware used for calibration
  source_tokens: 73664          # Number of context cells used for measurement
  source_cache_gb: 0.84         # Raw KV cache size measured in the log
```

### Filenaming Convention
Files are prefixed with `vl_` (vLLM) or `ol_` (Ollama) and sanitized:
*   Spaces become hyphens (`-`).
*   Slashes become double-hyphens (`--`).
*   Uppercase is preserved.
*   Example: `QuantTrio/Qwen3-VL-30B` -> `vl_quanttrio--qwen3-vl-30b.yaml`.

---

## 3. Evidence Store: `model_calibrations/source_logs/`

Whenever a model is calibrated, a copy of the source log is archived here.
*   **Purpose**: Traceability and verification.
*   **Naming**: Logs are named strictly by the sanitized Model ID (e.g., `ol_moondream2.log`).
*   **Deduplication**: In batch mode, if multiple logs for the same model exist, the last one processed overwrites previous ones, ensuring a 1:1 relationship between YAML and Log evidence.
