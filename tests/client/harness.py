import sys
import os
import argparse
import time
import json
import yaml
import threading
from loguru import logger

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

from ui import JarvisApp
from utils.infra.session import init_session
from tests.client.runner import AutomationController, StatusDumper, VisualVerifier

def run_internal_step(app, scenario_data, step_idx, start_t, automation, dumper, visual):
    timeline = scenario_data.get('timeline', [])
    if step_idx >= len(timeline):
        logger.info("✅ INTERNAL RUNNER: Scenario Complete")
        app.after(1000, app.on_closing)
        return

    elapsed = time.perf_counter() - start_t
    step = timeline[step_idx]
    t = float(str(step['t']).replace('s', ''))
    
    if elapsed >= t:
        action = step.get('action')
        target = step.get('target')
        value = step.get('value')
        logger.info(f"🚀 [Step {step_idx}] {action} {target or ''} {value or ''}")
        
        try:
            if action == "select_dropdown": automation.select_dropdown(target, value)
            elif action == "click_element": automation.click(target)
            elif action == "maximize_window": automation.maximize()
            elif action == "take_screenshot": visual.capture_window(step.get('file', 'snap.jpg'))
            elif action == "take_desktop_screenshot": visual.capture_desktop(step.get('file', 'desktop.jpg'))
        except Exception as e:
            logger.error(f"❌ Step {step_idx} failed: {e}")
        
        # Schedule next step immediately if we already reached this one's time
        app.after(10, lambda: run_internal_step(app, scenario_data, step_idx + 1, start_t, automation, dumper, visual))
    else:
        # Poll again soon
        app.after(50, lambda: run_internal_step(app, scenario_data, step_idx, start_t, automation, dumper, visual))

def main():
    parser = argparse.ArgumentParser(description="Jarvis UI Test Harness")
    parser.add_argument("--mock-all", action="store_true", help="Enable mocking for all models and hardware.")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging to console.")
    parser.add_argument("--hold-for-signal", action="store_true", help="Wait for stdin signal before launching UI (for test pre-warming).")
    parser.add_argument("--initial-state", type=str, help="Path to initial state JSON (for fast-booting).")
    parser.add_argument("--scenario", type=str, help="Path to scenario YAML to execute internally.")
    parser.add_argument("--report-dir", type=str, help="Directory to save the execution report.")
    parser.add_argument("--ready-file", type=str, help="File to write to when UI is pre-warmed.")
    args = parser.parse_args()

    if args.debug:
        os.environ['JARVIS_DEBUG'] = "1"

    from test_utils.mock_context import mock_context
    session_dir = os.environ.get('JARVIS_SESSION_DIR')
    
    # Wrap in mock_context for session init and env management
    with mock_context(mock_all=args.mock_all, session_type="APP", service_name="Worker", session_dir=session_dir):
        if args.hold_for_signal:
            import socket
            # Bind to a random port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            sock.listen(1)
            
            # Signal readiness. UIWorker will capture this from the log file.
            logger.info(f"READY_PORT: {port}")
            logger.info(f"⌛ UI PRE-WARMED: Listening for GO signal on port {port}...")

            if args.ready_file:
                try:
                    with open(args.ready_file, "w") as f:
                        f.write(str(port))
                except: pass
            
            # Wait for connection
            conn, addr = sock.accept()
            try:
                with conn:
                    # Read until double newline or EOF
                    data = b""
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk: break
                        data += chunk
                        if b"\n\n" in data: break
                    
                    config_str = data.decode('utf-8').strip()
                    if config_str:
                        try:
                            cfg = json.loads(config_str)
                            if "scenario" in cfg:
                                args.scenario = cfg["scenario"]
                            if "report_dir" in cfg:
                                args.report_dir = cfg["report_dir"]
                        except Exception as e:
                            logger.error(f"Failed to parse socket config: {e}")
            finally:
                sock.close()

        app = JarvisApp(initial_state_path=args.initial_state)

        if args.scenario:
            with open(args.scenario, "r") as f:
                scenario_data = yaml.safe_load(f)
            
            def start_internal():
                # Settle period
                time.sleep(0.5)
                automation = AutomationController(app)
                dumper = StatusDumper(app)
                visual = VisualVerifier(app, args.report_dir or ".")
                start_t = time.perf_counter()
                logger.info(f"🎬 INTERNAL RUNNER: Starting {len(scenario_data.get('timeline', []))} steps")
                app.after(100, lambda: run_internal_step(app, scenario_data, 0, start_t, automation, dumper, visual))

            threading.Thread(target=start_internal, daemon=True).start()

        try:
            app.mainloop()
        except KeyboardInterrupt:
            logger.info("Exiting gracefully due to KeyboardInterrupt...")
            app.destroy()
            sys.exit(0)

if __name__ == "__main__":
    main()
