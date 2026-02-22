import asyncio
import json
import os
import subprocess
import time
import websockets
import logging
import sys

# Ensure root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("e2e_runner")

TIMEOUT = 10.0 

class E2ETestSuite:
    def __init__(self, port=8005):
        self.port = port
        self.proc = None
        self.uri = f"ws://127.0.0.1:{port}"

    def start_backend(self):
        logger.info(f"🚀 Spawning Backend Stub on port {self.port}...")
        cmd = [sys.executable, "backend/main.py", "--stub", "--port", str(self.port)]
        # Directing output to a file for inspection
        with open("tests/e2e_backend.log", "w") as f:
            self.proc = subprocess.Popen(cmd, cwd=project_root, stdout=f, stderr=f)
        time.sleep(3) 

    def stop_backend(self):
        if self.proc:
            logger.info("🛑 Cleaning up processes...")
            self.proc.terminate()
            try: self.proc.wait(timeout=2)
            except: self.proc.kill()

    async def run_all(self):
        results = []
        try:
            async with websockets.connect(self.uri) as ws:
                logger.info("✅ Connected to Backend.")
                
                # 1. Text Chat Test
                results.append(await self.test_step("Text Chat", lambda: self.test_text_chat(ws)))
                
                # 2. Mode Switch Test
                results.append(await self.test_step("Mode Switching", lambda: self.test_mode_switching(ws)))
                
                # 3. Audio Trigger Test
                results.append(await self.test_step("Audio Trigger", lambda: self.test_sts_audio_trigger(ws)))
            
            print("\n" + "="*40)
            print(f"{'MODULAR E2E TEST SUMMARY':^40}")
            print("="*40)
            all_pass = True
            for name, success, err in results:
                status = "✅ PASS" if success else f"❌ FAIL"
                print(f"{name:<25}: {status}")
                if not success:
                    print(f"   ↳ Error: {err}")
                    all_pass = False
            print("="*40)
            
            if not all_pass: sys.exit(1)
        except Exception as e:
            logger.error(f"💥 CRITICAL RUNNER ERROR: {e}")
            sys.exit(1)

    async def test_step(self, name, func_with_ws):
        logger.info(f"🏃 Running: {name}")
        try:
            await func_with_ws()
            return name, True, None
        except Exception as e:
            return name, False, str(e)

    async def test_text_chat(self, ws):
        await ws.send(json.dumps({"type": "session_init", "session_id": "e2e_text"}))
        raw = await asyncio.wait_for(ws.recv(), TIMEOUT)
        if json.loads(raw).get("state") != "CONNECTED":
            raise Exception("Failed to connect session")
        
        await ws.send(json.dumps({"type": "config", "mode": "text"}))
        # Wait for READY
        ready = False
        start_t = time.time()
        while time.time() - start_t < TIMEOUT:
            msg = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT))
            if msg.get("type") == "status" and msg.get("state") == "READY":
                ready = True; break
        if not ready: raise Exception("Did not reach READY state for 'text' mode")
        
        await ws.send(json.dumps({"type": "message", "content": "Hello"}))
        
        found = False
        start_t = time.time()
        while time.time() - start_t < TIMEOUT:
            msg = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT))
            if msg.get("type") == "log" and msg.get("role") == "assistant":
                found = True; break
        if not found: raise Exception("No assistant response received")

    async def test_mode_switching(self, ws):
        await ws.send(json.dumps({"type": "config", "mode": "sts"}))
        ready = False
        start_t = time.time()
        while time.time() - start_t < TIMEOUT:
            msg = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT))
            if msg.get("type") == "status" and msg.get("state") == "READY":
                ready = True; break
        if not ready: raise Exception("Failed to switch to STS mode")

    async def test_sts_audio_trigger(self, ws):
        # Send binary data (1.5s of audio)
        await ws.send(b"\x00" * 48000)
        
        thinking = False
        start_t = time.time()
        while time.time() - start_t < TIMEOUT:
            raw = await asyncio.wait_for(ws.recv(), TIMEOUT)
            if isinstance(raw, str):
                msg = json.loads(raw)
                if msg.get("type") == "status" and msg.get("state") == "THINKING":
                    thinking = True; break
        if not thinking: raise Exception("Binary stream did not trigger THINKING state")

if __name__ == "__main__":
    suite = E2ETestSuite()
    try:
        suite.start_backend()
        asyncio.run(suite.run_all())
    finally:
        suite.stop_backend()
