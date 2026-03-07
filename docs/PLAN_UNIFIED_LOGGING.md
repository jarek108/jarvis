# Architectural Plan: Unified Logging Strategy & Session Management

## 1. VISION
This plan establishes a professional-grade, unified logging architecture across the entire Jarvis ecosystem. By shifting from ad-hoc `print` statements and scattered logger configurations to a centralized "Session Director" model powered by `loguru`, we will ensure that every Backend Test, UI Test, and Production Client session generates a perfectly structured, deterministic artifact footprint. 

This strategy focuses on **High-Signal Telemetry**, **Crash Resilience**, and **Performance Profiling**, guaranteeing that critical state changes and fatal exceptions are permanently persisted to disk without suffocating the standard console output with repetitive noise.

## 2. ARCHITECTURAL REQUIREMENTS

### Requirement A: The Session Directory Standard
*   All runtime artifacts must reside within a single session-specific directory inside `logs/sessions/`.
*   Session directories must be strictly prefixed by the entry point that created them:
    *   `BE_YYYYMMDD_HHMMSS` for Backend Test Runner (`tests/backend/runner.py`)
    *   `UIT_YYYYMMDD_HHMMSS` for UI Test Runner (`tests/client/runner.py`)
    *   `APP_YYYYMMDD_HHMMSS` for Production Client (`jarvis_client.py`)
*   The `cleanup_old_logs()` function must respect these prefixes and maintain a configurable retention policy *per category* (defined in `system_config/config.yaml`, e.g., keep 10 `APP`, 20 `BE`).

### Requirement B: "File First, Console Filtered" Policy
*   **Disk Telemetry:** Everything (level `DEBUG` and above) must be written to disk files within the session directory.
*   **Console Output:** Must default to `INFO` level and above to remain clean and human-readable. A global `--debug` flag (or `JARVIS_DEBUG=1` env var) will lower the console threshold to `DEBUG`.
*   **No File Management in Components:** Child components (`JarvisApp`, `PipelineExecutor`, `JarvisController`) must **not** manage file paths or create their own sinks. They must simply emit logs via the global `logger`.

### Requirement C: Domain-Specific Log Routing (Filters)
The master log configuration must utilize `loguru.bind()` tags to automatically route specific event streams into dedicated files within the session directory.
*   `system.log`: The default catch-all for infrastructure, engine, and general events.
*   `ui.log`: Dedicated sink for high-signal frontend rendering and user interactions (`logger.bind(domain="UI")`).
*   `orchestrator.log`: Dedicated sink for automated test runner milestones (`logger.bind(domain="ORCHESTRATOR")`).
*   `svc_<name>.log`: Dedicated sink for stdout/stderr captured from isolated model subprocesses.

### Requirement D: Crash Resilience & Performance Profiling
*   **The Excepthook:** The logging initializer must bind `loguru` to Python's `sys.excepthook`. This guarantees that if the application encounters a fatal error, the full stack trace is intercepted and written to `system.log` before the process terminates.
*   **Polling Latency Tracking:** The backend `_status_polling_loop` must emit strict Start/End `DEBUG` markers. This will provide irrefutable timing data to diagnose blocking I/O (e.g., slow HTTP requests to booting models delaying VRAM telemetry).

## 3. IMPLEMENTATION PHASES

### Phase 1: Establish the Centralized Bootstrapper
1.  **Target:** `utils/infra/logs.py` (or a dedicated `utils/infra/session.py`)
2.  **Action:** Create `def init_logging(session_prefix: str) -> str:`
    *   Generates the timestamped directory.
    *   Calls `logger.remove()` to clear existing default sinks.
    *   Adds the console sink with a custom format (replacing `log_msg` formatting).
    *   Adds the file sinks (`system.log`, `ui.log`, `orchestrator.log`) using appropriate domain filters.
    *   Implements `sys.excepthook` override.
    *   Dumps `system_info.yaml` to ensure consistent environment tracking.
    *   Returns the `session_dir` path.

### Phase 2: Refactor the Entry Points
1.  **Target:** `tests/backend/runner.py`, `tests/client/runner.py`, `jarvis_client.py`
    *   **Action:** Call `init_logging("<PREFIX>")` at the very start of `main()`. Remove the legacy `init_session` calls. Ensure the returned `session_dir` is passed down to components that need it (like the visual screenshot tool).

### Phase 3: Instrument High-Signal UI Telemetry
1.  **Target:** `ui/app.py`
    *   **Action:** Eradicate raw `QUEUE_RECV` spam. Do not log the receipt of raw backend text intended for the UI terminal.
    *   **Action:** Implement **Smart Deduplication** in `update_health_ui`. Cache the previous `vram_str`. Emit a `logger.bind(domain="UI").info("VRAM_RENDER")` log *only* if the values physically changed.
    *   **Action:** Log discrete, actionable events (e.g., `[USER_ACTION] Loadout Changed`, `[SPINNER_STATE] Stopped`).

### Phase 4: Deprecate Legacy Wrappers & Add Profiling
1.  **Target:** `utils/infra/console.py` or wherever `log_msg` lives.
    *   **Action:** Delete the custom `log_msg` formatting wrapper. Transition the codebase to rely directly on standard `logger.info()` patterns.
2.  **Target:** `ui/controller.py` -> `_status_polling_loop`
    *   **Action:** Wrap the polling sequence in `logger.debug()` start and end markers, calculating and logging the exact `time.perf_counter()` duration of the loop to diagnose the +10s latency issue.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Decision 1: UI Double-Logging**
    *   *Tradeoff:* The UI currently prints raw backend logs (e.g., "Starting STT") to its visual terminal. If the UI also writes these to disk, they appear twice in the logs.
    *   *Resolution:* The UI will strictly only write *UI-native* events (clicks, layout changes, deduplicated renders) to `ui.log`. The backend will write its own events to `system.log`. The visual terminal remains a temporary display.
*   **Decision 2: Subprocess Logging (`svc_*.log`)**
    *   *Tradeoff:* Model engines currently run in separate processes. `loguru`'s global configuration does not automatically bridge process boundaries without complex IPC.
    *   *Resolution:* We will retain the existing strategy where the loadout manager redirects raw `stdout`/`stderr` of the model servers directly to `svc_<name>.log` files.
*   **Decision 3: Test Runner "Cheating"**
    *   *Tradeoff:* The test runner asserts states by reading the Python backend memory (`app.controller.health_state`) rather than doing OCR or hierarchy parsing on the Tkinter UI.
    *   *Resolution:* We accept this tradeoff. As a monolithic application, testing the logical state of the integrated controller is vastly faster, less brittle, and more reliable than pixel-matching. We use `mss` screenshots exclusively for layout regressions.