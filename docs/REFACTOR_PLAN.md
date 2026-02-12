# Jarvis Refactor Plan: Unified Testing & Lean Reporting

**Status:** Planned
**Date:** February 11, 2026

## 1. Goal: Reduce Redundancy & Optimize Structure
The current testing architecture has significant overlap between domain-specific scripts (STT, TTS, LLM, VLM, S2S). We will unify these into a single orchestration point while moving detailed data delivery from the terminal to the Excel artifacts.

## 2. Key Changes

### A. Unified Test Runner (`tests/runner.py`)
*   **Role:** Single entry point for all component and integration tests.
*   **Arguments:**
    *   `--domain`: Single string or comma-separated list (e.g., `stt`, `llm,vlm`). Defaults to ALL if omitted.
    *   `--loadout`: Target loadout name.
    *   `--purge`: Enable system sweep before/after.
    *   `--full`: Enable full environment parity.
    *   `--benchmark-mode`: Enable deterministic output.
    *   `--local`: Suppress GDrive upload.
*   **Logic:** Orchestrates the `LifecycleManager` and imports the scenario logic from domain modules.

### B. Lean Terminal Output
*   Terminal will only show high-level progress (e.g., `[PASS] Scenario Name`).
*   Detailed metrics (TTFT, TPS, VRAM, full text) will be exclusively stored in the JSON artifacts and the final Excel report.
*   Removes all ASCII tables from the console to reduce clutter and speed up execution.

### C. Standardized Artifact Generation
*   `tests/generate_report.py` will be the primary engine for artifact collection.
*   `tests/run_extensive_comparison.py` will be refactored to call `tests/runner.py` internally for each domain.

## 3. Prioritized Implementation Steps
1.  **Modularize Scenarios:** Ensure `test.py` files in each domain export a clean `run_suite(model_id)` function without CLI overhead.
2.  **Create `tests/runner.py`:** Implement the multi-domain logic and lifecycle wrapping.
3.  **Update Master Suites:** Refactor `run_extensive_comparison.py` and `run_health_check.py` to use the new runner.
4.  **Verification:** Execute a full comparison run and verify the multi-tab GDrive report.
