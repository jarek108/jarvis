# Tutorial: Onboarding Your First Model

In this lesson, you will learn how to "onboard" a new model into the Jarvis ecosystem. By the end, you will have generated a **Physics Datasheet** that allows Jarvis to manage the model's VRAM efficiently.

## Prerequisites
*   Jarvis is installed and configured.
*   The model you want to add is downloaded (e.g., `ollama pull qwen2.5:0.5b`).

## Step 1: Generate Evidence (The Run)
Jarvis needs to "see" the model run once to understand its memory signatures.

1.  Open your terminal.
2.  Start the model manually:
    *   **Ollama**: `ollama run qwen2.5:0.5b`
    *   **vLLM**: Run a test plan containing the model (e.g., `python tests/runner.py plans/LLM_fast.yaml`).

## Step 2: Locate the Logs
During the run, the engine produces logs containing its internal memory allocations.

*   **If you used Ollama**: Your system log is located at `%LOCALAPPDATA%\Ollama\server.log`.
*   **If you used vLLM**: Capture the docker log: `docker logs vllm-server > startup.log`.

## Step 3: Calibrate
Now, we use the calibration tool to translate that log into a physics datasheet.

```powershell
# Point the script to the log you found in Step 2
python utils/calibrate_models.py C:\Path\To\Your\LogFile.log
```

## Step 4: Verify the Results
1.  Navigate to the `model_calibrations/` directory in the project root.
2.  You should see a new `.yaml` file named after your model (e.g., `ol_qwen2.5-0.5b.yaml`).
3.  Open it. You will see the `base_vram_gb` and `kv_cache_gb_per_10k` values that Jarvis discovered.

## Success!
Jarvis now understands the "physics" of this model. The next time you use it in a test plan or loadout, Jarvis will automatically optimize the VRAM allocation based on these numbers.
