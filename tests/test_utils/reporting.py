import json
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor
from utils.console import GREEN, RED, RESET
from .ui import fmt_with_chunks as _fmt_with_chunks

def format_status(status):
    if status == "PASSED": return f"{GREEN}[PASS]{RESET}"
    return f"{RED}[FAIL]{RESET}"

def fmt_with_chunks(text, chunks):
    return _fmt_with_chunks(text, chunks)

def report_llm_result(res_obj):
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def report_scenario_result(res_obj):
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def save_artifact(domain, data, session_dir=None):
    if not session_dir:
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(utils_dir))
        artifacts_dir = os.path.join(project_root, "tests", "artifacts")
    else:
        artifacts_dir = session_dir

    os.makedirs(artifacts_dir, exist_ok=True)
    file_path = os.path.join(artifacts_dir, f"{domain}.json")
    
    existing_data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except:
            existing_data = []
    
    new_loadouts = [d['loadout'] for d in data]
    combined_data = [d for d in existing_data if d['loadout'] not in new_loadouts]
    combined_data.extend(data)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, indent=4, ensure_ascii=False)

def trigger_report_generation(upload=True, session_dir=None):
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tests_dir = os.path.join(project_root, "tests")
        if tests_dir not in sys.path: sys.path.append(tests_dir)
        from generate_report import generate_excel, upload_to_gdrive
        path = generate_excel(upload=upload, session_dir=session_dir)
        if upload and path: upload_to_gdrive(path)
        return path
    except Exception as e:
        sys.stderr.write(f"⚠️ Auto-report failed: {e}\n"); return None

class GDriveAssetManager:
    def __init__(self, service):
        self.service = service
        self.folders = {} # Name -> ID
        self.file_cache = {} # folder_id -> {filename: link}

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

    def preload_folder(self, folder_id):
        if folder_id in self.file_cache: return self.file_cache[folder_id]
        print(f"🔍 Pre-loading GDrive manifest for folder {folder_id}...")
        results = []
        page_token = None
        while True:
            res = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(name, webViewLink)",
                pageToken=page_token
            ).execute()
            results.extend(res.get('files', []))
            page_token = res.get('nextPageToken')
            if not page_token: break
        mapping = {f['name']: f['webViewLink'] for f in results}
        self.file_cache[folder_id] = mapping
        return mapping

    def sync_file(self, local_path, folder_id, overwrite=True):
        if not local_path or not os.path.exists(local_path): return None
        file_name = os.path.basename(local_path)
        cache = self.file_cache.get(folder_id, {})
        if file_name in cache and not overwrite: return cache[file_name]
        from googleapiclient.http import MediaFileUpload
        ext = os.path.splitext(file_name)[1].lower()
        mimetype = 'application/octet-stream'
        if ext in ['.wav', '.mp3']: mimetype = 'audio/mpeg' if ext == '.mp3' else 'audio/wav'
        elif ext in ['.png', '.jpg', '.jpeg']: mimetype = 'image/png' if ext == '.png' else 'image/jpeg'
        elif ext in ['.mp4']: mimetype = 'video/mp4'
        media = MediaFileUpload(local_path, mimetype=mimetype, resumable=True)
        meta = {'name': file_name, 'parents': [folder_id]}
        created = self.service.files().create(body=meta, media_body=media, fields='webViewLink').execute()
        link = created.get('webViewLink')
        if folder_id in self.file_cache: self.file_cache[folder_id][file_name] = link
        return link

    def batch_upload(self, local_paths, folder_id, label="artifacts", max_workers=10):
        if not local_paths: return {}
        cache = self.preload_folder(folder_id)
        to_upload = [p for p in local_paths if os.path.basename(p) not in cache]
        if not to_upload:
            print(f"✅ All {label} already exist on GDrive.")
            return cache
        print(f"🚀 Uploading {len(to_upload)} new {label} in parallel...")
        def upload_one(path):
            try: return path, self.sync_file(path, folder_id, overwrite=False)
            except Exception as e:
                print(f"  ❌ Failed to upload {os.path.basename(path)}: {e}")
                return path, None
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(upload_one, to_upload))
        for path, link in results:
            if link: cache[os.path.basename(path)] = link
        return cache
