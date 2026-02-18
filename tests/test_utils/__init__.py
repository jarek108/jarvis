import sys
import os

# Ensure project root is in sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import root utils package
import utils
import utils.console

# Expose specific core functions for convenience
load_config = utils.load_config
resolve_path = utils.resolve_path
get_hf_home = utils.get_hf_home
get_ollama_models = utils.get_ollama_models
is_port_in_use = utils.is_port_in_use
start_server = utils.start_server
wait_for_port = utils.wait_for_port
kill_process_on_port = utils.kill_process_on_port
get_jarvis_ports = utils.get_jarvis_ports
kill_all_jarvis_services = utils.kill_all_jarvis_services
is_vllm_docker_running = utils.is_vllm_docker_running
stop_vllm_docker = utils.stop_vllm_docker
get_vllm_logs = utils.get_vllm_logs
is_vllm_model_local = utils.is_vllm_model_local
get_vram_estimation = utils.get_vram_estimation
get_ollama_vram = utils.get_ollama_vram
get_loaded_ollama_models = utils.get_loaded_ollama_models
get_service_status = utils.get_service_status
get_system_health = utils.get_system_health
get_gpu_vram_usage = utils.get_gpu_vram_usage
get_gpu_total_vram = utils.get_gpu_total_vram
check_ollama_offload = utils.check_ollama_offload
check_and_pull_model = utils.check_and_pull_model
warmup_llm = utils.warmup_llm
is_model_local = utils.is_model_local

ensure_utf8_output = utils.console.ensure_utf8_output
CYAN = utils.console.CYAN
GREEN = utils.console.GREEN
RED = utils.console.RED
YELLOW = utils.console.YELLOW
GRAY = utils.console.GRAY
RESET = utils.console.RESET
BOLD = utils.console.BOLD
LINE_LEN = utils.console.LINE_LEN

# Test-specific utils (Relative imports)
from .ui import LiveFilter, RichDashboard
from .reporting import (
    format_status, fmt_with_chunks, report_llm_result, 
    report_scenario_result, save_artifact, trigger_report_generation
)
from .lifecycle import LifecycleManager, run_test_lifecycle
from .session import init_session
from .collectors import BaseReporter, StdoutReporter, AccumulatingReporter
