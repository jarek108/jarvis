# Plan: Client Testing Infrastructure Upgrade

## 1. VISION
The current client testing suite is functional but "stateless"—it overwrites visual artifacts, provides no summary of results, and cannot be easily filtered for targeted development. 

This upgrade will align Client Testing with Backend Testing standards by introducing **Session-Aware Storage**, **Tabulated Results**, and **CLI Scenario Filtering**.

## 2. ARCHITECTURAL REQUIREMENTS
*   **Artifact Preservation**: Every test run must have a unique, timestamped directory. No run should ever overwrite the results of another.
*   **Result Persistence**: Summary results must be saved as JSON and printed to the terminal in a high-signal table.
*   **Flexible Filtering**: Developers must be able to run a subset of scenarios from a large plan using pattern matching.
*   **Standardized Cleanup**: Automated log rotation to prevent `logs/test_ui/ or logs/test_be/` from consuming excessive disk space.

## 3. IMPLEMENTATION PHASES

### Phase 1: Session Management & Image Namespacing
*   **Action**: Integrate `init_session` from `test_utils` to create `logs/test_ui/ or logs/test_be/CLIENT_RUN_YYYYMMDD_HHMMSS/`.
*   **Action**: Update `VisualVerifier` to store screenshots in `[SESSION_DIR]/images/`.
*   **Action**: Automatically prefix image filenames with the `scenario_id` to prevent name collisions between scenarios.

### Phase 2: Result Accumulation & Terminal Summary
*   **Action**: Create a `TestResult` dataclass to track `id`, `status`, `duration`, and `error`.
*   **Action**: Implement a `print_summary()` function that renders a formatted table at the end of the run.
*   **Action**: Save the final results to `report.json` in the session directory.

### Phase 3: Targeted Execution & Fail-Fast
*   **Action**: Add `--scenario` (`-s`) CLI flag to support substring filtering of scenario IDs.
*   **Action**: Add `--fail-fast` flag to terminate the suite immediately upon the first failure.
*   **Action**: Add `--keep-alive` flag to skip the initial `kill_loadout("all")` for rapid iterative testing.

---

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Decision: Image Verification remains Manual**
    *   *Choice*: We will not implement automated pixel-diffing yet.
    *   *Tradeoff*: While automated diffing is the "Holy Grail," it is too brittle for the current high-velocity UI development. Session-based folders make manual review much easier.
*   **Decision: Reuse Backend Session Logic**
    *   *Choice*: We will use the same `init_session` utility as the backend runner.
    *   *Tradeoff*: This ensures consistency but results in a mix of `RUN_...` and `CLIENT_RUN_...` folders in the same log directory. This is acceptable as it keeps all artifacts under `logs/test_ui/ or logs/test_be/`.
