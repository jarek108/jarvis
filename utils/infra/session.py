import os
import sys
import time
import yaml
import json
from loguru import logger

SESSION_START_TIME = time.perf_counter()

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

def relative_formatter(record):
    """Custom formatter to show timestamps relative to session/scenario start."""
    # Use context-provided relative_start if available (for tests), else global SESSION_START_TIME
    start_t = record["extra"].get("relative_start", SESSION_START_TIME)
    elapsed = time.perf_counter() - start_t
    
    # Format: [+0.123s]
    rel_time = f"[+{elapsed:07.3f}s]"
    
    # Check for domain to add prefix
    domain = record["extra"].get("domain", "")
    domain_str = f" | {domain: <12}" if domain else ""
    
    return f"<green>{rel_time}</green>{domain_str} | <level>{record['level']: <8}</level> | <level>{record['message']}</level>\n"

def init_session(domain: str) -> str:
    """
    Initializes a unified Jarvis session.
    1. Generates timestamped directory: logs/{domain}/{YYYYMMDD_HHMMSS}/.
    2. Configures loguru to stream EVERYTHING into timeline.log.
    3. Sets up crash resilience (excepthook + stream redirection).
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    session_dir = os.path.join(project_root, "logs", domain, timestamp)
    os.makedirs(session_dir, exist_ok=True)

    # 1. Configure Loguru
    logger.remove() # Clear default
    
    # Console Sink (Filtered by JARVIS_DEBUG and Dashboard State)
    log_level = "DEBUG" if os.getenv("JARVIS_DEBUG") == "1" else "INFO"
    
    def console_filter(record):
        # Silence console output if a RichDashboard is currently active to prevent layout corruption
        return not getattr(sys, "dashboard_active", False)

    # Simple format for console to stay readable with RichDashboard
    logger.add(sys.stderr, level=log_level, format=relative_formatter, filter=console_filter)

    # timeline.log (The Forensic Heartbeat)
    # Includes all domains (UI, ORCHESTRATOR, SYSTEM) in one chronological file
    logger.add(os.path.join(session_dir, "timeline.log"), level="DEBUG", format=relative_formatter, rotation="10 MB")

    # 2. Crash Resilience & Raw Stream Redirection
    def exception_handler(exctype, value, tb):
        logger.opt(exception=(exctype, value, tb)).critical("💥 UNCAUGHT EXCEPTION - CRASHING")
    sys.excepthook = exception_handler
    
    # Redirect raw stdout/stderr to capture non-Python errors (e.g. Tkinter/C++)
    sys.stdout = StreamToLogger(level="DEBUG")
    sys.stderr = StreamToLogger(level="ERROR")

    # 3. System Info Dump
    try:
        from tests.test_utils.session import gather_system_info
        info = gather_system_info("") 
        with open(os.path.join(session_dir, "system_info.yaml"), "w", encoding="utf-8") as f:
            yaml.dump(info, f, sort_keys=False)
    except Exception as e:
        # Use direct print since we hijacked logger via sys.stderr
        print(f"Failed to dump system_info: {e}")

    # 4. Retention Policy (Categorized by Domain Folder)
    try:
        from utils import load_config
        cfg = load_config()
        # Map domain name to config key (test_ui -> UIT, test_be -> BE, prod -> APP)
        key_map = {"test_ui": "UIT", "test_be": "BE", "prod": "APP"}
        config_key = key_map.get(domain, "APP")
        
        retention_limits = cfg.get('system', {}).get('log_retention', {"APP": 10, "BE": 20, "UIT": 10})
        limit = retention_limits.get(config_key, 10)
        
        domain_root = os.path.dirname(session_dir)
        folders = sorted([f for f in os.listdir(domain_root)], reverse=True)
        for old_folder in folders[limit:]:
            import shutil
            try:
                shutil.rmtree(os.path.join(domain_root, old_folder))
            except: pass
    except: pass

    logger.info(f"🚀 Session Started: {domain}/{timestamp}")
    return session_dir
