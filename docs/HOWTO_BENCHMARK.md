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

### Documentation Suite
*   **[How-to: Reporting](HOWTO_REPORTING.md)**: Instructions for generating and syncing reports.
*   **[Concept: Artifact Lifecycle](CONCEPT_REPORTING.md)**: Architectural theory behind "Turbo Sync."
*   **[Reference: Reporting Schema](REFERENCE_REPORTING.md)**: CLI flags and JSON data specifications.

### Excel Reporting
Reports are automatically generated and uploaded to Google Drive at the end of a run. Links to the GDrive file are displayed in the dashboard's "System Status" panel.

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

## 7. Model Calibration (How-to)

Calibration translates raw logs into the physical constants Jarvis needs for VRAM management.

### How to Calibrate a Single Model
1.  Run the model once to generate a log file.
2.  Run the calibrator:
    ```powershell
    python utils/calibrate_models.py path/to/your.log
    ```

### How to Refresh the Entire Physics Database
Use this after a hardware upgrade (e.g., more VRAM) or a major engine update (Ollama/vLLM version bump).
```powershell
python utils/calibrate_models.py model_calibrations/source_logs/
```

### How to Verify a Specification
1.  Open `model_calibrations/[model_id].yaml`.
2.  Check if `base_vram_gb` matches your model's weight size.
3.  For more details, see the **[Calibration Reference](REFERENCE_CALIBRATION.md)** and the **[Model Physics Concept](CONCEPT_MODEL_PHYSICS.md)**.
