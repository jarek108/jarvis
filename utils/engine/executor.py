import os
import time
import shutil
import asyncio
import aiohttp
from loguru import logger

import utils
from ..pipeline_adapters import get_adapter

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
        """Records packet envelope to the trace without parsing content."""
        self.trace.append({
            "t": time.perf_counter(),
            "node": node_id,
            "dir": direction,
            "type": packet.get("type"),
            "seq": packet.get("seq", 0),
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
        """Agnostic node runner using the Adapter Registry."""
        start_t = time.perf_counter()
        self.trace.append({"t": start_t, "node": node_id, "type": "START"})
        
        try:
            # 1. Setup Data Flow (Multi-Input Support)
            in_streams = {
                nid: self._proxy_stream(node_id, q) 
                for nid, q in input_queues.items()
            }
            out_q_wrapped = await self._capture_stream(node_id, output_queues[node_id])

            # 2. Get Specialized Adapter
            role = node.get('role', 'llm')
            adapter = get_adapter(role, self.project_root, session_dir=self.session_dir)
            
            self.log(f"  -> {node_id} (Running {role} adapter)")

            # 3. Track VRAM Peak
            try:
                v = utils.get_gpu_vram_usage()
                if v > self.vram_peak: self.vram_peak = v
            except: pass

            # 4. Execute
            await adapter.run(node_id, node, in_streams, out_q_wrapped, session)

            self.timings[node_id] = {
                "start": start_t, 
                "end": time.perf_counter(), 
                "duration": time.perf_counter() - start_t
            }
            self.trace.append({"t": time.perf_counter(), "node": node_id, "type": "FINISH"})
            
        except Exception as e:
            self.log(f"💥 {node_id} failed: {e}")
            self.trace.append({"t": time.perf_counter(), "node": node_id, "type": "ERROR", "msg": str(e)})
        finally:
            await output_queues[node_id].put(None)

    async def run(self, bound_graph, scenario_inputs):
        """Topological async execution loop."""
        self.results, self.timings, self.trace, self.vram_peak = {}, {}, [], 0.0
        queues = {nid: asyncio.Queue() for nid in bound_graph}
        
        async with aiohttp.ClientSession() as session:
            # 1. Initialize Source/Input Nodes
            for nid, node in bound_graph.items():
                if node['type'] in ['input', 'source']:
                    val = scenario_inputs.get(nid) or node.get('path')
                    
                    # Resolve input path (e.g. pipelines/prompts/sts_persona.txt)
                    if val and isinstance(val, str):
                        # Try relative to project root first (standard for prompts/tests data)
                        p_abs = os.path.join(self.project_root, val)
                        if not os.path.exists(p_abs):
                            # Maybe it was moved to system_config/pipelines/prompts?
                            if val.startswith("pipelines/prompts/"):
                                p_abs = os.path.join(self.project_root, "system_config", val)
                        
                        if os.path.exists(p_abs):
                            # Provision buffer in session_dir
                            bp = self.resolve_path(node.get('buffer'), f"{nid}.tmp")
                            os.makedirs(os.path.dirname(bp), exist_ok=True)
                            shutil.copy(p_abs, bp)
                            val = bp
                    
                    self.results[nid] = val
                    p = {"type": "input_source", "content": val, "ts": time.perf_counter()}
                    self.record_packet(nid, p, "OUT")
                    await queues[nid].put(p); await queues[nid].put(None)

            # 2. Run Processing and Sink Nodes Concurrently
            tasks = []
            for nid, node in bound_graph.items():
                if node['type'] in ['processing', 'sink']:
                    in_qs = {d: queues[d] for d in node.get('inputs', [])}
                    tasks.append(self.execute_node(nid, node, in_qs, queues, session))

            await asyncio.gather(*tasks)
            
        return True
