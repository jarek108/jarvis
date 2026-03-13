import os
import sys
import time
from contextlib import contextmanager
from loguru import logger
from utils.infra.session import init_session

@contextmanager
def mock_context(mock_all=True, session_type="APP", service_name=None, session_dir=None):
    """
    A unified context manager for handling mock environments, 
    log redirection, and state tracking.
    """
    # 1. Set Mock Environment Variables
    original_env = {}
    mock_vars = {
        'JARVIS_MOCK_ALL': "1" if mock_all else "0",
        'JARVIS_UI_TEST': "1" if mock_all else "0"
    }
    
    if session_dir:
        mock_vars['JARVIS_SESSION_DIR'] = session_dir

    for var, val in mock_vars.items():
        original_env[var] = os.environ.get(var)
        os.environ[var] = val

    # 2. Initialize Session / Log Redirection
    # If session_dir is provided, we use it directly instead of init_session
    if not session_dir and session_type:
        session_dir = init_session(session_type)
        
    if session_dir and service_name:
        # Add a specific sink for this service without removing others
        log_path = os.path.join(session_dir, f"{service_name.lower()}.log")
        logger.add(log_path, level="DEBUG", rotation="10 MB", filter=lambda record: record["extra"].get("service") == service_name or not service_name)
        logger.info(f"🚀 {service_name} started in Mock Context. Logs: {log_path}")

    # 3. Reset Mock State Tracker (for health checks)
    try:
        from utils.infra.status import _mock_state_tracker
        _mock_state_tracker.clear()
    except ImportError:
        pass

    try:
        yield session_dir
    finally:
        # Restore Environment
        for var, val in original_env.items():
            if val is None:
                if var in os.environ: del os.environ[var]
            else:
                os.environ[var] = val
        
        # Reset tracker again on exit to be clean
        try:
            from utils.infra.status import _mock_state_tracker
            _mock_state_tracker.clear()
        except ImportError:
            pass
