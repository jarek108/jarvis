# Jarvis Testing Procedures & Workflows

This document outlines the standard operating procedures for verifying changes, benchmarking performance, and ensuring system stability in the Jarvis ecosystem.

## 1. The Testing Hierarchy

To optimize for both speed and coverage, testing should follow a strict hierarchy. Always start small and expand only after success.

### Level 0: Refactor Guard (Plumbing Check)
**When to run:** Immediately after ANY code change or refactor.
**Goal:** Verify that imports, network ports, JSON schemas, and server coordination are still functional. **Does not require a GPU.**

*   **Command:** `python tests/runner.py tests/plans/ALL_fast.yaml --plumbing`
*   **Behavior:** Runs real server scripts (`stt_server.py`, `tts_server.py`, etc.) but uses lightweight stubs instead of loading model weights.
*   **Duration:** ~15-30 seconds.

### Level 1: Domain-Specific Fast Checks
**When to run:** After making changes to a specific component (e.g., updating `llm.py` or `stt_server.py`).
**Goal:** Verify logic against actual AI kernels on hardware.

*   **LLM Focus:** `python tests/runner.py tests/plans/LLM_fast.yaml`
*   **STT Focus:** `python tests/runner.py tests/plans/STT_fast.yaml`
*   **TTS Focus:** `python tests/runner.py tests/plans/TTS_fast.yaml`
*   **VLM Focus:** `python tests/runner.py tests/plans/VLM_fast.yaml`
*   **STS Focus:** `python tests/runner.py tests/plans/STS_fast.yaml`

### Level 2: The "Fast Health Check"
**When to run:** Before committing code or after integrating multiple components.
**Goal:** Verify full stack hardware compatibility.

*   **Command:** `python tests/runner.py tests/plans/ALL_fast.yaml`
*   **Duration:** ~2-3 minutes.

### Level 3: The "Exhaustive Global Comparison"
**When to run:** Before a major release or after significant hardware/driver updates.
**Goal:** Stress-test the system and generate official performance benchmarks.

*   **Command:** `python tests/runner.py tests/plans/ALL_exhaustive.yaml`
*   **Duration:** 20+ minutes.

---

## 2. Mock vs. Plumbing Mode

Both modes allow testing without loading actual model weights, but they operate at different depths:

| Feature | Mock Mode (`--mock`) | Plumbing Mode (`--plumbing`) |
| :--- | :--- | :--- |
| **Logic Layer** | Simulator (in Runner) | **Real Servers** (FastAPI) |
| **Network** | None (simulated) | **Actual TCP/HTTP** |
| **JSON API** | Not tested | **Fully Tested** |
| **Dashboard** | Full Display | Full Display |
| **Artifacts** | Mocked Data | **Real Structure** (WAVs, JSON) |
| **Primary Use** | UI/Reporting tweaks | **Refactor Guard / Plumbing** |

---

## 3. Artifact & Report Management

Every test run (real, mock, or plumbing) generates a unique session directory in `tests/logs/RUN_YYYYMMDD_HHMMSS/`.

### Persistent Artifacts
*   **`system_info.yaml`**: Host specs (GPU, RAM, CPU) and the plan executed.
*   **`progression.log`**: A human-readable textual snapshot of the execution flow.
*   **`svc_*.log`**: Full stdout/stderr capture for every spawned service.
    *   **vLLM Note**: Captured in real-time from the Docker container via `docker logs -f`.
*   **`domain.json`**: Incremental result data for each domain.
*   **`Jarvis_Benchmark_Report_*.xlsx`**: The final stylized Excel report.

### Excel Reporting
*   Reports are automatically generated and uploaded to Google Drive at the end of a run.
*   Links to the GDrive file are displayed in the dashboard's "System Status" panel.
*   If upload fails, the local path is provided.

---

## 4. Troubleshooting

*   **"Skipped" Scenarios:** Ensure `LiveFilter` in `ui.py` is correctly passing `SCENARIO_RESULT` lines to stdout.
*   **Dashboard Duplication:** Ensure all `print` statements in the runner/lifecycle logic are silenced or logged to `progression_logger` instead.
*   **Missing Logs:** Check `tests/logs/RUN_.../` for `svc_*.log` files. If missing, the service might have failed to start entirely (check `progression.log` for lifecycle errors).

---

## 5. Streaming vs. Batch Benchmarking

Jarvis supports side-by-side comparison of **Streaming** (Token-by-token) and **Batch** (Full response) performance to quantify latency trade-offs (Time-To-First-Token).

### Default Behavior
*   **Batch Mode:** By default, all LLM and VLM tests run in **Batch Mode** (`stream=False`). This ensures conservative benchmarking by measuring the full request-response cycle without protocol optimizations.

### The Flag Syntax (`#stream`)
To enable streaming for a specific model loadout, append the `#stream` flag to the model string in the test plan.

**Example (`tests/plans/LLM_fast.yaml`):**
```yaml
execution:
  - domain: llm
    loadouts:
      - ["OL_qwen2.5:0.5b"]          # Runs Batch
      - ["OL_qwen2.5:0.5b#stream"]   # Runs Streaming
```

### Reporting
*   **Separation:** The test runner treats these as distinct loadouts.
*   **Labeling:** In the Excel report and Dashboard, scenarios are automatically suffixed with `[Stream]` or `[Batch]` (e.g., `Story Gen [Stream]`).
*   **Metrics:** Streaming runs will show a significantly lower **TTFT (Time To First Token)**, while Batch runs provide a baseline for total throughput (TPS).

---

## 6. VLM Parameter Tuning

For Vision-Language Models (especially `Qwen3-VL`), you can tune memory and context behavior directly in the loadout string.

| Flag | Description | Example |
| :--- | :--- | :--- |
| `#ctx=N` | Sets `--max-model-len`. Crucial for long videos. | `#ctx=16384` |
| `#vid_lim=N` | Sets `--limit-mm-per-prompt video=N`. | `#vid_lim=2` |
| `#img_lim=N` | Sets `--limit-mm-per-prompt image=N`. | `#img_lim=4` |
| `#gpu_util=X` | Overrides config `gpu_memory_utilization`. | `#gpu_util=0.9` |

**Example (`tests/plans/vLLM_fast.yaml`):**
```yaml
execution:
  - domain: vlm
    loadouts:
      - ["VL_QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ#nativevideo#stream#ctx=16384"]
```

For a deep dive on why these parameters matter (and why VRAM usage looks static), see **[VRAM Tuning](analysis/VRAM_TUNING.md)**.

---

## 7. Model Calibration

To enable the **Smart Allocator** (vLLM) or **Hardware Guardrails** (Ollama), you must calibrate new models once. This generates a physics file in `model_calibrations/`.

Calibration is a **Zero-Config** log-parsing process. The engine and model name are auto-detected from the log content.

### Step 1: Capture a Log
*   **vLLM**: `docker logs vllm-server > model_startup.log`
*   **Ollama**: Locate the log at `%LOCALAPPDATA%\Ollama\server.log`.

### Step 2: Calibrate
Simply point the script to the log file:
```powershell
python utils/calibrate_models.py path/to/your.log
```

**Output:**
A YAML file (e.g., `ol_qwen2.5-0.5b.yaml`) containing `base_vram_gb` and `kv_cache_gb_per_10k`. The source log is archived in `model_calibrations/source_logs/` for traceability.
