# Troubleshooting Guide

Common issues and solutions for the Jarvis infrastructure.

## 1. Infrastructure & Startup

### "Port already in use"
*   **Symptom:** Server fails to start with a socket error.
*   **Cause:** A zombie process from a previous run is holding the port.
*   **Fix:**
    ```powershell
    python manage_loadout.py --kill all
    ```

### "Docker daemon not running"
*   **Symptom:** vLLM tests fail immediately with `NO-DOCKER`.
*   **Fix:** Start Docker Desktop. Ensure "Use WSL 2 based engine" is checked in Settings > General.

### "Parallel startup timeout"
*   **Symptom:** Tests fail after 800s.
*   **Cause:** vLLM is taking too long to load weights or compile CUDA graphs.
*   **Fix:**
    1.  Check `docker logs -f vllm-server` to see if it's stuck or downloading.
    2.  Increase `model_startup_timeout` in `config.yaml`.

## 2. Models & Inference

### "Model [MISSING]"
*   **Symptom:** Test setup is skipped (yellow/red status).
*   **Cause:** The model weights are not in the local cache.
*   **Fix:** Run with force download enabled:
    ```powershell
    python tests/runner.py tests/plans/ALL_fast.yaml --force-download
    ```

### "OOM" (Out of Memory)
*   **Symptom:** `svc_*.log` shows CUDA OOM error.
*   **Fix:**
    *   **Ollama:** Reduce context window or unload other models (`ollama stop model`).
    *   **vLLM:** Verify the model has been calibrated (`model_calibrations/`). If the calculated VRAM requirement exceeds your GPU capacity, lower the `default_context_size` in `config.yaml`.

## 3. Google Drive Reporting

### "RefreshError: Token has been expired or revoked"
*   **Symptom:** Report upload fails.
*   **Fix:** Delete `token.pickle` in the root directory. The next run will prompt you to re-authenticate in the browser.
