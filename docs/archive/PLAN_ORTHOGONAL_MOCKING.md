# Plan: Orthogonal Mocking & Virtual-Default Testing

## 1. Objective
Refactor the test runner's control logic to use orthogonal, component-based flags (`--mock-models` and `--mock-edge`) instead of scenario-based flags. Establish the **Virtualized Environment** (simulators) as the default state for all tests.

---

## 2. The New Realism Matrix

| Flag(s) | Models | Hardware Drivers | Environment |
| :--- | :--- | :--- | :--- |
| **(None)** | **REAL** | **PRODUCTION** | **VIRTUAL** (Simulators) |
| **`--mock-models`** | **STUB** | **PRODUCTION** | **VIRTUAL** (Simulators) |
| **`--mock-edge`** | **REAL** | **MOCKED** | **STATIC** (Files) |
| **`--physical`** | **REAL** | **PRODUCTION** | **REAL** (Human) |

### Definitions:
- **`--mock-models`**: Replaces LLM/STT/TTS servers with zero-VRAM stubs.
- **`--mock-edge`**: Replaces hardware source/sink nodes (Mic, Speaker, Keyboard) with non-functional or file-based mocks.
- **`--physical`**: Disables the `E2EOrchestrator` (simulators), forcing the runner to wait for real physical triggers.

---

## 3. Implementation Phases

### Phase 1: Runner Refactor (`tests/runner.py`)
- Update `argparse` to remove `--plumbing` and `--e2e`, adding `--mock-models`, `--mock-edge`, and `--physical`.
- Implement a `Default Compatibility` layer where `--plumbing` still works as an alias for `--mock-models --mock-edge`.
- Modify `run_scenario` to:
    1.  Enable virtualization by default unless `--physical` is set.
    2.  Automatically populate `overrides` with mock implementations if `--mock-edge` is set.

### Phase 2: Edge Mock Definition
- Update `tests/test_utils/mocks.py` to provide standard mocks for all hardware roles:
    - `MicMock`: returns path from scenario inputs.
    - `SpeakerMock`: does nothing (no-op).
    - `KeyboardMock`: no-op.

### Phase 3: Documentation Sync
- Update `REFERENCE_ENGINE.md` with the new CLI schema.
- Update `HOWTO_HARDWARE_TESTING.md` to reflect that virtualization is now the default.

---

## 4. Success Criteria
1. Running `python tests/runner.py [plan]` without flags automatically attempts to play virtual audio and synchronize signals.
2. Running with `--mock-edge` allows testing model logic using real model servers but static input files (no hardware drivers loaded).
3. The codebase remains free of `if testing:` branches.
