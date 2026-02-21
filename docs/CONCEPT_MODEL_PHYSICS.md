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

## 2. The "Container vs. Cup" Analogy

To understand VRAM allocation, especially in rigid engines like vLLM, distinguish between the **Physical Capacity** and the **Declared Limit**.

1.  **The Container (Physical Capacity)**:
    *   Determined by: `gpu_memory_utilization` (e.g., 26GB on an RTX 5090).
    *   **Formula**: `(Total VRAM - Model Weights) = Surplus for KV Cache`.
    *   If you allocate a 26GB container for a 17GB model, you have a **~9GB Surplus** for tokens.

2.  **The Cup (Declared Limit)**:
    *   Determined by: `#ctx` (`--max-model-len`).
    *   **Function**: The maximum context size reserved for a *single request*.

**Startup Constraint**: The engine checks if `Container Size >= Cup Size`. If your surplus can only fit 45k tokens but you request a 64k "Cup," the engine will fail to start.

## 3. Calibration: Empirical Discovery
... [rest of file] ...

Rather than relying on vague estimates, Jarvis uses **Calibration** to discover these three constants for any specific model/hardware combination.

### The Physics Formula
Jarvis calculates the required VRAM utilization ratio ($U_{vllm}$) for a given context length ($C$) using a two-stage formula:

1.  **Total Required GB**:
    $$V_{req} = Base + (C \times Cost_{token}) + Floor$$
2.  **Utilization Ratio**:
    $$U_{vllm} = (V_{req} / V_{total}) + Buffer$$

*   **Base**: Model Weights + Static Compute Buffer (from calibration).
*   **Cost per token**: The linear growth rate of the KV cache (from calibration).
*   **Floor** (`vram_static_floor`): A flat GB amount added to ensure CUDA kernels and activation buffers have adequate room (default: 1.0 GB).
*   **Buffer** (`vram_safety_buffer`): A percentage of total VRAM reserved *after* the calculation to account for fragmentation and system stability (default: 0.15 or 15%).

## 3. Engine-Specific Applications

### vLLM: Deterministic Allocation
vLLM is a "Control Freak." It demands a rigid memory budget at startup via the `--gpu-memory-utilization` flag. 
Jarvis uses the physics database and the configured tuning parameters to perform **Smart Allocation**:

1.  **Context-Aware**: If a user requests `#ctx=4096`, the allocator calculates a lower utilization than for `#ctx=16384`.
2.  **Pipeline-Safe**: By explicitly defining the `Floor` and `Buffer`, Jarvis ensures that vLLM leaves exactly enough "air" on the GPU for concurrent models (like Whisper or Chatterbox) to load without causing Out-of-Memory (OOM) errors.
3.  **Deterministic Capacity**: Because vLLM pre-fills the allocated space with KV cache pages, the number of concurrent requests a model can handle is predictable (e.g., 55k tokens total / 4k per request = ~13 concurrent slots).

### Ollama: Predictive Guardrails
Ollama is a "Lazy Loader." It dynamically manages its own memory and will offload layers to the CPU if VRAM is insufficient.
Jarvis uses the physics database to provide **Hardware Guardrails**:
1.  Before startup, Jarvis predicts the required VRAM for the requested `#ctx`.
2.  If $Predicted > Available$, Jarvis issues a warning to the dashboard.
3.  This allows the user to lower the context length *before* experiencing the performance hit of CPU offloading.
