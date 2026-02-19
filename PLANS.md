# Planned Work & Analysis

This document serves as a scratchpad for future architectural improvements, known technical debt, and analyzing proposed features.

## 1. Backlog

### Documentation
- [ ] **User Guide**: `docs/USER_GUIDE.md` needs to be created to document client keybindings and UI.

### Testing
- [ ] **Mock Mode V2**: Decouple logic simulation from the `runner.py` to allow testing the dashboard UI without spawning processes.

### Infrastructure
- [ ] **Dynamic Port Allocation**: Currently ports are hardcoded in `config.yaml`. Moving to dynamic allocation would allow parallel test runs.

## 2. Active Analysis

### TTS Streaming
*   **Status**: Decision made to keep TTS atomic.
*   **Reasoning**: See `docs/analysis/STREAMING_ANALYSIS.md`. Server-side chunking adds protocol complexity with minimal gain for conversational STS.

### vLLM Multi-Tenant VRAM
*   **Issue**: vLLM grabs 90% VRAM by default.
*   **Current Fix**: Manual tuning via `config.yaml` > `model_vram_map`.
*   **Goal**: Automated discovery of optimal `gpu_memory_utilization` based on available free VRAM at startup.

### Native Video (vLLM)
*   **Goal**: Unlock Temporal Positional Embeddings in Qwen2-VL.
*   **Plan**: See `docs/analysis/NATIVE_VIDEO_PLAN.md`.
*   **Status**: Research Phase. Need to verify if `vllm-openai` accepts `video_url` payloads.
