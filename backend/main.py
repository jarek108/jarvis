import asyncio
import logging
import os
import sys

# Ensure root is in path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.transport.server import JarvisServer
from backend.session.manager import SessionManager
from backend.pipeline.orchestrator import PipelineManager
from backend.pipeline.definitions import PipelineConfig
from backend.models.resource import ResourceManager

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("jarvis.backend")

async def main():
    # 1. Setup Infrastructure
    sessions_dir = os.path.join(project_root, "logs", "sessions")
    session_mgr = SessionManager(sessions_dir)
    resource_mgr = ResourceManager(project_root)
    pipeline_mgr = PipelineManager(session_mgr, resource_mgr)
    
    # 2. Register Pipelines
    # Mock pipeline for fast verification
    mock_config = PipelineConfig(
        name="mock",
        description="Non-model test pipeline",
        input_mode="text_message",
        trigger="manual",
        models=[]
    )
    pipeline_mgr.register_pipeline(mock_config)

    sts_config = PipelineConfig(
        name="sts",
        description="Full Speech-to-Speech interaction",
        input_mode="audio_stream",
        trigger="vad",
        models=["faster-whisper-tiny", "chatterbox-turbo", "OL_qwen2.5:0.5b"]
    )
    pipeline_mgr.register_pipeline(sts_config)

    # 3. Setup Server
    server = JarvisServer(port=8003)
    
    # 4. Message Handler
    async def handle_message(msg_type, data):
        if msg_type == "text" and isinstance(data, dict):
            cmd = data.get("type")
            
            if cmd == "session_init":
                session_id = data.get("session_id", "default_user")
                await pipeline_mgr.initialize_session(session_id, server.output_queue)
                await server.push_output("text", {"type": "status", "state": "CONNECTED"})
                
            elif cmd == "config":
                mode = data.get("mode", "mock")
                success = await pipeline_mgr.switch_mode(mode)
                if not success:
                    await server.push_output("text", {"type": "error", "message": f"Failed to switch to {mode}"})
            
            elif cmd == "ping":
                await server.push_output("text", {"type": "pong"})
            
            else:
                await pipeline_mgr.handle_input(msg_type, data)
        else:
            await pipeline_mgr.handle_input(msg_type, data)

    server.set_message_handler(handle_message)
    
    # 5. Start Server
    logger.info("🟢 Jarvis Backend ready and waiting for connections.")
    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("👋 Shutting down...")

if __name__ == "__main__":
    asyncio.run(main())
