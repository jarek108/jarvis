# Plan: Client Testing Infrastructure Refactor (Phase 2)

## 1. VISION
The goal of this refactor is to transform the "Fast-Boot" prototype into a robust, professional-grade testing infrastructure. By decoupling the test harness from the production entry point, standardizing Inter-Process Communication (IPC), and modularizing the monolith runner, we will achieve a 10x reduction in test overhead without compromising the integrity of the production codebase or the reliability of the tests on Windows.

## 2. ARCHITECTURAL REQUIREMENTS
*   **Production Purity**: `jarvis_client.py` must contain zero lines of test-specific orchestration logic.
*   **Isolated Harness**: UI testing logic must reside in `tests/client/harness.py`, which imports `JarvisApp` as a library.
*   **Robust IPC**: Replace brittle "Ready Files" and `stdin` JSON injection with a lightweight Local TCP Socket protocol for Runner <-> Worker communication.
*   **Modular Runner**: `runner.py` must be split into functional domains: Orchestration, Process Management, and UI Reporting (Dashboard).
*   **Unified Mocking**: A centralized `MockContext` utility to ensure consistency between the Daemon, the Client, and the Orchestrator.

## 3. IMPLEMENTATION PHASES

### Phase 1: Entry Point Extraction
1.  Create `tests/client/harness.py`: Move all `args.scenario` processing and `run_internal_step` logic from `jarvis_client.py` to this file.
2.  Refactor `jarvis_client.py`: Revert to a clean, production-only entry point.
3.  Update `UIWorker`: Change the spawn command to use `tests/client/harness.py` instead of `jarvis_client.py`.

### Phase 2: Socket-Based IPC Standard
1.  Implement `TestCommandListener`: A lightweight thread in the test harness that opens a local random port and listens for a "GO" JSON packet.
2.  Update `UIWorker`:
    *   Stop polling for `worker_X.ready` files.
    *   Capture the port assigned to the worker from its `stdout`.
    *   Transmit the scenario configuration via TCP instead of `stdin`.
3.  Benefit: Eliminates Windows pipe buffering issues and file-system race conditions.

### Phase 3: Orchestrator Modularization
1.  Extract `tests/infra/process_manager.py`: Responsible for Daemon lifecycle, `UIWorkerPool` management, and ensuring no zombie processes survive a crash.
2.  Extract `tests/infra/dashboard_manager.py`: Encapsulate all `Rich` dashboard logic and metrics collection.
3.  Refactor `runner.py`: Focus exclusively on test plan resolution and scenario execution logic.

### Phase 4: Unified Mock Context
1.  Create `utils/test_utils/mock_context.py`: A context manager that handles:
    *   Setting all `JARVIS_MOCK_*` environment variables.
    *   Initializing the `_mock_state_tracker` for health checks.
    *   Redirecting logs to the appropriate session sub-folder.
2.  Apply this context manager across `runner.py`, `jarvis_daemon.py`, and `harness.py`.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **TCP Sockets vs. Named Pipes**: While Named Pipes are more "native" for IPC, TCP sockets on `127.0.0.1` are more portable across Python versions and operating systems (Win/Linux) and easier to debug with standard tools.
    *   *Tradeoff*: Requires managing port collisions, though using port `0` (OS-assigned) mitigates this.
*   **Pool Sizing vs. Resource Consumption**: Pre-warming 2+ UI workers consumes significant RAM (~200MB+ per worker).
    *   *Decision*: Maintain a default pool size of 1, but allow scaling via `--pool-size` for high-core count CI environments.
*   **Test Fidelity vs. Mocking**: The further we move into "Fast-Boot" territory (state injection, pre-warmed imports), the less we are testing the actual "Cold Boot" performance.
    *   *Mitigation*: Retain a `smoke_test` suite that disables all pre-warming and mocking to verify real-world startup latency once per release.
