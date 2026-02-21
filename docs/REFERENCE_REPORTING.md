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
*   **`duration`**: Inference time in seconds.
*   **`setup_time`**: VRAM allocation and container startup time.
*   **`vram_peak`**: Highest observed memory usage during execution.
*   **`input_file`**: Relative path to the source media.
*   **`output_file`**: Relative path to the generated artifact.

---

## 4. Google Drive Folder IDs
Folder IDs are managed by the `GDriveAssetManager` and cached in the user's GDrive account under these specific names. Jarvis will automatically create them if they do not exist.
