# Reference: Reactive Flow Engine

Technical specifications for the Jarvis pipeline execution engine and its unified node abstraction.

## 1. NodeImplementation Schema
Every node in a Jarvis pipeline is realized by a `NodeImplementation` object retrieved from the `ImplementationRegistry`.

```python
@dataclass
class NodeImplementation:
    id: str                    # Unique identifier (e.g., "PushToTalkMic")
    input_types: list[IOType]  # Expected input data types
    output_types: list[IOType] # Provided output data types
    execute_fn: Callable       # Standard async execution function
    config: dict               # Static config (ports, model IDs, etc.)
    capabilities: list         # Capabilities for AutoBinder discovery
    physics_weight: float      # VRAM/Param count proxy for sorting
```

### IOType Enumeration
Used for strict signature validation and simulator matching.
- `TEXT_STREAM`: Incremental tokens.
- `TEXT_FINAL`: Consolidated strings.
- `AUDIO_FILE`: Path to a .wav/.mp3.
- `AUDIO_STREAM`: Live PCM bytes.
- `IMAGE_FILE`: Path to a .jpg/.png.
- `SIGNAL`: Boolean events (e.g., PTT hold).

---

## 2. Test Runner CLI (`tests/runner.py`)
The unified test runner supports multiple levels of realism via flags.

### Usage
`python tests/runner.py [plan_path] [flags]`

### Flags
| Flag | Mode | Logic | Servers | Hardware |
| :--- | :--- | :--- | :--- | :--- |
| **`--plumbing`** | Logic-Only | Mocks/Lambda | Stub (0 VRAM) | Disconnected |
| **`--e2e`** | Virtualized | Production | Real | Virtual Feeders |
| *(None)* | Manual | Production | Real | Physical |

---

## 3. Pipeline YAML Schema
Additions to the standard pipeline YAML for the Unified Engine.

### Fixed Bindings
Bypass the AutoBinder heuristics by specifying a direct implementation ID.
```yaml
nodes:
  - id: input_mic
    type: source
    implementation: "PushToTalkMic" # Exact registry ID
```

---

## 4. Implementation Registry
Located in `utils/engine/registry.py`.

### Methods
- `register(impl)`: Adds an implementation to the global pool.
- `get(id)`: Retrieves a specific implementation.
- `find_by_capability(caps)`: Returns candidates matching capability requirements.
- `find_by_io(inputs, outputs)`: Returns candidates matching specific IO signatures.
