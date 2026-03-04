# Concept: Unified Node Abstraction

## The Evolution
Jarvis has transitioned from a specialized **Adapter Hierarchy** to a **Unified Node Abstraction**. This shift was driven by the need to treat remote models (70B LLMs) and local scripts (Keyboard drivers) with the same level of symmetry and testability.

---

## 1. The Legacy: OOP Adapters
Previously, nodes were executed via specialized classes like `LLMAdapter` or `SourceAdapter`. 
- **Problem**: Adding a new modality required creating a new Python class.
- **Problem**: Remote models and local hardware were handled via completely different code paths, making the engine complex.
- **Problem**: Testing required complex subclassing or mocking of entire classes.

## 2. The Solution: Functional Strategies
In the Unified Abstraction, every node implementation is a simple data object (`NodeImplementation`) that points to a **standalone async function**.

### The Symmetrical Signature
Every implementation in the system follows the exact same functional signature:
```python
async def execute_fn(node_id, in_streams, config, out_q, session):
    # node_id: ID of the node being executed
    # in_streams: Dict of {parent_id: AsyncGenerator}
    # config: Consolidated config (YAML + Implementation + Scenario)
    # out_q: Async queue to push results to
    # session: Shared aiohttp session
```

### Why this is better:
1.  **Uniformity**: The `PipelineExecutor` is now "dumb." It doesn't care if it's running a model or a mic script; it just calls the function.
2.  **No Dynamic Classes**: New models in a loadout don't need new Python classes. They just need a new `NodeImplementation` instance pointing to the standard `execute_openai_chat` function.
3.  **Mockability**: To mock a node, you don't need to change the engine. You just swap the `execute_fn` for a lambda or a simple mock function that returns static data.

---

## 3. Data-Driven Mapping
Because every implementation now declares its **Data Signatures** (`input_types` and `output_types`), the `AutoBinder` can perform strict validation. 

A node requiring `AUDIO_STREAM` will never be accidentally bound to a model that only provides `TEXT_FINAL`, preventing runtime crashes and providing early feedback via the "Runnability" report.
