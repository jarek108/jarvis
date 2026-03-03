# Plan: UI Architectural Cleanup & Modularization

This document outlines the strategy to de-bloat `jarvis_client.py` and move towards a clean MVC (Model-View-Controller) architecture for the Jarvis Console.

## 1. Identified Issues
*   **Monolithic Bloat**: `jarvis_client.py` is an 800-line god object containing business logic, custom widgets, and layout code.
*   **Leaky Abstractions**: The UI view directly accesses the engine's resolver and config.
*   **Procedural Component Creation**: Dynamic UI updates (like the health cards) use deep nesting and closures instead of dedicated classes.
*   **Magic Numbers**: Numerous hex codes and dimensions remain hardcoded outside of the central config.

## 2. Implementation Strategy

### Phase 1: Modular Extraction
We will move the core classes into a dedicated `ui/` package to isolate concerns.
*   `ui/controller.py`: The `JarvisController` class (The logic hub).
*   `ui/graph_widget.py`: The `PipelineGraphWidget` class (The specialized canvas).
*   `ui/app.py`: The `JarvisApp` class (The main window and layout).
*   `jarvis_client.py`: Becomes a thin entry point that imports and runs `JarvisApp`.

### Phase 2: Sidebar & Card Modularization
Break down the sidebar into manageable sub-components.
*   `VramMonitor`: A dedicated widget class for the VRAM stats and bar.
*   `ModelHealthCard`: A dedicated widget class for individual model status entries, replacing nested closures with class methods.

### Phase 3: MVC Isolation
*   **State Control**: The Controller will provide high-level methods (e.g., `get_active_pipeline_graph()`) so the UI doesn't need to know about `PipelineResolver`.
*   **Async Logging**: Move log tailing from a UI-blocked loop into a Controller-managed background thread that pushes to the UI queue.

### Phase 4: CSS Sweep
Move all remaining hardcoded hex colors and layout dimensions into the `ui` block of `system_config/config.yaml`.

## 3. Verification
*   Execute `python jarvis_client.py` and ensure zero functionality regression.
*   Verify log viewing still functions correctly with the new background tailing.
*   Ensure "Auto Layout" and "Drag & Drop" remain functional after extraction.
