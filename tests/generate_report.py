import pandas as pd
import json
import os
import subprocess
import argparse
import pickle
import time
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def load_json(path):
    if not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []

def generate_excel():
    # Use absolute project-relative paths
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    artifacts_dir = os.path.join(project_root, "tests", "artifacts")
    
    # Add date to filename
    date_str = time.strftime("%Y-%m-%d")
    file_name = f"Jarvis_Benchmark_Report_{date_str}.xlsx"
    output_path = os.path.join(artifacts_dir, file_name)
    
    sheets = {}
    has_any_data = False

    # 1. STT / TTS (Standard structure)
    for domain in ["stt", "tts"]:
        data = load_json(os.path.join(artifacts_dir, f"latest_{domain}.json"))
        if not data: continue
        rows = []
        for entry in data:
            loadout = entry.get('loadout', 'unknown')
            for scenario in entry.get('scenarios', []):
                rows.append({
                    "Loadout": loadout,
                    "Scenario": scenario.get('name'),
                    "Status": scenario.get('status'),
                    "Duration (s)": scenario.get('duration'),
                    "Result": scenario.get('result')
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
            loadout = entry.get('loadout', 'unknown')
            vram = entry.get('vram', {}).get('peak_gb', 0)
            for s in entry.get('scenarios', []):
                rows.append({
                    "Loadout": loadout,
                    "Scenario": s.get('name'),
                    "Status": s.get('status'),
                    "TTFT (s)": s.get('ttft'),
                    "TPS": s.get('tps'),
                    "VRAM Peak (GB)": vram,
                    "Text": s.get('text')
                })
        if rows:
            sheets[domain.upper()] = pd.DataFrame(rows)
            has_any_data = True

    # 3. S2S
    data = load_json(os.path.join(artifacts_dir, "latest_s2s.json"))
    if data:
        rows = []
        for entry in data:
            loadout = entry.get('loadout', 'unknown')
            vram = entry.get('vram', {}).get('peak_gb', 0)
            for s in entry.get('scenarios', []):
                m = s.get('metrics', {})
                rows.append({
                    "Loadout": loadout, "Scenario": s.get('name'), "Mode": s.get('mode'),
                    "Status": s.get('status'), "Total Duration (s)": s.get('duration'),
                    "STT Time": s.get('stt_inf') or m.get('stt', [0,0])[1],
                    "LLM Time": s.get('llm_tot') or (m.get('llm', [0,0])[1] - m.get('llm', [0,0])[0]),
                    "TTS Time": s.get('tts_inf') or (m.get('tts', [0,0])[1] - m.get('tts', [0,0])[0]),
                    "VRAM Peak (GB)": vram
                })
        if rows:
            sheets["S2S"] = pd.DataFrame(rows)
            has_any_data = True

    if not has_any_data:
        print("⚠️ No artifact data found. Excel generation skipped.")
        return None

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
            # --- AUTO-SIZE COLUMNS ---
            worksheet = writer.sheets[name]
            for idx, col in enumerate(df.columns):
                series = df[col]
                max_len = max((series.astype(str).map(len).max(), len(str(series.name)))) + 2
                max_len = min(max_len, 100)
                worksheet.column_dimensions[chr(65 + idx)].width = max_len
            
    print(f"📊 Excel Report Generated: {output_path}")
    return output_path

def get_gdrive_service():
    creds = None
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

def upload_to_gdrive(file_path):
    service = get_gdrive_service()
    if not service: return
    file_name = os.path.basename(file_path)
    folder_name = "Jarvis_Reports"
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    folders = results.get('files', [])
    if not folders:
        folder_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        folder_id = folder.get('id')
        print(f"📁 Created new GDrive folder: {folder_name}")
    else:
        folder_id = folders[0].get('id')
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    media = MediaFileUpload(file_path, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', resumable=True)
    if not files:
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print(f"📤 Uploaded new report to GDrive: {file_name}")
    else:
        file_id = files[0].get('id')
        service.files().update(fileId=file_id, media_body=media).execute()
        print(f"🔄 Updated existing report on GDrive: {file_name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and upload Jarvis benchmark reports.")
    parser.add_argument("--upload", action="store_true", help="Upload to GDrive via native API")
    args = parser.parse_args()
    path = generate_excel()
    if args.upload and path:
        upload_to_gdrive(path)
