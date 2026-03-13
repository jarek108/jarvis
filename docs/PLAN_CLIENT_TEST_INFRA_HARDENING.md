# Plan: Client Testing Infrastructure Hardening (Phase 3)

## 1. VISION
Transform the current "working but messy" test infrastructure into a strictly decoupled, professional-grade framework. By enforcing a **Zero-Tkinter Orchestrator** policy and centralizing automation logic, we will eliminate architectural circularity and maintenance debt. This phase moves us from "Fast-Boot" as a feature to "Fast-Boot" as the standard, immutable execution path.

## 2. ARCHITECTURAL REQUIREMENTS
*   **Import Isolation**: The Orchestrator (`runner.py`) must NOT import `JarvisApp` or `tkinter`. It should only manage processes and report results.
*   **Shared Automation Library**: All UI-interaction logic (`StatusDumper`, `AutomationController`, `VisualVerifier`) must reside in a standalone module accessible by both the Worker and (optionally) the Orchestrator.
*   **Single Execution Path**: Remove the "Original Path" (synchronous/local execution) from the runner to ensure 100% of tests are validated through the pre-warmed worker infrastructure.
*   **Deterministic Cleanup**: The `UIWorkerPool` must implement a synchronous `shutdown()` method that guarantees zero zombie processes on Windows, even during keyboard interrupts.

## 3. IMPLEMENTATION PHASES

### Phase 1: Automation Library Extraction
1.  **Create `tests/client/automation.py`**: Migrate `StatusDumper`, `VisualVerifier`, and `AutomationController` from `runner.py` to this new file.
2.  **Refactor `harness.py`**: Update imports to use `tests.client.automation`.
3.  **Refactor `runner.py`**: Remove the class definitions for these components.

### Phase 2: Orchestrator Slimming & "Zero-Tkinter"
1.  **Delete "Original Path"**: Remove the `if not self.args.no_prewarm` block logic in `runner.py`. Every scenario must now run via `worker.trigger_go()`.
2.  **Purge UI Imports**: Remove `from ui import JarvisApp` and any `tkinter` related code from `runner.py`. 
3.  **Result Aggregation**: Ensure the Worker (`harness.py`) writes its specific result (JSON) to the scenario folder so the Orchestrator can simply read the final status rather than tracking it via process exit codes alone.

### Phase 3: Infrastructure Formalization
1.  **Rename & Relocate**: Move `tests/test_utils/lifecycle.py` to `tests/infra/process_manager.py` to align with the Phase 3 architectural plan.
2.  **IPC Handshake Hardening**: Replace the "Log-Parsing" port discovery in `UIWorker` with a direct `stdout.readline()` handshake or a temporary "Port File" to reduce startup latency and parsing errors.

### Phase 4: Lifecycle & Pool Hardening
1.  **Refill Logic Refactor**: Replace the background refill thread in `UIWorkerPool` with a more robust async-aware mechanism or a capped semaphore to prevent "runaway spawning" on slow systems.
2.  **Global Shutdown Hook**: Implement a centralized `atexit` or Signal Handler that triggers `pool.shutdown()` to ensure the `UIWorker` log files are closed and processes are killed cleanly.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Total Removal of Synchronous Path**: 
    *   *Decision*: Delete it. 
    *   *Tradeoff*: We lose the ability to run a "one-off" test without the worker pool overhead, but we gain 100% consistency and eliminate the most significant source of code duplication.
*   **Location of Automation Logic**: 
    *   *Decision*: Keep it within `tests/client/` rather than `utils/`.
    *   *Reasoning*: These tools are specific to the UI testing domain and should not clutter the production utility tree.
*   **IPC: Sockets vs. Files for Results**: 
    *   *Decision*: Use Sockets for commands (Trigger GO) but use Files (JSON) for result reporting.
    *   *Tradeoff*: Sockets are great for "Pushing" commands to a waiting process, but Files are better for "Persisting" the history of a test run for post-mortem analysis.
