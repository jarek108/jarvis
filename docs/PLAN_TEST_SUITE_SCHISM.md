# Feature Plan: Test Suite Architectural Schism

## 1. VISION
The Jarvis testing infrastructure has outgrown a single, flat directory. The introduction of Client (UI) testing—driven by a chronological Puppet Master loop—has highlighted a fundamental incompatibility with the reactive, turn-based Backend pipeline tests. 

This plan envisions a clean "Schism" of the `tests/` directory into two distinct, physically separated domains: `tests/backend/` and `tests/client/`. This separation will eliminate namespace crowding, prevent accidental schema mixing, and enforce strict boundaries between UI automation and engine verification, resulting in a cleaner, more intuitive developer experience.

## 2. ARCHITECTURAL REQUIREMENTS
*   **Physical Separation**: Runners, Plans, and Scenarios must be fully isolated into their respective `client` and `backend` directories.
*   **Plan-Driven Resolution**: Runners must dynamically load scenarios based on explicit declarations within the Plan YAMLs, eliminating all hardcoded `os.path.join(..., "core.yaml")` assumptions.
*   **Shared Utilities**: Core testing utilities (like `init_session`, `RichDashboard`, and log management) must remain in a shared `tests/test_utils/` directory accessible by both runners.
*   **Documentation Integrity**: All Diátaxis documentation, `GEMINI.MD` mandates, and `README.md` pointers must be updated to reflect the new path structures.

## 3. IMPLEMENTATION PHASES

### Phase 1: Directory Restructuring (The Schism)
*   **Action**: Create `tests/backend/` and `tests/client/` directories.
*   **Action**: Create `plans/` and `scenarios/` subdirectories within both.
*   **Action**: Move `tests/runner.py` to `tests/backend/runner.py`.
*   **Action**: Move `tests/client_runner.py` to `tests/client/runner.py`.
*   **Action**: Distribute existing Plans and Scenarios:
    *   *Backend*: `integration_fast.yaml`, `components_fast.yaml`, `core.yaml`, etc.
    *   *Client*: `client_fast.yaml`, `client_ui.yaml`.

### Phase 2: Plan-Driven Scenario Resolution
*   **Action**: Update Backend Plan YAMLs to include a `scenario_sources` array (e.g., `[core.yaml, visual.yaml]`).
*   **Action**: Refactor `tests/backend/runner.py` to parse `scenario_sources` and dynamically load the required YAML files, removing the hardcoded lookup of `core.yaml`.
*   **Action**: Apply the identical `scenario_sources` logic to `tests/client/runner.py` and `client_fast.yaml`.

### Phase 3: Path Re-wiring & Utility Sharing
*   **Action**: Update import paths in both runners to ensure they correctly resolve the shared `tests/test_utils/` directory despite moving one level deeper in the tree.
*   **Action**: Verify that session directories are still correctly generated in the root `logs/test_ui/ or logs/test_be/` folder.

### Phase 4: Documentation Synchronization
*   **Action**: Update `GEMINI.MD` Refactor and Client Guards.
*   **Action**: Update `docs/CONCEPT_TESTING_PYRAMID.md` to explain the structural split.
*   **Action**: Update all testing commands in `TUTORIAL_*.md` and `HOWTO_*.md` files.

---

## 4. KEY DECISIONS & SYMMETRY

### 1. Shared Data
*   **Decision**: The `tests/data/` folder will remain global.
*   **Rationale**: Data sharing is safe. Both UI and Backend tests may realistically need to reference the exact same sample audio or visual assets, making duplication unnecessary.

### 2. CLI Flag Symmetry
*   **Decision**: Both `tests/client/runner.py` and `tests/backend/runner.py` must support the exact same suite of control flags.
    *   **Mocking**: Both will fully support `--mock-all`, `--mock-models`, and `--mock-edge`. The client runner will translate these into the appropriate environment variables (`JARVIS_MOCK_MODELS`, `JARVIS_MOCK_EDGE`) for the underlying `JarvisController` to consume.
    *   **Control**: The backend runner will adopt the client runner's `--fail-fast` and `--scenario (-s)` filtering flags to ensure developers have identical workflows regardless of the testing domain.
