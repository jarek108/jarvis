import os
import yaml
import json
import time
import shutil
import asyncio
import aiohttp
from loguru import logger

import utils
from .pipeline_adapters import get_adapter

class PipelineResolver:
    def __init__(self, project_root, base_dir=None):
        self.project_root = project_root
        # Use provided base_dir (must be absolute) or default to project's pipelines folder
        if base_dir:
            self.base_dir = base_dir if os.path.isabs(base_dir) else os.path.join(project_root, base_dir)
        else:
            self.base_dir = os.path.join(project_root, "pipelines")
            
        self.cal_dir = os.path.join(project_root, "model_calibrations")
        self.registry_path = os.path.join(self.cal_dir, "runtime_registry.json")

    def load_yaml(self, name):
        """Loads a YAML from the configured absolute base_dir."""
        # Ensure we don't have .yaml extension doubled
        clean_name = name.replace(".yaml", "")
        path = os.path.join(self.base_dir, f"{clean_name}.yaml")
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"YAML not found at: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_live_models(self):
        if not os.path.exists(self.registry_path):
            return []
        with open(self.registry_path, "r") as f:
            data = json.load(f)
            return data.get("active_loadout", [])

    def get_model_capabilities(self, model_id, engine):
        """Looks up capabilities in the calibration registry with lenient matching."""
        prefix = "vl_" if engine == "vllm" else ("ol_" if engine == "ollama" else "")
        if engine == "native":
            if "whisper" in model_id.lower(): prefix = "stt_"
            elif "chatterbox" in model_id.lower(): prefix = "tts_"
        
        # Sanitize and normalize target
        target = model_id.lower().split('#')[0]
        if target.startswith("ol_"): target = target[3:]
        if target.startswith("vl_"): target = target[3:]
        target = target.replace(':', '-').replace('/', '--')
        
        # Clean target for fuzzy matching (remove common suffixes)
        clean_target = target.replace('-instruct', '').replace('-fp16', '').replace('-q4_k_m', '').replace('.', '').replace('-', '')

        # 1. Direct match attempt
        cal_path = os.path.join(self.cal_dir, f"{prefix}{target}.yaml")
        if os.path.exists(cal_path):
            with open(cal_path, "r") as f:
                return yaml.safe_load(f).get("capabilities", [])

        # 2. Fuzzy match in calibration directory
        if os.path.exists(self.cal_dir):
            for f in os.listdir(self.cal_dir):
                if f.startswith(prefix) and f.endswith(".yaml"):
                    f_name = f.lower().replace('.yaml', '')[len(prefix):].replace('.', '').replace('-', '')
                    if clean_target in f_name or f_name in clean_target:
                        with open(os.path.join(self.cal_dir, f), "r") as yaml_f:
                            return yaml.safe_load(yaml_f).get("capabilities", [])
        
        # 3. Last resort fallback based on engine
        if engine == "ollama" or engine == "vllm":
            return ["text_in", "text_out"]
        return []

    def resolve(self, pipeline_name, mapping_name=None):
        """
        Binds a pipeline to live models.
        """
        pipeline = self.load_yaml(pipeline_name)
        mapping = self.load_yaml(mapping_name) if mapping_name else None
        live_models = self.get_live_models()
        
        bound_nodes = {}
        # ... [remaining resolve logic remains the same] ...
        for nid in [n['id'] for n in pipeline['nodes'] if n['type'] == 'input']:
            bound_nodes[nid] = next(n for n in pipeline['nodes'] if n['id'] == nid)

        for node in [n for n in pipeline['nodes'] if n['type'] == 'processing']:
            node_id = node['id']
            # Skip resolution for local utility nodes
            if node.get('role') == 'utility':
                bound_nodes[node_id] = node.copy()
                continue
                
            required_caps = node.get('capabilities', [])
            bound_model = None

            if mapping:
                candidates = mapping['bindings'].get(node_id, {}).get('candidates', [])
                for cid in candidates:
                    match = next((m for m in live_models if m['id'] == cid), None)
                    if match and all(c in self.get_model_capabilities(match['id'], match['engine']) for c in required_caps):
                        bound_model = match; break
            else:
                matches = []
                for m in live_models:
                    actual_caps = self.get_model_capabilities(m['id'], m['engine'])
                    if all(c in actual_caps for c in required_caps):
                        matches.append(m)
                if len(matches) == 1: bound_model = matches[0]
                elif len(matches) > 1: raise ValueError(f"Ambiguity for {node_id}: Multiple matches { [m['id'] for m in matches] }.")
                else: raise ValueError(f"No live model satisfies {required_caps} for '{node_id}'.")

            if not bound_model: raise ValueError(f"Resolution failed for node '{node_id}'.")
            
            bn = node.copy()
            bn['binding'] = bound_model
            bound_nodes[node_id] = bn

        logger.info(f"✅ Resolved '{pipeline_name}' ({'AUTO' if not mapping else mapping_name})")
        return bound_nodes

class PipelineExecutor:
    def __init__(self, project_root, dashboard=None):
        self.project_root = project_root
        self.results = {}     # Node-id -> Consolidated results (for UI/debugging)
        self.timings = {}     # Node-id -> {start, end, duration}
        self.trace = []       # Global Flight Recorder (Packet metadata)
        self.dashboard = dashboard
        self.vram_peak = 0.0

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
            adapter = get_adapter(role, self.project_root)
            
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
            # 1. Initialize Input Nodes
            for nid, node in bound_graph.items():
                if node['type'] == 'input':
                    val = scenario_inputs.get(nid) or node.get('path')
                    if val and isinstance(val, str) and os.path.exists(os.path.join(self.project_root, val)):
                        bp = os.path.join(self.project_root, node.get('buffer', f"buffers/{nid}.tmp"))
                        os.makedirs(os.path.dirname(bp), exist_ok=True); shutil.copy(os.path.join(self.project_root, val), bp)
                        val = bp
                    
                    p = {"type": "input_source", "content": val, "ts": time.perf_counter()}
                    self.record_packet(nid, p, "OUT")
                    await queues[nid].put(p); await queues[nid].put(None)

            # 2. Run All Nodes Concurrently
            tasks = []
            for nid, node in bound_graph.items():
                if node['type'] == 'processing':
                    in_qs = {d: queues[d] for d in node.get('inputs', [])}
                    tasks.append(self.execute_node(nid, node, in_qs, queues, session))

            await asyncio.gather(*tasks)
            
        return True
