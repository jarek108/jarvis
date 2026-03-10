# Feature Plan: Coordinated Client-Daemon Synchronization

## 1. VISION
Now that the Loadout Daemon enforces a **State-Aware Mutex**, the client layers (UI Controller and Test Runners) must be updated to follow this protocol. The goal is to eliminate "sabotage" race conditions where one scenario's setup tears down the previous scenario's models prematurely. This will result in 100% deterministic UI automation and a more responsive, error-aware user interface.

## 2. ARCHITECTURAL REQUIREMENTS

### Core Constraints
*   **Protocol Alignment:** Clients must treat HTTP `202 Accepted` as a successful delegation and handle `409 Conflict` by waiting/retrying.
*   **Settling Phase:** Runners must implement a mandatory "Wait for Stability" period after requesting a loadout but before starting the scenario timer.
*   **Idempotent Cleanup:** Per-scenario "hard deletes" must be replaced with session-level cleanup to allow "Smart Reuse" to function between test cases.

### Data Contracts (Client Perspective)
*   **Success Codes:** `[200, 202]` are valid responses for lifecycle requests.
*   **Readiness Check:** `GET /status` -> `ready: true` is the only valid signal to proceed with a new lifecycle command.
*   **Model Population:** The client must not consider a loadout "active" until the `models` list in the status response is populated (not empty).

## 3. IMPLEMENTATION PHASES

### Phase 1: UI Controller Protocol Sync (`ui/controller.py`)
*   **Objective:** Fix communication bugs and add Mutex awareness.
*   **Tasks:**
    *   Update `trigger_loadout_change` to accept `202` as a success code.
    *   Implement basic retry logic for `409 Conflict`.
    *   Ensure the controller updates its internal `health_state` as soon as the Daemon returns the "starting" models list.

### Phase 2: UI Test Runner Stabilization (`tests/client/runner.py`)
*   **Objective:** Eliminate the "Sabotage" loop and implement coordination.
*   **Tasks:**
    *   **Remove Per-Scenario Cleanup:** Delete any redundant `DELETE /loadout` calls within the scenario loops.
    *   **Implement `wait_for_daemon_ready()`:** A blocking helper that polls `/status` until `ready == True` AND `models` is not empty.
    *   **Coordinated Start:** Call `wait_for_daemon_ready()` immediately after the initial `DELETE` (Session Start) and after every `POST /loadout`.

### Phase 3: Pipeline (Backend) Runner Alignment (`tests/backend/runner.py`)
*   **Objective:** Ensure backend component tests benefit from the same stability.
*   **Tasks:**
    *   Update the `execution_wrapper` to implement a similar "Settling" check between loadout blocks.

### Phase 4: Verification & Performance Tuning
*   **Objective:** Prove stability and reduce total run time.
*   **Tasks:**
    *   Run `debug.yaml` with ultra-short timers (3s, 5s) to prove the desync is gone.
    *   Calibrate the polling interval in the runners (move from 1s to 200ms) to reduce "dead time" between tests.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Removal of Per-Scenario DELETE:**
    *   *Decision:* We are trading "Guaranteed Fresh Boot" for "Stability and Speed."
    *   *Mitigation:* The `soft=True` flag in the `POST` request still kills/restarts any model that reports as unhealthy.

*   **Blocking vs. Polling in Runners:**
    *   *Decision:* The Runner will block (poll internally) until the Daemon is ready. This ensures scenario timelines start from a stable base.
