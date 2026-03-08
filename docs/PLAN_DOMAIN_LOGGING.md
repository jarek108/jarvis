# Architectural Plan: Domain-Segregated Logging & Scenario Isolation

## 1. VISION
The goal of this architectural refactor is to simplify the logging system into a clean, intent-driven hierarchy (`prod`, `test_ui`, `test_be`). It radically simplifies the root session directory by combining all macroscopic text logs into a single, chronological timeline (`timeline.log`) and a machine-readable summary (`report.json`). Furthermore, it introduces **Status-Prefixed Scenario Isolation**, placing scenario-specific artifacts (screenshots, traces) into subfolders that are dynamically renamed based on the test result (e.g., `FAILED__UI_BOOT__ui_startup_state`), providing instant visual feedback in the file system.

## 2. ARCHITECTURAL REQUIREMENTS

### Requirement A: The Tri-Domain Directory Structure
All logging output must be routed into one of three rigid top-level categories within the `logs/` directory.
*   `logs/prod/`: For standard user application runs.
*   `logs/test_ui/`: For the Client Test Runner.
*   `logs/test_be/`: For the Backend Pipeline Runner.

### Requirement B: The Unified "Heartbeat" Files
Every session root must contain exactly two primary files:
1.  **`timeline.log`**: A single, continuously-appended text stream of every python-level event (Orchestrator, UI, System) interleaved chronologically. Includes raw crash tracebacks.
2.  **`report.json`**: A machine-readable JSON summary of the session results (pass/fail, duration, error strings). Generated at session termination.

### Requirement C: Status-Prefixed Scenario Isolation
Scenario artifacts are isolated into subfolders located directly in the session root.
*   **Initial Path**: `logs/{domain}/{run_id}/{Domain}__{ScenarioName}/`
*   **Final Path**: Upon scenario completion, the folder is renamed to `{STATUS}__{Domain}__{ScenarioName}/` (e.g., `PASSED__` or `FAILED__`).
*   **Contents**: Screenshots (`.jpg`), Heavy Inference Traces (`.json`).
*   **Process Logs**: External service logs (`svc_*.log`) remain in the session root as they span across multiple scenarios.

## 3. IMPLEMENTATION PHASES

### Phase 1: Overhaul the Session Bootstrapper
*   **Target**: `utils/infra/session.py`
*   **Action**: Modify `init_session(domain: str)` to support the `prod`/`test_ui`/`test_be` paths.
*   **Action**: Consolidate all sinks into a single `timeline.log` file sink.

### Phase 2: Refactor the Entry Points
*   **Target**: `jarvis_client.py`, `tests/client/runner.py`, `tests/backend/runner.py`.
*   **Action**: Standardize on the new `init_session` domain parameters.

### Phase 3: Implement Artifact Routing & Renaming
*   **Target**: `ClientTestRunner` (Client) and `PipelineTestRunner` (Backend).
*   **Action**: Dynamically create and rename `{Status}__{Domain}__{Scenario}` subfolders.

### Phase 4: Sync Dashboard & Documentation
*   **Target**: `RichDashboard` and all `.md` files in `docs/`.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Decision: Renaming Folders at Runtime**
    *   *Tradeoff*: Renaming a folder while files might be open can be risky.
    *   *Resolution*: Ensure all file handles (JSON writers, Image savers) are strictly closed/flushed before the `os.rename` call at the end of each scenario.
*   **Decision: Flat Folders vs `scenarios/` wrapper**
    *   *Resolution*: Prefixing with `{Status}__` and `{Domain}__` ensures that when sorted by name, all Failed tests appear together at the top of the directory, and all Passed tests appear together below them. This is more useful than a generic `scenarios/` folder.
