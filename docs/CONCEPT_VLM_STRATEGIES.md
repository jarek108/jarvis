# Concept: VLM Vision Strategies

This document explains how Jarvis handles visual input, specifically the "Video-as-Image" paradigm used to unify multimodal inference across different engines.

## 1. Video-as-Image (Slicing)

Jarvis currently enforces **Client-Side Slicing** to maintain a fair 1:1 comparison between Ollama and vLLM.

### The Mechanism
1.  The client opens a video file (e.g., MP4).
2.  It extracts `N` frames (default: 8) evenly spaced across the duration.
3.  These frames are converted into a "Bag of Images" (Base64).
4.  The engine receives a single prompt with 8 distinct images.

### The Temporal Gap
Since the engine receives a slideshow rather than a continuous stream, it must **infer** motion. Action verbs ("jumping", "dropping") are recognized via static poses in sequential frames rather than motion vectors.

## 2. Model-Specific Nuances

### Ollama (Strict Slicing)
Ollama has no native concept of a "video file." It is exclusively a frame-consumer.

### vLLM (Native Potential)
Some models (e.g., Qwen2-VL) support native video tensors. While Jarvis benchmark paths currently use slicing for parity, vLLM can theoretically perform true **Temporal Encoding**, which is more accurate for complex action recognition but significantly more compute-intensive.

## 3. Tuning Multimodal Limits
Visual data consumes significant KV Cache cells.
*   **Images**: Typically ~1,000 to 4,000 tokens depending on resolution.
*   **Videos**: `N_frames * Image_Cost`.
*   **Constraint**: If your `#ctx` is too small, the prompt will be truncated, and the model will lose visual context.
