# Plan: Unified Node Abstraction

## 1. Context & Objective
Currently, Jarvis uses a fragmented system for node execution:
- **Models (Loadouts)**: Handled by `NodeAdapter` subclasses (e.g., `LLMAdapter`) with hardcoded API logic.
- **Hardware (Edge)**: Handled by `EdgeImplementation` subclasses (e.g., `PushToTalkMic`) wrapped in a `SourceAdapter` or `SinkAdapter`.
- **Logic (Utility)**: Handled by `UtilityAdapter` using a switch/case on operations.

**Objective**: Unify all types of execution (Models, Hardware, Logic, Mocks) under a single, data-driven **NodeImplementation** structure. Move away from deep OOP inheritance in favor of a functional "Strategy" pattern.

---

## 2. Proposed Architecture

### A. The Implementation Object
Instead of inheriting from base classes, every implementation in the system (whether a local script or a remote model) is represented by a standard data object.

```python
class NodeImplementation:
    id: str                    # e.g., "ollama://qwen2.5" or "PushToTalkMic"
    input_types: list[str]     # e.g., ["audio_path"]
    output_types: list[str]    # e.g., ["text_stream"]
    
    # The actual execution logic
    execute_fn: Callable       
    
    # Static parameters (ports, model names, delimiters)
    config: dict               
```

### B. Unified Registry
A single registry will track all available implementations. 
- **Static Implementations**: Hardcoded logic (chunkers, local sensors).
- **Dynamic Implementations**: Generated on-the-fly when a Loadout is applied (Models).
- **Mock Implementations**: Injected during test scenarios to override production defaults.

---

## 3. Implementation Phases

### Phase 1: Core Type Definitions
- Create `utils/engine/contract.py` (or update it) to define strict `IOType` enums (e.g., `TEXT_PACKET`, `AUDIO_STREAM`, `IMAGE_PATH`).
- Define the `NodeImplementation` dataclass.

### Phase 2: Functional Logic Migration
- Move logic out of `LLMAdapter`, `STTAdapter`, etc., into standalone functions:
    - `execute_model_api(...)`: Generic HTTP/Streaming caller.
    - `execute_local_sensor(...)`: Local driver logic.
    - `execute_logical_op(...)`: Pure data manipulation (chunking/routing).
- These functions will be the `execute_fn` for their respective implementations.

### Phase 3: The Unified Resolver (AutoBinder)
- Update `AutoBinder` to resolve nodes based on `InputType` and `OutputType` signatures rather than loose "capabilities" strings.
- Implement "Fixed Binding": If a pipeline YAML specifies `implementation: ClassName`, the binder skips discovery and binds that exact implementation.

### Phase 4: Executor Simplification
- Refactor `PipelineExecutor` to be "dumb." 
- It no longer looks for "Adapters." It simply looks at a node's bound `NodeImplementation` and calls its `execute_fn`, passing in the standardized input streams.

### Phase 5: Test Injection
- Update `tests/runner.py` to allow `mock_overrides` in test plans.
- These mocks are just `NodeImplementation` objects with a lambda `execute_fn` that returns static test data.

---

## 4. Key Benefits

1. **No Dynamic Classes**: We don't need to generate Python classes for new models. We just create a new `NodeImplementation` instance pointing to the standard API function.
2. **True E2E Testing**: Tests run the exact same executor code as the app, merely swapping the implementation object for a mock.
3. **Rigid Mapping Support**: Pipeline designers can "lock" a node to a specific implementation class in the YAML, ensuring reliability while keeping other nodes (like the LLM) flexible for auto-mapping.
4. **Simpler Logic**: Eliminates the "Adapter vs Implementation" confusion. Everything is just an Implementation.
