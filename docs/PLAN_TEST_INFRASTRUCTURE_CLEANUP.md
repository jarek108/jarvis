# Action Plan: Test Infrastructure Unification & Cleanup

## Desired Goal
To finalize the transition to a purely Pipeline-Driven testing architecture. This involves purging all legacy component-test artifacts, flattening the directory structure, ensuring rigorous VRAM interference tracking, and making the reporting engine dynamically adapt to any pipeline topology without hardcoded logic.

---

## Phase 1: Physical Consolidation (The Purge)
**Objective**: Eliminate technical debt and organize assets logically for cross-pipeline reuse.

*   **Step 1.1: Data Centralization**
    *   Create a unified `tests/data/` directory.
    *   Move all physical test assets (audio files like `.wav`, media like `.mp4`, `.png`) from nested legacy folders (`tests/stt/whisper/input_data`, `tests/vlm/input_data`) into the new `data/` folder.
*   **Step 1.2: Scenario Relocation**
    *   Create a unified `tests/scenarios/` directory.
    *   Move `tests/integration/scenarios.yaml` to `tests/scenarios/core.yaml`.
    *   Update all internal file paths in `core.yaml` to point to `tests/data/`.
*   **Step 1.3: The Grand Purge**
    *   Delete obsolete domain directories: `tests/stt`, `tests/tts`, `tests/llm`, `tests/vlm`, `tests/sts`.
    *   Delete the obsolete `tests/integration` folder.
    *   Rename `tests/runner_pipeline.py` to `tests/runner.py`.

---

## Phase 2: Engine-Agnostic VRAM Physics
**Objective**: Replace brittle Ollama API checks with a robust, system-level VRAM tracking strategy to detect interference and RAM swaps.

*   **Step 2.1: The 3-Point Measurement Strategy**
    *   Modify `run_test_lifecycle` and `runner.py` to capture three distinct VRAM states:
        1.  `vram_background`: Total GPU VRAM usage *before* any models are loaded (detects OS/App interference).
        2.  `vram_static`: Total GPU VRAM usage *after* models are loaded but *before* inference begins.
        3.  `vram_peak`: The maximum VRAM usage sampled during active scenario execution.
*   **Step 2.2: Reporting Injection**
    *   Ensure all three metrics are saved into the JSON artifact for every scenario run.

---

## Phase 3: Node-Driven Dynamic Reporting
**Objective**: Ensure the generated Excel reports accurately reflect the topology of the pipeline being tested without relying on hardcoded name matching.

*   **Step 3.1: Metric Flattening in Runner**
    *   Update `runner.py` to store metrics strictly by `node_id`. Instead of flattening `proc_stt` into global `stt_inf` keys, keep a nested dictionary:
        ```json
        "node_metrics": {
            "proc_stt": {"rtf": 0.5, "similarity": 0.9},
            "proc_llm": {"ttft": 1.2, "tps": 40.0}
        }
        ```
*   **Step 3.2: Dynamic Excel Columns**
    *   Refactor `tests/generate_report.py`.
    *   Instead of guessing based on the domain string (e.g., `if "TTS" in domain:`), the script will iterate through the `node_metrics` dictionary of the first scenario in the JSON.
    *   It will dynamically generate columns like `proc_stt (RTF)`, `proc_llm (TPS)`, ensuring 100% adaptability to future pipelines like `video_sentry`.
