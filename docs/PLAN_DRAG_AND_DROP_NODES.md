# Plan: Drag-and-Drop Pipeline Nodes

This document outlines the implementation strategy for making pipeline nodes interactive and movable within the `PipelineGraphWidget`.

## 1. Objective
Transform the static, tiered graph layout into an interactive canvas where users can manually reposition nodes to better visualize complex data flows.

## 2. Technical Strategy

### Phase 1: State Management
*   **Coordinate Store**: Introduce `self.manual_positions = {}` in `PipelineGraphWidget` to store `(x, y)` overrides for specific node IDs.
*   **Drag State**: Track `self.dragging_node_id` and `self.drag_offset = (dx, dy)` to handle relative movement during the drag operation.

### Phase 2: Event Handling
Bind the following canvas events:
1.  **`<ButtonPress-1>`**: 
    *   Identify if the cursor is over a node bounding box.
    *   If yes, initiate drag state and store the offset between the cursor and the node center.
2.  **`<B1-Motion>`**: 
    *   Update the `(x, y)` in `self.manual_positions` based on current cursor position + offset.
    *   Trigger `draw_graph()` for real-time visual feedback.
3.  **`<ButtonRelease-1>`**: 
    *   Finalize position.
    *   (Optional) Implement grid-snapping (e.g., 20px) for alignment.
    *   Clear drag state.

### Phase 3: Layout Logic Refactoring
Update `draw_graph()` to follow this precedence:
1.  **Calculated Default**: Perform the existing tier-based layout calculation.
2.  **Manual Override**: If a node exists in `self.manual_positions`, use those coordinates instead of the defaults.
3.  **Clamping**: Ensure manually moved nodes stay within the visible canvas boundaries, even during window resizing.

## 3. Verification
*   Drag a source node to the bottom of the screen; verify all connected edges (arrows) update their paths in real-time.
*   Verify that clicking a node still selects it (for log viewing) without interfering with the drag start.
*   Verify that switching pipelines clears the manual positions (or attempts to preserve them if IDs match).
