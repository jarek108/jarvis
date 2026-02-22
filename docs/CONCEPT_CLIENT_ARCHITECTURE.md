# Concept: Modular Interaction Pipeline Architecture

> **Context**: "Jarvis" is a local, high-performance multimodal AI assistant designed for NVIDIA RTX 5090 hardware. It integrates Speech-to-Text (STT), Text-to-Speech (TTS), Large Language Models (LLM), and Vision Language Models (VLM). This document outlines the architecture for a flexible, configurable backend pipeline capable of supporting diverse interaction modes (voice chat, visual monitoring, agentic routing).

## 1. Current System Capabilities (The Foundation)

Our existing backend infrastructure (`sts_server.py`) has been rigorously benchmarked and optimized. It currently supports a linear **Speech-to-Speech (STS)** pipeline.

### Backend Primitives
*   **Speech-to-Text (STT)**: Low-latency streaming transcription via `faster-whisper`.
*   **Text-to-Speech (TTS)**: High-fidelity, real-time synthesis via `chatterbox`.
*   **LLM Inference**: High-throughput text generation via `vLLM` (native) and `Ollama`.
*   **Vision (VLM)**: Capability to process images and video frames via `QuantTrio` and `Qwen-VL`.
*   **Orchestrator**: A unified server that manages the flow of Audio $\rightarrow$ Text $\rightarrow$ Audio.

### Performance Profile
*   **Latency**: STT/TTS latency is negligible (<200ms). LLM TTFT is <50ms.
*   **Throughput**: Capable of handling continuous streams.
*   **VRAM**: Smart Allocator ensures simultaneous loading of Vision (30B), Audio (Large), and TTS models within 32GB VRAM.

---

## 2. Desired Interaction Modes (The Requirements)

The backend must support distinct "Modes of Operation." Each mode is a specific configuration of inputs, triggers, logic, and outputs.

### A. Conversational Modes
1.  **STS (Voice Chat)**: Hands-free verbal interaction.
    *   *Input*: Audio Stream. *Output*: Audio Stream + Text Event.
2.  **Whisper Mode**: Silent input, private output.
    *   *Input*: Text. *Output*: Audio Stream.
3.  **Broadcast Mode**: Verbal dictation.
    *   *Input*: Audio Stream. *Output*: Text Event (to be injected by client).

### B. Visual Intelligence Modes
4.  **Visual Chat**: "Jarvis, look at this."
    *   *Trigger*: On-demand.
    *   *Input*: Audio + Image Payload. *Output*: Audio.
5.  **Active Monitor (Promptable Observer)**: "Alert me if the server crashes."
    *   *Trigger*: Continuous Loop (e.g., 1Hz).
    *   *Input*: Video Stream / Frame Sequence. *Output*: Notification Event.
6.  **Holo-Field (Contextual Help)**:
    *   *Input*: Image Region (ROI). *Output*: Text Metadata (for overlay).

### C. Camera & Presence Modes
7.  **Sentry Mode (Presence Detection)**:
    *   *Input*: Camera Frame Stream.
    *   *Logic*: Detects person/absence. *Output*: State Change Event (e.g., `user_away`).
8.  **Co-Pilot (Active Watcher)**: "Watch me build this hardware."
    *   *Input*: Camera Stream + Audio.
    *   *Logic*: Multimodal reasoning on physical actions. *Output*: Audio Guidance.

### D. Agentic Modes
9.  **Router Mode**:
    *   *Input*: Any.
    *   *Logic*: LLM acts as a router. Decides to answer directly OR emit a `delegate_action` event (e.g., for Gemini CLI or Web Search).
10. **Deep Dive**:
    *   *Input*: Complex Query.
    *   *Logic*: Spins up a specialized "Reasoning Model" (e.g., DeepSeek-R1) for slow, deliberative thought. *Output*: Final Answer.

---

## 3. The Backend Pipeline Architecture

To support these diverse modes, we need to move from a hardcoded `sts_server` to a **Modular Pipeline Engine**.

### The "Pipeline" Configuration
The backend will expose an API to load/unload specific pipelines. A pipeline is defined by:

#### 1. Input Channels (Sources)
The API must accept diverse data types concurrently:
*   `stream/audio`: Raw PCM chunks (for STT).
*   `stream/video`: Frame sequences (for VLM monitoring).
*   `message/text`: Direct text prompts.
*   `payload/image`: Single base64 images.

#### 2. Trigger Strategy (Execution Logic)
*   **VAD-Gated**: Standard voice chat (process when silence detected).
*   **Continuous**: Process every $N$ frames (Monitor/Sentry).
*   **Request-Response**: Explicit API call (Visual Chat).

#### 3. Cognitive Loadout (Resource Management)
*   **Dynamic Loading**: The backend must handle requesting VRAM for the specific models required by the active pipeline (e.g., unloading Whisper to load a larger VLM for "Deep Dive").

#### 4. Output Router (Sinks)
The pipeline produces **Events**, not just streams.
*   `audio_chunk`: For playback.
*   `text_token`: For streaming logs.
*   `control_signal`: e.g., `{"action": "lock_screen"}`, `{"tool": "gemini", "args": "..."}`.

This architecture decouples the "Brain" from the "Body" (Client), allowing any frontend (CLI, GUI, Headless) to plug into these powerful capabilities.
