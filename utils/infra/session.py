import os
import sys
import time
import yaml
import json
from loguru import logger

def init_session(prefix: str) -> str:
    """
    Initializes a unified Jarvis session.
    1. Generates timestamped directory with prefix (BE_, UIT_, APP_).
    2. Configures loguru sinks (Console, system.log, ui.log, orchestrator.log).
    3. Sets up sys.excepthook for crash resilience.
    4. Dumps system_info.yaml for environment tracking.
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    session_id = f"{prefix}_{timestamp}"
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    session_dir = os.path.join(project_root, "logs", "sessions", session_id)
    os.makedirs(session_dir, exist_ok=True)

    # 1. Configure Loguru
    logger.remove() # Clear default
    
    # Console Sink (Filtered by JARVIS_DEBUG)
    log_level = "DEBUG" if os.getenv("JARVIS_DEBUG") == "1" else "INFO"
    logger.add(sys.stderr, level=log_level, format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")

    # system.log (Everything)
    logger.add(os.path.join(session_dir, "system.log"), level="DEBUG", rotation="10 MB")

    # ui.log (UI Domain only)
    logger.add(
        os.path.join(session_dir, "ui.log"), 
        level="DEBUG", 
        filter=lambda r: r["extra"].get("domain") == "UI"
    )

    # orchestrator.log (Orchestrator Domain only)
    logger.add(
        os.path.join(session_dir, "orchestrator.log"), 
        level="DEBUG", 
        filter=lambda r: r["extra"].get("domain") == "ORCHESTRATOR"
    )

    # 2. Crash Resilience
    def exception_handler(exctype, value, tb):
        logger.opt(exception=(exctype, value, tb)).critical("💥 UNCAUGHT EXCEPTION - CRASHING")
    sys.excepthook = exception_handler

    # 3. System Info Dump
    try:
        from tests.test_utils.session import gather_system_info
        # We need a dummy plan path for gather_system_info
        info = gather_system_info("") 
        with open(os.path.join(session_dir, "system_info.yaml"), "w", encoding="utf-8") as f:
            yaml.dump(info, f, sort_keys=False)
    except Exception as e:
        logger.error(f"Failed to dump system_info: {e}")

    # 4. Retention Policy (Categorized)
    try:
        from utils import load_config
        cfg = load_config()
        retention = cfg.get('system', {}).get('log_retention', {"APP": 10, "BE": 20, "UIT": 10})
        
        sessions_root = os.path.dirname(session_dir)
        for p, count in retention.items():
            folders = sorted([f for f in os.listdir(sessions_root) if f.startswith(p)], reverse=True)
            for old_folder in folders[count:]:
                import shutil
                try:
                    shutil.rmtree(os.path.join(sessions_root, old_folder))
                    logger.debug(f"🗑️ Retention Policy: Removed old session {old_folder}")
                except: pass
    except: pass

    logger.info(f"🚀 Session Started: {session_id}")
    return session_dir
