# Analysis: Startup Latency & UI Freezing (Plumbing Mode)

This document breaks down the technical causes for the ~30s "getup" time and the non-responsive UI observed during the initiation of the test runner, even when using `--plumbing` (stub) mode.

## 1. Breakdown of the 30-Second Wait

The "getup" time is the result of several sequential operations that block the execution flow before the first test scenario actually begins.

| Phase | Estimated Time | What is actually happening? |
| :--- | :--- | :--- |
| **Pre-Flight / Session Init** | 2–5s | **Hardware Detection:** Calls to `nvidia-smi` to gather GPU metadata and VRAM totals. Driver initialization and process execution for `nvidia-smi` can take seconds on Windows. |
| **Cleanup & Kill** | 3–5s | **Environment Purge:** Iterating through all 11 possible Jarvis ports to ensure a clean slate. Batch killing with `psutil` is faster than sequential, but `taskkill /T` on Windows involves slow process-tree traversal. |
| **Sequential Spawning** | 9–12s | **The "Wait-Start-Wait" Loop:** The `LifecycleManager` starts services one-by-one. It starts the STT stub, then **waits** for it to respond, then starts the TTS stub, then **waits**, etc. This prevents parallel resource utilization. |
| **Internal Orchestration** | 10–15s | **STS Redundancy:** The `sts_server.py` is designed to be an autonomous orchestrator. Even if stubs are already started by the runner, the STS server performs its own internal health checks and warmup cycles upon startup. |

## 2. The "Jumpy" / Frozen UI

**Cause: Main Thread Blocking**

The `RichDashboard` (UI) and the `reconcile` (Setup) logic currently share the **Main Thread**. 

- While `reconcile` is waiting for a port to open (using `time.sleep`), the CPU is effectively "captured" by that function. 
- The Dashboard's refresh cycle (which handles the progress bars, clocks, and live logs) cannot execute while the main thread is busy waiting for a network response.
- Once the setup finishes and the function returns, the dashboard "bursts" to life, catching up on all missed frames at once, which creates the "jumpy" appearance.

## 3. Identified Root Causes

1.  **Sequential Boot Logic:** Service A must be fully "ON" before Service B is even spawned.
2.  **Redundant Health Checks:** The runner checks for service readiness, and then the STS server checks for the same readiness immediately after.
3.  **Synchronous Setup:** The UI cannot update while the setup logic is performing network I/O or sleeping.
4.  **OS Latency:** Subprocess calls for `taskkill` and `nvidia-smi` have high overhead on Windows.

## 4. Proposed Strategy (Post-Analysis)

- **Parallel Spawning:** Launch all required sub-processes simultaneously and then perform a single parallel wait for all ports.
- **STS "Fast-Track" Flag:** Introduce a `--trust-deps` or `--fast` flag for `sts_server.py` to skip internal dependency checks when running in a managed test environment.
- **Background Setup:** Move the `reconcile` logic to a background worker thread so the Dashboard can maintain a 10Hz+ refresh rate regardless of network waits.

## 5. Implemented Fixes

1.  **Parallel Spawning:** Launching all required stubs simultaneously.
2.  **Fast Purge:** Single-pass process scanning for environment cleanup.
3.  **Config/Hardware Caching:** Eliminating redundant `nvidia-smi` and disk reads.
4.  **Live Init Measurement:** The Dashboard now starts *before* pre-flight checks and displays a "Booting / Pre-flight" task, making the initialization phase transparent and measurable.
5.  **Removed Mock Mode:** Unified on the fast Plumbing path for higher fidelity testing.
