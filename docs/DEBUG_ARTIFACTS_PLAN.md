# Targeted Debug Plan: STT Metadata & vLLM Logging

This plan addresses specific anomalies found in run `RUN_20260217_072239`.

## 1. STT Metadata Fix (The "N/A" Model issue)
*   **Issue**: Failed STT scenarios appear as "Model: N/A" in Excel and missing names in hierarchy.
*   **Cause**: `tests/stt/test.py` only adds the `stt_model` key to the result object in the `status == 200` (success) path.
*   **Fix**: Move the `stt_model` assignment to the top of the scenario loop in `tests/stt/test.py`.

## 2. vLLM Log Capture Fix
*   **Issue**: `svc_llm_vllm-*.log` files only contain a Docker Container ID hash.
*   **Cause**: detached mode (`docker run -d`) returns the ID and exits the host process immediately. The server logs stay inside the container.
*   **Fix**: 
    1.  Update `LifecycleManager.reconcile` to read the Container ID from the `start_server` output.
    2.  Spawn a background `docker logs -f <id>` process.
    3.  Redirect that stream into the session's log file.

## 3. Iterative Verification Suite
*   **Plan**: `tests/plans/DEBUG_ARTIFACTS.yaml`
*   **Loadouts**:
    *   `stt`: `faster-whisper-tiny`, `faster-whisper-base` (Scenarios: `english_std`, `chinese_std`)
    *   `vlm`: `VL_Qwen/Qwen2-VL-2B-Instruct` (Scenarios: `jarvis_logo`)
