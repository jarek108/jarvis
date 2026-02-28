# Concept: Reactive Flow Graph Engine

## Overview
Jarvis has transitioned from a hardcoded, sequential orchestration model to a **Declarative Reactive Flow** system. This architecture unifies testing and production by using the same execution engine for both benchmark scenarios and real-time interaction.

## Core Pillars

### 1. The Modality-Blind Executor
The `PipelineExecutor` acts as a pure "Traffic Cop" (Dispatcher). It is completely unaware of the data types (audio, tokens, video) passing through it.
*   **Transport**: Uses `asyncio.Queue` for non-blocking handoffs between nodes.
*   **Standard Packet Protocol**: All data is wrapped in a `PipelinePacket`:
    ```json
    {
      "type": "text_token",
      "content": "Hello",
      "seq": 0,
      "ts": 12345.678,
      "metadata": {}
    }
    ```
*   **Flight Recorder (Trace)**: Records every packet's metadata (envelope) into a `trace.json` artifact, enabling post-hoc performance analysis.

### 2. Node Adapter Registry
Specialized logic is isolated in **Adapters**. The Executor retrieves the appropriate adapter via the `get_adapter(role)` factory.
*   **LLM Adapter**: Manages streaming from Ollama/vLLM and performs context templating.
*   **STT/TTS Adapters**: Manage binary/text conversion and reactive speech synthesis.
*   **Utility Adapters**: Handle logical transformations (e.g., text chunking) within the graph.

### 3. Reactive Data Flow
Nodes can begin processing data as soon as their upstream dependency yields its first packet.
*   **Streaming Handoff**: `LLM (Token Stream) -> Logic Chunker (Sentence Stream) -> TTS (Audio Stream)`.
*   **Concurrent Execution**: All nodes in a graph run as parallel async tasks, waiting only for data to appear in their respective input queues.

### 4. Robust Context Templating
Adapters receive a dictionary of all upstream input streams. The `LLMAdapter` uses a `context_layout` to merge these streams into a final prompt:
```yaml
context_layout: |
  SYSTEM: {{ sys_prompt }}
  USER: {{ proc_stt }}
```

## Trace-Based Evaluation
Metrics are no longer calculated "in-line" during execution. Instead:
1.  The **Executor** generates a "Dumb Trace" (raw timestamps and packet types).
2.  **Domain Evaluators** analyze the trace to calculate high-level metrics:
    *   **STT**: Real-Time Factor (RTF).
    *   **LLM**: Time to First Token (TTFT), Tokens Per Second (TPS).
    *   **TTS**: Characters Per Second (CPS).

## Future Extensibility
To add a new modality (e.g., **Vision**):
1.  Define a new node in a YAML pipeline.
2.  Add a `VisionAdapter` to `utils/pipeline_adapters/`.
3.  The `PipelineExecutor` will automatically handle its transport and tracing without modification.
