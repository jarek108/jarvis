# VLM Parameter Tuning: Context, Limits & VRAM

This document analyzes the relationship between context window size (`#ctx`), multimodal limits (`#img_lim`, `#vid_lim`), and actual VRAM usage in vLLM. It provides a strategic guide for tuning performance on restricted hardware (e.g., single GPU).

## 1. The Core Findings: KV Cache Dynamics

### A. The "Container vs. Cup" Analogy
To understand VRAM usage, distinguishing between the **Physical Capacity** and the **Declared Limit** is crucial.

1.  **The Container (Physical Capacity):**
    *   Determined by: `gpu_memory_utilization` (e.g., 26GB on an RTX 5090).
    *   **Calculation:** `(Total VRAM - Model Weights) = Surplus for KV Cache`.
    *   **Example:** A 30B model takes ~17GB. With 26GB allocated, you have **~9GB Surplus**.
    *   **Capacity:** 9GB fits roughly **45,000 tokens** (the "Physical Limit").

2.  **The Cup (Declared Limit):**
    *   Determined by: `#ctx` (`--max-model-len`).
    *   **Function:** The maximum context size reserved for a *single request*.
    *   **Example:** `#ctx=32768`.

### B. Startup Logic ("Will it Blend?")
At startup, vLLM performs a simple check:
> **Is Container Size >= Cup Size?**

*   **Scenario 1 (Safe):** Container (45k) > Cup (32k). vLLM starts. The extra 13k tokens sit idle (waiting for a second parallel request).
*   **Scenario 2 (Oversized):** Container (45k) < Cup (64k). vLLM fails or warns ("I cannot guarantee 64k context").

### C. Runtime VRAM Behavior
Contrary to intuition, changing parameters often shows **identical peak VRAM usage**.
*   **Why:** vLLM pre-allocates the *entire* `gpu_memory_utilization` block at startup.
*   **Result:** Whether you run 1 video or 4, the VRAM usage reported by `nvidia-smi` will stay flat at your defined limit (e.g., 26GB). The *internal* utilization of that block changes, but the allocation does not.

## 2. Parameter Tuning Guide

### `#ctx` (Context Window)
*   **Role:** Defines the maximum total tokens (Text + Images + Video) for a single request.
*   **Recommendation:**
    *   **Images:** `8192` is usually sufficient.
    *   **Video:** `16384` or `32768` is required for native video encoding (~256 tokens/sec).
*   **Risk:** Setting this higher than your Physical Capacity prevents startup.

### `#vid_lim` / `#img_lim`
*   **Role:** A "Guardrail" for the scheduler.
*   **Myth:** "Setting `#vid_lim=4` reserves 4x memory." -> **FALSE**.
*   **Reality:** It simply allows the scheduler to accept a request with 4 videos. If those 4 videos combined exceed `#ctx`, the request fails.
*   **Strategy:** Set these high (e.g., `4` or `8`) to avoid artificial errors. Use `#ctx` as your real safety limit.

## 3. "Logical" OOM vs. "Physical" OOM

*   **Physical OOM (CUDA Error):** Happens at **Startup** if `Model Weights > GPU VRAM * gpu_util`.
*   **Logical OOM (Context Error):** Happens at **Runtime** if `(Tokens in Video) + (Tokens in Text) > #ctx`.

**Optimization Strategy for Single-User (Jarvis):**
1.  **Tune Down `gpu_util`:** Set it just high enough to fit the weights + your desired context (e.g., `0.7`). This leaves VRAM free for the OS/Desktop.
2.  **Tune Up `#ctx`:** Maximize this to fill the container. (e.g., if you have space for 45k tokens, set `#ctx=32768`).
3.  **Ignore Concurrency:** As a single user, you don't need the surplus "idle" tokens meant for parallel requests.
