# Plan: E2E Testing for Modular Pipeline

> **Objective**: Verify the behavioral integrity of the modular interaction pipeline, transport layer, and session persistence using a unified runner.

## 1. Testing Strategy: Two-Layer QA

We distinguish between testing the *ingredients* (Component QA) and the *cake* (System QA).

### A. Component QA (Legacy Runner)
*   **Tool**: `tests/runner.py`
*   **Scope**: Individual Models (STT, TTS, LLM).
*   **Goal**: Ensure models load and infer correctly via HTTP APIs.
*   **Status**: Existing and stable.

### B. System QA (Modular Runner)
*   **Tool**: `tests/runner_modular_e2e.py`
*   **Scope**: Orchestrator, Session Manager, Transport.
*   **Goal**: Ensure the application logic (State Machine, Hot-Swap, Event Routing) works as a cohesive unit.

---

## 2. The Unified Runner (`tests/runner_modular_e2e.py`)

This script supports two modes controlled by CLI flags:

### 2.1. Plumbing Mode (`--plumbing`)
*   **Backend**: Spawns `backend/main.py --stub`.
*   **Models**: Uses `StubAdapter` (instant text/audio).
*   **Use Case**: CI/CD, rapid logic iteration. Verifies that JSON messages route correctly and sessions persist.

### 2.2. Full Mode (Default)
*   **Backend**: Spawns `backend/main.py` (real models).
*   **Models**: Uses `STTAdapter`, `TTSAdapter`, `LLMAdapter` connected to real services/hardware.
*   **Use Case**: Final hardware verification. Verifies VRAM arbitration and real-time latency.

---

## 3. Test Scenarios

These scenarios run identically in both modes (only the latency and content differ).

### 3.1. Basic Text Interaction
*   **Mode**: `text`
*   **Goal**: Verify JSON message routing and LLM adapter integration.
*   **Verification**: Client sends `type: message`, receives `type: log` with role `assistant`.

### 3.2. Pipeline Hot-Swapping
*   **Flow**: `IDLE -> text (LLM only) -> sts (STT+LLM+TTS)`
*   **Goal**: Verify `ResourceManager` correctly triggers swaps and emits status events.
*   **Verification**: Client receives multiple `type: status` events (LOADING -> READY).

### 3.3. Session Persistence
*   **Flow**: Connect Session A -> Send "Turn 1" -> Disconnect -> Reconnect Session A -> Send "Turn 2".
*   **Goal**: Ensure `SessionManager` correctly recovers history from disk.
*   **Verification**: Final LLM prompt contains context from "Turn 1".

### 3.4. Binary Stream Integrity
*   **Mode**: `sts`
*   **Goal**: Verify raw PCM chunks reaching the orchestrator.
*   **Verification**: Client streams binary data, receives `type: status` (THINKING) once buffer threshold met.
