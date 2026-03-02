# Plan: Project Structure Cleanup & Consolidation

This document outlines the strategy to de-clutter the Jarvis root directory, encapsulate WIP features, and resolve the architectural fragility of hardcoded buffer paths.

## 1. Session-Scoped Buffers (Traceability)
**Problem**: The global `buffers/` directory is hardcoded in YAML files, causing race conditions and making it impossible to trace the artifacts (audio/text) of a specific historical run.

**Action**:
*   **Refactor `utils/pipeline.py`**: Update the `PipelineExecutor` to accept an optional `session_dir`. If provided, all relative `buffer` paths in the YAML will be resolved against this directory.
*   **Update YAMLs**: Strip the `buffers/` prefix from all pipeline definitions (e.g., `buffer: "user_voice.wav"`).
*   **Infrastructure Update**: Update `tests/runner.py` and `manage_loadout.py` to pass the active session directory to the executor.
*   **Cleanup**: Delete the global `buffers/` folder. Artifacts will now be automatically pruned by the Log Retention Policy (7 days).

## 2. Gemini Integration (WIP Isolation)
**Problem**: Gemini CLI integration logic and logs are scattered in the root.

**Action**:
*   Create `utils/gemini/`.
*   Move `gemini.exp`, `gemini_session.log`, and `gemini_session_log*` directories into this new folder.

## 3. Root De-cluttering & State Management
**Problem**: The root directory contains transient state files and orphaned debug artifacts.

**Action**:
*   **State Files**: Move `checkpoint-client.json` and `checkpoint-jarvis.json` into a new `.cache/` directory. Add `.cache/` to `.gitignore`.
*   **Prompts**: Move the `prompts/` directory to `pipelines/prompts/` to keep logic and data adjacent.
*   **Documentation**: Move `PLANS.md` into `docs/`.
*   **Orphan Purge**: Delete `query`, `MANUAL_UPLOAD_TEST.txt`, `run.log`, and the entire `research/` directory.

## 4. Verification
*   Run `python tests/runner.py tests/plans/ALL_fast.yaml --plumbing` to ensure the new buffer resolution logic works.
*   Verify that `logs/sessions/RUN_.../` now contains the generated `.wav` and `.tmp` files after a run.
