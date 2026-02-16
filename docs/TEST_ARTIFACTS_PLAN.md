# Test Artifacts & Robustness Upgrade Plan

This document outlines the architectural changes required to enhance the reliability, traceability, and user experience of the Jarvis test runner.

## 1. Goal
To ensure that all test run artifacts (logs, results, system state) are persistently tracked and preserved in real-time, allowing for full post-mortem analysis even in the event of a system crash or interruption.

## 2. Session Management
We will move away from the single `tests/artifacts/latest_*.json` model to a history-based session model.

### 2.1 Directory Structure
Every test run will initialize a unique session directory:
`tests/logs/RUN_{YYYYMMDD}_{HHMMSS}/`

This directory will contain:
*   `system_info.yaml`: Snapshot of the host environment and test plan.
*   `progression.log`: A clean, high-level event log of the test run.
*   `{domain}.json`: Incremental result files (e.g., `llm.json`, `stt.json`).
*   `{service}_{model}_{timestamp}.log`: Full stdout/stderr captures for every spawned service.
*   `report.xlsx`: The final Excel report generated from this specific run's data.

### 2.2 System Snapshot (`system_info.yaml`)
Before any tests execute, `runner.py` will generate this file containing:
*   **Host**: OS, CPU Count, Total RAM, GPU Model (e.g., RTX 5090).
*   **Git**: Current commit hash and branch.
*   **Plan**: The full content of the executing `.yaml` test plan.
*   **Start Time**: ISO timestamp.

## 3. Logging Architecture

### 3.1 Service Logs
The `LifecycleManager` will be updated to accept the `session_dir`.
*   **Action**: All `start_server` calls will redirect `stdout` and `stderr` to a file within `session_dir`.
*   **Naming**: `svc_{domain}_{model_safe_name}_{timestamp}.log`
*   **Ollama**: We will enforce a **mandatory** kill of any existing Ollama instance at the start of the run (or domain execution) to ensure we capture its startup logs from scratch in our session log file.

### 3.2 Progression Log (`progression.log`)
A new logger will be implemented to mirror critical TUI events to a file.
*   **Format**: `[HH:MM:SS] [LEVEL] Message`
*   **Events**:
    *   "Starting Test Run: [Plan Name]"
    *   "Switching to Domain: [Domain]"
    *   "Loading Model: [Model Name]"
    *   "Scenario [Name]: PASSED/FAILED (Duration: Xs)"
    *   "Error: [Details]"

## 4. Real-Time Artifacts

### 4.1 Incremental JSON
The reporting mechanism will be refactored to support **append-only** or **read-modify-write** operations.
*   **Current Behavior**: Results are accumulated in memory and saved at the very end.
*   **New Behavior**: 
    1.  Test finishes a scenario.
    2.  `runner.py` immediately reads `{session_dir}/{domain}.json` (if exists).
    3.  Appends the new result.
    4.  Writes it back to disk.
*   **Crash Safety**: This ensures that if the run crashes at 50%, the JSON file contains valid data for the first 50%.

### 4.2 Excel Generation
*   The `generate_report.py` script will be updated to accept an input directory argument.
*   It will generate the Excel report based on whatever `.json` files are present in that directory, regardless of whether the run is "complete" or not.

## 5. TUI Dashboard (Rich)

We will replace the scrolling text output with a static, updating dashboard using the `rich` library.

### 5.1 Layout
*   **Header**: Run ID, System Info (CPU/RAM/GPU), Test Plan Name.
*   **Progress Section**:
    *   **Total Progress**: Bar showing overall completion (Scenarios Done / Total Scenarios).
    *   **Domain Progress**: Bar for the current domain.
    *   **Time**: Elapsed Time | Estimated Remaining.
*   **Status Panel**:
    *   **Current Action**: "Warming up [Model]...", "Running [Scenario]..."
    *   **Active Services**: List of running ports/models.
    *   **Live VRAM**: Real-time VRAM usage bar (polled from `utils.vram`).
*   **Log Window**: A scrollable box showing the last ~10 lines of `progression.log` for context.

## 6. Implementation Steps

1.  **`tests/utils/session.py`**: Create session initialization and system info logic.
2.  **`tests/utils/ui.py`**: Implement the `RichDashboard` class.
3.  **`tests/utils/lifecycle.py`**: Update to use `session_dir` for logs and enforce strict Ollama cleanup.
4.  **`tests/utils/reporting.py`**: Implement incremental JSON saving.
5.  **`tests/runner.py`**: Orchestrate the flow: Init Session -> Start Dashboard -> Run Tests (update dashboard/artifacts) -> Generate Excel.

## 7. Migration
*   **Legacy Cleanup**: Remove code related to `tests/artifacts/latest_*.json`.
*   **Gitignore**: Ensure `tests/logs/` is ignored (already done), but verify subfolders are covered.
