# Jarvis Testing Procedures & Workflows

This document outlines the standard operating procedures for verifying changes, benchmarking performance, and ensuring system stability in the Jarvis ecosystem.

## 1. The Testing Hierarchy

To optimize for both speed and coverage, testing should follow a strict hierarchy. Always start small and expand only after success.

### Level 0: Fast Infra Check (Plumbing)
**When to run:** Immediately after ANY code change or refactor.
**Goal:** Verify that imports, network ports, JSON schemas, and server coordination are still functional. **Does not require a GPU.**

*   **Command:** `python tests/runner.py tests/plans/integration_fast.yaml --mock-all`
*   **Behavior:** Runs real server scripts (`stt_server.py`, `tts_server.py`, etc.) but uses lightweight stubs instead of loading model weights, and mocks hardware drivers.
*   **Duration:** ~15-30 seconds.

### Level 1: Domain-Specific Checks
**When to run:** After making changes to a specific component (e.g., updating `llm.py` or `stt_server.py`).
**Goal:** Verify logic in isolation.

*   **Command:** `python tests/runner.py tests/plans/components_fast.yaml`
*   **Behavior:** Tests individual atomic nodes (STT, LLM, TTS) using real models but virtualized hardware inputs.

### Level 2: Fast Deployment Check
**When to run:** Before committing code or after integrating multiple components.
**Goal:** Verify full stack hardware compatibility using a representative production pipeline.

*   **Command:** `python tests/runner.py tests/plans/integration_fast.yaml`
*   **Duration:** ~2-3 minutes.

### Level 3: Comprehensive Audit
**When to run:** Before a major release or after significant hardware/driver updates.
**Goal:** Stress-test the system and generate official performance benchmarks across all model variants.

*   **Atomic Audit:** `python tests/runner.py tests/plans/components_exhaustive.yaml`
*   **System Audit:** `python tests/runner.py tests/plans/integration_exhaustive.yaml`
*   **Duration:** 20+ minutes.

---

## 2. Orthogonal Mocking Flags

The test runner uses orthogonal flags to control which parts of the system are real vs. simulated:

| Flag | Component | Behavior |
| :--- | :--- | :--- |
| **`--mock-models`** | AI Models | Uses zero-VRAM stub servers. |
| **`--mock-edge`** | Hardware | Bypasses `pyaudio`/`mss` drivers; uses file readers/no-ops. |
| **`--mock-all`** | Everything | Alias for both flags above. Equivalent to old "plumbing" mode. |
| *(None)* | Production | Uses **Real Models** + **Real Drivers** in a **Virtualized Environment**. |

> **Note on Hard-Crash Philosophy**: Non-mocking tests (standard or `--mock-models` only) require physical or virtualized hardware. If drivers or virtual audio cables are missing, the test will **fail loudly** rather than silently passing.

---

## 3. Artifact & Report Management

Every test run (real, mock, or plumbing) generates a unique session directory in `logs/test_ui/ or logs/test_be/RUN_YYYYMMDD_HHMMSS/`.

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
*   **Missing Logs:** Check `logs/test_ui/ or logs/test_be/RUN_.../` for `svc_*.log` files. If missing, the service might have failed to start entirely (check `progression.log` for lifecycle errors).

---

## 5. Streaming vs. Batch Benchmarking

Jarvis supports side-by-side comparison of **Streaming** (Token-by-token) and **Batch** (Full response) performance to quantify latency trade-offs (Time-To-First-Token).

### Default Behavior
*   **Batch Mode:** By default, all LLM and VLM tests run in **Batch Mode** (`stream=False`). This ensures conservative benchmarking by measuring the full request-response cycle without protocol optimizations.

### The Flag Syntax (`#stream`)
To enable streaming for a specific model loadout, append the `#stream` flag to the model string in the test plan.

**Example (`tests/plans/integration_exhaustive.yaml`):**
```yaml
execution:
  - domain: llm
    loadouts:
      - ["ollama://qwen2.5:0.5b"]          # Runs Batch
      - ["ollama://qwen2.5:0.5b#stream"]   # Runs Streaming
```

---

## 6. VLM Parameter Tuning

For Vision-Language Models (especially `Qwen3-VL`), you can tune memory and context behavior directly in the loadout string.

| Flag | Description | Example |
| :--- | :--- | :--- |
| `#ctx=N` | Sets `--max-model-len`. | `#ctx=16384` |
| `#gpu_util=X` | Overrides config `gpu_memory_utilization`. | `#gpu_util=0.9` |

For a deep dive on why these parameters matter, see **[VRAM Tuning](analysis/VRAM_TUNING.md)**.

---

## 7. Model Calibration (How-to)

Calibration translates raw logs into the physical constants Jarvis needs for VRAM management.

### How to Calibrate a Single Model
1.  Run the model once to generate a log file.
2.  Run the calibrator:
    ```powershell
    python tools/calibrate_models.py path/to/your.log
    ```

### How to Refresh the Entire Physics Database
Use this after a hardware upgrade (e.g., more VRAM) or a major engine update (Ollama/vLLM version bump).
```powershell
python tools/calibrate_models.py system_config/model_calibrations/source_logs/
```
