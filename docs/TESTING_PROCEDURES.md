# Jarvis Testing Procedures & Workflows

This document outlines the standard operating procedures for verifying changes, benchmarking performance, and ensuring system stability in the Jarvis ecosystem.

## 1. The Testing Hierarchy

To optimize for both speed and coverage, testing should follow a strict hierarchy. Always start small and expand only after success.

### Level 1: Domain-Specific Fast Checks
**When to run:** After making changes to a specific component (e.g., updating `llm.py` or `stt_server.py`).
**Goal:** Instant feedback loop (< 30 seconds).

*   **LLM Focus:** `python tests/runner.py tests/plans/LLM_fast.yaml`
*   **STT Focus:** `python tests/runner.py tests/plans/STT_fast.yaml`
*   **TTS Focus:** `python tests/runner.py tests/plans/TTS_fast.yaml`
*   **VLM Focus:** `python tests/runner.py tests/plans/VLM_fast.yaml`
*   **STS Focus:** `python tests/runner.py tests/plans/STS_fast.yaml`

### Level 2: The "Fast Health Check"
**When to run:** Before committing code, after integrating multiple components, or when performing a general system sanity check.
**Goal:** Verify that all core services (LLM, STT, TTS, VLM, STS) can start up and handle at least one request.

*   **Command:** `python tests/runner.py tests/plans/ALL_fast.yaml`
*   **Scope:** Runs the lightest model for each domain (e.g., `qwen2.5:0.5b`, `faster-whisper-base`).
*   **Duration:** ~2-3 minutes.

### Level 3: The "Exhaustive Global Comparison"
**When to run:** Before a major release, after significant hardware/driver updates, or when generating official benchmark reports.
**Goal:** Stress-test the system, verify all model permutations, and generate a comprehensive performance matrix.

*   **Command:** `python tests/runner.py tests/plans/ALL_exhaustive.yaml`
*   **Scope:** Runs EVERY defined model loadout against ALL scenarios.
*   **Duration:** 20+ minutes (depends on hardware).

---

## 2. Mock Mode (UI & Artifact Testing)

**When to run:** When iterating on the Test Runner UI, dashboard, logging, or Excel report generation logic, without waiting for actual models to load.

*   **Command:** `python tests/runner.py tests/plans/ALL_fast.yaml --mock`
*   **Behavior:** Simulates model loading times, execution durations, and failures based on `config.yaml` settings (`mock` section).
*   **Use Case:** Perfect for testing the `RichDashboard`, file persistence, or GDrive upload workflows.

---

## 3. Artifact & Report Management

Every test run (real or mock) generates a unique session directory in `tests/logs/RUN_YYYYMMDD_HHMMSS/`.

### Persistent Artifacts
*   **`system_info.yaml`**: Host specs (GPU, RAM, CPU) and the plan executed.
*   **`progression.log`**: A human-readable textual snapshot of the execution flow.
*   **`svc_*.log`**: Full stdout/stderr capture for every spawned service (Ollama, vLLM, etc.).
*   **`domain.json`**: Incremental result data for each domain (saved in real-time).
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
