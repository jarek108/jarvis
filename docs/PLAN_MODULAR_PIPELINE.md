# Implementation Plan: Modular Interaction Pipeline

> **Objective**: Transform the Jarvis backend from a fixed STS script into a modular, event-driven Pipeline Engine capable of multimodal interaction.
> **Reference**: `docs/ARCHITECTURE_MODULAR_PIPELINE.md`

## 0. Migration & Compatibility Strategy

*   **Side-by-Side Build**: The new `backend/` will be developed alongside the existing `servers/` directory.
*   **Legacy Preservation**: `sts_server.py`, `stt_server.py`, and `tts_server.py` MUST remain operational to support the `tests/runner.py` suite. This test suite is our **Component QA** (ingredients).
*   **Code Reuse**: The new backend will import from `utils/` (config, infra, VRAM math) and wrapping logic from `tests/test_utils/lifecycle.py`, ensuring a single source of truth for "Model Physics."

---

## Phase 1: Foundation (Transport & Session)

**Goal**: Establish the communication layer and persistent state management.

### 1.1. Module Structure
*   Create directory structure: `backend/transport`, `backend/session`, `backend/pipeline`, `backend/models`, `backend/tools`.
*   Establish `backend/main.py` as the new entry point.

### 1.2. WebSocket Server (`transport/server.py`)
*   Implement an `asyncio` server using the `websockets` library.
*   **Protocol Handler**:
    *   Detect message type: Text (JSON) vs Binary (Bytes).
    *   Route JSON commands (`start`, `stop`, `config`) to the Orchestrator.
    *   Route Binary chunks (Audio PCM, Video Frames) to the Active Pipeline Input.
*   **Output Queue**: Implement an `asyncio.Queue` for thread-safe broadcasting of results back to the client.

### 1.3. Session Manager (`session/manager.py`)
*   Create a `Session` class holding:
    *   `history`: List of conversation turns.
    *   `context`: Key-Value store for active mode settings.
*   Implement `save()` and `load()` methods (JSON serialization).

## Phase 2: The Pipeline Engine

**Goal**: Create the "Brain" that executes logic sequentially while remaining responsive.

### 2.1. Pipeline Definitions (`pipeline/definitions.py`)
*   Define `PipelineConfig` (dataclass) capturing:
    *   `input_mode`: (`stream`, `frame`, `text`)
    *   `trigger`: (`vad`, `continuous`, `manual`)
    *   `models`: List of required model IDs.
*   Create `PipelineContext` to hold runtime buffers (audio buffer, current frame).

### 2.2. The Orchestrator (`pipeline/orchestrator.py`)
*   Implement `PipelineManager` class.
*   **State Machine**: `IDLE` -> `LOADING` -> `LISTENING` -> `THINKING` -> `SPEAKING`.
*   **Loop**:
    *   Read from Input Queue (non-blocking).
    *   Check Trigger (e.g., is VAD active?).
    *   Execute Step 1 (STT), Step 2 (LLM), Step 3 (TTS).
    *   Push to Output Queue.

## Phase 3: Model Integration

**Goal**: Wrap existing components into a unified API without breaking legacy tests.

### 3.1. Model Abstractions (`models/interface.py`)
*   Define `ModelInterface` with methods: `load()`, `unload()`, `infer(data)`.

### 3.2. Service Adapters
*   **Implementation Choice**: Use **IPC / Direct Import**. To minimize latency, the Pipeline should try to instantiate the model classes (`ChatterboxTTS`, `Whisper`) directly if possible, or manage them as subprocesses if isolation is needed.
*   **STT**: Wrap `faster-whisper` (streaming mode).
*   **TTS**: Wrap `chatterbox` (stream output to bytes).
*   **LLM/VLM**: Wrap `vLLM` / `Ollama` API calls (these remain as separate processes due to their size).

### 3.3. Resource Manager (`models/resource.py`)
*   **Port Logic**: Refactor `tests/test_utils/lifecycle.py` logic into a reusable `ResourceManager` class that can be used by BOTH the new Pipeline and the old Test Runner (eventually).
*   **Functionality**:
    *   Calculate VRAM delta using `utils/calibrate_models.py`.
    *   Evict non-sticky models.
    *   Spin up/down Docker containers or Processes.

## Phase 4: Verification & First Mode

**Goal**: Verify the system using the Two-Layer Testing Strategy.

### 4.1. STS Mode Configuration
*   Define the `STS_PIPELINE` config:
    *   Input: `stream/audio`
    *   Trigger: `vad` (Server-side VAD for V1, or trust Client VAD flags)
    *   Action: `STT -> User_Prompt -> LLM -> TTS`

### 4.2. Integration Testing (`tests/runner_modular_e2e.py`)
This is the **System QA** suite. It verifies the *application* built from the components.
*   **Plumbing Mode (`--plumbing`)**: Spawns `backend/main.py --stub`. Verifies Transport, Session, and Pipeline Logic instantly.
*   **Full Mode (Default)**: Spawns `backend/main.py` (real models). Verifies hardware integration and VRAM arbitration.

## Execution Order
1.  **Phase 1**: Build the skeletal WS server and Session state.
2.  **Phase 3**: Create the Model Adapters (reuse existing logic).
3.  **Phase 2**: Connect the pieces with the Orchestrator.
4.  **Phase 4**: Configure STS and Run the Test Client.
