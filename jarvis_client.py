import sys
import os
import argparse
from loguru import logger

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

from utils.infra.session import init_session
from ui import JarvisApp

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Desktop Client")
    parser.add_argument("--mock-all", action="store_true", help="Enable mocking for all models and hardware.")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging to console.")
    args = parser.parse_args()

    if args.debug:
        os.environ['JARVIS_DEBUG'] = "1"

    # Initialize Unified Session
    init_session("APP")

    if args.mock_all:
        os.environ['JARVIS_MOCK_ALL'] = "1"
        logger.info("🧪 MOCK MODE ENABLED")

    app = JarvisApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("Exiting gracefully due to KeyboardInterrupt...")
        app.destroy()
        sys.exit(0)
