# Plan: Pipeline Testing Refactor & Consolidation

## 1. Objective
Eliminate pipeline duplication, remove hardcoded runner logic, and consolidate the fragmented test plan system into a structured hierarchy. Ensure that production pipelines are tested directly without specialized "test copies."

---

## 2. Implementation Phases

### Phase 1: Pipeline Deduplication (Testing Production)
- **Action**: Delete `hybrid_chat.yaml`, `multimodal_sentry.yaml`, and `voice_to_voice.yaml` from `tests/pipelines/`.
- **Action**: Update `tests/runner.py` and `PipelineResolver` to support a search path for pipelines:
    1.  Check `tests/pipelines/` (for component/atomic tests).
    2.  Check `system_config/pipelines/` (for production integration tests).

### Phase 2: Scenario Data Binding Refactor
- **Action**: Remove the `if pid == 'atomic_tts' ...` hardcoding in `tests/runner.py`.
- **Action**: Update `tests/scenarios/*.yaml` to allow explicit target node selection in the `send` block.
    - *Example*: `send: {node: "input_instruction", content: "Hello"}`
- **Action**: Update the runner to map these explicit keys directly into the `executor.run` input dictionary.

### Phase 3: Test Plan Consolidation
- **Action**: Delete the dozen fragmented `atomic_*_fast/exhaustive.yaml` files.
- **Action**: Standardize on four primary plans in `tests/plans/`:
    - `components_fast.yaml`: Component verification using zero-VRAM stubs.
    - `components_exhaustive.yaml`: All model variants in isolation.
    - `integration_fast.yaml`: Production pipelines using zero-VRAM stubs.
    - `integration_exhaustive.yaml`: Full-system E2E/Hardware verification.

### Phase 4: Expansion of Coverage
- **Action**: Create `tests/scenarios/visual.yaml` to specifically exercise VLM and ScreenCapture nodes.
- **Action**: Implement explicit verification for the `FileReader` node in a test scenario.

---

## 3. Success Criteria
1. No production pipelines are duplicated in the `tests/` directory.
2. `tests/runner.py` contains zero references to specific pipeline IDs (e.g., no `if pid == ...`).
3. Adding a new production pipeline automatically makes it available for testing without runner modifications.
