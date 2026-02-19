# Plan: Native Video Support in vLLM

This document outlines the strategy for researching and potentially implementing "Native Video" processing for vLLM models (specifically Qwen2-VL), moving beyond the current client-side "Video-as-Image" slicing.

## 1. The Core Objective
**Unlock Temporal Awareness.**
Current client-side slicing sends a "Bag of Images" to the model, stripping away temporal metadata. "Native Video" support implies using the model's native input processor (e.g., M-RoPE in Qwen2-VL) to inject frames with **Temporal Positional Embeddings**, allowing the model to understand causality and motion (Time Axis).

## 2. Research Spike (Phase 1)

### Hypothesis
vLLM's OpenAI-compatible server (`vllm serve`) might support a non-standard content type (e.g., `{"type": "video_url"}`) or a specific message structure that triggers its internal video loader.

### Experiment A: The API Probe
Create `research/vllm_video_probe.py` to test payload variations against a running `vllm/vllm-openai` container hosting `Qwen2-VL`.

1.  **Variation 1: The "video_url" Extension**
    ```json
    "content": [{"type": "video_url", "video_url": {"url": "http://host.docker.internal/video.mp4"}}]
    ```
2.  **Variation 2: The "video" type**
    ```json
    "content": [{"type": "video", "url": "..."}]
    ```
3.  **Variation 3: The Multi-Image Sequence (Control)**
    Pass 64 frames as `image_url` and measure TTFT. If TTFT is identical to a hypothetical video loader, vLLM might just be slicing internally.

### Experiment B: The Volume Mount
vLLM inside Docker cannot see client files.
*   **Requirement:** We must place a test video in the mapped `%USERPROFILE%\.cache\huggingface` volume (or a new dedicated volume) so the container can access it via `file:///root/.cache/...`.

## 3. Implementation (Phase 2)

If Phase 1 confirms that vLLM accepts a video pointer:

### Step 1: Infrastructure
*   Update `config.yaml` to define a `temp_data_path`.
*   Update `utils/lifecycle.py` to mount this path into the vLLM Docker container (e.g., `-v C:\Temp:/data`).

### Step 2: Client Logic (`tests/vlm/test.py`)
*   Add logic for the `#nativeVideo` flag.
*   **If Flag Present:**
    1.  Skip `PyAV` slicing.
    2.  Copy target video to the shared `temp_data_path`.
    3.  Construct payload with the discovered "Video Pointer" syntax (pointing to the in-container path `/data/video.mp4`).

## 4. Success Metrics
How do we know it's "Better"?

1.  **Latency (TTFT):** "Native" loading might be faster (server-side decoding) or slower (processing more frames/embeddings).
2.  **Accuracy (Qualitative):** Run the `traffic` scenario ("Is traffic moving fast or slow?").
    *   *Slicing:* Might guess based on blur.
    *   *Native:* Should see the distance change over time.

## 5. Risks & Blockers
*   **API Limitation:** vLLM's OpenAI server might strictly enforce the official OpenAI schema (Text/Image only), stripping out unknown types.
*   **Fallback:** If the API rejects it, we would need to write a custom `vllm_native_server.py` using `AsyncLLMEngine`. **Decision:** This is out of scope for now due to maintenance cost.
