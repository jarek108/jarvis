# Plan: Test Structure Simplification & Plan-Driven Execution

## 1. VISION
The current testing architecture allows for ambiguous entry points (running both Plans and Scenarios directly) and inconsistent filtering logic (`-s` flag). This creates technical debt and corrupts the integrity of session reports.

This plan enforces a **Strict Plan-Driven** architecture. Both the Backend and Client runners will be refactored to only accept Plan YAMLs as input. Arbitrary string filtering will be removed in favor of explicit, version-controlled Plan definitions, ensuring that the "Session Report" always matches the intent of the manifest.

## 2. ARCHITECTURAL REQUIREMENTS
*   **Strict Entry**: Runners must only accept YAML files containing a valid Plan schema (`execution` for backend, `scenarios` for client).
*   **Unified Resolution**: Scenario loading from `scenario_sources` must be centralized into a shared utility to ensure consistency across domains.
*   **Zero Ambiguity**: Removal of the `--scenario (-s)` flag to prevent non-deterministic suite execution.
*   **Simplified Runners**: Removal of complex parsing and filtering logic from `main()`, delegating these tasks to the Runner classes and shared utilities.

## 3. IMPLEMENTATION PHASES

### Phase 1: Centralized Scenario Loader
*   **Action**: Create `tests/test_utils/scenarios.py`.
*   **Action**: Implement `load_scenarios_from_sources(project_root, domain, sources)` which resolves and merges YAML files from the respective domain's `scenarios/` directory.

### Phase 2: Backend Runner Refactor
*   **Action**: Remove the `--scenario` and `-s` flags from `argparse`.
*   **Action**: Remove the `if "timeline" in data` fallback logic.
*   **Action**: Update `PipelineTestRunner` to use the new shared scenario loader.
*   **Action**: Clean up `main()` to focus strictly on session initialization and runner instantiation.

### Phase 3: Client Runner Refactor
*   **Action**: Remove the `--scenario` and `-s` flags from `argparse`.
*   **Action**: Standardize the Client Plan schema to be consistent with the Backend where possible (e.g., using `execution` blocks if applicable, or keeping it distinct but plan-only).
*   **Action**: Update `ClientTestRunner` to use the new shared scenario loader.
*   **Action**: Clean up `main()` to remove the complex scenario resolution tuples.

### Phase 4: Documentation & Standards Update
*   **Action**: Update `GEMINI.MD` and `CONCEPT_TESTING_PYRAMID.md` to reflect that Plans are the only way to run tests.
*   **Action**: Remove any examples in tutorials that show running a scenario file directly.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Decision: Removal of `-s` Filtering**
    *   *Choice*: Developers must now create a temporary `plans/dev.yaml` if they want to run a single scenario.
    *   *Tradeoff*: Slightly more friction for "one-off" tests, but total certainty that test results are reproducible and correctly mapped to a manifest.
*   **Decision: Plan Schema Convergence**
    *   *Choice*: We will keep the Client Plan schema (`scenarios: []`) separate from the Backend (`execution: []`) for now to avoid over-engineering a unified schema that doesn't fit both domains perfectly.
