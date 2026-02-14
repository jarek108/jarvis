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
from utils.ui import fmt_with_chunks

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
    try:
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

        # Helper for totals
        def append_total_row(df, duration_cols=None):
            if not duration_cols: duration_cols = ["Execution (s)", "Setup (s)", "Cleanup (s)"]
            sum_data = {c: "" for c in df.columns}
            sum_data[df.columns[0]] = "TOTAL"
            has_cols = False
            for col in duration_cols:
                if col in df.columns:
                    sum_data[col] = pd.to_numeric(df[col], errors='coerce').sum()
                    has_cols = True
            if has_cols:
                sum_row = pd.DataFrame([sum_data])
                return pd.concat([df, sum_row], ignore_index=True)
            return df

        def link_file(local_path, folder_id, overwrite=True, label="Open"):
            if not asset_mgr or not local_path: return local_path
            if not os.path.isabs(local_path):
                local_path = os.path.join(project_root, local_path)
            if not os.path.exists(local_path): return "N/A"
            url = asset_mgr.sync_file(local_path, folder_id, overwrite=overwrite)
            if url and url.startswith("http"):
                return f'=HYPERLINK("{url}", "{label}")'
            return url

        def get_link_label(path, base="Open"):
            if not path: return base
            ext = os.path.splitext(path)[1].lower()
            if ext in [".wav", ".mp3", ".ogg"]: return "▶️ Play wav"
            if ext in [".mp4", ".mkv", ".avi"]: return "🎬 Watch video"
            return base

        # 1. STT
        stt_path = os.path.join(artifacts_dir, "latest_stt.json")
        data = load_json(stt_path)
        if data:
            print(f"📁 Loading STT data from {stt_path}...")
            rows = []
            for entry in data:
                setup = entry.get('loadout', 'unknown')
                for s in entry.get('scenarios', []):
                    rows.append({
                        "Setup": setup,
                        "Model": s.get("stt_model", "N/A"),
                        "Scenario": s.get('name'),
                        "Input wav": link_file(s.get('input_file'), input_folder_id, overwrite=False, label="▶️ Play wav"),
                        "Input Text (GT)": s.get('input_text', 'N/A'),
                        "Output Text": f"{s.get('output_text', 'N/A')} ({s.get('duration', 0):.2f}s)",
                        "Status": s.get('status'),
                        "Result": s.get('result'),
                        "Prior VRAM (GB)": s.get('vram_prior', 0),
                        "Peak VRAM (GB)": s.get('vram_peak', 0),
                        "Execution (s)": s.get('duration'),
                        "Setup (s)": s.get('setup_time', 0),
                        "Cleanup (s)": s.get('cleanup_time', 0)
                    })
            if rows:
                df = pd.DataFrame(rows)
                df.sort_values(by=["Setup", "Scenario"], inplace=True)
                df = append_total_row(df)
                sheets["STT"] = df
                has_any_data = True

        # 2. TTS
        tts_path = os.path.join(artifacts_dir, "latest_tts.json")
        data = load_json(tts_path)
        if data:
            print(f"📁 Loading TTS data from {tts_path}...")
            rows = []
            for entry in data:
                setup = entry.get('loadout', 'unknown')
                for s in entry.get('scenarios', []):
                    rows.append({
                        "Setup": setup,
                        "Model": s.get("tts_model", "N/A"),
                        "Scenario": s.get('name'),
                        "Input Text": s.get('input_text', 'N/A'),
                        "Output wav": link_file(s.get('output_file'), output_folder_id, overwrite=True, label="▶️ Play wav"),
                        "Status": s.get('status'),
                        "Result": s.get('result'),
                        "Prior VRAM (GB)": s.get('vram_prior', 0),
                        "Peak VRAM (GB)": s.get('vram_peak', 0),
                        "Execution (s)": s.get('duration'),
                        "Setup (s)": s.get('setup_time', 0),
                        "Cleanup (s)": s.get('cleanup_time', 0)
                    })
            if rows:
                df = pd.DataFrame(rows)
                df.sort_values(by=["Setup", "Scenario"], inplace=True)
                df = append_total_row(df)
                sheets["TTS"] = df
                has_any_data = True

        # 3. LLM
        llm_path = os.path.join(artifacts_dir, "latest_llm.json")
        data = load_json(llm_path)
        if data:
            print(f"📁 Loading LLM data from {llm_path}...")
            rows = []
            for entry in data:
                setup = entry.get('loadout', 'unknown')
                for s in entry.get('scenarios', []):
                    out_text = s.get('text') or s.get('raw_text', 'N/A')
                    if s.get('streaming') and s.get('chunks'):
                        out_text = fmt_with_chunks(out_text, s['chunks'])
                    else:
                        out_text = f"{out_text} ({s.get('duration', 0):.2f}s)"

                    rows.append({
                        "Setup": setup,
                        "Model": s.get("llm_model", "N/A"),
                        "Scenario": s.get('name'),
                        "Input Text": s.get('input_text', 'N/A'),
                        "Output Text": out_text,
                        "Status": s.get('status'),
                        "Result": s.get('result', 'N/A'),
                        "Streaming": "Yes" if s.get('streaming') else "No",
                        "Prior VRAM (GB)": s.get('vram_prior', 0),
                        "Peak VRAM (GB)": s.get('vram_peak', 0),
                        "TTFT (s)": s.get('ttft'),
                        "TPS": s.get('tps'),
                        "Execution (s)": s.get('duration'),
                        "Setup (s)": s.get('setup_time', 0),
                        "Cleanup (s)": s.get('cleanup_time', 0)
                    })
            if rows:
                df = pd.DataFrame(rows)
                df.sort_values(by=["Setup", "Scenario"], inplace=True)
                df = append_total_row(df)
                sheets["LLM"] = df
                has_any_data = True

        # 4. VLM
        vlm_path = os.path.join(artifacts_dir, "latest_vlm.json")
        data = load_json(vlm_path)
        if data:
            print(f"📁 Loading VLM data from {vlm_path}...")
            rows = []
            for entry in data:
                setup = entry.get('loadout', 'unknown')
                for s in entry.get('scenarios', []):
                    label = get_link_label(s.get('input_file'), "👁️ View")
                    out_text = s.get('text') or s.get('raw_text', 'N/A')
                    if s.get('streaming') and s.get('chunks'):
                        out_text = fmt_with_chunks(out_text, s['chunks'])
                    else:
                        out_text = f"{out_text} ({s.get('duration', 0):.2f}s)"

                    rows.append({
                        "Setup": setup,
                        "Model": s.get("llm_model", "N/A"),
                        "Scenario": s.get('name'),
                        "Input Text": s.get('input_text', 'N/A'),
                        "Input Media": link_file(s.get('input_file'), input_folder_id, overwrite=False, label=label),
                        "Output Text": out_text,
                        "Status": s.get('status'),
                        "Result": s.get('result', 'N/A'),
                        "Streaming": "Yes" if s.get('streaming') else "No",
                        "Prior VRAM (GB)": s.get('vram_prior', 0),
                        "Peak VRAM (GB)": s.get('vram_peak', 0),
                        "TTFT (s)": s.get('ttft'),
                        "TPS": s.get('tps'),
                        "Execution (s)": s.get('duration'),
                        "Setup (s)": s.get('setup_time', 0),
                        "Cleanup (s)": s.get('cleanup_time', 0)
                    })
            if rows:
                df = pd.DataFrame(rows)
                df.sort_values(by=["Setup", "Scenario"], inplace=True)
                df = append_total_row(df)
                sheets["VLM"] = df
                has_any_data = True

        # 5. STS
        sts_path = os.path.join(artifacts_dir, "latest_sts.json")
        data = load_json(sts_path)
        if data:
            print(f"📁 Loading STS data from {sts_path}...")
            rows = []
            for entry in data:
                setup = entry.get('loadout', 'unknown')
                for s in entry.get('scenarios', []):
                    m = s.get('metrics', {})
                    out_text = s.get('llm_text', 'N/A')
                    if s.get('streaming') and s.get('chunks'):
                        out_text = fmt_with_chunks(out_text, s['chunks'])
                    else:
                        out_text = f"{out_text} ({s.get('duration', 0):.2f}s)"

                    rows.append({
                        "Setup": setup, 
                        "STT Model": s.get('stt_model', 'N/A'),
                        "LLM Model": s.get('llm_model', 'N/A'),
                        "TTS Model": s.get('tts_model', 'N/A'),
                        "Scenario": s.get('name'), 
                        "Input wav": link_file(s.get('input_file'), input_folder_id, overwrite=False, label="▶️ Play wav"),
                        "Input Text": s.get('stt_text', 'N/A'),
                        "Output wav": link_file(s.get('output_file'), output_folder_id, overwrite=True, label="▶️ Play wav"),
                        "Output Text": out_text,
                        "Status": s.get('status'),
                        "Result": s.get('result', 'N/A'),
                        "Streaming": "Yes" if s.get('streaming') else "No",
                        "Prior VRAM (GB)": s.get('vram_prior', 0),
                        "Peak VRAM (GB)": s.get('vram_peak', 0),
                        "STT Time": s.get('stt_inf') or m.get('stt', [0,0])[1],
                        "LLM Time": s.get('llm_tot') or (m.get('llm', [0,0])[1] - m.get('llm', [0,0])[0]),
                        "TTS Time": s.get('tts_inf') or (m.get('tts', [0,0])[1] - m.get('tts', [0,0])[0]),
                        "Execution (s)": s.get('duration'),
                        "Setup (s)": s.get('setup_time', 0),
                        "Cleanup (s)": s.get('cleanup_time', 0)
                    })
            if rows:
                df = pd.DataFrame(rows)
                df.sort_values(by=["Setup", "Scenario"], inplace=True)
                df = append_total_row(df, duration_cols=["Execution (s)", "Setup (s)", "Cleanup (s)"])
                sheets["STS"] = df
                has_any_data = True

        if not has_any_data:
            print("⚠️ No artifact data found. Excel generation skipped.")
            return None

        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.formatting.rule import FormulaRule, ColorScaleRule

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name, index=False)
                worksheet = writer.sheets[name]
                
                # 1. AutoFilter
                worksheet.auto_filter.ref = worksheet.dimensions
                
                # 2. Header Style
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
                for cell in worksheet[1]:
                    cell.font = header_font
                    cell.fill = header_fill

                # 3. Column Widths
                for idx, col in enumerate(df.columns):
                    col_letter = chr(65 + idx)
                    if any(x in col.lower() for x in ["wav", "video", "media", "link"]):
                        worksheet.column_dimensions[col_letter].width = 15
                        for row_idx in range(2, len(df) + 2):
                            worksheet.cell(row=row_idx, column=idx+1).alignment = Alignment(horizontal='center')
                    elif col == "Setup":
                        worksheet.column_dimensions[col_letter].width = 25
                    elif col == "Status":
                        worksheet.column_dimensions[col_letter].width = 15
                    elif col == "Streaming":
                        worksheet.column_dimensions[col_letter].width = 15
                    elif "VRAM" in col:
                        worksheet.column_dimensions[col_letter].width = 18
                    else:
                        series = df[col]
                        valid_series = series[:-1] if len(series) > 1 else series
                        max_len = max((valid_series.astype(str).map(len).max(), len(str(series.name)))) + 2
                        max_len = min(max_len, 80)
                        worksheet.column_dimensions[col_letter].width = max_len

                # 4. Conditional Formatting
                green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
                red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
                yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
                gray_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")

                for idx, col in enumerate(df.columns):
                    col_letter = chr(65 + idx)
                    range_str = f"{col_letter}2:{col_letter}{len(df)+1}"
                    
                    if col == "Status":
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="PASSED"'], stopIfTrue=True, fill=green_fill))
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="FAILED"'], stopIfTrue=True, fill=red_fill))
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="MISSING"'], stopIfTrue=True, fill=yellow_fill))
                    
                    elif col == "Streaming":
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="Yes"'], stopIfTrue=True, fill=green_fill))
                        worksheet.conditional_formatting.add(range_str, FormulaRule(formula=[f'{col_letter}2="No"'], stopIfTrue=True, fill=gray_fill))

                    elif "(s)" in col or "Time" in col:
                        rule = ColorScaleRule(start_type='min', start_color='C6EFCE', 
                                              mid_type='percentile', mid_value=50, mid_color='FFEB9C',
                                              end_type='max', end_color='FFC7CE')
                        worksheet.conditional_formatting.add(range_str, rule)
                    
                    elif "VRAM" in col:
                        rule = ColorScaleRule(start_type='min', start_color='C6EFCE', 
                                              mid_type='percentile', mid_value=50, mid_color='FFEB9C',
                                              end_type='max', end_color='FFC7CE')
                        worksheet.conditional_formatting.add(range_str, rule)

                # 5. Bold Total Row
                total_row_idx = len(df) + 1
                for cell in worksheet[total_row_idx]:
                    cell.font = Font(bold=True)
            
        print(f"📊 Excel Report Generated: {output_path}")
        return output_path

    except Exception as e:
        print(f"❌ Excel Generation Error: {e}")
        traceback.print_exc()
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and upload Jarvis benchmark reports.")
    parser.add_argument("--upload", action="store_true", help="Upload to GDrive via native API")
    args = parser.parse_args()
    path = generate_excel(sync_artifacts=args.upload)
    if args.upload and path:
        upload_to_gdrive(path)
