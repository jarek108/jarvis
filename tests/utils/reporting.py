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
    status_fmt = format_status(res_obj['status'])
    name = res_obj['name']
    tps = res_obj.get('tps', 0)
    text = res_obj.get('text', "N/A")
    thought = res_obj.get('thought', "")
    t1 = res_obj.get('ttft', 0)
    t2 = res_obj.get('duration', 0)
    if res_obj.get('chunks'):
        text = fmt_with_chunks(res_obj.get('raw_text', ""), res_obj.get('chunks'))
    row = f"  - {status_fmt} | {t1:.3f} → {t2:.3f}s | TPS:{tps:.1f} | Scenario: {name:<15}\n"
    sys.stdout.write(row)
    if thought:
        sys.stdout.write(f"    \t💭 Thought: \"{thought[:100]}...\"\n")
    sys.stdout.write(f"    \t🧠 Text: \"{text}\"\n")
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def report_scenario_result(res_obj):
    status_fmt = format_status(res_obj['status'])
    name = res_obj['name']
    dur = res_obj.get('duration', 0)
    result = res_obj.get('result', "")
    if res_obj.get('mode') in ["WAV", "STREAM"] and "stt_model" in res_obj:
        m = res_obj.get('metrics', {})
        if res_obj['mode'] == "STREAM":
            t1_audio, t2_audio = m.get('tts', [0,0])
            sys.stdout.write(f"  - {status_fmt} {name} ({t1_audio:.2f} → {t2_audio:.2f}s) | STREAM\n")
            def fmt_range(key):
                r = m.get(key, [0, 0])
                return f"{r[0]:.2f} → {r[1]:.2f}s"
            stt_ready = m.get('stt',[0,0])[1]
            stt_text = f"{m.get('stt_text', 'N/A')} ({stt_ready:.2f} → {stt_ready:.2f}s)"
            llm_text = fmt_with_chunks(m.get('llm_text', 'N/A').strip(), m.get('llm_chunks', []))
            if "(" not in llm_text and llm_text != "N/A":
                llm_end = m.get('llm',[0,0])[1]
                llm_text = f"{llm_text} ({llm_end:.2f} → {llm_end:.2f}s)"
            sys.stdout.write(f"    \t🎙️ {fmt_range('stt')} | [{res_obj.get('stt_model','STT')}] | Text: \"{stt_text}\"\n")
            sys.stdout.write(f"    \t🧠 {fmt_range('llm')} | [{res_obj.get('llm_model','LLM')}] | Text: \"{llm_text}\"\n")
            sys.stdout.write(f"    \t🔊 {fmt_range('tts')} | [{res_obj.get('tts_model','TTS')}] | Path: {result}\n")
        else:
            stt_end = res_obj.get('stt_inf', 0)
            llm_end = stt_end + res_obj.get('llm_tot', 0)
            sys.stdout.write(f"  - {status_fmt} {name} ({dur:.2f} → {dur:.2f}s) | WAV\n")
            fmt_stt = f"{stt_end:.2f} → {stt_end:.2f}s"
            fmt_llm = f"{llm_end:.2f} → {llm_end:.2f}s"
            fmt_tts = f"{dur:.2f} → {dur:.2f}s"
            stt_text = res_obj.get('stt_text', 'N/A')
            llm_text = res_obj.get('llm_text', 'N/A')
            sys.stdout.write(f"    \t🎙️ {fmt_stt} | [{res_obj.get('stt_model','STT')}] | Text: \"{stt_text} ({fmt_stt})\"\n")
            sys.stdout.write(f"    \t🧠 {fmt_llm} | [{res_obj.get('llm_model','LLM')}] | Text: \"{llm_text} ({fmt_llm})\"\n")
            sys.stdout.write(f"    \t🔊 {fmt_tts} | [{res_obj.get('tts_model','TTS')}] | Path: {result}\n")
    else:
        sys.stdout.write(f"  - {status_fmt} | {dur:.2f}s | {name:<25} | {result}\n")
    sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(res_obj)}\n")
    sys.stdout.flush()

def save_artifact(domain, data):
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        # Import dynamically to avoid top-level dependencies
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if parent_dir not in sys.path:
            sys.path.append(parent_dir)
        from generate_report import generate_excel, upload_to_gdrive
        path = generate_excel()
        if upload and path:
            upload_to_gdrive(path)
    except Exception as e:
        print(f"⚠️ Auto-report failed: {e}")
    print("-" * 40 + "\n")
