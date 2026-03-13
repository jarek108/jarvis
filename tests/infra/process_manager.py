import os
import sys
import time
import yaml
import json
import subprocess
import threading
import queue
import socket
from loguru import logger
import utils
from utils.console import ensure_utf8_output, BOLD, CYAN, RESET, LINE_LEN
# Use direct module import to bypass __init__.py and avoid circular dependency
from tests.test_utils.reporting import LiveFilter

class UIWorker:
    """Manages a single pre-warmed UI process."""
    _id_counter = 0
    def __init__(self, session_dir, initial_state_file=None, project_root=None):
        self.session_dir = session_dir
        self.initial_state_file = initial_state_file
        self.project_root = project_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.proc = None
        self.orch_log = logger.bind(domain="ORCHESTRATOR")
        self.worker_id = UIWorker._id_counter
        UIWorker._id_counter += 1
        self.port = None
        self._spawn()

    def _spawn(self):
        # Phase 3 Improvement: Added --report-dir to harness so it knows where to save screenshots/results
        cmd = [sys.executable, os.path.join(self.project_root, "tests", "client", "harness.py"), 
               "--mock-all", "--hold-for-signal"]
        if self.initial_state_file:
            cmd.extend(["--initial-state", self.initial_state_file])
        
        # On Windows, we avoid blocking on PIPE by using a log file.
        self.log_path = os.path.join(self.session_dir, f"worker_{self.worker_id}.log")
        self.log_file = open(self.log_path, "w", encoding="utf-8")

        env = os.environ.copy()
        if self.session_dir:
            env['JARVIS_SESSION_DIR'] = self.session_dir

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        # Phase 3 Improvement: Direct log-polling for READY_PORT
        start_t = time.time()
        while time.time() - start_t < 30:
            if self.proc.poll() is not None:
                # Read end of log to see why it died
                try:
                    with open(self.log_path, "r", encoding="utf-8") as f:
                        last_lines = f.readlines()[-5:]
                        logger.error(f"Worker {self.worker_id} died. Last output: {''.join(last_lines)}")
                except: pass
                raise RuntimeError(f"UI Worker {self.worker_id} died prematurely. Check {self.log_path}")
            
            if os.path.exists(self.log_path):
                try:
                    with open(self.log_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        if "READY_PORT:" in content:
                            import re
                            match = re.search(r"READY_PORT:\s*(\d+)", content)
                            if match:
                                self.port = int(match.group(1))
                                break
                except: pass
            time.sleep(0.5)
        
        if not self.port:
            self.proc.terminate()
            raise RuntimeError(f"UI Worker {self.worker_id} timed out waiting for READY_PORT signal.")
        self.orch_log.debug(f"🟢 UI Worker {self.worker_id} pre-warmed on port {self.port}.")

    def trigger_go(self, config_json=None):
        """Sends the signal to the UI to start its mainloop via TCP socket."""
        if not self.port:
            self.orch_log.error(f"Cannot trigger GO for worker {self.worker_id}: No port assigned.")
            return

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect(('127.0.0.1', self.port))
                data = config_json if config_json else "{}"
                # Append double newline as EOF marker for the harness
                s.sendall((data + "\n\n").encode('utf-8'))
        except Exception as e:
            self.orch_log.error(f"Failed to trigger GO for worker {self.worker_id} via socket: {e}")

    def terminate(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
            except: 
                try: self.proc.kill()
                except: pass
            finally:
                if hasattr(self, 'log_file') and not self.log_file.closed:
                    self.log_file.close()


class UIWorkerPool:
    """Maintains a pool of pre-warmed UI processes."""
    def __init__(self, session_dir, initial_state_file=None, project_root=None, size=1):
        self.session_dir = session_dir
        self.initial_state_file = initial_state_file
        self.project_root = project_root
        self.target_size = size
        self.pool = queue.Queue()
        self.all_workers = []
        self.is_running = True
        self.spawning_count = 0
        self._lock = threading.Lock()
        self._refill_thread = threading.Thread(target=self._refill_loop, daemon=True)
        self._refill_thread.start()

    def _refill_loop(self):
        while self.is_running:
            with self._lock:
                # Clean up dead workers from tracking list
                self.all_workers = [w for w in self.all_workers if w.proc.poll() is None]
                current_count = self.pool.qsize()
                needed = self.target_size - (current_count + self.spawning_count)
            
            if needed > 0:
                with self._lock:
                    self.spawning_count += 1
                
                # Spawn worker in a background task but tracked
                def spawn_task():
                    worker = None
                    try:
                        worker = UIWorker(self.session_dir, initial_state_file=self.initial_state_file, project_root=self.project_root)
                        with self._lock:
                            if self.is_running:
                                self.pool.put(worker)
                                self.all_workers.append(worker)
                            else:
                                worker.terminate()
                    except Exception as e:
                        logger.error(f"Failed to pre-warm UI worker: {e}")
                    finally:
                        with self._lock:
                            self.spawning_count -= 1

                threading.Thread(target=spawn_task, daemon=True).start()
            
            time.sleep(1.0)

    def get_worker(self) -> UIWorker:
        try:
            # Wait up to 45s for a worker
            return self.pool.get(timeout=45.0)
        except queue.Empty:
            raise RuntimeError("Timed out waiting for a pre-warmed UI worker from the pool.")

    def shutdown(self):
        """Synchronously kills all workers in the pool."""
        self.is_running = False
        logger.info("🛑 Shutting down UI Worker Pool...")
        with self._lock:
            # Drain the queue
            while not self.pool.empty():
                try: self.pool.get_nowait()
                except: break
            
            # Kill all known workers
            for worker in self.all_workers:
                try: worker.terminate()
                except: pass
            self.all_workers = []

class LifecycleManager:
    def __init__(self, setup_name, models=None, session_dir=None, **kwargs):
        self.setup_name = setup_name
        self.models = models or []
        self.session_dir = session_dir
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
    def identify_models(self): return {"stt": None, "tts": None, "llm": None}
