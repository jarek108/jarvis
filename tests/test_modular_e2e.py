import asyncio
import json
import os
import subprocess
import time
import pytest
import websockets
import logging

# Ensure root is in path
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_e2e")

class BackendFixture:
    def __init__(self, port=8004):
        self.port = port
        self.proc = None

    def start(self):
        cmd = [sys.executable, "backend/main.py", "--stub", "--port", str(self.port)]
        self.proc = subprocess.Popen(cmd, cwd=project_root)
        logger.info(f"🚀 Started Backend Stub on port {self.port}")
        time.sleep(2) # Wait for boot

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait()
            logger.info("🛑 Stopped Backend Stub")

@pytest.fixture(scope="module")
def backend():
    fix = BackendFixture()
    fix.start()
    yield fix
    fix.stop()

@pytest.mark.asyncio
async def test_text_flow(backend):
    uri = f"ws://127.0.0.1:{backend.port}"
    async with websockets.connect(uri) as ws:
        # 1. Init
        await ws.send(json.dumps({"type": "session_init", "session_id": "test_text"}))
        resp = await ws.recv()
        assert json.loads(resp)["state"] == "CONNECTED"

        # 2. Config
        await ws.send(json.dumps({"type": "config", "mode": "text"}))
        # Wait for READY
        ready = False
        for _ in range(5):
            msg = json.loads(await ws.recv())
            if msg.get("state") == "READY":
                ready = True; break
        assert ready

        # 3. Message
        await ws.send(json.dumps({"type": "message", "content": "Hello"}))
        
        # 4. Verification (Expect Log with assistant role)
        found_assistant = False
        for _ in range(10):
            msg = json.loads(await ws.recv())
            if msg.get("type") == "log" and msg.get("role") == "assistant":
                assert "stub" in msg["content"]
                found_assistant = True; break
        assert found_assistant

@pytest.mark.asyncio
async def test_mode_switch(backend):
    uri = f"ws://127.0.0.1:{backend.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "session_init", "session_id": "test_swap"}))
        await ws.recv()

        # Switch to STS
        await ws.send(json.dumps({"type": "config", "mode": "sts"}))
        
        states = []
        for _ in range(10):
            msg = json.loads(await ws.recv())
            if msg.get("type") == "status":
                states.append(msg["state"])
                if msg["state"] == "READY": break
        
        assert "LOADING" in states
        assert "READY" in states

@pytest.mark.asyncio
async def test_binary_sts_trigger(backend):
    uri = f"ws://127.0.0.1:{backend.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "session_init", "session_id": "test_binary"}))
        await ws.recv()
        await ws.send(json.dumps({"type": "config", "mode": "sts"}))
        
        # Wait for READY
        while True:
            m = json.loads(await ws.recv())
            if m.get("state") == "READY": break

        # Send binary data (1 second of fake audio > 32000 bytes)
        fake_audio = b"\x00" * 33000
        await ws.send(fake_audio)

        # Expect transition to THINKING
        thinking = False
        for _ in range(10):
            m = await ws.recv()
            if isinstance(m, str):
                msg = json.loads(m)
                if msg.get("state") == "THINKING":
                    thinking = True; break
        assert thinking
