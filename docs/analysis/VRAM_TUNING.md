# VLM Parameter Tuning: Context, Limits & VRAM

This document analyzes the relationship between context window size (`#ctx`), multimodal limits (`#img_lim`, `#vid_lim`), and actual VRAM usage in vLLM. It is based on empirical data from benchmarking the `QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ` model.

## 1. The Core Findings

### A. VRAM Allocation is Deterministic (at Startup)
Contrary to intuition, changing the number of allowed images/videos (`limit_mm_per_prompt`) or increasing the context window (`max_model_len`) often results in **identical peak VRAM usage** during the "Setup" phase.

**Evidence (Run 20260220_031231):**
| Context | Vid Limit | Status | Peak VRAM |
| :--- | :--- | :--- | :--- |
| `8192` | `1` | PASSED | **16.96 GB** |
| `16384` | `1` | PASSED | **16.96 GB** |
| `32768` | `1` | PASSED | **16.96 GB** |
| `8192` | `2` | PASSED | **16.96 GB** |
| `8192` | `4` | PASSED | **16.96 GB** |

*Note: The 16.96 GB figure represents the Model Weights + Static Overhead. The KV Cache is allocated dynamically into the *remaining* space based on `gpu_memory_utilization`.*

### B. The Trade-off: Concurrency vs. Context
Since the VRAM pie is fixed (by `gpu_memory_utilization`), increasing the Context Window size (`#ctx`) directly reduces the number of concurrent requests the engine can handle.

| Context (`#ctx`) | Max Concurrency |
| :--- | :--- |
| `8192` | **6.58x** |
| `16384` | **3.29x** |

**Implication:** Doubling the context window halves the concurrency. For single-user assistants (Jarvis), this is a perfectly acceptable trade-off to gain the ability to process long videos.

## 2. Parameter Tuning Guide

### `#ctx` (Context Window)
*   **Role:** Defines the maximum total tokens (Text + Images + Video) for a single request.
*   **Recommendation:**
    *   **Images:** `4096` or `8192` is usually sufficient.
    *   **Video:** `16384` or `32768` is required for long clips (>30s), as native video encoding consumes ~256 tokens/sec depending on resolution.
*   **Risk:** Setting this too high (e.g., `65536` on a 24GB card) might leave 0 room for KV cache blocks, preventing startup.

### `#vid_lim` / `#img_lim`
*   **Role:** A "Guardrail" for the scheduler. It rejects requests containing more items than this limit.
*   **VRAM Impact:** Negligible. Setting `#vid_lim=4` does not reserve 4x the VRAM at startup. It simply allows a request with 4 videos to attempt to be scheduled.
*   **Recommendation:** Set high (e.g., `4` or `8`) to avoid artificial errors. The real limit is the Context Window (`#ctx`).

## 3. "Logical" OOM vs. "Physical" OOM

*   **Physical OOM (CUDA Error):** Happens at startup if model weights > GPU VRAM * `gpu_util`.
*   **Logical OOM (Context Error):** Happens at runtime if `(Tokens in Video) + (Tokens in Text) > #ctx`.

**Strategy:**
1.  Set `gpu_memory_utilization` to fit the weights (e.g., `0.5` for 30B AWQ on 5090).
2.  Set `#ctx` as high as possible (`32768`) to accommodate long videos.
3.  Let concurrency drop. (Who cares if you can only run 1 request at a time? You are one user).
