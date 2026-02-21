import pandas as pd
import json
import os
import argparse
import pickle
import time
import traceback
import webbrowser
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
    """Core logic for creating the Excel file and syncing artifacts."""
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
            if asset_mgr:
                fid = asset_mgr.get_folder_id(folder_name)
                cache = asset_mgr.file_cache.get(fid, {})
                if fname in cache:
                    label = "▶️ Play" if ".wav" in fname else "👁️ View"
                    return f'=HYPERLINK("{cache[fname]}", "{label}")'
            return f'=HYPERLINK("{abs_p}", "📁 Local File")'

        for domain in ["STT", "TTS", "LLM", "VLM", "STS"]:
            fname = f"{domain.lower()}.json" if session_dir else f"latest_{domain.lower()}.json"
            data = load_json(os.path.join(artifacts_dir, fname))
            if not data: continue
            print(f"📊 Processing {domain} sheet...")
            rows = []
            for entry in data:
                loadout_name = entry.get('loadout', 'N/A')
                for s in entry.get('scenarios', []):
                    # Priority: 
                    # 1. detailed_model (New runs, contains resolved defaults)
                    # 2. loadout_name (Parent entry name, usually has flags)
                    # 3. scenario-level model ID
                    model_col = s.get('detailed_model') or loadout_name
                    if model_col == 'N/A':
                        model_col = s.get('llm_model') or s.get('stt_model') or s.get('tts_model') or "N/A"
                    
                    # Initialize row with Model/Setup as the FIRST column
                    model_key = "Setup" if domain == "STS" else "Model"
                    row = {model_key: model_col, "Scenario": s.get('name'), "Status": s.get('status')}
                    
                    if domain == "STT":
                        row.update({"Audio": get_link(s.get('input_file')), "Result": s.get('output_text'), "Match %": s.get('match_pct', 0)})
                    elif domain == "TTS":
                        row.update({"Audio": get_link(s.get('output_file'), "Jarvis_Artifacts_Outputs"), "Input": s.get('input_text')})
                    elif domain == "LLM":
                        row.update({"Prompt": s.get('input_text'), "Response": s.get('text') or s.get('raw_text'), "TTFT": s.get('ttft'), "TPS": s.get('tps')})
                    elif domain == "VLM":
                        row.update({"Media": get_link(s.get('input_file')), "Prompt": s.get('input_text'), "Response": s.get('text') or s.get('raw_text')})
                    elif domain == "STS":
                        row.update({"Input": get_link(s.get('input_file')), "Output": get_link(s.get('output_file'), "Jarvis_Artifacts_Outputs"), "Text": s.get('llm_text')})
                    
                    # Append common metrics at the end
                    row.update({
                        "Execution (s)": s.get('duration'), 
                        "Setup (s)": s.get('setup_time', 0), 
                        "Cleanup (s)": s.get('cleanup_time', 0), 
                        "VRAM Peak": s.get('vram_peak', 0)
                    })
                    rows.append(row)
            if rows:
                sheets[domain] = pd.DataFrame(rows)
                has_any_data = True

        if not has_any_data: return None

        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.formatting.rule import FormulaRule, ColorScaleRule

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name, index=False)
                worksheet = writer.sheets[name]
                last_data_row = len(df) + 1
                worksheet.auto_filter.ref = f"A1:{chr(64 + len(df.columns))}{last_data_row}"
                worksheet.freeze_panes = "B2"
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
                for cell in worksheet[1]:
                    cell.font = header_font
                    cell.fill = header_fill

                for idx, col in enumerate(df.columns):
                    col_letter = chr(65 + idx)
                    if name == "Summary":
                        if col == "Category": worksheet.column_dimensions[col_letter].width = 15
                        elif col == "Metric": worksheet.column_dimensions[col_letter].width = 25
                        elif col == "Value": worksheet.column_dimensions[col_letter].width = 60
                        continue
                    if any(x in col.lower() for x in ["audio", "media", "input", "output", "link"]):
                        worksheet.column_dimensions[col_letter].width = 15
                        for row_idx in range(2, len(df) + 2):
                            worksheet.cell(row=row_idx, column=idx+1).alignment = Alignment(horizontal='center')
                    else:
                        series = df[col]
                        max_len = max((series.astype(str).map(len).max(), len(str(series.name)))) + 2
                        max_len = min(max_len, 80)
                        worksheet.column_dimensions[col_letter].width = max_len

                green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
                red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
                yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

                for idx, col in enumerate(df.columns):
                    col_letter = chr(65 + idx)
                    range_str = f"{col_letter}2:{col_letter}{len(df)+1}"
                    if col == "Status":
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="PASSED"'], stopIfTrue=True, fill=green_fill))
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="FAILED"'], stopIfTrue=True, fill=red_fill))
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="MISSING"'], stopIfTrue=True, fill=yellow_fill))
                    elif "(s)" in col or col in ["TTFT", "TPS"] or "VRAM" in col:
                        rule = ColorScaleRule(start_type='min', start_color='C6EFCE', mid_type='percentile', mid_value=50, mid_color='FFEB9C', end_type='max', end_color='FFC7CE')
                        worksheet.conditional_formatting.add(range_str, rule)
        
        print(f"📊 Excel Report Generated: {output_path}")
        return output_path
    except Exception as e:
        print(f"❌ Excel Error: {e}"); traceback.print_exc(); return None

def generate_and_upload_report(session_dir, upload_report=True, upload_outputs=False, open_browser=True):
    """Unified entry point for both standalone and runner modes."""
    path = generate_excel(upload=upload_report, upload_outputs=upload_outputs, session_dir=session_dir)
    link = None
    if upload_report and path:
        link = upload_to_gdrive(path)
        if link and open_browser:
            print(f"✅ GDrive Link: {link}")
            print(f"🌐 Opening report in browser...")
            webbrowser.open(link)
    return link or path

def main():
    parser = argparse.ArgumentParser(description="Generate and upload Jarvis benchmark reports.")
    parser.add_argument("--upload-report", action=argparse.BooleanOptionalAction, default=True, help="Upload report and artifacts to GDrive")
    parser.add_argument("--upload-outputs", action="store_true", help="Include transient output artifacts")
    parser.add_argument("--no-open", action="store_false", dest="open_browser", help="Don't open browser automatically")
    parser.add_argument("--dir", type=str, help="Path to a specific session directory")
    args = parser.parse_args()
    
    return generate_and_upload_report(
        session_dir=args.dir, 
        upload_report=args.upload_report, 
        upload_outputs=args.upload_outputs,
        open_browser=args.open_browser
    )

if __name__ == "__main__":
    main()
