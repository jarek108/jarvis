<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# just write the design, no more questions. just assume local-first, single-user/request, super-low latency, memory efficient approach - we will never have multiple calls/users

Below is a draft “Design \& Decisions” section for the architecture/SE/tech stack, assuming local-first, single-user, single-active-request, ultra-low latency, and memory efficiency.[^1]

***

## Architectural overview

The system is a single-node, local-first multimodal assistant running on an RTX 5090 class machine, exposing a unified WebSocket API to a single client. The backend is a monolithic Python service embedding STT, TTS, LLM, VLM, and agentic tools, orchestrated by a modular pipeline engine that runs exactly one active pipeline at a time. All conversational, visual, and agentic modes are expressed as concrete pipeline configurations over shared primitives rather than separate services.[^1]

### Key design principles

- Local-first, offline-friendly: all core inference (STT, TTS, LLM, VLM) runs locally; external calls are optional tools.
- Single active request: the engine serializes inference, simplifying concurrency, VRAM management, and debugging.
- Streaming by default: input and output are streamed over WebSocket for minimal perceived latency.
- Configuration over code: interaction modes are defined as pipeline configs over reusable components.

***

## Runtime architecture

The runtime is structured into a small number of clearly defined layers.[^1]


| Layer | Responsibility | Tech choices / constraints |
| :-- | :-- | :-- |
| Transport | WebSocket bidirectional streaming and control | Python async WebSocket server (e.g., websockets) |
| Session \& State | Per-session context, history, mode, and settings | In-memory session manager + JSON snapshots |
| Pipeline Engine | Build/execute pipelines, manage triggers, route events | Asyncio-based orchestrator, linear execution |
| Model Runtime | STT, TTS, LLM, VLM model abstractions and VRAM management | faster-whisper, chatterbox, vLLM/Ollama, QuantTrio, Qwen-VL[^1] |
| Tools \& Agents | Router, Deep Dive, external tools (Gemini CLI, scripts) | Python tool registry \& execution |
| Logging \& Metrics | Structured logs, basic timing/VRAM metrics | Local log files, optional lightweight metrics |

Each client connection maps to a single logical session with one active pipeline; changing mode tears down the current pipeline and instantiates a new one using the existing session state.[^1]

***

## Communication and protocol

- **Protocol:** A single WebSocket endpoint handles:
    - Upstream: audio chunks (PCM), MJPEG/binary frames, text messages, control commands.
    - Downstream: audio chunks, text tokens, structured events (`control_signal`, `notification`, `tool_result`).[^1]
- **Message framing:** All messages are small JSON envelopes with a `type` field (`audio_chunk`, `video_frame`, `text`, `control`, `event`) and optional binary payload (e.g., JPEG bytes) transported via WebSocket message frames.
- **Backpressure \& flow control:** The server is authoritative; for the first version, overflow is handled by dropping non-critical frames (e.g., video) while preserving audio and control messages.

Control messages (e.g., `start_pipeline`, `switch_mode`, `interrupt`) are just JSON events on the same WebSocket, simplifying client implementation and avoiding additional control channels.

***

## Concurrency and execution model

- **Single active pipeline:** At any moment, only one pipeline instance is executing user work; all inference calls are serialized to guarantee deterministic VRAM usage and avoid contention.
- **Async wrapper:** The server uses `asyncio` for:
    - Non-blocking WebSocket I/O.
    - Handling interrupts while a long-running generation or tool is in progress.
    - Internal `asyncio.Queue`-based event routing between components.
- **Interrupt semantics:**
    - An `interrupt` control message attempts to cancel any in-flight generation or long-running tool.
    - The pipeline engine drains/flushes output queues and emits a terminal `interrupted` event, then returns to idle.

This model targets low complexity and predictable performance over raw throughput, which is acceptable under the single-user, single-request constraint.

***

## Pipeline model and configuration

Pipelines formalize how inputs, triggers, models, and outputs are composed.[^1]

### Pipeline definition

Each pipeline is defined by:

- **Input channels:** which of `{stream/audio, stream/video, message/text, payload/image}` are active and how they are decoded.[^1]
- **Trigger strategy:** one of:
    - `vad_gated` (voice turns),
    - `continuous(n)` (e.g., every N frames),
    - `request_response` (explicit client call).[^1]
- **Cognitive loadout:** which models to load (STT, TTS, LLM, VLM, reasoning model), quantization/precision settings, and VRAM budget estimate.[^1]
- **Processing graph:** a linear sequence with optional branches:
    - Pre-processors (e.g., audio normalization, frame resizing).
    - Core inference steps (STT → LLM → TTS, or VLM → LLM, etc.).
    - Optional agents/tools (router, Deep Dive).
- **Output sinks:** which event types are emitted: `audio_chunk`, `text_token`, `notification`, `control_signal`.[^1]

The first implementation treats pipelines as **linear templates with hooks**, not arbitrary DAGs, to minimize complexity.

### Example mode mappings

- **STS (Voice Chat):** `stream/audio` + `vad_gated` → STT → LLM → TTS → `audio_chunk` + `text_token`.[^1]
- **Broadcast Mode:** `stream/audio` + `vad_gated` → STT → `text_event` only.[^1]
- **Visual Chat:** `message/text` + `payload/image` + `request_response` → VLM → LLM → TTS → `audio_chunk`.[^1]
- **Active Monitor:** `stream/video` + `continuous(n)` → VLM → rule/LLM → `notification_event`.[^1]
- **Router Mode / Deep Dive:** reuse text pipeline but swap cognitive loadout (small router model vs heavy reasoning model) and tool usage.[^1]

Pipelines are declared as Python objects (builder API) in the first version; a declarative config format can be layered on later without changing the engine core.

***

## Resource and model management

- **VRAM policy:** Only the models required by the active pipeline are kept in VRAM; switching pipelines can unload unused models and load the new ones as needed.[^1]
- **Hot swapping:**
    - Mode switches are explicit; small loading delays are acceptable (e.g., when moving into Deep Dive).
    - STT and TTS can be treated as “semi-sticky” models that remain resident unless a large VLM or reasoning model needs their VRAM.
- **Optional always-on router:** A tiny SLM (e.g., sub-1B) may stay resident to implement router logic and quick classification even when large models are swapped.

The model runtime abstracts STT/TTS/LLM/VLM backends (faster-whisper, chatterbox, vLLM/Ollama, QuantTrio/Qwen-VL) behind uniform interfaces so pipelines do not depend on specific libraries.[^1]

***

## Session, context, and persistence

- **Session manager:**
    - Maintains per-session:
        - conversation history (turns, mode tags),
        - runtime configuration (current mode, voice, temperature),
        - lightweight structured memory (e.g., key-value facts).
    - Exposed as a shared service across all pipelines so context survives mode switches.
- **Persistence:**
    - Periodically serializes session state to JSON files.
    - On startup, can restore the last session or start fresh based on configuration.
- **History management:**
    - Basic in-memory length limits per session; when exceeded, older turns are summarized or dropped based on heuristics.
    - Summarization can be implemented as a background or on-demand pipeline using a smaller LLM.

This approach keeps state local, inspectable, and easy to back up or migrate.

***

## Client responsibilities

- **VAD and audio capture:** The client runs local VAD and only streams speech segments as `stream/audio` chunks, reducing bandwidth and backend work.
- **Video capture:** For visual modes, the client encodes frames as JPEG (or similar) and sends them over the existing WebSocket as MJPEG/binary at a modest FPS.
- **Rendering and controls:** The client:
    - Renders text tokens and plays back audio chunks.
    - Displays visual overlays (e.g., Holo-Field metadata) on top of local UI.
    - Sends control events (`start_mode`, `switch_mode`, `interrupt`, `confirm_action`).

The client is intentionally thin; all cognitive behavior, routing, and tool execution reside in the backend.

***

## Agentic tools and routing

- **Tools:** Tools are Python-callable capabilities (e.g., Gemini CLI wrapper, local shell script, web fetch) registered in a central registry with metadata (name, arguments, safety flags).
- **Router mode:**
    - Uses an LLM (possibly small) to decide between direct answer and `delegate_action` tool calls.[^1]
    - Emits `control_signal` events when a tool should be invoked, including arguments.[^1]
- **Execution model:**
    - The backend executes tools in a controlled environment (separate process where needed).
    - Tool outputs are streamed back as `tool_result` events and optionally fed back into the LLM as context.

High-impact actions (e.g., lock screen, shutdown) are emitted as `control_signal` events that the client may require explicit user confirmation for before acting.

***

## Tech stack choices

- **Language \& runtime:** Python 3.x, leveraging `asyncio` for WebSocket I/O and internal event queues.
- **WebSocket server:** A minimal async framework (e.g., bare `websockets` or FastAPI/Starlette with WebSocket endpoints) for simplicity.
- **Models \& libraries:**
    - STT: faster-whisper (streaming).
    - TTS: chatterbox (real-time synthesis).
    - LLM: vLLM as the primary runtime, Ollama as alternative backend for specific models.
    - VLM: QuantTrio and Qwen-VL for image and video frame understanding.[^1]
- **Packaging \& deployment:**
    - Single service process with a small set of worker subprocesses for tools if needed.
    - Config via local files (YAML/JSON) and environment variables for paths, ports, and model configs.

This stack optimizes for local performance and pragmatic integration with existing components.

***

## Software engineering practices

- **Module layout:**
    - `transport/` – WebSocket server, message schemas.
    - `session/` – session manager, persistence.
    - `pipeline/` – pipeline engine, pipeline definitions per mode.
    - `models/` – abstractions and adapters for STT/TTS/LLM/VLM.
    - `tools/` – agent tools, router and Deep Dive logic.
    - `logging/` – structured logging and basic metrics.
- **Configuration:**
    - Central config object for model paths, quantization, ports, and default pipelines.
    - Mode presets defined as code-level descriptors referencing shared components.
- **Testing:**
    - Unit tests for pipeline definitions and model adapters (using mocked backends).
    - Scenario tests for core modes (STS, Visual Chat, Active Monitor) using recorded inputs.
- **Observability:**
    - Structured logs (JSON lines) for events, mode switches, tool invocations, and timing.
    - Lightweight metrics (histograms for latency, counters for tokens/frames) exposed locally or logged for offline inspection.

These choices keep the system debuggable and evolvable without sacrificing the single-user, low-latency focus.

<div align="center">⁂</div>

[^1]: CONCEPT_CLIENT_ARCHITECTURE.md

