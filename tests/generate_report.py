import pandas as pd
import json
import os
import glob
import time
import subprocess
import argparse

def load_json(path):
    if not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_excel():
    artifacts_dir = os.path.join(os.path.dirname(__file__), "artifacts")
    output_path = os.path.join(artifacts_dir, "Jarvis_Benchmark_Report.xlsx")
    
    writer = pd.ExcelWriter(output_path, engine='openpyxl')
    
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
        df = pd.DataFrame(rows)
        df.to_excel(writer, sheet_name=domain.upper(), index=False)

    # 2. LLMSTRUCTURE
    data = load_json(os.path.join(artifacts_dir, "latest_llm.json"))
    if data:
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
        pd.DataFrame(rows).to_excel(writer, sheet_name="LLM", index=False)

    # 3. VLM STRUCTURE
    data = load_json(os.path.join(artifacts_dir, "latest_vlm.json"))
    if data:
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
        pd.DataFrame(rows).to_excel(writer, sheet_name="VLM", index=False)

    # 4. S2S STRUCTURE
    data = load_json(os.path.join(artifacts_dir, "latest_s2s.json"))
    if data:
        rows = []
        for entry in data:
            loadout = entry.get('loadout', 'unknown')
            vram = entry.get('vram', {}).get('peak_gb', 0)
            for s in entry.get('scenarios', []):
                m = s.get('metrics', {})
                rows.append({
                    "Loadout": loadout,
                    "Scenario": s.get('name'),
                    "Mode": s.get('mode'),
                    "Status": s.get('status'),
                    "Total Duration (s)": s.get('duration'),
                    "STT Time": s.get('stt_inf') or m.get('stt', [0,0])[1],
                    "LLM Time": s.get('llm_tot') or (m.get('llm', [0,0])[1] - m.get('llm', [0,0])[0]),
                    "TTS Time": s.get('tts_inf') or (m.get('tts', [0,0])[1] - m.get('tts', [0,0])[0]),
                    "VRAM Peak (GB)": vram
                })
        pd.DataFrame(rows).to_excel(writer, sheet_name="S2S", index=False)

    writer.close()
    print(f"📊 Excel Report Generated: {output_path}")
    return output_path

def upload_rclone(file_path):
    print(f"☁️ Uploading to GDrive via rclone...")
    try:
        # We assume a remote named 'gdrive' exists
        cmd = ["rclone", "copy", file_path, "gdrive:Jarvis_Reports", "-v"]
        subprocess.run(cmd, check=True)
        print("✅ Upload successful!")
    except Exception as e:
        print(f"❌ Upload failed (Is rclone configured?): {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and upload Jarvis benchmark reports.")
    parser.add_argument("--upload", action="store_true", help="Upload to GDrive via rclone")
    args = parser.parse_args()
    
    path = generate_excel()
    if args.upload:
        upload_rclone(path)
