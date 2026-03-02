# Jarvis Architectural Roadmap: The "Strategy" Model

This document outlines the migration to a dynamic, graph-based pipeline architecture with explicit state management.

## Phase 1: Standardization & State (Loadout 2.0)
*   [ ] **Redefine Loadout Schema**: Convert `loadouts/*.yaml` to a flat list of `services` with explicit `params`. Remove role keys (`stt`, `llm`).
*   [ ] **Refactor `manage_loadout.py`**: Implement `runtime_registry.json` generation. The manager becomes the "Writer" of system state.
*   [ ] **Update Test Runners**: Ensure test plans align with the new schema.

## Phase 2: Capability Registry (The Knowledge Base)
*   [ ] **Extend Calibration Schema**: Add `capabilities: [text_in, audio_out, vision, ...]` to `model_calibrations/*.yaml`.
*   [ ] **Static Calibrations**: Generate calibration files for STT (Whisper) and TTS (Chatterbox) engines to standardize them as "Models."
*   [ ] **Auto-Detection**: Update `calibrate_models.py` to infer capabilities from logs where possible.

## Phase 3: The Pipeline Engine (The Logic)
*   [ ] **Create `mappings/`**: Define Strategy YAMLs mapping abstract nodes to candidate model lists.
*   [ ] **Implement `PipelineResolver`**: The logic core that binds `Pipeline + Mapping + Registry + Calibration` into an executable graph.
*   [ ] **Refactor Orchestrator**: Replace hardcoded loops with graph traversal.

## Phase 4: Documentation & Polish
*   [ ] Update Architecture concepts.
*   [ ] Create Pipeline reference guides.
*   [ ] Deprecate legacy config maps.
