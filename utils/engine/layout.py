import os

class GraphLayoutEngine:
    """
    Topological DAG layout engine (Vertical Flow: Top to Bottom).
    Prioritizes straight-line data flow and crossing minimization.
    """
    def __init__(self, node_w=160, node_h=60, min_spacing_x=40):
        self.node_w = node_w
        self.node_h = node_h
        self.min_spacing_x = min_spacing_x

    def calculate_layout(self, bound_graph, canvas_w, canvas_h):
        if not bound_graph: return {}

        # 1. Build Adjacency (Parents)
        adj = {nid: node.get('inputs', []).copy() for nid, node in bound_graph.items()}
        for nid, node in bound_graph.items():
            sys_p = node.get('system_prompt')
            if sys_p: adj[nid].append(sys_p)
        
        # 2. Assign Topological Ranks (Y-Rows)
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
        margin_y = canvas_h / (max_rank + 2)
        start_y = margin_y

        # Rank 0: Even horizontal distribution centered in canvas
        r0 = nodes_by_rank[0]
        spacing_x0 = canvas_w / (len(r0) + 1)
        for i, nid in enumerate(r0):
            new_positions[nid] = (spacing_x0 * (i + 1), start_y)

        # Rank 1+: Align with parents and resolve overlaps
        min_dist_x = self.node_w + self.min_spacing_x

        for r in range(1, max_rank + 1):
            nodes = nodes_by_rank[r]
            cy = start_y + (margin_y * r)
            
            # Target X is the average X of parents (Barycenter)
            requested = []
            for nid in nodes:
                parents = [p for p in adj.get(nid, []) if p in new_positions]
                if parents:
                    target_x = sum(new_positions[p][0] for p in parents) / len(parents)
                else:
                    target_x = canvas_w / 2
                requested.append({'id': nid, 'x': target_x})

            # Reorder horizontal positions to reduce crossing (Sort by parent X)
            requested.sort(key=lambda x: x['x'])
            
            # Initial placement with overlap detection
            placed_x = []
            for i, req in enumerate(requested):
                x = req['x']
                if i > 0:
                    x = max(x, placed_x[-1] + min_dist_x)
                placed_x.append(x)
            
            # Center the entire rank block around the mean of requested positions
            avg_req = sum(r['x'] for r in requested) / len(requested)
            avg_placed = sum(placed_x) / len(placed_x)
            shift = avg_req - avg_placed
            
            for i, req in enumerate(requested):
                final_x = placed_x[i] + shift
                # Final Clamping to avoid nodes leaving canvas
                final_x = max(self.node_w, min(canvas_w - self.node_w, final_x))
                new_positions[req['id']] = (final_x, cy)

        return new_positions
