# Reference: Reporting CLI & Data Schema

Technical specifications for the Jarvis benchmark reporting system.

## 1. CLI: `tests/generate_report.py`

### Arguments
| Flag | Default | Description |
| :--- | :--- | :--- |
| `--dir` | None | Path to the session folder (required for standalone use). |
| `--upload-report` | `True` | Syncs report and input artifacts to Google Drive. |
| `--no-upload-report` | `False` | Disables all GDrive communication. |
| `--upload-outputs` | `False` | Forces upload of transient generated audio/video. |

---

## 2. Core Metadata: `system_info.yaml`
Every session folder must contain this file for report generation to succeed.

### Key Fields
*   **`timestamp`**: The original execution start time (used for report naming).
*   **`plan`**: Dictionary containing `name` and `description` of the test plan.
*   **`host`**: CPU, GPU, and RAM specs of the machine.
*   **`git`**: Branch and hash of the code used during the run.

---

## 3. Result Schema: `[domain].json`
Each domain (STT, TTS, LLM, VLM, STS) generates an array of scenario results.

### Common Scenario Fields
*   **`name`**: The unique scenario ID from the test plan.
*   **`status`**: `PASSED`, `FAILED`, or `MISSING`.
*   **`duration`**: (Exec) Inference time in seconds.
*   **`setup_time`**: (Setup) VRAM allocation and container startup time.
*   **`cleanup_time`**: (Cleanup) Time taken to kill processes and release memory.
*   **`vram_peak`**: (VRAM) Highest observed memory usage during execution.
*   **`rtf`**: Real-Time Factor (Duration / Audio Length).
*   **`ttft`**: Time to First Token.
*   **`tps`**: Tokens per second.
*   **`input_file`**: Relative path to the source media.
*   **`output_file`**: Relative path to the generated artifact.

---

## 4. Excel Report Layout
The Excel report uses an **Analysis-First** layout, ordering columns by importance:
`Identity > Status > Metrics > Artifacts > Text Details`.

### Column Definitions (Excel Notes)
Every column header in the Excel report contains a tooltip explaining its meaning:

| Header | Tooltip / Formula |
| :--- | :--- |
| **Exec** | Duration of the primary inference or pipeline call (s). |
| **Setup** | Time taken to boot servers and load models into VRAM (s). |
| **Cleanup** | Time taken to kill processes and release GPU memory (s). |
| **VRAM** | Highest recorded GPU memory consumption (GB). |
| **RTF** | Execution Time / Audio Duration (Lower is better). |
| **TTFT** | Latency until the first piece of data is received (s). |
| **TPS** | Average generation speed (tokens/s). |
| **Match %** | Fuzzy matching score between result and ground truth. |

### Visual Heatmaps
Jarvis applies conditional formatting automatically:
*   **Status**: Green (Passed), Red (Failed), Yellow (Missing).
*   **Performance**: Color scales (Green to Red).
    *   *Lower is Better*: Exec, Setup, Cleanup, VRAM, RTF, TTFT.
    *   *Higher is Better*: TPS, WPS, CPS, Match %.

---

## 5. Google Drive Folder IDs
Folder IDs are managed by the `GDriveAssetManager` and cached in the user's GDrive account under these specific names. Jarvis will automatically create them if they do not exist.
