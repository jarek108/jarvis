import pandas as pd
import json
import os
import subprocess
import argparse
import pickle
import time
import traceback
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Use the consolidated manager from utils
from utils.reporting import GDriveAssetManager

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def load_json(path):
    if not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []

def get_gdrive_service():
    try:
        creds = None
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(tests_dir)
        pickle_path = os.path.join(project_root, 'token.pickle')
        creds_path = os.path.join(project_root, 'credentials.json')
        
        if os.path.exists(pickle_path):
            with open(pickle_path, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(creds_path):
                    print(f"❌ ERROR: Google API credentials not found at {creds_path}")
                    return None
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(pickle_path, 'wb') as token:
                pickle.dump(creds, token)

        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ GDrive Auth Error: {e}")
        traceback.print_exc()
        return None

def upload_to_gdrive(file_path):
    service = get_gdrive_service()
    if not service: return
    manager = GDriveAssetManager(service)
    reports_folder = manager.get_folder_id("Jarvis_Reports")
    print(f"📤 Uploading report to GDrive: {os.path.basename(file_path)}...")
    link = manager.sync_file(file_path, reports_folder, overwrite=False)
    if link:
        print(f"✅ GDrive Upload Successful: {link}")
    else:
        print("❌ GDrive Upload Failed (no link returned).")
    return link

def generate_excel(sync_artifacts=True):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    artifacts_dir = os.path.join(project_root, "tests", "artifacts")
    
    date_str = time.strftime("%Y-%m-%d_%H-%M-%S")
    file_name = f"Jarvis_Benchmark_Report_{date_str}.xlsx"
    output_path = os.path.join(artifacts_dir, file_name)
    
    service = get_gdrive_service() if sync_artifacts else None
    asset_mgr = GDriveAssetManager(service) if service else None
    
    input_folder_id = asset_mgr.get_folder_id("Jarvis_Artifacts_Inputs") if asset_mgr else None
    output_folder_id = asset_mgr.get_folder_id("Jarvis_Artifacts_Outputs") if asset_mgr else None

    sheets = {}
    has_any_data = False

    def link_file(local_path, folder_id, overwrite=True, label="Open"):
        if not asset_mgr or not local_path: return local_path
        if not os.path.isabs(local_path):
            local_path = os.path.join(project_root, local_path)
        url = asset_mgr.sync_file(local_path, folder_id, overwrite=overwrite)
        if url and url.startswith("http"):
            return f'=HYPERLINK("{url}", "{label}")'
        return url

    # 1. STT / TTS
    for domain in ["stt", "tts"]:
        data = load_json(os.path.join(artifacts_dir, f"latest_{domain}.json"))
        if not data: continue
        rows = []
        for entry in data:
            setup = entry.get('loadout', 'unknown')
            for s in entry.get('scenarios', []):
                rows.append({
                    "Setup": setup,
                    "Model": s.get(f"{domain}_model", "N/A"),
                    "Scenario": s.get('name'),
                    "Status": s.get('status'),
                    "Input Text": s.get('input_text', 'N/A'),
                    "Input Link": link_file(s.get('input_file'), input_folder_id, overwrite=False),
                    "Output Link": link_file(s.get('output_file'), output_folder_id, overwrite=True),
                    "Duration (s)": s.get('duration'),
                    "Result": s.get('result')
                })
        if rows:
            sheets[domain.upper()] = pd.DataFrame(rows)
            has_any_data = True

    # 2. LLM / VLM
    for domain in ["llm", "vlm"]:
        data = load_json(os.path.join(artifacts_dir, f"latest_{domain}.json"))
        if not data: continue
        rows = []
        for entry in data:
            setup = entry.get('loadout', 'unknown')
            vram = entry.get('vram', {}).get('peak_gb', 0)
            for s in entry.get('scenarios', []):
                rows.append({
                    "Setup": setup,
                    "Model": s.get("llm_model") or entry.get("model") or "N/A",
                    "Scenario": s.get('name'),
                    "Status": s.get('status'),
                    "Input Text": s.get('input_text', 'N/A'),
                    "Input Link": link_file(s.get('input_file'), input_folder_id, overwrite=False),
                    "TTFT (s)": s.get('ttft'),
                    "TPS": s.get('tps'),
                    "VRAM Peak (GB)": vram,
                    "Text": s.get('text')
                })
        if rows:
            sheets[domain.upper()] = pd.DataFrame(rows)
            has_any_data = True

    # 3. STS
    data = load_json(os.path.join(artifacts_dir, "latest_sts.json"))
    if data:
        rows = []
        for entry in data:
            setup = entry.get('loadout', 'unknown')
            vram = entry.get('vram', {}).get('peak_gb', 0)
            for s in entry.get('scenarios', []):
                m = s.get('metrics', {})
                rows.append({
                    "Setup": setup, 
                    "STT Model": s.get('stt_model', 'N/A'),
                    "LLM Model": s.get('llm_model', 'N/A'),
                    "TTS Model": s.get('tts_model', 'N/A'),
                    "Scenario": s.get('name'), 
                    "Mode": s.get('mode'),
                    "Status": s.get('status'),
                    "Input Text": s.get('input_text', 'N/A'),
                    "Input Link": link_file(s.get('input_file'), input_folder_id, overwrite=False),
                    "Output Link": link_file(s.get('output_file'), output_folder_id, overwrite=True),
                    "Total Duration (s)": s.get('duration'),
                    "STT Time": s.get('stt_inf') or m.get('stt', [0,0])[1],
                    "LLM Time": s.get('llm_tot') or (m.get('llm', [0,0])[1] - m.get('llm', [0,0])[0]),
                    "TTS Time": s.get('tts_inf') or (m.get('tts', [0,0])[1] - m.get('tts', [0,0])[0]),
                    "VRAM Peak (GB)": vram
                })
        if rows:
            sheets["STS"] = pd.DataFrame(rows)
            has_any_data = True

    if not has_any_data:
        print("⚠️ No artifact data found. Excel generation skipped.")
        return None

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
            worksheet = writer.sheets[name]
            for idx, col in enumerate(df.columns):
                series = df[col]
                max_len = max((series.astype(str).map(len).max(), len(str(series.name)))) + 2
                max_len = min(max_len, 100)
                worksheet.column_dimensions[chr(65 + idx)].width = max_len
            
    print(f"📊 Excel Report Generated: {output_path}")
    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and upload Jarvis benchmark reports.")
    parser.add_argument("--upload", action="store_true", help="Upload to GDrive via native API")
    args = parser.parse_args()
    path = generate_excel(sync_artifacts=args.upload)
    if args.upload and path:
        upload_to_gdrive(path)
