# Feature Plan: Testing Architecture & Documentation Stabilization

## 1. VISION
The recent unification of the pipeline engine and consolidation of test plans vastly improved the system's robustness, but it left behind a wake of broken documentation pointers and legacy "zombie" test files. 

This initiative will resolve these discrepancies, eradicate dead code (`client_test.py`), and formally document the new "Testing Pyramid" within the Diátaxis framework. This will ensure new developers have a frictionless onboarding experience and clearly understand the depth and flexibility of the Jarvis testing suite.

## 2. ARCHITECTURAL REQUIREMENTS
*   **Documentation Integrity**: All shell commands in `README.md`, `TUTORIAL_*.md`, and `GEMINI.MD` must execute successfully against the current `main` branch.
*   **Single Source of Truth**: The testing methodologies (Mocking vs. Virtualizing) must be centralized in a conceptual document to avoid confusing users with disparate CLI flags.
*   **Dead Code Elimination**: Code that does not align with the current `PipelineExecutor` or `asyncio.Queue` architecture must be aggressively pruned to prevent architectural confusion for future contributors.

## 3. IMPLEMENTATION PHASES

### Phase 1: Eradicate Technical Debt
*   **Task**: Delete `tests/client_test.py`. It is a relic of an abandoned WebSocket architecture that conflicts with the current in-process reactive flow engine.

### Phase 2: Mend Broken Pointers (The "First Impression" Fix)
*   **Task**: Update the "Refactor Guard" command in `GEMINI.MD` to use the new standardized plan:
    *   *Old*: `python tests/runner.py tests/plans/ALL_fast.yaml --mock-all`
    *   *New*: `python tests/runner.py tests/plans/integration_fast.yaml --mock-all`
*   **Task**: Update the "Verification" section in `docs/TUTORIAL_QUICKSTART.md` to reflect the same change.
*   **Task**: Update `docs/HOWTO_BENCHMARK.md` and `docs/HOWTO_TROUBLESHOOTING.md` to point to `integration_fast.yaml`.
*   **Task**: Scan `README.md` (if applicable) for any lingering references to `ALL_fast.yaml`.

### Phase 3: Formalize the Testing Pyramid
*   **Task**: Create `docs/CONCEPT_TESTING_PYRAMID.md`. This document will map the new consolidated plans to their intended operational mode, explicitly highlighting the "Hard Crash" philosophy for missing hardware:
    1.  **Fast Infra Check** (`integration_fast.yaml --mock-all`): Tests pure pipeline logic and compilation, using zero-VRAM stubs and no hardware drivers.
    2.  **Fast Deployment Check** (`integration_fast.yaml`): Verifies production pipelines against a single set of real models and virtualized hardware. Fails loudly if virtual audio cables or VRAM are missing.
    3.  **Comprehensive Hardware/Load Audit** (`integration_exhaustive.yaml`): The "I can wait but want to be sure" test. Verifies all model variants and edge cases under heavy load setups. Fails loudly on missing capabilities.
    4.  **Component Tests** (`components_fast.yaml` / `components_exhaustive.yaml`): Primarily for developers verifying individual node logic in isolation.

### Phase 4: Consolidate Documentation (Clean up)
*   **Task**: Ensure `docs/HOWTO_HARDWARE_TESTING.md` links gracefully to the new `CONCEPT_TESTING_PYRAMID.md` to keep the "How-To" strictly procedural and the "Concept" strictly theoretical, adhering to Diátaxis.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Decision: Deleting `client_test.py` vs. Upgrading it.**
    *   *Choice*: Deletion.
    *   *Consequence*: We formally embrace that the Jarvis UI and Pipeline Engine are currently coupled in-process (via `ui/controller.py`). A formal remote client testing strategy will be revisited later if distributed architecture is pursued.
*   **Decision: The "Hard Crash" Philosophy for E2E Tests**
    *   *Choice*: Tests running without `--mock-edge` will fail loudly if the physical or virtual hardware (e.g., VB-Audio Cable) is not configured correctly.
    *   *Consequence*: No silent fallbacks to mocks. E2E tests are explicitly designed to test hardware capability; hiding a lack of capability defeats their purpose. Users must configure their environment to pass the Deployment Check.
