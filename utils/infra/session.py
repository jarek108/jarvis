import os
import sys
import time
import yaml
import json
from loguru import logger

class StreamToLogger:
    """
    Fake file-like object that redirects writes to a loguru logger.
    Used to capture raw stdout/stderr from C-extensions like Tkinter.
    """
    def __init__(self, level="INFO", domain=None):
        self.level = level
        self.domain = domain
        self.buffer = self # Satisfy TextIOWrapper

    def write(self, buf):
        # Handle both string and bytes
        if isinstance(buf, bytes):
            buf = buf.decode('utf-8', errors='replace')
            
        for line in buf.rstrip().splitlines():
            if line.strip():
                if self.domain:
                    logger.bind(domain=self.domain).log(self.level, line.rstrip())
                else:
                    logger.log(self.level, line.rstrip())

    def flush(self):
        pass

    def fileno(self):
        return 1 # Standard stdout/stderr descriptor fallback

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False

    @property
    def closed(self):
        return False

def init_session(prefix: str) -> str:
    """
    Initializes a unified Jarvis session.
    1. Generates timestamped directory with prefix (BE_, UIT_, APP_).
    2. Configures loguru sinks (Console, system.log, ui.log, orchestrator.log).
    3. Sets up sys.excepthook and redirects raw stdout/stderr for crash resilience.
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
    # Note: We use a simple format for console to stay readable with RichDashboard
    logger.add(sys.stderr, level=log_level, format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>")

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

    # 2. Crash Resilience & Raw Stream Redirection
    def exception_handler(exctype, value, tb):
        logger.opt(exception=(exctype, value, tb)).critical("💥 UNCAUGHT EXCEPTION - CRASHING")
    sys.excepthook = exception_handler
    
    # Redirect raw stdout/stderr to capture non-Python errors (e.g. Tkinter/C++)
    # We log stdout as DEBUG and stderr as ERROR
    sys.stdout = StreamToLogger(level="DEBUG")
    sys.stderr = StreamToLogger(level="ERROR")

    # 3. System Info Dump
    try:
        from tests.test_utils.session import gather_system_info
        info = gather_system_info("") 
        with open(os.path.join(session_dir, "system_info.yaml"), "w", encoding="utf-8") as f:
            yaml.dump(info, f, sort_keys=False)
    except Exception as e:
        # Use direct print since we just hijacked logger via sys.stderr
        print(f"Failed to dump system_info: {e}")

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
                except: pass
    except: pass

    logger.info(f"🚀 Session Started: {session_id}")
    return session_dir
