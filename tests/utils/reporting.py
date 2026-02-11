import json
import sys
import os
import time
from .ui import GREEN, RED, RESET, fmt_with_chunks as _fmt_with_chunks

def format_status(status):
    if status == "PASSED": return f"{GREEN}[PASS]{RESET}"
    return f"{RED}[FAIL]{RESET}"

def fmt_with_chunks(text, chunks):
    return _fmt_with_chunks(text, chunks)

def report_llm_result(res_obj):
    """Lean reporting: Status and Name only."""
    status_fmt = format_status(res_obj['status'])
    name = res_obj['name']
    
    # Minimal console row
    row = f"  - {status_fmt} {name}\n"
    sys.stdout.write(row)
    
    # Still write machine JSON for the orchestrator to capture
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def report_scenario_result(res_obj):
    """Lean reporting: Status and Name only."""
    status_fmt = format_status(res_obj['status'])
    name = res_obj['name']
    
    # Minimal console row
    row = f"  - {status_fmt} {name}\n"
    sys.stdout.write(row)

    # Still write machine JSON for the orchestrator to capture
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def save_artifact(domain, data):
    # reporting.py is in tests/utils/reporting.py, so parent of parent of parent is project root
    utils_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(utils_dir))
    artifacts_dir = os.path.join(project_root, "tests", "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    file_path = os.path.join(artifacts_dir, f"latest_{domain}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"✅ Artifact saved: {os.path.relpath(file_path, project_root)}")

def trigger_report_generation(upload=True):
    print("\n" + "-"*40)
    print("🔄 TRIGGERING AUTO-REPORT GENERATION...")
    try:
        # reporting.py is in tests/utils/reporting.py, so parent is tests/
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        tests_dir = os.path.dirname(utils_dir)
        if tests_dir not in sys.path:
            sys.path.append(tests_dir)
        
        from generate_report import generate_excel, upload_to_gdrive
        path = generate_excel()
        if upload and path:
            upload_to_gdrive(path)
    except Exception as e:
        print(f"⚠️ Auto-report failed: {e}")
    print("-" * 40 + "\n")
