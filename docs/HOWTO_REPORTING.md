# How-to Guide: Managing Benchmark Reports

This guide provides instructions for generating, regenerating, and synchronizing performance reports.

## 1. Automatic Reporting (Standard Run)
By default, the test runner automatically triggers a report at the end of every successful execution.

*   **Behavior**: Generates an Excel file, syncs all **input** artifacts to GDrive, and uploads the final report.
*   **Link**: The GDrive sharing link is printed in the dashboard and recorded in the run's `progression.log`.

## 2. Manual Regeneration
Use the standalone `generate_report.py` script to recreate a report from an existing run folder.

### Basic Regeneration
```powershell
python tests/generate_report.py --dir tests/logs/RUN_20260221_093804
```
*   This will refresh the Excel file in the target folder and ensure its links are up to date.

### Full Cloud Sync (Including Outputs)
By default, transient output audio is not uploaded to save time. To create a fully portable cloud report:
```powershell
python tests/generate_report.py --dir tests/logs/RUN_XYZ --upload-outputs
```

### Local Only (No Network)
If you are working offline or want a quick draft:
```powershell
python tests/generate_report.py --dir tests/logs/RUN_XYZ --no-upload-report
```

## 3. Organizing the Archive
Jarvis generates many folders. To maintain a clean environment:
1.  **Keep `system_info.yaml`**: The report generator cannot run without this file.
2.  **Keep domain JSONs**: `stt.json`, `tts.json`, etc., contain the raw metrics.
3.  **Delete `.log` files**: If you only care about the metrics and not the low-level traces, the `svc_*.log` files can be safely removed to save space.

## 4. Handling Auth Errors
If the report generator fails with a "Token Expired" error:
1.  Delete `token.pickle` in the project root.
2.  Run any report command.
3.  A browser window will open for you to re-authenticate with your Google account.
