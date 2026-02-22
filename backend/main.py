import asyncio
import logging
import os
import sys
import yaml

# Ensure root is in path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.transport.server import JarvisServer
from backend.session.manager import SessionManager
from backend.pipeline.orchestrator import PipelineManager
from backend.pipeline.definitions import OperationMode
from backend.models.resource import ResourceManager

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("jarvis.backend")

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stub", action="store_true", help="Use stub models for testing")
    parser.add_argument("--port", type=int, default=8003)
    args = parser.parse_args()

    # 1. Setup Infrastructure
    sessions_dir = os.path.join(project_root, "logs", "sessions")
    session_mgr = SessionManager(sessions_dir)
    resource_mgr = ResourceManager(project_root)
    pipeline_mgr = PipelineManager(session_mgr, resource_mgr, stubs=args.stub)
    
    # 2. Load and Register Operation Modes
    modes_path = os.path.join(project_root, "backend", "pipeline", "operation_modes.yaml")
    with open(modes_path, "r", encoding="utf-8") as f:
        modes_data = yaml.safe_load(f)
        for name, data in modes_data.items():
            mode = OperationMode(
                name=name,
                input_modalities=data["input_modalities"],
                trigger=data["trigger"],
                output_format=data["output_format"],
                requirements=data["requirements"],
                history_limit=data.get("history_limit", 5),
                system_prompt=data.get("system_prompt", ""),
                description=data.get("description", "")
            )
            pipeline_mgr.register_operation_mode(mode)

    # 3. Setup Server
    server = JarvisServer(port=args.port)
    
    # 4. Message Handler
    async def handle_message(msg_type, data):
        if msg_type == "text" and isinstance(data, dict):
            cmd = data.get("type")
            
            if cmd == "session_init":
                session_id = data.get("session_id", "default_user")
                await pipeline_mgr.initialize_session(session_id, server.output_queue)
                await server.push_output("text", {"type": "status", "state": "CONNECTED"})
                
            elif cmd == "config":
                mode = data.get("mode")
                loadout = data.get("loadout", [])
                success = await pipeline_mgr.switch_mode(mode, loadout)
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
