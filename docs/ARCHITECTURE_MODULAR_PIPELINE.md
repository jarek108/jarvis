# Architecture: Modular Interaction Pipeline

> **Context**: This architecture defines the backend for "Jarvis," a local, high-performance AI assistant running on NVIDIA RTX 5090 hardware. It replaces fixed endpoints with a flexible, stateful pipeline capable of multimodal interaction (Voice, Vision, Agents).

## 1. Core Principles

1.  **Single Active Request**: The system processes one primary interaction at a time. It does not need to handle concurrent multi-user contention.
2.  **Local-First**: All compute (STT, TTS, LLM, VLM) happens on-device. Latency is minimized by avoiding cloud round-trips.
3.  **Responsiveness**: While compute is sequential, the I/O layer must remain asynchronous to handle interrupts (e.g., user stops TTS mid-sentence).

---

## 2. The Runtime Architecture

The backend is organized into distinct layers to separate transport logic from cognitive processing.

### Module Layout
*   `transport/`: WebSocket server, message schemas, and frame decoding.
*   `session/`: In-memory session manager, context persistence (JSON), and state history.
*   `pipeline/`: The execution engine and pipeline definitions (STS, Sentry, etc.).
*   `models/`: Abstractions for STT (Whisper), TTS (Chatterbox), and LLM/VLM (vLLM/Ollama).
*   `tools/`: Registry for external actions (Gemini CLI, Python scripts, Web Fetch).

### The Pipeline Engine
A Pipeline is a composed sequence of:
1.  **Input Handler**:
    *   *Stream*: Accumulates raw audio chunks (PCM).
    *   *Frame*: Accepts MJPEG/Base64 video frames.
    *   *Backpressure*: Drops non-critical video frames if compute lags, but buffers audio/control signals.
2.  **Cognitive Logic**:
    *   *STT*: Transcribes audio (VAD-gated).
    *   *Inference*: Calls the loaded LLM/VLM.
    *   *Tool Use*: Executes local functions.
3.  **Output Generator**:
    *   *TTS*: Synthesizes speech.
    *   *Event*: Emits JSON control signals (`{"action": "lock_screen"}`).

---

## 3. Communication Layer (WebSockets)

The Client and Server communicate via a **Unified WebSocket**.

### Protocol Design
*   **Text Frames (JSON)**: Used for control signals, chat logs, and metadata.
    *   `{"type": "config", "mode": "sentry"}` (Client -> Server)
    *   `{"type": "log", "content": "Thinking..."}` (Server -> Client)
*   **Binary Frames**: Used for raw media streams to minimize overhead.
    *   *Input*: Microphone PCM audio, Webcam JPEG frames.
    *   *Output*: TTS PCM audio chunks.

### Concurrency Strategy
*   **I/O Layer (`asyncio`)**: Handles the WebSocket heartbeat and message routing. Allows the user to send an "Interrupt" signal even while the LLM is generating.
*   **Compute Layer**: Heavy inference runs in separate processes/threads. The Orchestrator awaits their result (sequential logic) but remains responsive to the network.

---

## 4. Resource Management (VRAM)

Given the **Single Request** assumption, we utilize a **Smart Hot-Swap Strategy** for the 32GB VRAM budget.

*   **Semi-Sticky Persistence**: 
    *   Lightweight models (STT, TTS, Router SLM) remain resident by default ("Sticky").
    *   Heavy models (LLM, VLM) are swapped based on the active mode.
*   **Eviction Logic**: If a "Deep Dive" mode requires 30GB for a Reasoning Model, the system evicts the Sticky models to free space, accepting a reload delay when returning to "Voice Chat."
*   **Mode Switch Flow**:
    1.  Orchestrator pauses processing.
    2.  Calculates VRAM requirements for new mode.
    3.  Unloads conflicting models (if any).
    4.  Loads new models.
    5.  Signals "Ready" to client.

---

## 5. Usage Modes (Examples)

### Scenario 1: Voice Chat (STS)
*   **Config**: `{"input": "audio", "trigger": "vad", "output": "audio"}`
*   **Flow**: Mic Stream $\rightarrow$ VAD $\rightarrow$ STT $\rightarrow$ LLM $\rightarrow$ TTS $\rightarrow$ Speaker.

### Scenario 2: Sentry Mode
*   **Config**: `{"input": "video", "trigger": "continuous", "frequency": 1.0}`
*   **Flow**: Webcam Frame (1fps) $\rightarrow$ VLM $\rightarrow$ Logic ("Is person present?") $\rightarrow$ Event (`user_away`).

### Scenario 3: Deep Dive
*   **Config**: `{"input": "text", "output": "text", "model": "reasoning"}`
*   **Flow**: User Query $\rightarrow$ **Swap to DeepSeek-R1** $\rightarrow$ Long Inference $\rightarrow$ Final Answer.
