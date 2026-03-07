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
