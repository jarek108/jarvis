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
    row = f"  - {status_fmt} {name}\n"
    sys.stdout.write(row)
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def report_scenario_result(res_obj):
    """Lean reporting: Status and Name only."""
    status_fmt = format_status(res_obj['status'])
    name = res_obj['name']
    row = f"  - {status_fmt} {name}\n"
    sys.stdout.write(row)
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def save_artifact(domain, data):
    utils_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(utils_dir))
    artifacts_dir = os.path.join(project_root, "tests", "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    file_path = os.path.join(artifacts_dir, f"latest_{domain}.json")
    
    existing_data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except:
            existing_data = []
    
    # Check if this loadout already exists in existing_data to avoid duplicates if re-run
    new_loadouts = [d['loadout'] for d in data]
    combined_data = [d for d in existing_data if d['loadout'] not in new_loadouts]
    combined_data.extend(data)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, indent=4, ensure_ascii=False)
    print(f"✅ Artifact saved: {os.path.relpath(file_path, project_root)}")

def trigger_report_generation(upload=True):
    print("\n" + "-"*40)
    print("🔄 TRIGGERING AUTO-REPORT GENERATION...")
    try:
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        tests_dir = os.path.dirname(utils_dir)
        if tests_dir not in sys.path:
            sys.path.append(tests_dir)
        from generate_report import generate_excel, upload_to_gdrive
        path = generate_excel(sync_artifacts=upload)
        if upload and path:
            upload_to_gdrive(path)
    except Exception as e:
        print(f"⚠️ Auto-report failed: {e}")
    print("-" * 40 + "\n")

class GDriveAssetManager:
    def __init__(self, service):
        self.service = service
        self.folders = {} # Name -> ID cache

    def get_folder_id(self, name, parent_id=None):
        if name in self.folders: return self.folders[name]
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id: query += f" and '{parent_id}' in parents"
        results = self.service.files().list(q=query, fields='files(id)').execute()
        files = results.get('files', [])
        if not files:
            meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
            if parent_id: meta['parents'] = [parent_id]
            folder = self.service.files().create(body=meta, fields='id').execute()
            fid = folder.get('id')
        else:
            fid = files[0].get('id')
        self.folders[name] = fid
        return fid

    def sync_file(self, local_path, folder_id, overwrite=True):
        """Uploads or updates a file and returns its webViewLink."""
        if not local_path or not os.path.exists(local_path): return None
        file_name = os.path.basename(local_path)
        query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
        results = self.service.files().list(q=query, fields='files(id, webViewLink)').execute()
        files = results.get('files', [])
        from googleapiclient.http import MediaFileUpload
        ext = os.path.splitext(file_name)[1].lower()
        mimetype = 'application/octet-stream'
        if ext in ['.wav', '.mp3']: mimetype = 'audio/mpeg' if ext == '.mp3' else 'audio/wav'
        elif ext in ['.png', '.jpg', '.jpeg']: mimetype = 'image/png' if ext == '.png' else 'image/jpeg'
        elif ext in ['.mp4']: mimetype = 'video/mp4'
        media = MediaFileUpload(local_path, mimetype=mimetype, resumable=True)
        if files and overwrite:
            file_id = files[0].get('id')
            updated = self.service.files().update(fileId=file_id, media_body=media, fields='webViewLink').execute()
            return updated.get('webViewLink')
        elif not files:
            meta = {'name': file_name, 'parents': [folder_id]}
            created = self.service.files().create(body=meta, media_body=media, fields='webViewLink').execute()
            return created.get('webViewLink')
        else:
            return files[0].get('webViewLink')
