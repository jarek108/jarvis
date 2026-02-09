# Plan: Determinism & Repeatability in Benchmarking

To ensure that performance comparisons between different hardware tiers and model variants are scientifically valid, we must eliminate sampling-based variance.

## 🎯 Primary Goal
Force every component in the Jarvis pipeline to produce the exact same output (tokens and audio structures) for a given input, ensuring that timing differences reflect only computational performance, not content variation.

## 🛠️ Component Strategy

### 1. LLM (Ollama)
The LLM has the highest variance due to random sampling.
- **Action**: Set `temperature: 0` and a fixed `seed: 42`.
- **Implementation**: Pass these options in the `/v1/chat/completions` payload in `s2s_server.py`.

### 2. STT (Faster-Whisper)
Whisper uses beam search which is generally stable but can vary at the margins.
- **Action**: Set `beam_size: 1` (Greedy Decoding) and a fixed `seed`.
- **Implementation**: Update the `model.transcribe()` call in `stt_server.py`.

### 3. TTS (Chatterbox)
TTS models often use stochastic processes for prosody or vocoding.
- **Action**: Set a fixed manual seed for the underlying Torch generator.
- **Implementation**: Use `torch.manual_seed(42)` before the `model.generate()` call in `tts_server.py`.

## 🚀 Execution: "Benchmark Mode"
We will introduce a `benchmark_mode` flag to the servers.
- **`True`**: Forced determinism (Temp 0, Seed 42, Greedy Decoding). Used for `run_extensive_comparison.py`.
- **`False`**: Natural variance enabled. Used for `jarvis_client.py`.

---
*Date: February 9, 2026*
