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

from utils.config import get_project_root

class PipelineResolver:
    def __init__(self, project_root=None, base_dir=None):
        self.project_root = project_root if project_root else get_project_root()
        # ISOLATION: Define explicit directories for different graph artifacts
        if base_dir:
            self.pipelines_dir = base_dir if os.path.isabs(base_dir) else os.path.join(self.project_root, base_dir)
        else:
            self.pipelines_dir = os.path.join(self.project_root, "pipelines")
            
        self.strategies_dir = os.path.join(self.project_root, "strategies")
        self.cal_dir = os.path.join(self.project_root, "model_calibrations")
        self.registry_path = os.path.join(self.cal_dir, "runtime_registry.json")

    def load_yaml(self, name, folder=None):
        """Loads a YAML from the configured absolute base_dir or a specified folder."""
        clean_name = name.replace(".yaml", "")
        base = folder if folder else self.pipelines_dir
        path = os.path.join(base, f"{clean_name}.yaml")
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"YAML not found at: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_live_models(self):
        if not os.path.exists(self.registry_path):
            return {"models": [], "external": 0.0}
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content: return {"models": [], "external": 0.0}
                data = json.loads(content)
                models = data.get("active_loadout", [])
                external = data.get("system_external_vram", 0.0)
                for m in models:
                    try:
                        m['capabilities'] = self.get_model_capabilities(m['id'], m['engine'])
                    except Exception as e:
                        logger.error(f"Error getting caps for {m['id']}: {e}")
                        m['capabilities'] = []
                return {"models": models, "external": external}
        except Exception as e:
            logger.error(f"Error reading registry: {e}")
            return {"models": [], "external": 0.0}

    def get_model_capabilities(self, model_id, engine):
        """Looks up capabilities in the calibration registry."""
        from .config import safe_filename
        
        caps = []
        safe_id = safe_filename(model_id)
        
        # 1. Direct match using standard naming convention
        cal_path = os.path.join(self.cal_dir, f"{engine}_{safe_id}.yaml")
        
        # Fallback to legacy prefix format if migration is incomplete
        if not os.path.exists(cal_path):
            legacy_prefix = "vl_" if engine == "vllm" else ("ol_" if engine == "ollama" else "")
            if engine == "native":
                if "whisper" in model_id.lower(): legacy_prefix = "stt_"
                elif "chatterbox" in model_id.lower(): legacy_prefix = "tts_"
            cal_path = os.path.join(self.cal_dir, f"{legacy_prefix}{safe_id}.yaml")
            
        if os.path.exists(cal_path):
            with open(cal_path, "r") as f:
                caps = yaml.safe_load(f).get("capabilities", [])

        # 2. Engine-based defaults (ENSURE IN/OUT are present)
        if engine == "ollama" or engine == "vllm":
            if not caps: caps = ["text_in", "text_out"]
            if "vl" in model_id.lower() and "image_in" not in caps:
                caps.append("image_in")
        
        return caps

    def resolve(self, pipeline_name, strategy_name=None):
        """
        Binds a pipeline to live models using a specific strategy.
        """
        pipeline = self.load_yaml(pipeline_name)
        strategy = self.load_yaml(strategy_name, folder=self.strategies_dir) if strategy_name else None
        live_models = self.get_live_models().get("models", [])
        
        bound_nodes = {}
        # Identify entry points (input or source nodes)
        for nid in [n['id'] for n in pipeline['nodes'] if n['type'] in ['input', 'source']]:
            bound_nodes[nid] = next(n for n in pipeline['nodes'] if n['id'] == nid)

        for node in [n for n in pipeline['nodes'] if n['type'] in ['processing', 'sink', 'utility']]:
            node_id = node['id']
            # Skip resolution for local utility or sink nodes (handled at edge)
            if node.get('role') in ['utility', 'memory', 'sink'] or node.get('type') in ['sink', 'utility']:
                bound_nodes[node_id] = node.copy()
                continue
                
            required_caps = node.get('capabilities', [])
            bound_model = None

            if strategy:
                candidates = strategy['bindings'].get(node_id, {}).get('candidates', [])
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
                else: raise ValueError(f"ARCH_MISMATCH: No model satisfies {required_caps} for node '{node_id}'.")

            if not bound_model: raise ValueError(f"Resolution failed for node '{node_id}'.")
            
            bn = node.copy()
            bn['binding'] = bound_model
            bound_nodes[node_id] = bn

        logger.info(f"✅ Resolved '{pipeline_name}' ({'AUTO' if not strategy else strategy_name})")
        return bound_nodes

    def check_runnability(self, pipeline_name, strategy_name=None, external_health=None):
        """
        Proactively verifies if a pipeline is runnable based on live system health.
        Returns: {runnable: bool, errors: list, map: dict}
        """
        report = {"runnable": True, "errors": [], "map": {}}
        
        # 1. Load the raw pipeline first to populate the map even if resolution fails
        try:
            raw_pipeline = self.load_yaml(pipeline_name)
            for node in raw_pipeline['nodes']:
                report["map"][node['id']] = {"status": "UNRESOLVED", "model": "None"}
        except Exception as e:
            return {"runnable": False, "errors": [f"Pipeline Load Error: {e}"], "map": {}}

        # 2. Try to Resolve the graph (Detects ARCH_MISMATCH or strategy errors)
        try:
            bound_graph = self.resolve(pipeline_name, strategy_name)
        except Exception as e:
            report["runnable"] = False
            report["errors"].append(f"Resolution Error: {e}")
            return report

        # 3. Check Live Health for all bound ports
        if external_health:
            health = external_health
        else:
            from .infra import get_system_health
            health = get_system_health()
        
        for nid, node in bound_graph.items():
            role = node.get('role', '').lower()
            if node['type'] == 'processing' and role not in ['utility', 'memory']:
                binding = node.get('binding')
                if not binding:
                    report["runnable"] = False
                    report["errors"].append(f"Node '{nid}' is unbound.")
                    continue
                
                port = binding.get('port')
                svc_info = health.get(port, {"status": "OFF", "info": None})
                
                report["map"][nid] = {
                    "status": svc_info['status'],
                    "model": binding['id'],
                    "port": port
                }
                
                if svc_info['status'] != "ON":
                    report["runnable"] = False
                    report["errors"].append(f"Service for '{nid}' ({binding['id']} on port {port}) is {svc_info['status']}.")
            
            else:
                # Utility, Memory, or Sink nodes
                report["map"][nid] = {"status": "LOCAL", "role": role or node['type']}

        return report

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
            # 1. Initialize Source/Input Nodes
            for nid, node in bound_graph.items():
                if node['type'] in ['input', 'source']:
                    val = scenario_inputs.get(nid) or node.get('path')
                    if val and isinstance(val, str) and os.path.exists(os.path.join(self.project_root, val)):
                        bp = os.path.join(self.project_root, node.get('buffer', f"buffers/{nid}.tmp"))
                        os.makedirs(os.path.dirname(bp), exist_ok=True); shutil.copy(os.path.join(self.project_root, val), bp)
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
