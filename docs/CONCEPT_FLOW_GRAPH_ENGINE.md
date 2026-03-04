# Concept: Reactive Flow Graph Engine

## Overview
Jarvis has transitioned from a hardcoded, sequential orchestration model to a **Declarative Reactive Flow** system. This architecture unifies testing and production by using the same execution engine for both benchmark scenarios and real-time interaction.

## Core Pillars

### 1. The Modality-Blind Executor
The `PipelineExecutor` acts as a pure "Traffic Cop" (Dispatcher). It is completely unaware of the data types (audio, tokens, video) passing through it.
*   **Agnostic Execution**: It does not use specialized classes. It simply retrieves a `NodeImplementation` from the registry and calls its `execute_fn`.
*   **Transport**: Uses `asyncio.Queue` for non-blocking handoffs between nodes.
*   **Flight Recorder (Trace)**: Records every packet's metadata (envelope) and content (for text) into a `trace.json` artifact.

### 2. Unified Implementation Registry
All logic is centralized in the `ImplementationRegistry`. Instead of deep OOP hierarchies, the system uses **Functional Composition**:
*   **Static Implementations**: Hardcoded logic for local drivers (Mic, Speaker, Keyboard) and utility ops (Chunkers, Memory).
*   **Dynamic Implementations**: Generated at runtime when a Loadout is applied, wrapping remote models (Ollama, vLLM) in a standard `execute_fn`.
*   **Data Contracts**: Every implementation declares `input_types` and `output_types` (using the `IOType` enum) for strict validation.

### 3. Reactive Data Flow
Nodes begin processing as soon as their upstream dependency yields its first packet.
*   **Streaming Handoff**: `LLM (Token Stream) -> Logic Chunker (Sentence Stream) -> TTS (Audio Stream)`.
*   **Concurrent Execution**: All nodes run as parallel async tasks, waiting for data in their input queues.

### 4. Robust Context Templating
Processing nodes receive a dictionary of all upstream input streams. The `LLM` implementation uses a `context_layout` to merge these streams into a final prompt:
```yaml
context_layout: |
  SYSTEM: {{ sys_prompt }}
  USER: {{ proc_stt }}
```

### 5. Autonomous Capability Binding (ACB)
The Pipeline Engine utilizes the `AutoBinder` to map logical nodes to physical implementations:
1.  **Fixed Binding**: YAML can specify an exact `implementation` ID (e.g., `PushToTalkMic`), bypassing discovery.
2.  **Capability Contract**: Nodes declare required capabilities (e.g., `[text_in, text_out]`).
3.  **Physics-Aware Sorting**: Ambiguities are resolved by prioritizing models based on VRAM footprint and the global `mapping_preference`.

## Future Extensibility
To add a new modality (e.g., **Vision**):
1.  Define a new node in a YAML pipeline.
2.  Add an `execute_vision_op` function to `utils/engine/implementations.py`.
3.  Register it in `utils/engine/registry.py`.
4.  The `PipelineExecutor` handles transport without modification.
