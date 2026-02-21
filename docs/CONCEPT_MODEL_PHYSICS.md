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
Jarvis calculates the required VRAM ($V_{req}$) for a given context length ($C$) using:
$$V_{req} = Base + (C 	imes Cost_{token})$$

*   **Base**: Model Weights + Compute Buffer.
*   **Cost per token**: The slope of KV cache growth.

## 3. Engine-Specific Applications

### vLLM: Deterministic Allocation
vLLM is a "Control Freak." It demands a rigid memory budget at startup via the `--gpu-memory-utilization` flag. 
Jarvis uses the physics database to calculate the **Smart Allocation**:
1.  User requests `#ctx=16384`.
2.  Jarvis calculates: $Util = (Base + (16384 	imes Cost)) / Total_{VRAM} + 5\%$.
3.  The container starts with the *exact* amount of VRAM needed, leaving the rest free for the OS or other models.

### Ollama: Predictive Guardrails
Ollama is a "Lazy Loader." It dynamically manages its own memory and will offload layers to the CPU if VRAM is insufficient.
Jarvis uses the physics database to provide **Hardware Guardrails**:
1.  Before startup, Jarvis predicts the required VRAM for the requested `#ctx`.
2.  If $Predicted > Available$, Jarvis issues a warning to the dashboard.
3.  This allows the user to lower the context length *before* experiencing the performance hit of CPU offloading.
