# Strategic Plan: The Final Server Consolidation

## The Desired Architecture
Jarvis is migrating to a fully declarative, flow-graph-driven architecture. The core principle is a strict separation between **Infrastructure** (model servers) and **Orchestration** (pipelines).

In the target state:
1.  **Infrastructure Managers** (`manage_loadout.py`) boot "dumb" model servers (STT, TTS, Ollama).
2.  **The Universal Host** (`jarvis_server.py`) replaces all hardcoded orchestrators (like `sts_server.py`). It loads a specific pipeline YAML, binds it to the live infrastructure, and executes it via the `PipelineExecutor`.
3.  **The Client** (`jarvis_client.py`) acts as a pure presentation layer, sending input to the Universal Host and rendering the output stream.

## Phase 1: Clean the Slate (The Purge)
The `backend/` directory represents an older, competing prototype of pipeline management that was abandoned in favor of the current YAML-driven `utils/pipeline.py` engine.
1.  **Delete `backend/`**: Remove the entire directory.
2.  **Delete `servers/sts_server.py`**: This script is an architectural violation (it acts as both a server and a hardcoded orchestrator). It will be completely removed.

## Phase 2: Preserving Lost Capabilities (Stubs)
Before we delete `backend/`, we must ensure its valuable concepts (like session memory) have a home in the new graph engine.
1.  **Session Memory Stub**: Create `utils/pipeline_adapters/memory.py`. For now, it will be an empty adapter (`role: memory`), serving as a placeholder for when we implement true cross-turn conversation history within the graph.

## Phase 3: The Universal Host
Create the new, single entry point for the Jarvis backend.
1.  **Create `servers/jarvis_server.py`**:
    *   Takes arguments for `--pipeline` and `--loadout`.
    *   Initializes the `PipelineResolver` and `PipelineExecutor`.
    *   Exposes a single `/stream` endpoint.
    *   Receives multi-modal input (text, audio files), passes it to the active graph, and streams the resulting `PipelinePackets` back to the caller.

## Phase 4: Infrastructure Realignment
Update the surrounding ecosystem to recognize the new architecture.
1.  **Update `manage_loadout.py`**: Remove logic that attempts to spawn or kill `sts_server.py`. The loadout manager is strictly for model infrastructure.
2.  **Config Adjustments**: Ensure `config.yaml` points the "main server port" to `jarvis_server.py` instead of the old `sts_server.py`.

*(Note: The UI Client `jarvis_client.py` will be updated in a subsequent sprint to point to the new Universal Host. For now, it will remain untouched).*
