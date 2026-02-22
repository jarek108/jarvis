import asyncio
import json
import logging
from typing import Optional, Callable, Awaitable
import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger("jarvis.transport")

class JarvisServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8003):
        self.host = host
        self.port = port
        self.current_connection: Optional[WebSocketServerProtocol] = None
        self.on_message_callback: Optional[Callable[[str, any], Awaitable[None]]] = None
        self.output_queue = asyncio.Queue()

    async def start(self):
        logger.info(f"🚀 Starting Jarvis WebSocket Server on {self.host}:{self.port}")
        async with websockets.serve(self.handler, self.host, self.port):
            await self.process_outputs()

    async def handler(self, websocket: WebSocketServerProtocol):
        if self.current_connection:
            logger.warning("🚫 Connection attempt while another is active. Rejecting.")
            await websocket.close(code=1013, reason="Single user system: Busy")
            return

        self.current_connection = websocket
        logger.info("✅ Client connected")
        
        try:
            async for message in websocket:
                if self.on_message_callback:
                    # Detect type
                    msg_type = "text" if isinstance(message, str) else "binary"
                    if msg_type == "text":
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError:
                            data = message
                    else:
                        data = message
                    
                    await self.on_message_callback(msg_type, data)
        except websockets.ConnectionClosed:
            logger.info("ℹ️ Client disconnected")
        finally:
            self.current_connection = None

    async def send_text(self, data: dict):
        if self.current_connection:
            await self.current_connection.send(json.dumps(data))

    async def send_binary(self, data: bytes):
        if self.current_connection:
            await self.current_connection.send(data)

    async def process_outputs(self):
        """Background task to drain the output queue and send to client."""
        while True:
            out_type, data = await self.output_queue.get()
            try:
                if out_type == "text":
                    await self.send_text(data)
                elif out_type == "binary":
                    await self.send_binary(data)
            except Exception as e:
                logger.error(f"❌ Error sending output: {e}")
            finally:
                self.output_queue.task_done()

    def set_message_handler(self, callback: Callable[[str, any], Awaitable[None]]):
        self.on_message_callback = callback

    async def push_output(self, out_type: str, data: any):
        await self.output_queue.put((out_type, data))
