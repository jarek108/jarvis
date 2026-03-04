# Plan: Edge Virtualization & Dual-Registry AutoBinding

## 1. VISION
To achieve true architectural symmetry, we are expanding the Autonomous Capability Binding (ACB) system to encompass Hardware/Edge nodes. 
Instead of hardcoding `source` and `sink` behaviors in the Executor or Pipeline Adapters, these nodes will be treated as logical contracts (e.g., `requires: [audio_out]`). The AutoBinder will resolve them against an **Edge Registry** of pluggable physical implementations (e.g., `PushToTalkMic`, `MockWavReader`, `SystemSpeaker`).

## 2. ARCHITECTURAL REQUIREMENTS
*   **Dual-Registry Binding**: The AutoBinder maps `processing` nodes to the Loadout (Models) and `source/sink` nodes to the Edge Registry (Hardware/Scripts).
*   **Symmetrical Execution**: The `PipelineExecutor` will no longer contain hardcoded logic for input/source data loading. All nodes, including sources, will be executed via the standard `NodeAdapter` abstraction.
*   **Encapsulated Edge Implementations**: Hardware scripts (Sensors/Actuators) must declare their provided capabilities and encapsulate their own trigger mechanisms (e.g., listening for a UI event or a global hotkey).

## 3. IMPLEMENTATION PHASES

### Phase 1: The Edge Registry & Implementations
*   Create `utils/edge/registry.py` to hold available Edge classes.
*   Define a base `EdgeImplementation` class with a `get_capabilities()` method.
*   Implement `PushToTalkMic` (Source) and `SystemSpeaker` (Sink) as formal Edge implementations with capabilities `[AUDIO_OUT]` and `[AUDIO_IN]` respectively.
*   Implement a `WavFileReader` for testing symmetry.

### Phase 2: AutoBinder Extension
*   Modify `utils/engine/binder.py` to accept the `EdgeRegistry`.
*   Update `generate_manifest` to resolve `source` and `sink` nodes by matching their required capabilities against the Edge Registry.
*   Persist edge bindings in `.cache/pipeline_bindings.json` alongside model bindings.

### Phase 3: Executor & Adapter Unification
*   Create a generic `SourceAdapter` in `utils/pipeline_adapters/source.py` that invokes the bound Edge Implementation.
*   Refactor `SinkAdapter` to invoke the bound Edge Implementation rather than hardcoding audio/notification logic.
*   Clean up `PipelineExecutor.run()` to treat all nodes symmetrically (remove the hardcoded `input_source` bootstrapping).

### Phase 4: The Hold-to-Talk Implementation
*   Update `ui/app.py` to pass a shared state object (e.g., an `Event` or `Queue`) in the `scenario_inputs` when launching the pipeline.
*   The `PushToTalkMic` implementation will consume this state to know when to start/stop recording, ensuring clean decoupling between the UI and the physical audio capture.

## 4. KEY DECISION POINTS & TRADEOFFS
*   **Global Hotkey vs. UI Injection**: For the PTT Mic, we will inject a `threading.Event` from the UI through the Executor's `scenario_inputs`. This prevents the script from needing global OS-level hook permissions while still keeping the physical audio logic isolated in the Edge class.
*   **Adapter vs Edge Script**: The `SourceAdapter` is part of the Engine (handles queues, tracing, asyncio). The `PushToTalkMic` is part of the Edge (handles `pyaudio`, byte buffers). This maintains a strict separation of concerns.
