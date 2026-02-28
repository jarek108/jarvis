# Vision: Unified Flow-Graph Orchestration

## Goal
To replace all hardcoded domain-specific test runners (`tests/stt/test.py`, etc.) and hardcoded production servers (`servers/sts_server.py`) with a single, declarative **Flow-Graph Engine**. This unified architecture ensures that benchmarks measure the exact same logic paths used in production while maintaining domain-specific evaluation expertise in isolated modules.

## Architectural Principles
1. **Declarative Topology**: All logic (streaming, chunking, routing) must be visible in the `pipelines/*.yaml` flow graphs, not hidden in Python code.
2. **Simple Executor**: The `PipelineExecutor` must remain a lean "Traffic Cop" (Dispatcher). It should not contain domain-specific knowledge (no "if LLM" or "if STT").
3. **Logic Nodes**: Complex behaviors like "token-to-sentence buffering" are implemented as simple, reusable utility nodes within the graph.
4. **Trace-Based Evaluation**: Metrics (TTFT, Similarity, CPS) are calculated post-hoc by analyzing an "Event Trace" (log of all inputs/outputs with timestamps) generated during the run.
5. **Entry-Point Injection**: Any node in a graph can serve as an entry point for a test, enabling "Component Testing" to be a subset of "System Testing."

---

## Execution Plan

### Phase 1: Logic Nodes & Reactive Flow
*   **Utility Adapters**: Create a `utils/transformers.py` containing simple logic like `chunk_by_delimiter`.
*   **Generator Support**: Update `PipelineExecutor` to treat every node as a potential generator. If a node yields data, the executor immediately pushes it to downstream nodes.
*   **Streaming YAML**: Update `voice_to_voice.yaml` to include a `text_chunker` node between `proc_llm` and `proc_tts`.

### Phase 2: Trace-Based Instrumentation
*   **The Observer**: Add an instrumentation layer to the `PipelineExecutor` that records every packet of data moving between nodes, tagged with high-resolution timestamps.
*   **Trace Artifact**: Save this `trace.json` into the session log folder.
*   **Domain Evaluators**: Update `tests/[domain]/evaluator.py` to accept a `trace.json` and calculate its specific metrics (RTF, CPS, etc.) from the event history.

### Phase 3: Transition & Retirement
*   **Atomic Pipelines**: Create 1-node pipelines for STT, TTS, and LLM to replace the old component-level tests.
*   **Scenario Translation**: Update `runner_pipeline.py` to map legacy flat-YAML scenarios into the unified graph runner.
*   **Production Parity**: Refactor `sts_server.py` to be a thin FastAPI wrapper that simply hosts the `voice_to_voice.yaml` graph using the shared executor.
*   **Test Composition**: Finalize a suite of `fast` and `exhaustive` test plans (`ALL_fast.yaml`, `ALL_exhaustive.yaml`) that use the new pipeline runner to cover all core capabilities (STT, LLM, TTS, VLM, Multi-Input) with varied data scenarios.

### Phase 4: Hardware Physics (VRAM)
*   **Environmental Realism**: Measure "System VRAM Delta" for every run. 
*   **Validation**: Ensure the peak usage during a 3-model pipeline run is what we use to calibrate the system's "GB-first" strategy.

## Future State
When the transition is complete, adding a new capability to Jarvis (e.g., "Vision-to-Voice") will only require:
1. Creating a new **Flow Graph** (YAML).
2. Adding a **Domain Evaluator** for specific benchmarks.
3. Running it through the **Unified Runner**.
