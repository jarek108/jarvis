# Plan: E2E Testing for Modular Pipeline

> **Objective**: Verify the behavioral integrity of the modular interaction pipeline, transport layer, and session persistence.

## 1. Test Scenarios

### 1.1. Basic Text Interaction
*   **Mode**: `text`
*   **Goal**: Verify JSON message routing and LLM adapter integration.
*   **Verification**: Client sends `type: message`, receives `type: log` with role `assistant`.

### 1.2. Pipeline Hot-Swapping
*   **Flow**: `IDLE -> text (LLM only) -> sts (STT+LLM+TTS)`
*   **Goal**: Verify `ResourceManager` correctly triggers swaps and emits status events.
*   **Verification**: Client receives multiple `type: status` events (LOADING -> READY).

### 1.3. Session Persistence
*   **Flow**: Connect Session A -> Send "Turn 1" -> Disconnect -> Reconnect Session A -> Send "Turn 2".
*   **Goal**: Ensure `SessionManager` correctly recovers history from disk.
*   **Verification**: Final LLM prompt contains context from "Turn 1".

### 1.4. Binary Stream Integrity (Plumbing Mode)
*   **Mode**: `sts`
*   **Goal**: Verify raw PCM chunks reaching the orchestrator.
*   **Verification**: Client streams binary data, receives `type: status` (THINKING) once buffer threshold met.

## 2. Infrastructure for Testing

To ensure tests are fast and deterministic, we will implement a **Stub Infrastructure**:

1.  **Stub Models**: Create a `StubAdapter` that returns immediate, canned responses (text and silence audio).
2.  **E2E Runner**: A script that:
    *   Spawns the `backend/main.py` process with a `--stub` flag.
    *   Runs a suite of WebSocket client tests.
    *   Kills the backend and reports results.

## 3. Implementation Steps
1.  **Stub Adapter**: Implement `backend/models/stub_adapter.py`.
2.  **Backend Integration**: Update `main.py` to allow overriding adapters with stubs.
3.  **Test Suite**: Implement `tests/test_modular_e2e.py` using `pytest-asyncio`.
