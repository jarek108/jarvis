# Jarvis Assistant Project Overview

Jarvis is a high-performance Speech-to-Speech (STS) and Vision-Language (VLM) assistant infrastructure optimized for NVIDIA RTX 50-series hardware.

## Core Components

- **STT (faster-whisper)**: Multiple model sizes running on ports `8100-8104`.
- **TTS (Chatterbox)**: Optimized English, Multilingual, and Turbo variants on ports `8200-8202`.
- **LLM/VLM Engines**:
    - **Ollama**: Native low-latency inference.
    - **vLLM**: High-throughput Dockerized serving on port `8300`.
- **STS Pipeline**: The central orchestrator (`sts_server.py`) that manages the STT -> LLM -> TTS flow.

## Directory Structure

```text
/loadouts/          # Production presets for the functioning app
/servers/           # Component server implementations
/tests/             # Test runner and domain suites
  /sts/
    test_setups.yaml # Test matrix for STS
  /llm/
    test_setups.yaml # Test matrix for LLM
  ...
/logs/              # Runtime logs
/jarvis-venv/       # Python environment (Gold version)
```

## Testing & Benchmarking

The system features a decoupled test architecture. While `/loadouts` define how the app runs for a user, `tests/*/test_setups.yaml` define the permutations tested during QA. 

Benchmarks are automatically exported to **Google Drive** as stylized Excel reports, featuring:
- Split timings (Setup vs Execution vs Cleanup).
- Peak VRAM usage tracking.
- Multi-language support (UTF-8).
- Interactive media links.

## Infrastructure Management

Jarvis provides a `manage_loadout.py` utility to control the entire cluster. It manages both native Windows processes and Docker containers, ensuring clean GPU memory state between sessions.
