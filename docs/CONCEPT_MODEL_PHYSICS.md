# Concept: Model Physics & Memory Management

This document explains the theoretical framework Jarvis uses to manage VRAM across different inference engines.

## 1. The Trinity of VRAM Usage

Every Large Language Model (LLM) or Vision Model (VLM) consumes VRAM in three distinct categories:

1.  **Model Weights (Static)**:
    *   The raw size of the model parameters (e.g., a 7B 4-bit model takes ~4GB).
    *   This cost is constant regardless of how many tokens you process.
2.  **KV Cache (Dynamic)**:
    *   The "memory" of the conversation. 
    *   This scales linearly with the number of tokens in the context window.
    *   High-resolution images and videos consume significant KV cache cells.
3.  **Compute Buffer (Overhead)**:
    *   Temporary memory used for activations, intermediate tensors, and the "Compute Graph."
    *   This is typically a fixed overhead allocated during model initialization.

## 2. Engine-Specific Logic

Jarvis applies the physical constants discovered during calibration differently depending on how the inference engine manages memory.

### vLLM: Strict Enforcement
vLLM is a "Control Freak." It demands a rigid memory budget at startup via the `--gpu-memory-utilization` flag.

*   **Mandatory Calibration**: Jarvis **refuses** to start a vLLM model without a valid calibration datasheet. Because vLLM pre-allocates the entire KV cache block, an incorrect estimate can lead to a "Negative Memory" allocation or a container crash.
*   **The Smart Allocator**: Jarvis uses the calibrated `base_vram_gb` and `kv_cache_gb_per_10k` to calculate the *exact* percentage of the GPU required to satisfy the user's requested `#ctx`.
*   **Safety Lock**: If no calibration exists, the test scenario is skipped with a status of `UNCALIBRATED`.

### Ollama: Predictive Guardrails
Ollama is a "Lazy Loader." It dynamically manages its own memory and will attempt to run a model even if the GPU is full by offloading layers to the CPU.

*   **Optional Calibration**: While recommended, calibration is not strictly required to start an Ollama model.
*   **The Guardrail**: If a calibration exists, Jarvis will **predict** the VRAM usage before starting the server. If the predicted usage exceeds the available physical VRAM, Jarvis issues a warning to the console and dashboard. 
*   **Goal**: This prevents "Slow Failures" where a model runs but at 1% speed due to CPU offloading.

## 3. The Physics Formula

Jarvis calculates the required VRAM ($V_{req}$) for a given context length ($C$) using the following formula:

$$V_{req} = Base + (\frac{C}{10000} \times Cost_{10k}) + Floor$$

*   **Base**: Model Weights + Static Compute Buffer (from calibration).
*   **Cost_{10k}**: The VRAM cost for 10,000 tokens (from calibration).
*   **Floor** (`vram_static_floor`): A flat GB amount added to ensure CUDA kernels and activation buffers have adequate room (default: 1.0 GB).

### Utilization Calculation
For vLLM, the utilization percentage ($U_{vllm}$) is derived as:

$$U_{vllm} = (V_{req} / V_{total}) + Buffer_{pct}$$

*   **Buffer** (`vram_safety_buffer`): A percentage of total VRAM reserved *after* the calculation to account for fragmentation and system stability (default: 0.15).
