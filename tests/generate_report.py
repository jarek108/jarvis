import pandas as pd
import json
import os
import argparse
import pickle
import time
import traceback
import webbrowser
import re
import wave
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

def find_log_fallback(artifacts_dir, model_id, domain_type):
    """Searches directory for a log file matching the model and domain type."""
    # 1. Extract core model ID from potential multi-model STS string
    clean_id = model_id
    if "_" in model_id and domain_type == "llm":
        # Search for the component with engine prefix
        parts = model_id.split("_")
        for p in parts:
            if any(x in p.upper() for x in ["OL_", "VL_", "VLLM:"]):
                clean_id = p; break
    
    # 2. Strip flags (#) and sanitize
    base_id = clean_id.split('#')[0].replace("/", "--").replace(":", "-").lower()
    
    # 3. Try multiple patterns
    patterns = [
        f"svc_{domain_type.lower()}_{base_id}",
        # Fallback for STS where model_id might be engine-less
        f"svc_llm_vl_{base_id}",
        f"svc_llm_ol_{base_id}",
        f"svc_llm_{base_id}",
        f"svc_{domain_type.lower()}"
    ]
    
    # Sort files by name length to find most specific match first
    candidates = sorted(os.listdir(artifacts_dir), key=len, reverse=True)
    for f in candidates:
        if not f.endswith(".log"): continue
        f_lower = f.lower()
        for p in patterns:
            if p.lower() in f_lower:
                return os.path.join(artifacts_dir, f)
    return None

def infer_detailed_name(model_id):
    """Adds resolved defaults to legacy model names for transparent reporting."""
    if not model_id or model_id == "N/A": return model_id
    
    # If it's a combined STS loadout string (joined by _)
    if "_" in model_id:
        parts = model_id.split("_")
        # Recursively infer for each part and join with +
        return " + ".join([infer_detailed_name(p) for p in parts])

    name = model_id.upper()
    # Support legacy nativevideo flag in loadout name
    if "NATIVEVIDEO" in name and "#NATIVE" not in name:
        name = name.replace("NATIVEVIDEO", "#NATIVE")
    
    # Only infer CTX for LLM/VLM engines
    if "#CTX=" not in name:
        # Check if it contains LLM engine patterns
        if "OL_" in name: name += "#CTX=4096"
        elif "VL_" in name: name += "#CTX=16384"
        elif "/" in name or ":" in name: # Guess it's an LLM if it has these markers
            name += "#CTX=16384"
            
    return name

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
        
        master_id = asset_mgr.get_folder_id("Jarvis") if asset_mgr else None
        inputs_id = asset_mgr.get_folder_id("Inputs", master_id) if asset_mgr else None
        outputs_root_id = asset_mgr.get_folder_id("Outputs", master_id) if asset_mgr else None
        session_out_id = asset_mgr.get_folder_id(session_id, outputs_root_id) if asset_mgr else None
        session_out_link = asset_mgr.get_folder_link(session_id, outputs_root_id) if asset_mgr else None

        input_paths = set(); output_paths = set(); log_paths = set(); domains = ["stt", "tts", "llm", "vlm", "sts"]
        all_data = {}
        for d in domains:
            fname = f"{d}.json" if session_dir else f"latest_{d}.json"
            all_data[d] = load_json(os.path.join(artifacts_dir, fname))
        for d, data in all_data.items():
            for entry in data:
                for s in entry.get('scenarios', []):
                    if s.get('input_file'): input_paths.add(s['input_file'])
                    if s.get('output_file'): output_paths.add(s['output_file'])
                    l_path = s.get('log_path')
                    if not l_path:
                        m_id = s.get('llm_model') or s.get('stt_model') or s.get('tts_model') or entry.get('loadout')
                        if m_id:
                            m_type = "llm" if any(x in m_id.lower() for x in ["ol_", "vl_", "vllm:"]) else d
                            l_path = find_log_fallback(artifacts_dir, m_id, m_type)
                    if l_path:
                        s['log_path'] = l_path; log_paths.add(l_path)

        input_paths = [os.path.abspath(os.path.join(project_root, p)) for p in input_paths if p]
        output_paths = [os.path.abspath(os.path.join(project_root, p)) for p in output_paths if p]
        log_paths = [os.path.abspath(os.path.join(project_root, p)) for p in log_paths if p]

        if asset_mgr:
            asset_mgr.batch_upload(input_paths, inputs_id, label="input artifacts")
            if upload_outputs:
                asset_mgr.batch_upload(output_paths + log_paths, session_out_id, label="output artifacts and logs")

        sheets = {}; has_any_data = False
        sys_info_path = os.path.join(artifacts_dir, "system_info.yaml")
        if os.path.exists(sys_info_path):
            import yaml
            with open(sys_info_path, "r", encoding="utf-8") as f: sys_info = yaml.safe_load(f)
            run_val = f'=HYPERLINK("{session_out_link}", "{session_id}")' if session_out_link else session_id
            summary_rows = [
                {"Category": "Session", "Metric": "Run ID", "Value": run_val},
                {"Category": "Session", "Metric": "Original Timestamp", "Value": sys_info.get("timestamp", "N/A")},
                {"Category": "Session", "Metric": "Report Generated", "Value": time.strftime("%Y-%m-%d %H:%M:%S")}
            ]
            for k, v in sys_info.get("host", {}).items(): summary_rows.append({"Category": "Host", "Metric": k.replace("_", " ").title(), "Value": str(v)})
            for k, v in sys_info.get("git", {}).items(): summary_rows.append({"Category": "Git", "Metric": k.title(), "Value": str(v)})
            plan = sys_info.get("plan", {})
            summary_rows.append({"Category": "Plan", "Metric": "Name", "Value": plan.get("name", "N/A")})
            summary_rows.append({"Category": "Plan", "Metric": "Description", "Value": plan.get("description", "N/A")})
            sheets["Summary"] = pd.DataFrame(summary_rows); has_any_data = True

        def get_link(local_path, folder_id=None):
            if not local_path: return "N/A"
            abs_p = os.path.abspath(os.path.join(project_root, local_path))
            fname = os.path.basename(abs_p)
            if asset_mgr and folder_id:
                cache = asset_mgr.file_cache.get(folder_id, {})
                if fname in cache:
                    label = "▶️ Play" if ".wav" in fname else ("👁️ View" if "." in fname else "📄 Log")
                    return f'=HYPERLINK("{cache[fname]}", "{label}")'
            return f'=HYPERLINK("{abs_p}", "📁 Local File")'

        def r3(val):
            try: return round(float(val), 3) if val is not None else 0
            except: return 0

        for domain in ["STT", "TTS", "LLM", "VLM", "STS"]:
            data = all_data.get(domain.lower())
            if not data: continue
            print(f"📊 Processing {domain} sheet...")
            rows = []
            for entry in data:
                loadout_name = entry.get('loadout', 'N/A')
                for s in entry.get('scenarios', []):
                    raw_model = s.get('detailed_model') or loadout_name
                    if raw_model == 'N/A': raw_model = s.get('llm_model') or s.get('stt_model') or s.get('tts_model') or "N/A"
                    model_col = infer_detailed_name(raw_model)
                    log_link = get_link(s.get('log_path'), session_out_id)
                    model_val = f'=HYPERLINK("{log_link.split(chr(34))[1]}", "{model_col}")' if log_link and log_link.startswith("=") else model_col
                    prompt = str(s.get('input_text', 'N/A')).replace('\n', ' ').replace('\r', ' ')
                    response = str(s.get('text') or s.get('raw_text') or s.get('llm_text') or "N/A").replace('\n', ' ').replace('\r', ' ')
                    
                    # Resolve metrics
                    rtf = s.get('rtf', 0); wps = s.get('wps', 0); cps = s.get('cps', 0); ttft = s.get('ttft', 0); tps = s.get('tps', 0); exec_time = s.get('duration', 0)
                    if exec_time > 0:
                        if domain == "STT":
                            if not wps or wps == 0: wps = len(response.split()) / exec_time
                            if not rtf or rtf == 0:
                                audio_p = os.path.abspath(os.path.join(project_root, s.get('input_file', '')))
                                if os.path.exists(audio_p):
                                    try:
                                        with wave.open(audio_p, 'rb') as wf: rtf = exec_time / (wf.getnframes() / float(wf.getframerate()))
                                    except: pass
                        elif domain == "TTS":
                            if not cps or cps == 0: cps = len(prompt) / exec_time
                            if not wps or wps == 0: wps = len(prompt.split()) / exec_time

                    # --- ROW CONSTRUCTION (Order: Identity > Status > Metrics > Artifacts > Text) ---
                    row = {"Loadout": model_val, "Scenario": s.get('name'), "Status": s.get('status')}
                    
                    # 1. Metrics block
                    if domain == "STT": row.update({"RTF": r3(rtf), "WPS": r3(wps), "Match %": r3(s.get('match_pct'))})
                    elif domain == "TTS": row.update({"CPS": r3(cps), "WPS": r3(wps)})
                    elif domain == "LLM": row.update({"TTFT": r3(ttft), "TPS": r3(tps)})
                    elif domain == "VLM": row.update({"TTFT": r3(ttft), "TPS": r3(tps)})
                    elif domain == "STS":
                        m = s.get('metrics', {})
                        row.update({"TTFT": r3(ttft), "STT Inf": r3(s.get('stt_inf') or m.get('stt', [0,0])[1]), "LLM Tot": r3(s.get('llm_tot') or (m.get('llm', [0,0])[1] - m.get('llm', [0,0])[0])), "TTS Inf": r3(s.get('tts_inf') or (m.get('tts', [0,0])[1] - m.get('tts', [0,0])[0]))})
                    
                    row.update({"Exec": r3(exec_time), "Setup": r3(s.get('setup_time')), "Cleanup": r3(s.get('cleanup_time')), "VRAM": r3(s.get('vram_peak'))})
                    
                    # 2. Artifacts block
                    if domain == "STT": row.update({"Audio": get_link(s.get('input_file'), inputs_id)})
                    elif domain == "TTS": row.update({"Audio": get_link(s.get('output_file'), session_out_id)})
                    elif domain == "VLM": row.update({"Media": get_link(s.get('input_file'), inputs_id)})
                    elif domain == "STS": row.update({"Input": get_link(s.get('input_file'), inputs_id), "Output": get_link(s.get('output_file'), session_out_id)})
                    
                    # 3. Text block
                    if domain == "STT": row.update({"Result": response})
                    elif domain == "TTS": row.update({"Input": prompt})
                    elif domain in ["LLM", "VLM"]: row.update({"Prompt": prompt, "Response": response})
                    elif domain == "STS": row.update({"Text": response})
                    
                    rows.append(row)
            if rows:
                sheets[domain] = pd.DataFrame(rows); has_any_data = True

        if not has_any_data: return None
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.formatting.rule import FormulaRule, ColorScaleRule
        from utils import load_config
        cfg = load_config(); report_cfg = cfg.get('reporting', {}).get('excel', {})
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name, index=False)
                worksheet = writer.sheets[name]; last_data_row = len(df) + 1
                worksheet.auto_filter.ref = f"A1:{chr(64 + len(df.columns))}{last_data_row}"; worksheet.freeze_panes = "B2"
                header_font = Font(bold=True, color="FFFFFF"); header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
                for cell in worksheet[1]: cell.font = header_font; cell.fill = header_fill
                for row_idx in range(2, last_data_row + 1): worksheet.row_dimensions[row_idx].height = 15
                domain_overrides = report_cfg.get('domain_overrides', {}).get(name.lower(), {})
                for idx, col in enumerate(df.columns):
                    col_letter = chr(65 + idx)
                    for row_idx in range(2, last_data_row + 1): worksheet.cell(row=row_idx, column=idx+1).alignment = Alignment(wrap_text=False, vertical='center')
                    if name == "Summary":
                        if col == "Category": worksheet.column_dimensions[col_letter].width = 15
                        elif col == "Metric": worksheet.column_dimensions[col_letter].width = 25
                        elif col == "Value": worksheet.column_dimensions[col_letter].width = 60
                        continue
                    if col in domain_overrides: width = domain_overrides[col]
                    elif col == "Loadout": width = report_cfg.get('loadout_width', 35)
                    elif any(x in col.lower() for x in ["audio", "media", "input", "output", "link"]):
                        width = report_cfg.get('media_column_width', 12)
                        for row_idx in range(2, last_data_row + 1): worksheet.cell(row=row_idx, column=idx+1).alignment = Alignment(horizontal='center', wrap_text=False)
                    elif any(x in col.lower() for x in ["prompt", "response", "text", "result", "input"]): width = report_cfg.get('text_column_width', 50)
                    elif col in ["Exec", "Setup", "Cleanup", "VRAM", "TTFT", "TPS", "RTF", "WPS", "CPS", "Match %"] or "Inf" in col or "Tot" in col:
                        width = report_cfg.get('metric_column_width', 12)
                        for row_idx in range(2, last_data_row + 1): worksheet.cell(row=row_idx, column=idx+1).alignment = Alignment(horizontal='right', wrap_text=False)
                    else: width = report_cfg.get('default_width', 15)
                    worksheet.column_dimensions[col_letter].width = width
                green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"); red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"); yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
                for idx, col in enumerate(df.columns):
                    col_letter = chr(65 + idx); range_str = f"{col_letter}2:{col_letter}{last_data_row}"
                    if col == "Status":
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="PASSED"'], stopIfTrue=True, fill=green_fill))
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="FAILED"'], stopIfTrue=True, fill=red_fill))
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="MISSING"'], stopIfTrue=True, fill=yellow_fill))
                    elif col in ["Exec", "Setup", "Cleanup", "VRAM", "TTFT", "TPS", "RTF", "WPS", "CPS"]:
                        rule = ColorScaleRule(start_type='min', start_color='C6EFCE', mid_type='percentile', mid_value=50, mid_color='FFEB9C', end_type='max', end_color='FFC7CE')
                        if col in ["TPS", "WPS", "CPS"]: rule = ColorScaleRule(start_type='min', start_color='FFC7CE', mid_type='percentile', mid_value=50, mid_color='FFEB9C', end_type='max', end_color='C6EFCE')
                        worksheet.conditional_formatting.add(range_str, rule)
        print(f"📊 Excel Report Generated: {output_path}"); return output_path
    except Exception as e:
        print(f"❌ Excel Error: {e}"); traceback.print_exc(); return None

def generate_and_upload_report(session_dir, upload_report=True, upload_outputs=False, open_browser=True):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    service = get_gdrive_service() if upload_report else None
    asset_mgr = GDriveAssetManager(service) if service else None
    path = generate_excel(upload=upload_report, upload_outputs=upload_outputs, session_dir=session_dir)
    if not path: return None
    link = None
    if upload_report:
        master_id = asset_mgr.get_folder_id("Jarvis")
        print(f"📤 Uploading report to GDrive master folder...")
        link = asset_mgr.sync_file(path, master_id, overwrite=False)
        if link:
            print(f"✅ GDrive Link: {link}\n🌐 Opening report in browser...")
            if open_browser: webbrowser.open(link)
    return link or path

def main():
    parser = argparse.ArgumentParser(description="Generate and upload Jarvis benchmark reports.")
    parser.add_argument("--upload-report", action=argparse.BooleanOptionalAction, default=True, help="Upload report and artifacts to GDrive")
    parser.add_argument("--upload-outputs", action="store_true", help="Include transient output artifacts")
    parser.add_argument("--no-open", action="store_false", dest="open_browser", help="Don't open browser automatically")
    parser.add_argument("--dir", type=str, help="Path to a specific session directory")
    args = parser.parse_args()
    return generate_and_upload_report(session_dir=args.dir, upload_report=args.upload_report, upload_outputs=args.upload_outputs, open_browser=args.open_browser)

if __name__ == "__main__":
    main()
