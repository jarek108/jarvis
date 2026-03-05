# Plan: UI Configuration Refactoring

This document outlines the strategy to decouple UI styling from the core client logic, specifically targeting the `PipelineGraphWidget`. The goal is to move hardcoded magic numbers, colors, and dimensions into the central configuration system.

## 1. Architectural Friction
The `jarvis_client.py` currently contains hardcoded values for node dimensions, edge styling, and color mapping directly within its rendering methods (`draw_graph`, `draw_edge`). This creates a rigid UI that cannot be easily customized without modifying the Python source code. Furthermore, it bypasses the established top-level UI constants (like `ACCENT_COLOR`), creating internal inconsistency.

## 2. Implementation Strategy

### Phase 1: Configuration Schema
We will introduce a `ui` namespace within `system_config/config.yaml` to hold all presentation parameters.

```yaml
ui:
  theme: "dark"
  colors:
    bg: "#0B0F19"
    accent: "#00D1FF"
    text: "#E0E0E0"
    gray: "#2A2F3E"
    success: "#00FF94"
    error: "#FF4B4B"
    warning: "#FFD700"
    purple: "#BF40BF"
  graph:
    node:
      width: 160
      height: 60
      radius: 8
      bg_color: "#12161E"
      selected_bg_color: "#1A202C"
    font:
      primary: ["Consolas", 10, "bold"]
      secondary: ["Consolas", 8, "normal"]
    edge:
      width: 2
      color: "#2A2F3E"
      arrow_shape: [12, 14, 4] # [d1, d2, d3] for Tkinter arrow shape
```

### Phase 2: Python Client Refactoring (`jarvis_client.py`)
1.  **State Management**: Update `JarvisController` to load and hold the `ui` configuration block from the `load_config()` output.
2.  **Widget Initialization**: Pass the `cfg.get('ui')` dictionary to `PipelineGraphWidget` upon instantiation.
3.  **Method Updates**: 
    *   Refactor `draw_graph` to replace magic numbers (`160`, `60`, `#12161E`) with lookups from the config dictionary.
    *   Refactor `draw_edge` to accept and apply the `arrowshape` parameter based on the configuration.
4.  **Global Constants**: Replace the global `# --- UI CONSTANTS ---` block at the top of the file with dynamic lookups from the loaded configuration to ensure single-source-of-truth.

## 3. Verification
*   Modify a value in `system_config/config.yaml` (e.g., change the accent color or node width).
*   Launch `jarvis_client.py` and verify the UI updates without requiring code changes.
