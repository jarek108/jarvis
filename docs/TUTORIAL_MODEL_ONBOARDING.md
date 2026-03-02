# Tutorial: Onboarding a New Model

In this lesson, you will learn how to "onboard" a new model into the Jarvis ecosystem. By the end, you will have generated a **Physics Datasheet** that allows Jarvis to manage the model's VRAM efficiently.

## Prerequisites
*   Jarvis is installed and configured.
*   The model you want to add is downloaded (e.g., `ollama pull qwen2.5:0.5b`).

## Step 1: Generate Evidence (The Run)
Jarvis needs to "see" the model run once to understand its memory signatures.

1.  Open your terminal.
2.  Start the model manually to generate an initialization log:
    *   **Ollama**: `ollama run qwen2.5:0.5b`
    *   **vLLM**: Run a test plan containing the model (e.g., `python tests/runner_component.py plans/VLM_fast.yaml`).

## Step 2: Locate the Logs
During the run, the engine produces logs containing its internal memory allocations.

*   **If you used Ollama**: Your system log is located at `%LOCALAPPDATA%\Ollama\server.log`.
*   **If you used vLLM**: Capture the docker log: `docker logs vllm-server > startup.log`.

## Step 3: Calibrate
Now, use the **Zero-Config** calibration tool to translate that log into a physics datasheet.

```powershell
# Simply point the script to the log file. 
# It will auto-detect the engine and the model name.
python tools/calibrate_models.py C:\Path\To\Your\startup.log
```

> **Note**: For vLLM models, this step is **MANDATORY**. Jarvis will refuse to run a vLLM model that has not been calibrated.

## Step 4: Verify the Results
1.  Navigate to the `model_calibrations/` directory in the project root.
2.  You should see a new `.yaml` file named after your model (e.g., `vl_qwen2-vl-2b-instruct.yaml`).
3.  Open it. You will see the `base_vram_gb` and `capabilities` Jarvis discovered.

## Success!
Jarvis now understands the "physics" of this model. The next time you use it, the system will automatically optimize the VRAM allocation or provide guardrail warnings.
