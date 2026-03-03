import os
import sys
import customtkinter as ctk
from utils.engine import GraphLayoutEngine

class PipelineGraphWidget(ctk.CTkFrame):
    def __init__(self, master, ui_config, initial_positions=None, **kwargs):
        super().__init__(master, **kwargs)
        self.ui_cfg = ui_config
        self.canvas = ctk.CTkCanvas(self, bg=self.ui_cfg['colors']['bg'], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.nodes = {}
        self.edges = []
        
        # Interaction State
        self.manual_positions = initial_positions or {} # nid -> (x, y)
        self.dragging_node_id = None
        self.drag_offset = (0, 0)
        self.has_dragged = False
        
        self.canvas.bind("<Configure>", self.on_resize)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        self.on_node_click_callback = None
        self.on_positions_changed_callback = None
        self.selected_node_id = None

    def on_resize(self, event):
        self.draw_graph()

    def set_graph_data(self, bound_graph, manual_positions=None):
        self.bound_graph = bound_graph
        self.manual_positions = manual_positions or {}
        self.draw_graph()

    def apply_auto_layout(self):
        """Calculates an optimized layout using the delegated GraphLayoutEngine."""
        if not hasattr(self, 'bound_graph') or not self.bound_graph: return
        
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1: return
        
        node_cfg = self.ui_cfg['graph']['node']
        engine = GraphLayoutEngine(node_w=node_cfg['width'], node_h=node_cfg['height'])
        
        new_positions = engine.calculate_layout(self.bound_graph, w, h)
        self.manual_positions = new_positions
        self.draw_graph()
        if self.on_positions_changed_callback:
            self.on_positions_changed_callback(new_positions)

    def on_press(self, event):
        x, y = event.x, event.y
        self.dragging_node_id = None
        self.has_dragged = False
        
        for nid, data in self.nodes.items():
            bx1, by1, bx2, by2 = data['bbox']
            if bx1 <= x <= bx2 and by1 <= y <= by2:
                self.dragging_node_id = nid
                self.drag_offset = (data['x'] - x, data['y'] - y)
                break

    def on_drag(self, event):
        if not self.dragging_node_id: return
        self.has_dragged = True
        
        new_x = event.x + self.drag_offset[0]
        new_y = event.y + self.drag_offset[1]
        
        # Clamp to canvas
        w, h = self.winfo_width(), self.winfo_height()
        node_cfg = self.ui_cfg['graph']['node']
        nw, nh = node_cfg['width'], node_cfg['height']
        
        new_x = max(nw/2, min(w - nw/2, new_x))
        new_y = max(nh/2, min(h - nh/2, new_y))
        
        self.manual_positions[self.dragging_node_id] = (new_x, new_y)
        self.draw_graph()

    def on_release(self, event):
        if not self.has_dragged and self.dragging_node_id:
            # Handle selection if it was just a click
            if self.selected_node_id == self.dragging_node_id:
                self.selected_node_id = None
            else:
                self.selected_node_id = self.dragging_node_id
            self.draw_graph()
            if self.on_node_click_callback:
                self.on_node_click_callback(self.selected_node_id)
        
        if self.has_dragged and self.on_positions_changed_callback:
            self.on_positions_changed_callback(self.manual_positions)

        self.dragging_node_id = None
        self.has_dragged = False

    def draw_rounded_rect(self, x, y, w, h, r, color, outline_color="", outline_width=0):
        # Create a rounded rectangle using lines and arcs
        points = [
            x+r, y,
            x+w-r, y,
            x+w, y,
            x+w, y+r,
            x+w, y+h-r,
            x+w, y+h,
            x+w-r, y+h,
            x+r, y+h,
            x, y+h,
            x, y+h-r,
            x, y+r,
            x, y
        ]
        return self.canvas.create_polygon(points, fill=color, outline=outline_color, width=outline_width, smooth=True)

    def draw_edge(self, x1, y1, x2, y2, color=None, style=None):
        if color is None: color = self.ui_cfg['graph']['edge']['color']
        width = self.ui_cfg['graph']['edge']['width']
        ashape = tuple(self.ui_cfg['graph']['edge']['arrow_shape'])
        
        # Draw a vertical "stepped" line with an arrowhead
        ctrl_y = (y1 + y2) / 2
        return self.canvas.create_line(x1, y1, x1, ctrl_y, x2, ctrl_y, x2, y2, fill=color, width=width, arrow=ctk.LAST, arrowshape=ashape, smooth=True, dash=style)

    def draw_label(self, x1, y1, x2, y2, label, color=None):
        if not label: return
        if color is None: color = self.ui_cfg['graph']['edge']['color']
        
        # Midpoint of the vertical flow
        mid_x = (x1 + x2) / 2
        ctrl_y = (y1 + y2) / 2
        f_sec = tuple(self.ui_cfg['graph']['font']['secondary'])
        
        # Create text first to measure it
        text_id = self.canvas.create_text(mid_x, ctrl_y, text=label.upper(), fill="#B0B0B0", font=f_sec)
        bbox = self.canvas.bbox(text_id)
        
        # Draw a background "pill" with generous padding
        px, py = 6, 3
        rect_id = self.canvas.create_rectangle(bbox[0]-px, bbox[1]-py, bbox[2]+px, bbox[3]+py, fill=self.ui_cfg['colors']['bg'], outline=color, width=1)
        
        # Ensure text is on top of its own rectangle
        self.canvas.tag_raise(text_id, rect_id)

    def draw_graph(self):
        self.canvas.delete("all")
        if not hasattr(self, 'bound_graph') or not self.bound_graph:
            self.canvas.create_text(self.winfo_width()/2, self.winfo_height()/2, text="No Pipeline Loaded", fill=self.ui_cfg['colors']['gray'], font=("Consolas", 14))
            return

        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1: return

        # 1. Use Layout Engine for "Defaults" if no manual positions exist
        node_cfg = self.ui_cfg['graph']['node']
        node_w, node_h, r = node_cfg['width'], node_cfg['height'], node_cfg['radius']
        
        engine = GraphLayoutEngine(node_w=node_w, node_h=node_h)
        default_positions = engine.calculate_layout(self.bound_graph, w, h)
        
        self.nodes = {}
        for nid, node in self.bound_graph.items():
            cx, cy = self.manual_positions.get(nid, default_positions.get(nid, (w/2, h/2)))
            
            self.nodes[nid] = {
                'x': cx, 'y': cy,
                'bbox': (cx - node_w/2, cy - node_h/2, cx + node_w/2, cy + node_h/2),
                'data': node
            }

        # 2. PASS 1: Draw Edge Lines
        label_queue = [] # (x1, y1, x2, y2, label, color)
        
        for nid, ndata in self.nodes.items():
            node = ndata['data']
            dest_caps = node.get('capabilities', [])
            
            # Standard Inputs
            inputs = node.get('inputs', [])
            for src_id in inputs:
                if src_id in self.nodes:
                    src = self.nodes[src_id]
                    src_node = src['data']
                    src_caps = src_node.get('capabilities', [])
                    
                    # Infer Data Type
                    src_outs = {c.replace("_out", "") for c in src_caps if c.endswith("_out")}
                    dest_ins = {c.replace("_in", "") for c in dest_caps if c.endswith("_in")}
                    common = src_outs.intersection(dest_ins)
                    dtype = list(common)[0] if common else None
                    if not dtype and (src_node.get('role') == 'memory' or node.get('role') == 'memory'): dtype = "text"

                    dash = (4, 4) if node.get('role') == 'memory' else None
                    # From BOTTOM of source to TOP of destination
                    x1, y1 = src['x'], src['bbox'][3]
                    x2, y2 = ndata['x'], ndata['bbox'][1]
                    
                    self.draw_edge(x1, y1, x2, y2, style=dash)
                    if dtype: label_queue.append((x1, y1, x2, y2, dtype, None))
            
            # System Prompt Connection
            sys_prompt_id = node.get('system_prompt')
            if sys_prompt_id and sys_prompt_id in self.nodes:
                src = self.nodes[sys_prompt_id]
                x1, y1 = src['x'], src['bbox'][3]
                x2, y2 = ndata['x'], ndata['bbox'][1]
                
                self.draw_edge(x1, y1, x2, y2, color=self.ui_cfg['colors']['purple'], style=(2, 2))
                label_queue.append((x1, y1, x2, y2, "text", self.ui_cfg['colors']['purple']))

        # 3. PASS 2: Draw Labels (On top of all lines)
        for args in label_queue:
            self.draw_label(*args)

        # 4. Draw Nodes (On top of everything)
        for nid, ndata in self.nodes.items():
            node = ndata['data']
            cx, cy = ndata['x'], ndata['y']
            bx1, by1, bx2, by2 = ndata['bbox']
            
            # Styling based on state and selection
            is_selected = (nid == self.selected_node_id)
            bg_color = node_cfg['bg_color']
            
            ntype = node.get('type')
            role = node.get('role', ntype)
            binding = node.get('binding')
            
            # Color Coding Strategy
            if ntype == 'source':
                is_sys_prompt = any(n.get('system_prompt') == nid for n in self.bound_graph.values())
                outline_color = self.ui_cfg['colors']['purple'] if is_sys_prompt else self.ui_cfg['colors']['accent']
            elif ntype == 'sink':
                outline_color = self.ui_cfg['colors']['warning']
            elif ntype == 'processing':
                if role == 'utility':
                    outline_color = self.ui_cfg['colors']['gray']
                elif not binding:
                    outline_color = self.ui_cfg['colors']['error']
                else:
                    outline_color = self.ui_cfg['colors']['success']
            else:
                outline_color = self.ui_cfg['colors']['gray']

            outline_w = 2.5 if is_selected else 1.5
            if is_selected: bg_color = node_cfg.get('selected_bg_color', "#1A202C")

            self.draw_rounded_rect(bx1, by1, node_w, node_h, r, bg_color, outline_color, outline_w)
            
            # Label Selection (favor YAML display_name, fallback to cleaned ID)
            if 'display_name' in node:
                display_name = node['display_name'].upper()
            else:
                display_name = nid
                if display_name.startswith("input_"): display_name = display_name[6:]
                if display_name.startswith("output_"): display_name = display_name[7:]
                if display_name.startswith("proc_"): display_name = display_name[5:]
                
                # Internal common abbreviations
                abbrevs = {"conversation_memory": "conv mem", "system_prompt": "sys prompt"}
                display_name = abbrevs.get(display_name, display_name).replace("_", " ").upper()
            
            # Text Content
            f_pri, f_sec = tuple(self.ui_cfg['graph']['font']['primary']), tuple(self.ui_cfg['graph']['font']['secondary'])
            self.canvas.create_text(cx, cy - 10, text=display_name, fill="#FFFFFF", font=f_pri)
            
            if binding:
                subtext = binding.get('id', 'Unknown')
                self.canvas.create_text(cx, cy + 10, text=subtext[:22], fill=self.ui_cfg['colors']['success'], font=f_sec)
            elif ntype == 'processing' and role != 'utility':
                self.canvas.create_text(cx, cy + 10, text="[UNBOUND]", fill=self.ui_cfg['colors']['error'], font=f_pri)
            else:
                # Only show role if it's not redundant
                role_text = f"[{role.upper()}]" if role != ntype else ""
                self.canvas.create_text(cx, cy + 10, text=role_text, fill=self.ui_cfg['colors']['gray'], font=f_sec)
