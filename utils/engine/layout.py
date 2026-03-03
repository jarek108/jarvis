import os

class GraphLayoutEngine:
    """
    Topological DAG layout engine.
    Prioritizes straight-line data flow and crossing minimization.
    """
    def __init__(self, node_w=160, node_h=60, min_spacing_y=40):
        self.node_w = node_w
        self.node_h = node_h
        self.min_spacing_y = min_spacing_y

    def calculate_layout(self, bound_graph, canvas_w, canvas_h):
        if not bound_graph: return {}

        # 1. Build Adjacency (Parents)
        adj = {nid: node.get('inputs', []).copy() for nid, node in bound_graph.items()}
        for nid, node in bound_graph.items():
            sys_p = node.get('system_prompt')
            if sys_p: adj[nid].append(sys_p)
        
        # 2. Assign Topological Ranks (X-Columns)
        ranks = {} 
        def get_rank(nid):
            if nid in ranks: return ranks[nid]
            parents = [p for p in adj.get(nid, []) if p in bound_graph]
            if not parents:
                ranks[nid] = 0
                return 0
            r = max([get_rank(p) for p in parents]) + 1
            ranks[nid] = r
            return r

        for nid in bound_graph:
            get_rank(nid)

        max_rank = max(ranks.values()) if ranks else 0
        nodes_by_rank = {r: [] for r in range(max_rank + 1)}
        for nid, r in ranks.items():
            nodes_by_rank[r].append(nid)

        # 3. Position Nodes (Iterative Alignment)
        new_positions = {}
        margin_x = canvas_w / (max_rank + 2)
        start_x = margin_x

        # Rank 0: Even vertical distribution centered in canvas
        r0 = nodes_by_rank[0]
        spacing_y0 = canvas_h / (len(r0) + 1)
        for i, nid in enumerate(r0):
            new_positions[nid] = (start_x, spacing_y0 * (i + 1))

        # Rank 1+: Align with parents and resolve overlaps
        min_dist_y = self.node_h + self.min_spacing_y

        for r in range(1, max_rank + 1):
            nodes = nodes_by_rank[r]
            cx = start_x + (margin_x * r)
            
            # Target Y is the average Y of parents (Barycenter)
            requested = []
            for nid in nodes:
                parents = [p for p in adj.get(nid, []) if p in new_positions]
                if parents:
                    target_y = sum(new_positions[p][1] for p in parents) / len(parents)
                else:
                    target_y = canvas_h / 2
                requested.append({'id': nid, 'y': target_y})

            # Reorder vertical positions to reduce crossing (Sort by parent Y)
            requested.sort(key=lambda x: x['y'])
            
            # Initial placement with overlap detection
            placed_y = []
            for i, req in enumerate(requested):
                y = req['y']
                if i > 0:
                    y = max(y, placed_y[-1] + min_dist_y)
                placed_y.append(y)
            
            # Center the entire rank block around the mean of requested positions
            # This maintains the "straight line" feel as much as possible
            avg_req = sum(r['y'] for r in requested) / len(requested)
            avg_placed = sum(placed_y) / len(placed_y)
            shift = avg_req - avg_placed
            
            for i, req in enumerate(requested):
                final_y = placed_y[i] + shift
                # Final Clamping to avoid nodes leaving canvas
                final_y = max(self.node_h, min(canvas_h - self.node_h, final_y))
                new_positions[req['id']] = (cx, final_y)

        return new_positions
