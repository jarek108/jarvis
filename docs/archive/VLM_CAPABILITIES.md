# VLM Capacity Analysis: vLLM vs. Ollama

This document analyzes the Vision-Language Model (VLM) capabilities of vLLM (`VL`) and Ollama (`OL`), specifically focusing on video processing strategies (Encoding vs. Slicing) and multi-image handling.

## Executive Summary

| Feature | Ollama (`OL`) | vLLM (`VL`) | Jarvis Implementation |
| :--- | :--- | :--- | :--- |
| **Pure Image** | ✅ Native | ✅ Native | Supported on both. |
| **Multi-Image** | ✅ Native (List of Base64) | ✅ Native (OpenAI `image_url` list) | Supported on both. |
| **Video Processing** | ❌ **Slicing Only** | ⚠️ **Model Dependent** (Native Tensor potential) | **Slicing Enforced** (Client-side) |
| **"Video-as-Image"** | Standard Approach | Fallback Approach | **Current Standard** |

---

## 1. The "Video-as-Image" Paradigm (Current State)

Currently, the Jarvis client (`tests/vlm/test.py`) unifies video handling by **forcing client-side slicing** for both engines.

*   **Mechanism:** The client uses `PyAV` to open a video file, extracts `N` frames (default: 8) evenly spaced across the duration, and converts them to Base64 JPEG images.
*   **Payload:** These frames are sent as a "Bag of Images" to the API.
    *   **Ollama:** `{"images": [b64_1, b64_2, ...]}`
    *   **vLLM:** `content: [{"type": "image_url", ...}, {"type": "image_url", ...}]`

**Implication:** To the engine, there is no "video." There is simply a user asking a question about 8 distinct images. The model must infer temporal continuity.

## 2. Engine Capabilities (Theoretical Limit)

### Ollama (`OL`)
*   **Architecture:** Optimized for GGUF/llama.cpp inference.
*   **Video Support:** **None.** Ollama's API is strictly image-based. It relies entirely on client-side frame extraction (Slicing) to "see" video. It treats a video as a slideshow.

### vLLM (`VL`)
*   **Architecture:** High-throughput serving of HuggingFace models.
*   **Video Support:** **Native Potential.**
    *   Models like **Qwen2-VL** have architectural support for "Video" as a distinct modality (using 3D convolutions or specific temporal embeddings).
    *   **The Gap:** While the *model* supports it, accessing this via the *OpenAI-compatible API* (`vllm serve`) often requires passing video inputs in a specific tensor format or utilizing proprietary extensions to the API. Standard usage falls back to the "multi-image" approach.
    *   **Encoding:** If raw video tensors were passed, vLLM would perform true "Video Encoding," capturing motion vectors and temporal dynamics that static slicing misses.

## 3. Comparative Analysis

### "Slicing" (Ollama Strategy)
*   **Pros:** Universal compatibility. Works with any VLM that accepts images. Low bandwidth (only sending keyframes).
*   **Cons:** Loss of temporal information. Action verbs ("running" vs "standing") are guessed from static poses. Subtle motion is lost.

### "Encoding" (vLLM Potential)
*   **Pros:** True understanding of time/motion. Higher accuracy for "What happened *before* X?" questions.
*   **Cons:** Massive compute cost. Processing video tensors requires significantly more VRAM and FLOPs than processing 8 static images. API complexity.

## 4. Conclusion & Recommendation

*   **Current Parity:** Jarvis currently treats both engines equally, using **Client-Side Slicing**. This is the correct "Baseline" implementation for fair benchmarking.
*   **Future Work:** To unlock vLLM's true potential, a dedicated "Native Video" client pathway would be needed to bypass frame extraction and send video pointers/tensors, but this would break the 1:1 comparison with Ollama.

**Verdict:** For general assistant tasks, **Slicing (Video-as-Image)** is the industry standard for efficiency. True Video Encoding is a specialized feature currently out of scope for general-purpose inference APIs.
