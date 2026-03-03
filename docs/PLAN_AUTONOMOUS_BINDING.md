# Plan: Autonomous Capability Binding (ACB)

This document refines the transition from manual "Strategy" files to an autonomous, physics-aware binding system that connects hardware Loadouts to logical Pipelines.

## 1. VISION
The user experience shifts to a **"Loadout-First"** workflow. You apply a loadout (e.g., `RTX_5090_HEAVY`), and the system automatically inspects the active models, evaluates their "physics" (size/VRAM), and binds them to the current pipeline's nodes based on your global `mapping_preference`. 

The "Strategy" as a user-facing concept is eliminated. In its place is a **Binding Manifest**—an internal, ephemeral state that can be persisted for specialized overrides but otherwise remains invisible.

## 2. ARCHITECTURAL REQUIREMENTS
*   **The Contract (`utils/engine/contract.py`)**: A centralized `Capability` Enum (e.g., `STT`, `TTS`, `LLM`, `VLM`, `VISION_ENCODER`). This is the "glue" that prevents silent handshake failures.
*   **The Physics-Aware Binder**: A module that sorts valid candidates for a node based on the `mapping_preference` flag:
    *   `PREFER_BIG`: Sort candidates by `num_params` (descending) or `required_gb`.
    *   `PREFER_SMALL`: Sort candidates by `num_params` (ascending) or `required_gb`.
*   **Multi-Node Allocation**: A single model instance (e.g., `vl_qwen2-vl-7b`) can be bound to multiple nodes (e.g., `proc_vlm` and `proc_llm`) simultaneously.
*   **Orphan Detection**: Models active in a loadout but not assigned to any node in the current pipeline are marked with a `[NOT IN USE]` warning in the UI sidebar.

## 3. IMPLEMENTATION PHASES

### Phase 1: The Formal Contract
*   Define the `Capability` Enum and the `MappingPreference` Enum.
*   **Location**: `utils/engine/contract.py`. This ensures both the Engine and the UI speak the same language.
*   Update `model_calibrations/*.yaml` to use these standardized Enum values.

### Phase 2: The Auto-Binder Logic
*   Create `utils/engine/binder.py`:
    *   `find_candidates(required_caps, active_models)`: Returns a list of models that provide the intersection of needs.
    *   `apply_physics_sorting(candidates, preference)`: Reorders candidates based on the physics database.
    *   `generate_manifest(pipeline, loadout)`: The core loop that builds the binding map.

### Phase 3: Resolver Refactor
*   Modify `PipelineResolver.resolve()`:
    *   If no `strategy_id` is provided, invoke the `AutoBinder`.
    *   Check hierarchy: **Manual Override (YAML)** > **Persistent Cache (.cache/)** > **Auto-Binder Heuristic**.

### Phase 4: UI & Observability
*   Remove the **Strategy** dropdown from `ui/app.py`.
*   Update `ui/sidebar_widgets.py` (`ModelHealthCard`) to show a "Dimmed" or "Warn" state if a model is an **Orphan** (not bound to the current graph).
*   Add a `[AUTO]` indicator in the node labels when a model is automatically bound.

## 4. KEY DECISION POINTS & TRADEOFFS

| Decision | Selection | Consequence |
| :--- | :--- | :--- |
| **Enum Source** | `utils/engine/contract.py` | Centralizes the "Contract" but adds a dependency to both low-level engine and high-level UI code. |
| **Physics Source** | `model_calibrations/` | The Binder must be able to load these YAMLs fast. We may need a lightweight `PhysicsRegistry` cache. |
| **Multi-Node Logic** | **Greedy Reuse** | If one model satisfies multiple roles, the system will bind it to all of them to save VRAM, rather than seeking a second redundant model. |
| **Persistence** | **Hybrid** | Specialized mappings are saved to `.cache/pipeline_bindings.json`, but we allow an `overrides` block in the Pipeline YAML for "Golden Mappings" that should be in Git. |
