# Feature Plan: Daemon State-Aware Mutex & Request Serialization

## 1. VISION
The current Jarvis Daemon is vulnerable to "request storms," where rapid-fire `POST` (Apply) and `DELETE` (Kill) commands from the UI or Test Runner create overlapping background threads. This leads to race conditions, zombie processes, and system instability.

This feature implements a **State-Aware Mutex** within the Daemon. The Daemon will transition from a "Fire-and-Forget" model to a **"Strict Admission Control"** model. It will track its internal state (`IDLE`, `APPLYING`, `KILLING`) and reject conflicting requests with a `409 Conflict` error. This ensures that lifecycle operations are atomic and linear, even if the API endpoints themselves remain non-blocking.

## 2. ARCHITECTURAL REQUIREMENTS

### Core Constraints
*   **Non-Blocking:** API endpoints must return immediately (`202 Accepted` or `409 Conflict`). Long-running tasks must happen in the background.
*   **Single-Task Concurrency:** Only one "Heavy" operation (Apply or Kill) can be active at any given time.
*   **Truth in Reporting:** The `/status` endpoint must accurately reflect whether the Daemon is ready to accept new commands.

### Data Contracts

**Updated `GET /status` Response:**
```json
{
  "loadout_id": "Speech-to-Speech",
  "global_state": "READY",
  "ready": true,          // NEW: True if IDLE, False if BUSY
  "active_task": null,    // NEW: "APPLYING", "KILLING", or null
  "models": [...],
  "vram": {...}
}
```

**Daemon Reaction Matrix:**

| # | State (active_task) | Incoming Request | Params | Result | HTTP Code |
|---|---|---|---|---|---|
| 1 | **NONE** | `POST /loadout` | Any | **Accept** (Start Apply) | `202` |
| 2 | **NONE** | `DELETE /loadout` | Any | **Accept** (Start Kill) | `202` |
| 3 | **APPLYING** | `POST /loadout` | Any | **Reject** (Busy) | `409` |
| 4 | **APPLYING** | `DELETE /loadout` | `force=false` | **Reject** (Busy) | `409` |
| 5 | **APPLYING** | `DELETE /loadout` | `force=true` | **Accept** (Interrupt) | `202` |
| 6 | **KILLING** | `POST /loadout` | Any | **Reject** (Busy) | `409` |
| 7 | **KILLING** | `DELETE /loadout` | `force=false` | **Reject** (Busy) | `409` |
| 8 | **KILLING** | `DELETE /loadout` | `force=true` | **Accept** (Retry Kill) | `202` |

## 3. IMPLEMENTATION PHASES

### Phase 1: State Manager Upgrade
*   **Objective:** Enhance `StateManager` to track `active_task`.
*   **Tasks:**
    *   Add `self.active_task = None` (thread-safe variable).
    *   Add a context manager or helper method `begin_task(task_name)` that raises an exception if already busy.
    *   Ensure `active_task` is reset to `None` in a `finally` block after background execution.

### Phase 2: Endpoint Logic & Guards
*   **Objective:** Implement the "Admission Control" logic in `jarvis_daemon.py`.
*   **Tasks:**
    *   Update `POST /loadout`: Check `active_task`. If busy, return `409`. Else, set `active_task="APPLYING"` and launch task.
    *   Update `DELETE /loadout`: Check `active_task`. If busy and `force=False`, return `409`. If `force=True` or `IDLE`, set `active_task="KILLING"` and launch task.
    *   Update `GET /status`: Include `ready` (derived from `active_task is None`) and `active_task` in the output.

### Phase 3: Documentation & Verification
*   **Objective:** Update contracts and verify stability.
*   **Tasks:**
    *   Update `docs/REFERENCE_API.md` with the new status fields and error codes.
    *   Manually verify that sending two `POST` requests in rapid succession results in one `202` and one `409`.

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Reject (409) vs. Queue:**
    *   *Decision:* We chose to **Reject**.
    *   *Tradeoff:* Clients (UI/Tests) must implement their own retry loops or wait logic.
    *   *Benefit:* Prevents the Daemon from accumulating a hidden backlog of state-changing commands that could execute surprisingly minutes later. It makes the system behavior deterministic.

*   **Force Flag Implementation:**
    *   *Decision:* `force=True` allows interrupting a task.
    *   *Tradeoff:* Interruption is "dirty." We cannot easily stop a Python thread mid-execution. `force=True` will likely just start a *concurrent* kill thread (ignoring the lock) to clean up the mess.
    *   *Benefit:* Essential escape hatch for "stuck" processes (e.g., a hanging network call).

*   **Polling Frequency:**
    *   *Decision:* `GET /status` remains the primary coordination mechanism.
    *   *Consequence:* The UI responsiveness is tied to the client's polling rate (1s or 500ms). This is acceptable for a heavy process manager compared to the complexity of adding WebSockets.
