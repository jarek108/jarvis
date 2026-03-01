# Feature Plan: Self-Aware Loadout & Configuration UI

## 1. VISION
Transform the Jarvis Client from a static terminal into an intelligent, self-monitoring dashboard that validates pipeline health in real-time. The goal is to eliminate "Connection Refused" and "Architecture Mismatch" errors by ensuring that all required model servers (Whisper, Ollama, vLLM) are healthy and correctly bound to the active graph before allowing user interaction.

## 2. ARCHITECTURAL REQUIREMENTS
*   **Resolver Intelligence**: The `PipelineResolver` must become the source of truth for "Runnability," capable of cross-referencing resolved node ports with the live health status of the inference cluster.
*   **State-Aware Triggers**: UI controls (e.g., the Record button) must be state-controlled components, dynamically enabled or disabled based on the health of the selected pipeline/mapping combination.
*   **Fulfillment Transparency**: The UI must render the "Binding Map," showing the user exactly which physical model and port is fulfilling each logical node in the graph.

## 3. IMPLEMENTATION PHASES

### Phase 1: Backend Runnability Logic
*   Extend `PipelineResolver` with a `check_runnability(pipeline_id, mapping_id)` method.
*   Implement logic to detect "Ghost Bindings" (models registered in the registry but unreachable on their ports) and "Capability Gaps" (nodes requiring capabilities that no live model can fulfill).
*   Standardize the return format to provide a list of specific missing dependencies (e.g., `{"stt": "OFFLINE", "llm": "BUSY"}`).

### Phase 2: Rich Infrastructure Sidebar
*   Implement a sidebar in `jarvis_client.py` using `get_system_health()` to show all base model servers with status indicators (Lamps).
*   Add tooltips to services showing their detected version and VRAM usage (where available).

### Phase 3: Interactive Configuration & Re-Resolution
*   Replace hardcoded pipeline/mapping strings in the client with dynamic dropdowns that list available YAMLs.
*   Implement a reactive loop: when the user changes a selection, the client immediately re-resolves the graph and performs a runnability check.
*   Render a simplified "Resolution Map" on screen (e.g., `proc_stt -> faster-whisper-tiny [OK]`).

### Phase 4: Safety-Gating & Feedback
*   Gate the main interaction button: if the runnability check fails, the button must be disabled.
*   Implement a "Status Banner" that provides descriptive error messages (e.g., *"Cannot Talk: Whisper Server on Port 8101 is not responding"*) to guide the user toward a fix.

### Phase 5: Persistence
*   Implement a `checkpoint-client.json` to store the user's active selections, ensuring the UI returns to the same state after a restart.

## 4. KEY DECISION POINTS & TRADEOFFS
*   **Polling Strategy**: Real-time polling every 2s ensures a "live" feel but introduces constant network activity. 
    *   *Decision*: We will implement a "Hybrid Poll" that runs every 5s normally, but switches to 1s when the window is focused or a selection is changed.
*   **Separation of Concerns**: Should the UI offer a "Start Service" button?
    *   *Tradeoff*: Adding process-management logic back into the UI violates our "Dumb Terminal" principle and adds subprocess technical debt. 
    *   *Decision*: The UI will remain a **Monitor only**. It will report problems but rely on the user running `python manage_loadout.py` to fix them, ensuring the architecture stays clean and network-ready.
