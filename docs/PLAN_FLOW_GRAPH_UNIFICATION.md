# Future Vision: Pluggable Transport Topology

## The Concept: "Library-First, Service-Optional"
Jarvis is currently architected as a pure, embedded Python library (the `PipelineExecutor`). This provides the absolute lowest latency by executing the entire flow graph—from physical edge sensors to AI models to edge actuators—within a single memory space. 

However, to support future use cases (like a lightweight web client, a browser extension, or a remote Raspberry Pi smart speaker), the pipeline must be capable of "Split Execution" across a network boundary.

## The Design: Runtime Context Resolution
We will achieve this *without* changing the declarative YAML pipelines. Instead, we will introduce a `RuntimeContext` to the `PipelineResolver`.

When a graph is resolved, the nodes are bound to different adapters based on the context:

### 1. Context: `LOCAL` (Current Architecture)
The pipeline runs entirely embedded in the host application (e.g., `jarvis_client.py` or `tests/runner.py`).
*   `source: microphone` ➔ Binds to `LocalAudioSensor` (PyAudio).
*   `processing: llm` ➔ Binds to `LLMAdapter` (HTTP call to local vLLM).
*   `sink: speaker` ➔ Binds to `LocalAudioActuator` (SoundDevice).
*   *Data flows in-memory via Python AsyncQueues.*

### 2. Context: `SERVER_HOST` (The Exposed API)
The pipeline runs in a headless server wrapper (`jarvis_server.py`), exposing the processing logic to the outside world.
*   `source: *` ➔ Binds to a `NetworkReceiverAdapter`. It waits for incoming packets on the websocket/API endpoint.
*   `processing: *` ➔ Binds normally.
*   `sink: *` ➔ Binds to a `NetworkSenderAdapter`. It streams resulting packets back down the websocket.

### 3. Context: `EDGE_CLIENT` (The Remote Sensor)
A lightweight script running on a remote device that "adopts" the edge nodes of a remote graph.
*   `source: *` ➔ Binds to local hardware sensors.
*   `processing: *` ➔ Binds to a `NetworkForwarderAdapter`. It does no processing; it simply blasts the data to the `SERVER_HOST`.
*   `sink: *` ➔ Binds to local hardware actuators.

## Implementation Roadmap (Deferred)
1.  **Define the Interface**: Standardize the `NetworkAdapter` class that can serialize/deserialize `PipelinePackets` over a websocket or gRPC stream.
2.  **Update the Resolver**: Allow `PipelineResolver` to accept a `mode="LOCAL" | "SERVER" | "EDGE"` argument during initialization.
3.  **Build the Host Wrapper**: Re-introduce a lightweight `jarvis_server.py` that instantiates the executor in `SERVER` mode.

*Status: Deferred to prevent premature complexity while the core local engine stabilizes.*
