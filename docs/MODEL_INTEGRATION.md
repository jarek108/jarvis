# Model Integration Guide: Ollama & vLLM

This document details how Jarvis interacts with external inference engines, specifically Ollama and vLLM, including lifecycle management, API protocols, and resource handling.

## 1. Engine Overview

Jarvis acts as an orchestrator that routes requests to specialized backends. It supports two primary engines for Large Language Models (LLMs) and Vision-Language Models (VLMs).

| Feature | Ollama | vLLM (Docker) |
| :--- | :--- | :--- |
| **Execution** | Native Windows Service | Linux Container (via WSL2) |
| **API Protocol** | Ollama Native (`/api/chat`) | OpenAI Compatible (`/v1/...`) |
| **GPU Access** | Direct Windows Driver | Docker `--gpus all` Pass-through |
| **Model Format** | GGUF | Safetensors / PyTorch |
| **Optimization** | Low-latency (llama.cpp) | High-throughput (PagedAttention) |

---

## 2. Ollama Integration

### Connectivity
*   **Port:** `11434` (Default)
*   **Protocol:** REST API
*   **Detection:** Jarvis pings `http://localhost:11434/api/tags` to verify the service is up and to list available models.

### Lifecycle Management
*   **Startup:** If not running, Jarvis attempts to spawn `ollama serve`.
*   **Model Loading:** Jarvis uses the `/api/chat` endpoint. Models are automatically "hot-loaded" by Ollama upon the first request.
*   **Cleanup:** Jarvis kills the `ollama` process tree to clear VRAM, although Ollama has its own 5-minute idle timeout for model unloading.

### Model Storage
*   Stored in `%USERPROFILE%\.ollama\models`.

---

## 3. vLLM (Docker) Integration

### Connectivity
*   **Port:** `8300` (Mapped from container port `8000`)
*   **Protocol:** OpenAI-compatible REST API.
*   **Detection:** Jarvis pings `http://localhost:8300/v1/models` to verify the container is ready.

### Lifecycle Management
*   **Containerization:** Jarvis manages a container named `vllm-server` using the `vllm/vllm-openai` image.
*   **WSL2 Requirement:** Docker Desktop must be configured with the WSL2 backend for GPU support.
*   **Startup Command:**
    ```bash
    docker run --gpus all -d --name vllm-server 
      -p 8300:8000 
      -v %USERPROFILE%\.cache\huggingface:/root/.cache/huggingface 
      vllm/vllm-openai --model [model_id]
    ```
*   **Cleanup:** Jarvis explicitly runs `docker stop vllm-server` and `docker rm vllm-server` to ensure the 5090's VRAM is fully released.

### Model Caching
*   **Volume Mapping:** The Windows HuggingFace cache folder (`%USERPROFILE%\.cache\huggingface`) is mapped into the container. This prevents redundant downloads across container lifecycles.

---

## 4. Model Availability & Downloads

### Soft Download Logic (The "Red Row")
To prevent unexpected long waits or disk space exhaustion, Jarvis implements a "Soft Download" policy during testing:
*   **Availability Check:** Before starting a test setup, Jarvis pings the engine (Ollama) or checks the disk (vLLM/HF Cache) to see if the model is already present.
*   **Behavior:** If a model is missing, the setup is skipped and reported as **[MISSING]** in the test runner and the final Excel report (highlighted in yellow/red).
*   **Bypass:** Use the `--force-download` flag in `runner.py` or `manage_loadout.py` to allow Jarvis to trigger automatic pulls/downloads.

### Loading Strategies
*   **Ollama (Lazy):** Models are loaded into VRAM on the first API request. This results in a high "TTFT" (Time to First Token) for the first interaction, which Jarvis mitigates with a dummy "warmup" request.
*   **vLLM (Eager):** Models are loaded into VRAM immediately upon container startup. The service is not considered "ON" by Jarvis until the model weights are fully resident and the API is responsive.

---

## 5. Model Discovery & Selection

### Prefix Convention
To distinguish between engines in reports and configuration, Jarvis uses prefixes:
*   `ol_`: Explicitly force Ollama (e.g., `ol_qwen2.5:0.5b`).
*   `vl_` or `vllm:`: Explicitly force vLLM (e.g., `vllm:Qwen/Qwen2.5-0.5B-Instruct`).
*   **Default:** Any model ID containing `:` or `/` without a prefix currently defaults to Ollama.

### Suffix Convention (Runtime Flags)
To pass runtime parameters to the test runner (without affecting the engine loader), append flags using the `#` delimiter:
*   `#stream`: Enables streaming mode (Time-To-First-Token measurement).
*   **Example:** `OL_qwen2.5:0.5b#stream` loads `OL_qwen2.5:0.5b` but executes tests with `stream=True`.

### Test Setups (`test_setups.yaml`)
Tests are driven by lists of model IDs. The `LifecycleManager` identifies the engine based on the prefix and the `config.yaml` port definitions.

---

## 5. Hardware Handling (RTX 5090)

*   **VRAM Seizure:** By default, vLLM allocates 90% of available VRAM. This can be tuned via `--gpu-memory-utilization` in the startup command if multi-tenant GPU usage is required.
*   **CUDA Graphs:** vLLM captures CUDA graphs during warmup. This is a one-time setup cost per session that significantly speeds up subsequent inference.
*   **WSL2 Overhead:** Note that memory pinning is disabled in WSL2, leading to a minor latency penalty compared to native Linux.
