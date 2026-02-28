# Vision: Unified Edge-Core Orchestration

## Goal
To transform Jarvis into a fully decoupled, hardware-agnostic platform where physical sensors (microphones, cameras) and actuators (speakers, keyboard, notifications) are treated as pluggable "Hardware Loadouts." This architecture ensures that the core flow-graph engine remains purely logical and modality-blind, while all physical environment interaction is managed at the Edge (the Client).

---

## Desired Deliverables

### 1. Modality-Blind Flow Topology
*   Refined Pipeline YAMLs that use **Capabilities** (e.g., `[audio_in]`, `[image_out]`) instead of hardcoded hardware paths or buffer locations.
*   The `PipelineExecutor` remains a stateless router, unaware of whether an `image` came from a webcam, a screenshot, or a file.

### 2. Edge Adapter Registry
*   A set of modular Python scripts/classes on the Client side that fulfill specific data contracts:
    *   `audio_recorder.py` (fulfills `audio_out`)
    *   `screen_grabber.py` (fulfills `image_out`)
    *   `system_notifier.py` (fulfills `text_in`)
    *   `keyboard_actuator.py` (fulfills `text_in`)

### 3. Unified Packet Protocol (The Bridge)
*   A robust communication layer (Websocket or gRPC) that carries `PipelinePackets` between the Client and Server.
*   Every packet contains the standard headers established in `docs/CONCEPT_FLOW_GRAPH_ENGINE.md` (`ts`, `seq`, `type`, `len`).

### 4. State-as-I/O (Minimalist Memory)
*   Conversation history and system state managed entirely via file/buffer read/write operations.
*   "Memory" becomes a special-case sensor (Read from `history.txt`) and actuator (Append to `history.txt`).

---

## Implementation Phases

### Phase 1: Protocol & Schema Refinement
*   **Contract Standardization**: Formalize the `capabilities` registry (e.g., `image_raw`, `audio_pcm`, `text_token`) to ensure all nodes speak the same language.
*   **Agnostic Pipelines**: Update `pipelines/*.yaml` to remove hardcoded `buffer` paths, replacing them with `source` and `sink` nodes that define their data requirements.

### Phase 2: Edge Adapter Development
*   **Sensor Suite**: Build the primary input adapters for the desktop environment (Microphone via PyAudio, Screen via MSS, Clipboard via Pyperclip).
*   **Actuator Suite**: Build the primary output adapters (Speaker playback, Desktop notifications, Keyboard emulation).
*   **Local Evaluator**: Ensure these adapters can be used by the Test Runner to feed files into the system, achieving 100% parity between "Test Data" and "Live Data."

### Phase 3: The Split-Execution Host
*   **Host Refactor**: Update `servers/jarvis_server.py` to become a "Broker." It must be able to signal to the Client: *"I have reached a Source Node (mic_in), please send me audio data."*
*   **Reactive Streaming**: Ensure that packets flow from Client Sensor -> Server Brain -> Client Actuator with microsecond latency.

### Phase 4: File-Based State & Memory
*   **Context Engineering**: Implement the `memory` node as a file-I/O utility.
*   **Validation**: Create a test plan where the LLM's response depends on a "Memory Source" being pre-populated with specific context, proving the State-as-I/O model.

## Future State
Adding a new device (e.g., an IoT Light Bulb) no longer requires touching the Brain or the Server. A developer simply:
1. Writes an Edge Adapter (`iot_bulb.py`) that consumes `[boolean_in]`.
2. Adds a `sink` node to their pipeline.
3. Maps the sink to the bulb in their Client configuration.
