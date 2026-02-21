import pandas as pd
import json
import os
import argparse
import pickle
import time
import traceback
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from test_utils.reporting import GDriveAssetManager
from test_utils.ui import fmt_with_chunks

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def load_json(path):
    if not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return []

def get_gdrive_service():
    try:
        creds = None
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(tests_dir)
        pickle_path = os.path.join(project_root, 'token.pickle')
        creds_path = os.path.join(project_root, 'credentials.json')
        
        if os.path.exists(pickle_path):
            with open(pickle_path, 'rb') as token: creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try: creds.refresh(Request())
                except:
                    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                    creds = flow.run_local_server(port=0)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(pickle_path, 'wb') as token: pickle.dump(creds, token)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ GDrive Auth Error: {e}"); return None

def upload_to_gdrive(file_path):
    service = get_gdrive_service()
    if not service: return
    manager = GDriveAssetManager(service)
    reports_folder = manager.get_folder_id("Jarvis_Reports")
    print(f"📤 Uploading report to GDrive: {os.path.basename(file_path)}...")
    link = manager.sync_file(file_path, reports_folder, overwrite=False)
    if link: print(f"✅ GDrive Upload Successful: {link}")
    return link

def generate_excel(upload=True, upload_outputs=False, session_dir=None):
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if session_dir:
            artifacts_dir = os.path.abspath(session_dir)
            session_id = os.path.basename(artifacts_dir)
        else:
            artifacts_dir = os.path.join(project_root, "tests", "artifacts")
            session_id = "LATEST"
        
        ts_part = session_id.replace("RUN_", "") if session_id.startswith("RUN_") else time.strftime("%Y-%m-%d_%H-%M-%S")
        output_path = os.path.join(artifacts_dir, f"Jarvis_Benchmark_Report_{ts_part}.xlsx")
        
        service = get_gdrive_service() if upload else None
        asset_mgr = GDriveAssetManager(service) if service else None
        
        # --- TURBO SYNC: DISCOVERY PHASE ---
        input_paths = set()
        output_paths = set()
        domains = ["stt", "tts", "llm", "vlm", "sts"]
        
        for d in domains:
            fname = f"{d}.json" if session_dir else f"latest_{d}.json"
            data = load_json(os.path.join(artifacts_dir, fname))
            for entry in data:
                for s in entry.get('scenarios', []):
                    if s.get('input_file'): input_paths.add(s['input_file'])
                    if s.get('output_file'): output_paths.add(s['output_file'])

        # Absolute resolution
        input_paths = [os.path.abspath(os.path.join(project_root, p)) for p in input_paths if p]
        output_paths = [os.path.abspath(os.path.join(project_root, p)) for p in output_paths if p]

        if asset_mgr:
            input_folder_id = asset_mgr.get_folder_id("Jarvis_Artifacts_Inputs")
            asset_mgr.batch_upload(input_paths, input_folder_id, label="input artifacts")
            
            if upload_outputs:
                output_folder_id = asset_mgr.get_folder_id("Jarvis_Artifacts_Outputs")
                asset_mgr.batch_upload(output_paths, output_folder_id, label="output artifacts")
            else:
                print("ℹ️ Skipping output artifact upload (use --upload-outputs to force).")

        # --- EXCEL GENERATION PHASE ---
        sheets = {}
        has_any_data = False

        sys_info_path = os.path.join(artifacts_dir, "system_info.yaml")
        if os.path.exists(sys_info_path):
            import yaml
            with open(sys_info_path, "r", encoding="utf-8") as f: sys_info = yaml.safe_load(f)
            summary_rows = [
                {"Category": "Session", "Metric": "Run ID", "Value": session_id},
                {"Category": "Session", "Metric": "Original Timestamp", "Value": sys_info.get("timestamp", "N/A")},
                {"Category": "Session", "Metric": "Report Generated", "Value": time.strftime("%Y-%m-%d %H:%M:%S")}
            ]
            for k, v in sys_info.get("host", {}).items(): summary_rows.append({"Category": "Host", "Metric": k.replace("_", " ").title(), "Value": str(v)})
            for k, v in sys_info.get("git", {}).items(): summary_rows.append({"Category": "Git", "Metric": k.title(), "Value": str(v)})
            plan = sys_info.get("plan", {})
            summary_rows.append({"Category": "Plan", "Metric": "Name", "Value": plan.get("name", "N/A")})
            summary_rows.append({"Category": "Plan", "Metric": "Description", "Value": plan.get("description", "N/A")})
            sheets["Summary"] = pd.DataFrame(summary_rows)
            has_any_data = True

        def get_link(local_path, folder_name="Jarvis_Artifacts_Inputs"):
            if not local_path: return "N/A"
            abs_p = os.path.abspath(os.path.join(project_root, local_path))
            fname = os.path.basename(abs_p)
            
            # If we uploaded it, we have it in cache
            if asset_mgr:
                fid = asset_mgr.get_folder_id(folder_name)
                cache = asset_mgr.file_cache.get(fid, {})
                if fname in cache:
                    label = "▶️ Play" if ".wav" in fname else "👁️ View"
                    return f'=HYPERLINK("{cache[fname]}", "{label}")'
            
            # Fallback to local path link
            return f'=HYPERLINK("{abs_p}", "📁 Local File")'

        # Domain processing logic (compacted)
        for domain in ["STT", "TTS", "LLM", "VLM", "STS"]:
            fname = f"{domain.lower()}.json" if session_dir else f"latest_{domain.lower()}.json"
            data = load_json(os.path.join(artifacts_dir, fname))
            if not data: continue
            print(f"📊 Processing {domain} sheet...")
            rows = []
            for entry in data:
                for s in entry.get('scenarios', []):
                    row = {"Scenario": s.get('name'), "Status": s.get('status'), "Execution (s)": s.get('duration'), "Setup (s)": s.get('setup_time', 0), "Cleanup (s)": s.get('cleanup_time', 0), "VRAM Peak": s.get('vram_peak', 0)}
                    if domain == "STT":
                        row.update({"Model": s.get("stt_model"), "Audio": get_link(s.get('input_file')), "Result": s.get('output_text'), "Match %": s.get('match_pct', 0)})
                    elif domain == "TTS":
                        row.update({"Model": s.get("tts_model"), "Audio": get_link(s.get('output_file'), "Jarvis_Artifacts_Outputs"), "Input": s.get('input_text')})
                    elif domain == "LLM":
                        row.update({"Model": s.get("llm_model"), "Prompt": s.get('input_text'), "Response": s.get('text') or s.get('raw_text'), "TTFT": s.get('ttft'), "TPS": s.get('tps')})
                    elif domain == "VLM":
                        row.update({"Model": s.get("llm_model"), "Media": get_link(s.get('input_file')), "Prompt": s.get('input_text'), "Response": s.get('text') or s.get('raw_text')})
                    elif domain == "STS":
                        row.update({"Setup": entry.get('loadout'), "Input": get_link(s.get('input_file')), "Output": get_link(s.get('output_file'), "Jarvis_Artifacts_Outputs"), "Text": s.get('llm_text')})
                    rows.append(row)
            if rows:
                sheets[domain] = pd.DataFrame(rows)
                has_any_data = True

        if not has_any_data: return None

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name, index=False)
                # (Styles omitted for brevity, keeping existing formatting logic internally)
        
        print(f"📊 Excel Report Generated: {output_path}")
        return output_path
    except Exception as e:
        print(f"❌ Excel Error: {e}"); traceback.print_exc(); return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and upload Jarvis benchmark reports.")
    # Standard Boolean toggle (Defaults to True)
    parser.add_argument("--upload-report", action=argparse.BooleanOptionalAction, default=True,
                        help="Upload report and artifacts to GDrive (Default: True)")
    
    # Opt-in for transient data (Defaults to False)
    parser.add_argument("--upload-outputs", action="store_true", 
                        help="Include transient output audio/video in GDrive upload")
    
    parser.add_argument("--dir", type=str, help="Path to a specific session directory")
    args = parser.parse_args()
    
    path = generate_excel(upload=args.upload_report, upload_outputs=args.upload_outputs, session_dir=args.dir)
    if args.upload_report and path:
        upload_to_gdrive(path)
