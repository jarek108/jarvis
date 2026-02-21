# Plan: Unified Calibration for Ollama (STATUS: ✅ IMPLEMENTED)

This document outlines the strategy for extending the `calibrate_vram.py` framework to support Ollama models. While Ollama cannot be configured as precisely as vLLM, measuring its physical constants enables **Hardware Guardrails** and **Performance Predictions**.

## 1. The Objective
Create a "Single Source of Truth" for model physics.
*   **vLLM:** Use calibration to **Configure** the engine (Smart Allocator).
*   **Ollama:** Use calibration to **Validate** the environment (CPU Offload Warnings).

## 2. Research Findings (The Formula)
Based on deep research (`docs/analysis/Ollama vram inspection.md`), Ollama logs the KV Cache size but not the model weights.

### The Algorithm
1.  **Start:** `ollama serve` (if not running).
2.  **Config:** Set a fixed context (e.g., `num_ctx=32768`) and concurrency (`parallel=1`).
3.  **Run:** Trigger model load: `ollama run model "hi"`.
4.  **Measure (Total):** Poll `nvidia-smi` for the peak VRAM usage of the `ollama_llama_server` process. -> $V_{total}$
5.  **Measure (KV):** Parse `server.log` for the line:
    `KV self size = 1792.00 MiB` -> $K_{MiB}$
6.  **Calculate:**
    *   **Base Weights:** $V_{base} \approx V_{total} - (K_{MiB} / 1024)$
    *   **Cost per 10k:** $\frac{K_{MiB} / 1024}{	ext{num\_ctx}} 	imes 10,000$

## 3. Implementation Plan

### Phase 1: Log Parsing Logic
*   **Challenge:** Locating `server.log` on Windows/Linux reliably.
*   **Action:** Add `utils.get_ollama_log_path()` helper.

### Phase 2: Update `calibrate_vram.py`
*   Add `--engine ollama` flag.
*   Implement the "Load & Measure" workflow:
    1.  Clean session (restart Ollama to clear previous models).
    2.  Send request via API.
    3.  Wait for stability.
    4.  Read Logs + Read GPU.

### Phase 3: Update `lifecycle.py`
*   **Goal:** Before starting a test, check `models/calibrations/{model}.yaml`.
*   **Logic:**
    *   Calculate required VRAM for requested `#ctx`.
    *   Check available GPU VRAM.
    *   **If Required > Available:** Print **WARNING: CPU OFFLOAD LIKELY**.

## 4. Artifact Structure
The output YAML remains identical to vLLM, ensuring a unified schema:
```yaml
id: ollama/qwen2.5-0.5b
engine: ollama
constants:
  base_vram_gb: 0.93
  kv_cache_gb_per_10k: 0.11
metadata:
  calibrated_at: ...
```
