import os
import sys
import time
import asyncio
import argparse
import yaml
import json
import subprocess
import requests
from loguru import logger
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict

# Add project root and tests directory to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
tests_dir = os.path.join(project_root, "tests")

if project_root not in sys.path: sys.path.insert(0, project_root)
if tests_dir not in sys.path: sys.path.insert(0, tests_dir)

import utils
from test_utils import (
    BOLD, GREEN, RED, YELLOW, RESET, LINE_LEN, 
    RichDashboard
)
from tests.infra.process_manager import UIWorkerPool
from test_utils.mock_context import mock_context

@dataclass
class TestResult:
    id: str
    name: str
    status: str
    duration: float
    error: Optional[str] = None

class ClientTestRunner:
    def __init__(self, args, session_dir: str, dashboard: Optional[RichDashboard] = None, worker_pool: Optional[UIWorkerPool] = None):
        self.args = args
        self.session_dir = session_dir
        self.worker_pool = worker_pool
        self.dashboard = dashboard
        self.is_running = True
        self.start_time = 0
        self.results: List[TestResult] = []
        self.orch_log = logger.bind(domain="ORCHESTRATOR")

    async def run_scenario(self, sid, scenario_data, domain_id):
        self.orch_log.info(f"🎬 Starting Scenario: {sid}")
        if self.dashboard:
            self.dashboard.update_phase(domain_id, "UI_SUITE", "execution", status="wip")
            self.dashboard.current_loadout = sid
            
        self.is_running = True

        # Initialize Scenario Directory
        safe_sid = sid.replace("/", "--")
        temp_scenario_dir = os.path.join(self.session_dir, f"{domain_id}__{safe_sid}")
        os.makedirs(temp_scenario_dir, exist_ok=True)

        self.start_time = time.perf_counter()
        
        # ALL tests now go through the Worker Pool
        if not self.worker_pool:
            raise RuntimeError("Worker pool is required for execution.")
            
        worker = self.worker_pool.get_worker()
        
        # Create a temporary scenario YAML for the internal runner
        scenario_yaml = os.path.join(temp_scenario_dir, "scenario.yaml")
        with open(scenario_yaml, "w") as f:
            yaml.dump(scenario_data, f)
        
        command = {
            "scenario": scenario_yaml,
            "report_dir": temp_scenario_dir
        }
        worker.trigger_go(json.dumps(command))
        
        # Wait for the process to finish with timeout
        wait_start = time.time()
        scenario_success = False
        error_msg = None
        
        while worker.proc.poll() is None:
            if time.time() - wait_start > 90: # Increased timeout for safety
                worker.terminate()
                error_msg = "Scenario timed out (90s)"
                break
            await asyncio.sleep(0.5)
        else:
            # Collect results
            scenario_success = worker.proc.returncode == 0
            error_msg = None if scenario_success else "Internal runner failed"
        
        duration = time.perf_counter() - self.start_time

        status = "PASSED" if scenario_success else "FAILED"
        self.results.append(TestResult(
            id=sid,
            name=scenario_data.get('name', sid),
            status=status,
            duration=duration,
            error=error_msg
        ))
        
        # RENAME Scenario Directory with Status Prefix
        final_scenario_dir = os.path.join(self.session_dir, f"{status}__{domain_id}__{safe_sid}")
        try:
            if os.path.exists(temp_scenario_dir):
                os.rename(temp_scenario_dir, final_scenario_dir)
        except Exception as e:
            self.orch_log.error(f"Failed to rename scenario folder: {e}")

        if self.dashboard:
            self.dashboard.update_scenario(
                domain_id, 
                "UI_SUITE", 
                sid, 
                status, 
                result=error_msg or "",
                duration=duration,
                scenario_dir=final_scenario_dir if status == "FAILED" else None
            )
            
        return scenario_success

    def print_summary(self):
        if not self.dashboard:
            print(f"\n{BOLD}JARVIS CLIENT TEST SUMMARY{RESET}")
            print("-" * LINE_LEN)
            print(f"{'Scenario ID':<40} | {'Status':<10} | {'Time':<8}")
            print("-" * LINE_LEN)
            
            total_passed = 0
            for r in self.results:
                color = GREEN if r.status == "PASSED" else RED
                if r.status == "PASSED": total_passed += 1
                print(f"{r.id:<40} | {color}{r.status:<10}{RESET} | {r.duration:>6.1f}s")
                if r.error:
                    print(f"   {YELLOW}↳ Error: {r.error}{RESET}")

            print("-" * LINE_LEN)
            final_color = GREEN if total_passed == len(self.results) else RED
            print(f"OVERALL: {final_color}{total_passed}/{len(self.results)} PASSED{RESET} | Session: {os.path.basename(self.session_dir)}")
        
        # Save summary report as report.json
        report_path = os.path.join(self.session_dir, "report.json")
        with open(report_path, "w") as f:
            json.dump([asdict(r) for r in self.results], f, indent=2)

async def main():
    try:
        parser = argparse.ArgumentParser(description="Jarvis Client UI Test Runner")
        parser.add_argument("plan", type=str, help="Path to a Plan YAML.")
        parser.add_argument("--mock-all", action="store_true", help="Alias for --mock-models and --mock-edge")
        parser.add_argument("--fail-fast", action="store_true", help="Stop execution on first failure.")
        parser.add_argument("--keep-alive", action="store_true", help="Skip initial backend cleanup.")
        parser.add_argument("--no-persistence", action="store_true", help="Disable plan-level daemon persistence.")
        args = parser.parse_args()

        plan_path = utils.resolve_path(args.plan)
        with open(plan_path, 'r') as f:
            plan_data = yaml.safe_load(f)

        # 1. Resolve ALL scenarios across all domains
        all_patterns = []
        for block in plan_data['execution']:
            all_patterns.extend(block.get('scenarios', []))
        
        from test_utils.scenarios import resolve_plan_scenarios
        resolved_scenarios = resolve_plan_scenarios(project_root, "client", all_patterns)

        from tests.test_utils.session import gather_system_info
        system_info = gather_system_info(plan_path)

        # Wrap in mock_context for session init and env management
        with mock_context(mock_all=args.mock_all, session_type="test_ui", service_name="Runner") as session_dir:
            session_id = os.path.basename(session_dir)
            
            # Setup Dashboard
            dashboard = RichDashboard("Jarvis UI Test", session_id=session_id)
            dashboard.active_log_path = os.path.join(session_dir, "timeline.log")
            
            # Build the dashboard structure using RESOLVED scenarios
            structure = {}
            for block in plan_data['execution']:
                d_id = block.get('domain', 'UI_TESTS').lower()
                patterns = block.get('scenarios', [])
                
                import fnmatch
                block_scen_ids = []
                for p in patterns:
                    source, scen_p = p.split("/", 1) if "/" in p else ("client_ui", p)
                    for rid in resolved_scenarios:
                        r_source, r_id = rid.split("/", 1)
                        if r_source == source and fnmatch.fnmatch(r_id, scen_p):
                            block_scen_ids.append(rid)
                
                if d_id not in structure:
                    structure[d_id] = {
                        "status": "pending", "done": 0, "total": 0,
                        "models_done": 0, "start_time": None, "duration": 0,
                        "loadouts": {
                            "UI_SUITE": {
                                "status": "pending", "done": 0, "total": 0,
                                "duration": 0, "errors": 0, "phase": None, "models": ["UI Automation Controller"],
                                "scenarios": {}
                            }
                        }
                    }
                
                structure[d_id]["total"] += len(block_scen_ids)
                structure[d_id]["loadouts"]["UI_SUITE"]["total"] += len(block_scen_ids)
                for rid in block_scen_ids:
                    structure[d_id]["loadouts"]["UI_SUITE"]["scenarios"][rid] = {"status": "pending", "duration": 0, "error": None}
                block['resolved_ids'] = block_scen_ids

            dashboard.init_plan_structure(structure)
            dashboard.start()

            # Pre-boot preparation
            from utils import load_config
            cfg = load_config()
            daemon_port = cfg.get('ports', {}).get('daemon', 5555)
            
            # Pre-test backend cleanup
            from manage_loadout import kill_loadout
            if not args.keep_alive:
                kill_loadout("all")
                # Kill any existing daemon on config port (Surgically)
                try:
                    import psutil
                    daemon_port = cfg.get('ports', {}).get('daemon', 5555)
                    # Faster way to find processes by port: check all processes
                    for proc in psutil.process_iter(['pid', 'name']):
                        try:
                            # Use net_connections() instead of connections() to avoid deprecation warning
                            for conn in proc.net_connections(kind='inet'):
                                if conn.laddr.port == daemon_port:
                                    proc.kill()
                                    logger.info(f"Surgically killed existing process on port {daemon_port} (PID {proc.pid})")
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            pass
                except Exception as e:
                    logger.warning(f"Surgical daemon cleanup failed: {e}")
                logger.info("🧹 Pre-test cleanup finished.")

            # Start Persistent Daemon
            daemon_proc = None
            if not args.no_persistence:
                logger.info("🚀 Starting Persistent Jarvis Daemon...")
                daemon_log_path = os.path.join(session_dir, "daemon_boot.log")
                daemon_log = open(daemon_log_path, "w")
                daemon_proc = subprocess.Popen(
                    [sys.executable, os.path.join(project_root, "jarvis_daemon.py")],
                    env=os.environ.copy(),
                    stdout=daemon_log,
                    stderr=subprocess.STDOUT
                )
                # Wait for daemon
                import requests
                logger.info(f"⏳ Waiting for Daemon on port {daemon_port}...")
                for i in range(30):
                    if daemon_proc.poll() is not None:
                        logger.error(f"❌ Daemon process died prematurely (Exit code: {daemon_proc.returncode}). Stop waiting.")
                        break
                    try:
                        if requests.get(f"http://127.0.0.1:{daemon_port}/status", timeout=0.5).status_code == 200: 
                            logger.info(f"✅ Daemon ready after {i*0.5:.1f}s")
                            break
                    except: pass
                    time.sleep(0.5)
                else:
                    logger.warning("🕒 Daemon wait timed out (15s). Proceeding anyway...")

            # Initialize Worker Pool
            # Create an initial state file for workers to fast-boot
            init_state_file = os.path.join(session_dir, "initial_state.json")
            try:
                r = requests.get(f"http://127.0.0.1:{daemon_port}/status", timeout=1.0)
                with open(init_state_file, "w") as f:
                    json.dump({"health": {}, "models": [], "loadout": "NONE", "vram": r.json().get('vram', {})}, f)
            except: pass
            
            # FINALIZE BOOT HERE - To capture all the pre-flight time
            dashboard.finalize_boot(session_id, system_info, session_dir=session_dir)

            logger.info("🏭 Initializing UI Worker Pool...")
            worker_pool = UIWorkerPool(session_dir, initial_state_file=init_state_file, project_root=project_root)

            runner = ClientTestRunner(args, session_dir, dashboard=dashboard, worker_pool=worker_pool)

            for block in plan_data['execution']:
                domain_id = block.get('domain', 'UI_TESTS').upper()
                resolved_ids = block.get('resolved_ids', [])
                
                success = True
                for sid in resolved_ids:
                    sdata = resolved_scenarios[sid]
                    
                    # RESET Daemon before each test if persistent
                    if not args.no_persistence:
                        try:
                            # Use a non-blocking clear
                            requests.delete(f"http://127.0.0.1:{daemon_port}/loadout", timeout=1.0)
                        except: pass

                    success = await runner.run_scenario(sid, sdata, domain_id)
                    if not success and args.fail_fast: break
                
                dashboard.finalize_loadout(domain_id, "UI_SUITE", 0, status="passed" if success else "failed")
                dashboard.finalize_domain(domain_id)
                if not success and args.fail_fast: break

            runner.print_summary()

    except Exception as e:
        import traceback
        err_details = traceback.format_exc()
        logger.critical(f"💥 UNCAUGHT EXCEPTION - CRASHING\n{err_details}")
        print(f"\n{RED}CRITICAL ERROR: {e}{RESET}")
        print(err_details)
        sys.exit(1)
    finally:
        try: dashboard.stop()
        except: pass
        if 'daemon_proc' in locals() and daemon_proc: 
            try: daemon_proc.terminate()
            except: pass
        wp = locals().get('worker_pool')
        if wp:
            # Shutdown pool cleanly
            try: wp.shutdown()
            except: pass
        if 'session_dir' in locals() and session_dir:
            print(f"\n✅ UI Test Session Complete\n📂 Session: {session_dir}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
