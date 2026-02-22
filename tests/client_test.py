import asyncio
import websockets
import json
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_client")

async def test_jarvis():
    uri = "ws://127.0.0.1:8003"
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("✅ Connected to Jarvis Backend")
            
            # 1. Initialize Session
            await websocket.send(json.dumps({
                "type": "session_init",
                "session_id": "test_verification_session"
            }))
            
            # 2. Configure Mock Mode (No models, fast)
            await websocket.send(json.dumps({
                "type": "config",
                "mode": "mock"
            }))
            
            # 3. Listen for status and ping
            async def run_logic():
                async for message in websocket:
                    if isinstance(message, str):
                        data = json.loads(message)
                        logger.info(f"📩 Server Event: {data}")
                        if data.get("type") == "status" and data.get("state") == "READY":
                            logger.info("🚀 System Ready! Sending message...")
                            await websocket.send(json.dumps({
                                "type": "message",
                                "content": "Ping"
                            }))
                            # Close after getting response
                        if data.get("type") == "log":
                            logger.info("✅ Test successful. Received response.")
                            return
            
            await asyncio.wait_for(run_logic(), timeout=10)
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_jarvis())
