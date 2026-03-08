# Reference: Calibration & Physics Database

Technical specifications for the Jarvis Model Physics system.

## 1. CLI: `tools/calibrate_models.py`

The primary tool for extracting physical constants from engine logs.

### Usage
```powershell
# Auto-detect engine and model ID from log
python tools/calibrate_models.py [PATH]

# Explicitly calibrate all logs in a directory
python tools/calibrate_models.py logs/test_ui/ or logs/test_be/RUN_20260225_183014/
```

### Positional Arguments
*   **`PATH`**: Path to a single `.log` file or a directory containing multiple logs. If a directory is provided, the script runs in **Batch Mode**.

### Options
*   **`--engine [vllm|ollama]`**: Force a specific engine parser. By default, the script auto-detects the engine using content fingerprints.
*   **`--model [ID]`**: Override the Model ID for the output filename. By default, the script extracts the ID from the log content or filename.

---

## 2. Datasheet Schema: `model_calibrations/*.yaml`

Each calibrated model has a YAML datasheet stored in the `model_calibrations/` root folder.

### Schema Description
| Field | Description |
| :--- | :--- |
| `id` | The internal model identifier (e.g., `qwen2.5:0.5b`). |
| `engine` | The inference engine (`vllm`, `ollama`, or `native`). |
| `capabilities` | List of supported modalities (e.g., `[text_in, image_in, text_out]`). |
| `constants.base_vram_gb` | Fixed VRAM cost (Weights + Static Compute Buffer). |
| `constants.kv_cache_gb_per_10k` | Variable VRAM cost (GB per 10,000 tokens). |
| `metadata.calibrated_at` | Timestamp of the extraction. |
| `metadata.gpu_vram_total_gb` | Total VRAM of the hardware used during calibration. |

### Filenaming Convention
Files are prefixed with the engine type and fully lowercased for cross-platform compatibility:
*   **Ollama**: `ol_<sanitized_id>.yaml`
*   **vLLM**: `vl_<sanitized_id>.yaml`
*   **STT**: `stt_<sanitized_id>.yaml`
*   **TTS**: `tts_<sanitized_id>.yaml`

**Sanitization Rules**:
*   Spaces become hyphens (`-`).
*   Slashes become double-hyphens (`--`).
*   Example: `Qwen/Qwen2-VL-2B-Instruct` -> `vl_qwen--qwen2-vl-2b-instruct.yaml`.

---

## 3. Status Codes & Error Messages

During a test run or system initialization, the `LifecycleManager` may report specific calibration-related states.

### `UNCALIBRATED` (Critical Skip)
*   **Engine**: vLLM strictly requires calibration.
*   **Meaning**: The requested model has no corresponding `.yaml` in `model_calibrations/`.
*   **Action**: Jarvis will **skip** the test scenario.
*   **Fix**: Run the model once manually to generate a log, then run `python tools/calibrate_models.py [your_log]`.

---

## 4. Static Calibrations (Native Services)

Services like `faster-whisper` (STT) and `Kokoro` (TTS) use static calibration files. Since their memory usage is strictly deterministic based on model size, these files are usually pre-populated and do not require log-parsing.

*   **STT Location**: `model_calibrations/stt_<model_name>.yaml`
*   **TTS Location**: `model_calibrations/tts_<variant_name>.yaml`
