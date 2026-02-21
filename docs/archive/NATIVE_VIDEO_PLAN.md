# Plan: Native Video Support in vLLM (Qwen3-VL Pivot)

This document outlines the strategy for implementing "Native Video" processing in Jarvis. Based on deep research, we are pivoting our focus from `Qwen2-VL` (which lacks API support) to **`Qwen3-VL-30B-A3B`**, which has first-class support for `video_url` in the vLLM OpenAI server.

## 1. The Core Objective
**Unlock Temporal Awareness via Standard API.**
We want to bypass client-side frame slicing ("Bag of Images") and send a video pointer (`video_url`) to vLLM. This allows the model to use **Interleaved M-RoPE** (Multimodal Rotary Positional Embeddings) to understand time, motion, and causality.

## 2. Research Findings (The Pivot)

| Feature | Qwen2-VL | Qwen3-VL-30B-A3B |
| :--- | :--- | :--- |
| **Native Video API** | ❌ **Not Supported** | ✅ **Supported** (`video_url`) |
| **Method** | Python `LLM()` only | Standard `/chat/completions` |
| **Quantization** | Various | **AWQ** (QuantTrio) fits 24GB+ GPUs |
| **Strategy** | **Abandon for Native** | **Adopt as Primary Heavy VLM** |

**Conclusion:** We do not need a custom server. We will use the standard `vllm/vllm-openai` Docker image with `Qwen3-VL`.

## 3. Implementation Plan

### Phase 1: The "Hello World" Probe (STATUS: ✅ SUCCESS)
The probe script `research/vllm_video_probe.py` successfully triggered native video processing in `Qwen3-VL-30B-AWQ` using the `video_url` payload and `file:///` local paths.

### Phase 2: Client Integration (`#nativeVideo`)
Update `tests/vlm/test.py` to support a new execution mode.

*   **Logic:**
    *   Check for `#nativeVideo` flag in loadout.
    *   **If True:**
        1.  Do NOT slice with `PyAV`.
        2.  Identify video path. If local, ensure it's accessible to Docker (shared volume) or serve it via ephemeral HTTP (complex, prefer volume).
        3.  Construct payload: `{"type": "video_url", "video_url": {"url": "..."}}`.
    *   **If False (Default):** Continue using `PyAV` slicing (Bag of Images).

### Phase 3: Infrastructure Tuning
*   **Volume Mapping:** Add a dedicated `input_data` volume to `config.yaml` and `lifecycle.py` so Jarvis clients can easily share videos with the Docker container.
*   **Parameter Tuning:** Experiment with `--limit-mm-per-prompt` and `--media-io-kwargs` to balance VRAM usage (OOM risk) vs. temporal resolution (FPS).

## 4. Risks & Constraints
*   **VRAM:** 30B AWQ is heavy (~18GB). Running this alongside STT/TTS on a 24GB card might be tight. On an RTX 5090 (32GB), it should be comfortable.
*   **Local Files:** Docker on Windows has strict volume mounting rules. We must ensure the `temp` directory is correctly shared.
