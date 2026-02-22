import asyncio
import json
import os
import subprocess
import time
import websockets
import logging
import sys
import yaml
import argparse

# Ensure root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import utils

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("modular_e2e")

TIMEOUT = 15.0 # Increased for real-model responses

class ModularScenarioRunner:
    def __init__(self, port=8005, plumbing=True):
        self.port = port
        self.plumbing = plumbing
        self.proc = None
        self.uri = f"ws://127.0.0.1:{port}"

    def start_backend(self):
        logger.info(f"🚀 Spawning Backend (Plumbing={self.plumbing}) on port {self.port}...")
        cmd = [sys.executable, "backend/main.py", "--port", str(self.port)]
        if self.plumbing: cmd.append("--stub")
        
        # Use a log file for the backend
        with open("tests/modular_backend.log", "w", encoding="utf-8") as f:
            self.proc = subprocess.Popen(cmd, cwd=project_root, stdout=f, stderr=f)
        time.sleep(3) # Initial boot

    def stop_backend(self):
        if self.proc:
            logger.info("🛑 Cleaning up processes...")
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except: self.proc.kill()
            if not self.plumbing:
                utils.kill_all_jarvis_services()

    async def execute_scenario(self, ws, name, data):
        logger.info(f"🏃 Running Scenario: {name}")
        turns = data.get('turns', [])
        
        for i, turn in enumerate(turns):
            # 1. Send Phase
            if 'send' in turn:
                await ws.send(json.dumps(turn['send']))
            elif 'send_binary' in turn:
                audio_path = os.path.join(project_root, turn['send_binary'])
                if not os.path.exists(audio_path):
                    raise Exception(f"Audio file missing: {audio_path}")
                with open(audio_path, "rb") as f:
                    await ws.send(f.read())

            # 2. Expect Phase
            expectations = turn.get('expect', [])
            for expected in expectations:
                start_t = time.time()
                received = False
                while time.time() - start_t < TIMEOUT:
                    raw = await asyncio.wait_for(ws.recv(), TIMEOUT)
                    if isinstance(raw, str):
                        msg = json.loads(raw)
                        if msg.get("type") == expected["type"]:
                            match = True
                            for k, v in expected.items():
                                if k != "label" and msg.get(k) != v:
                                    match = False; break
                            if match:
                                logger.info(f"   ✅ Received expected {expected['type']}" + (f" ({expected.get('role', '')})" if 'role' in expected else ""))
                                received = True; break
                    else:
                        if expected["type"] == "binary":
                            logger.info(f"   ✅ Received expected binary audio ({len(raw)} bytes)")
                            received = True; break
                
                if not received:
                    raise Exception(f"Timeout waiting for expectation: {expected}")

            # 3. Wait for State (Optional)
            if 'wait_state' in turn:
                target = turn['wait_state']
                start_t = time.time()
                reached = False
                while time.time() - start_t < TIMEOUT:
                    raw = await asyncio.wait_for(ws.recv(), TIMEOUT)
                    if isinstance(raw, str):
                        msg = json.loads(raw)
                        if msg.get("type") == "status" and msg.get("state") == target:
                            reached = True; break
                if not reached:
                    raise Exception(f"Timed out waiting for state: {target}")

    async def run_plan(self, plan_path):
        # Initialize Session
        from test_utils import init_session
        session_dir, session_id = init_session(plan_path)
        logger.info(f"📂 Session initialized: {session_id}")
        logger.info(f"📁 Artifacts: {session_dir}")

        with open(plan_path, "r") as f:
            plan = yaml.safe_load(f)
        
        scenario_db_path = os.path.join(project_root, "tests", "modular", "scenarios.yaml")
        with open(scenario_db_path, "r") as f:
            scenarios_db = yaml.safe_load(f)

        results = []
        try:
            async with websockets.connect(self.uri) as ws:
                logger.info("✅ Connected to Backend.")
                
                # Global Init
                await ws.send(json.dumps({"type": "session_init", "session_id": session_id}))
                await ws.recv() # Skip CONNECTED

                blocks = plan.get('execution', [])
                for block in blocks:
                    op_mode = block.get('operation_mode', 'text_chat')
                    loadouts = block.get('loadouts', [[]])
                    scenarios = block.get('scenarios', [])

                    for loadout in loadouts:
                        logger.info(f"🧬 Testing Mode: {op_mode} | Loadout: {loadout}")
                        
                        # 1. Configure backend for this specific 3-way pair
                        await ws.send(json.dumps({
                            "type": "config", 
                            "mode": op_mode,
                            "loadout": loadout
                        }))
                        
                        # 2. Wait for READY (Handle Loading)
                        ready = False
                        start_t = time.time()
                        while time.time() - start_t < 300: # Long wait for real models
                            raw = await asyncio.wait_for(ws.recv(), TIMEOUT)
                            msg = json.loads(raw)
                            if msg.get("type") == "status" and msg.get("state") == "READY":
                                ready = True; break
                            elif msg.get("type") == "error":
                                raise Exception(f"Backend reported error: {msg.get('message')}")
                        
                        if not ready:
                            results.append((f"{op_mode} @ {loadout}", False, "Backend failed to reach READY"))
                            continue

                        # 3. Run requested scenarios
                        for s_name in scenarios:
                            if s_name not in scenarios_db:
                                logger.warning(f"⚠️ Scenario {s_name} not found in database.")
                                continue
                            
                            try:
                                await self.execute_scenario(ws, s_name, scenarios_db[s_name])
                                results.append((f"{op_mode}:{s_name}", True, None))
                            except Exception as e:
                                results.append((f"{op_mode}:{s_name}", False, str(e)))

            # Summary
            print("\n" + "="*60)
            print(f"{'JARVIS INTEGRATION TEST SUMMARY':^60}")
            print("="*60)
            all_pass = True
            for name, success, err in results:
                status = "✅ PASS" if success else "❌ FAIL"
                print(f"{name:<40}: {status}")
                if not success:
                    print(f"   ↳ Error: {err}")
                    all_pass = False
            print("="*60)
            
            if not all_pass: sys.exit(1)

        except Exception as e:
            logger.error(f"💥 CRITICAL RUNNER ERROR: {e}")
            sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis System Integration Runner")
    parser.add_argument("plan", type=str, help="Path to a modular plan YAML")
    parser.add_argument("--plumbing", action="store_true", help="Use stub models for logic verification")
    parser.add_argument("--port", type=int, default=8005)
    args = parser.parse_args()

    runner = ModularScenarioRunner(port=args.port, plumbing=args.plumbing)
    try:
        runner.start_backend()
        asyncio.run(runner.run_plan(args.plan))
    finally:
        runner.stop_backend()
