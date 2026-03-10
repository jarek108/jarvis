# Feature Plan: Daemon Orchestration Refactor & DRY Consolidation

## 1. VISION
The recent stability updates successfully implemented a **State-Aware Mutex**, but at the cost of significant code duplication and "shadow" fallback logic. This plan aims to consolidate the coordination logic (`wait_for_daemon_ready`) into a single, shared utility and establish the Daemon as the **Sole Source of Truth** for model management. This will reduce technical debt, ensure consistent polling behavior across all test suites, and simplify future maintenance.

## 2. ARCHITECTURAL REQUIREMENTS

### Core Constraints
*   **Zero Functional Regressions:** The non-blocking, Mutex-guarded behavior of the Daemon must remain identical.
*   **DRY (Don't Repeat Yourself):** All `requests.get("/status")` polling loops must be centralized.
*   **Config-Driven:** Polling intervals and timeouts must be sourced from `system_config/config.yaml` rather than being hardcoded.
*   **Single Authority:** The UI Controller must delegate 100% of lifecycle management to the Daemon to prevent "Dual Authority" process conflicts.

### Data Contracts
*   **New Utility:** `utils.infra.daemon.wait_for_ready(timeout, require_models)`
*   **Registry Update:** `runtime_registry.json` will now optionally mirror the Daemon's `active_task` state for "offline" inspection.

## 3. IMPLEMENTATION PHASES

### Phase 1: Shared Infrastructure (`utils/infra/daemon.py`)
*   **Objective:** Create a unified synchronization library used by both production and testing code.
*   **Tasks:**
    *   Extract the `wait_for_daemon_ready` logic into a new module: `utils/infra/daemon.py`.
    *   Support both `async` (for UI/Runners) and `sync` (for legacy backend scripts) versions of the waiter.
    *   Standardize the `timeout` and `polling_interval` based on the central `config.yaml`.

### Phase 2: Runner Refactoring
*   **Objective:** Replace duplicated local methods with the new shared utility.
*   **Tasks:**
    *   Update `tests/client/runner.py`: Remove local `wait_for_daemon_ready` and import from `utils.infra.daemon`.
    *   Update `tests/backend/runner.py`: Remove local `wait_for_daemon_ready` and import from `utils.infra.daemon`.
    *   Align error handling: Ensure both runners log `409 Conflict` and "Timeout" errors with the same verbosity.

### Phase 3: UI Controller Simplification (`ui/controller.py`)
*   **Objective:** Remove "Shadow" local execution paths.
*   **Tasks:**
    *   Remove the `except` blocks in `trigger_loadout_change` that fall back to local `apply_loadout`.
    *   If the Daemon is unreachable, the Controller should set a "DAEMON_OFFLINE" state rather than attempting to manage processes itself.
    *   This enforces the Daemon as the **exclusive** manager of the model lifecycle.

### Phase 4: Registry Mirroring (Hardening)
*   **Objective:** Make the `runtime_registry.json` more informative for debugging.
*   **Tasks:**
    *   Update `jarvis_daemon.py` to pass the `active_task` string to `save_runtime_registry`.
    *   This allows the `StatusDumper` to report why a system is busy even if the HTTP API is lagging.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Removing Local Fallback in UI:**
    *   *Decision:* We are removing the "Local Fallback" entirely.
    *   *Tradeoff:* If the Daemon crashes, the user cannot start models from the UI until they manually restart the Daemon.
    *   *Benefit:* Prevents the "Dual Manager" bug where the UI and Daemon both try to spawn/kill the same ports, which historically caused the most severe zombie process issues on Windows.

*   **Shared Utility Location:**
    *   *Decision:* Putting the utility in `utils/infra/` rather than `tests/`.
    *   *Benefit:* Allows the production UI to use the same "Wait for Stability" logic if we want to add a "Loading..." progress bar to the real application.

*   **Sync vs Async Waiter:**
    *   *Decision:* Providing both `wait_for_ready` and `wait_for_ready_async`.
    *   *Impact:* Minimal code bloat in exchange for maximum compatibility across the codebase.
