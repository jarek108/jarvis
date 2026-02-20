# Planned Work & Analysis

This document serves as a scratchpad for future architectural improvements, known technical debt, and analyzing proposed features.

## 1. Backlog

### Documentation
- [ ] **User Guide**: `docs/USER_GUIDE.md` needs to be created to document client keybindings and UI.

### Testing
- [ ] **Mock Mode V2**: Decouple logic simulation from the `runner.py` to allow testing the dashboard UI without spawning processes.

### Infrastructure
- [ ] **Ollama Unified Calibration**: Implement calibration logic for Ollama models to enable hardware guardrails. Plan: `docs/analysis/OLLAMA_CALIBRATION_PLAN.md`.
- [ ] **Dynamic Port Allocation**: Currently ports are hardcoded in `config.yaml`. Moving to dynamic allocation would allow parallel test runs.

## 2. Active Analysis

### TTS Streaming
*   **Status**: Decision made to keep TTS atomic.
*   **Reasoning**: See `docs/analysis/STREAMING_ANALYSIS.md`. Server-side chunking adds protocol complexity with minimal gain for conversational STS.

### vLLM Multi-Tenant VRAM
*   **Issue**: vLLM grabs 90% VRAM by default.
*   **Status**: IMPLEMENTED. The "Smart Allocator" logic in `lifecycle.py` uses high-precision physical constants from `models/calibrations/` to calculate the exact `gpu_memory_utilization` needed for the requested `#ctx`.

### Native Video (vLLM)
*   **Goal**: Unlock Temporal Positional Embeddings in Qwen3-VL.
*   **Plan**: See `docs/analysis/NATIVE_VIDEO_PLAN.md`.
*   **Status**: VERIFIED. Supported both standalone (`#nativevideo`) and combined with streaming (`#nativevideo#stream`).
