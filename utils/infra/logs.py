import os
import time
from ..config import load_config

def check_log_for_errors(log_path):
    """Fast-scan the tail of a log file for fatal error signatures."""
    if not log_path or not os.path.exists(log_path):
        return False
        
    error_signatures = [
        "Traceback (most recent call last)",
        "OSError:",
        "HFValidationError",
        "ValueError: No available memory",
        "CUDA Out of Memory",
        "RuntimeError:",
        "AttributeError:",
        "ModuleNotFoundError:",
        "ImportError:",
        "failed to connect to the docker API",
        "is the docker daemon running"
    ]
    
    try:
        with open(log_path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            chunk = f.read().decode('utf-8', errors='ignore')
            for sig in error_signatures:
                if sig in chunk: return True
    except: pass
    return False

def get_ollama_log_path():
    if os.name == 'nt': return os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Ollama', 'server.log')
    return os.path.expanduser('~/.ollama/logs/server.log')

def log_msg(msg, tag="system", level="info"):
    """Timestamped logging helper."""
    from loguru import logger
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [{tag.upper()}] {msg}"
    
    if level == "info": logger.info(formatted)
    elif level == "warning": logger.warning(formatted)
    elif level == "error": logger.error(formatted)
    elif level == "debug": logger.debug(formatted)
    return formatted

def cleanup_old_logs():
    """Deletes RUN_ directories in logs/sessions and tests/logs older than configured retention period."""
    import shutil
    cfg = load_config()
    retention_days = cfg.get('system', {}).get('log_retention_days', 7)
    if retention_days < 0: return
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dirs = [
        os.path.join(project_root, "logs", "sessions"),
        os.path.join(project_root, "tests", "logs")
    ]
    
    now = time.time()
    retention_seconds = retention_days * 86400
    deleted_count = 0
    
    for base_dir in log_dirs:
        if not os.path.exists(base_dir): continue
        for entry in os.listdir(base_dir):
            if not entry.startswith("RUN_"): continue
            path = os.path.join(base_dir, entry)
            if not os.path.isdir(path): continue
            if (now - os.path.getmtime(path)) > retention_seconds:
                try:
                    shutil.rmtree(path)
                    deleted_count += 1
                except: pass
    
    if deleted_count > 0:
        print(f"  ↳ 🧹 Log Retention Policy: Cleaned up {deleted_count} old session directories.")
