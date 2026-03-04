import os
import time
import shutil
import asyncio
import aiohttp
from loguru import logger

import utils

class PipelineExecutor:
    def __init__(self, project_root, dashboard=None, session_dir=None):
        self.project_root = project_root
        self.session_dir = session_dir
        self.results = {}     # Node-id -> Consolidated results (for UI/debugging)
        self.timings = {}     # Node-id -> {start, end, duration}
        self.trace = []       # Global Flight Recorder (Packet metadata)
        self.dashboard = dashboard
        self.vram_peak = 0.0

    def resolve_path(self, path, default_filename=None):
        """Resolves a path relative to session_dir if available, otherwise project_root."""
        if not path and not default_filename: return None
        p = path if path else default_filename
        if os.path.isabs(p): return p
        base = self.session_dir if self.session_dir else self.project_root
        return os.path.normpath(os.path.join(base, p))

    def log(self, msg):
        logger.info(msg)
        if self.dashboard: self.dashboard.log(msg)

    def record_packet(self, node_id, packet, direction="OUT"):
        """Records packet envelope to the trace, including content for text modalities."""
        if not packet: return
        self.trace.append({
            "t": time.perf_counter(),
            "node": node_id,
            "dir": direction,
            "type": packet.get("type"),
            "seq": packet.get("seq", 0),
            "content": packet.get("content") if packet.get("type", "").startswith("text") else None,
            "data_len": len(str(packet.get("content", ""))) if packet.get("content") else 0
        })

    async def _proxy_stream(self, node_id, input_queue):
        """Yields packets from a queue and logs them as 'IN' events."""
        while True:
            packet = await input_queue.get()
            if packet is None: break
            self.record_packet(node_id, packet, direction="IN")
            yield packet

    async def _capture_stream(self, node_id, output_queue):
        """Intersects the output queue to record 'OUT' events and consolidate results."""
        class LoggingQueue:
            def __init__(self, target_q, recorder, nid, results):
                self.target_q = target_q
                self.recorder = recorder
                self.nid = nid
                self.results = results
            async def put(self, packet):
                if packet is not None:
                    self.recorder(self.nid, packet, "OUT")
                    if self.nid not in self.results: self.results[self.nid] = []
                    self.results[self.nid].append(packet.get('content'))
                await self.target_q.put(packet)
        return LoggingQueue(output_queue, self.record_packet, node_id, self.results)

    async def execute_node(self, node_id, node, input_queues, output_queues, session):
        """Agnostic node runner using the NodeImplementation system."""
        start_t = time.perf_counter()
        self.trace.append({"t": start_t, "node": node_id, "type": "START"})
        
        try:
            # 1. Setup Data Flow
            in_streams = {
                nid: self._proxy_stream(node_id, q) 
                for nid, q in input_queues.items()
            }
            out_q_wrapped = await self._capture_stream(node_id, output_queues[node_id])

            # 2. Extract Implementation (Binding)
            implementation = node.get('binding')
            if not implementation:
                # If node has no binding, it might be an input provider or a passthrough
                self.log(f"  -> {node_id} (Skipping: No binding)")
                return

            self.log(f"  -> {node_id} (Running {implementation.id})")

            # 3. Track VRAM Peak
            try:
                v = utils.get_gpu_vram_usage()
                if v > self.vram_peak: self.vram_peak = v
            except: pass

            # 4. Merge Config & Execute
            exec_config = node.copy()
            exec_config.update(implementation.config)
            exec_config['scenario_inputs'] = node.get('scenario_inputs', {})
            exec_config['session_dir'] = self.session_dir

            if implementation.execute_fn:
                await implementation.execute_fn(node_id, in_streams, exec_config, out_q_wrapped, session)
            else:
                self.log(f"⚠️ No execute_fn for {node_id}")

            self.timings[node_id] = {
                "start": start_t, 
                "end": time.perf_counter(), 
                "duration": time.perf_counter() - start_t
            }
            self.trace.append({"t": time.perf_counter(), "node": node_id, "type": "FINISH"})
            
        except Exception as e:
            self.log(f"💥 {node_id} failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.trace.append({"t": time.perf_counter(), "node": node_id, "type": "ERROR", "msg": str(e)})
        finally:
            await output_queues[node_id].put(None)

    async def run(self, bound_graph, scenario_inputs):
        """Topological async execution loop. Symmetrical for all node types."""
        self.results, self.timings, self.trace, self.vram_peak = {}, {}, [], 0.0
        queues = {nid: asyncio.Queue() for nid in bound_graph}
        
        # Inject scenario inputs into node configs
        for nid, node in bound_graph.items():
            node['scenario_inputs'] = scenario_inputs

        async with aiohttp.ClientSession() as session:
            tasks = []
            for nid, node in bound_graph.items():
                # Build input queue list
                input_ids = node.get('inputs', []).copy()
                sys_prompt_id = node.get('system_prompt')
                if sys_prompt_id and sys_prompt_id not in input_ids:
                    input_ids.append(sys_prompt_id)
                    
                in_qs = {d: queues[d] for d in input_ids if d in queues}
                tasks.append(self.execute_node(nid, node, in_qs, queues, session))

            await asyncio.gather(*tasks)
            
        return True
