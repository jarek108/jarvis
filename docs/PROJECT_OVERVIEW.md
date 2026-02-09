# Jarvis Assistant: Project Overview

Jarvis is a modular, high-performance local voice assistant optimized for the **NVIDIA RTX 5090 (Blackwell architecture)**. It leverages a persistent inference cluster to provide zero-latency switching between different model variants for Speech-to-Text (STT), Large Language Models (LLM), and Text-to-Speech (TTS).

## [Section] : Core Architecture
The system is built on a **Stateless Sub-Server** pattern orchestrated by a stateful **Speech-to-Speech (S2S) Pipeline**.

- **STT (faster-whisper)**: Multiple model sizes (tiny to large) running on dedicated ports (8010-8014). Includes internal warmup.
- **LLM (Ollama)**: Centralized local LLM service running on port 11434. Warmed up via the S2S orchestrator.
- **TTS (Chatterbox)**: Optimized English, Multilingual, and Turbo variants on dedicated ports (8020-8022). Includes internal warmup.
- **S2S Orchestrator**: A FastAPI server that coordinates the full STT ➔ LLM ➔ TTS pipeline.

## [Section] : Repository Structure

```text
C:\Users\chojn\jarvis
├── docs/                   # Documentation
│   └── RTX5090_COMPATIBILITY.md    # Critical dependency and CUDA guide
├── servers/                # Core service implementations
│   ├── stt_server.py       # Faster-Whisper wrapper with internal warmup
│   ├── tts_server.py       # Chatterbox wrapper with internal warmup
│   └── s2s_server.py       # Pipeline orchestrator with dynamic loadout support
├── tests/                  # Benchmarking and lifecycle tests
│   ├── loadouts/           # YAML presets (default.yaml, turbo_ultra.yaml, etc.)
│   ├── stt/                # Whisper multi-size test suites
│   ├── tts/                # Chatterbox variant test suites
│   ├── s2s/                # End-to-end pipeline verification (isolated_*.py)
│   ├── run_health_check.py # Master smoke test (Representative subset)
│   ├── run_extensive_comparison.py # Master benchmark suite (All variants)
│   └── utils.py            # 4-state health probes and process management
├── config.yaml             # Central registry for ports and hardware settings
├── manage_loadout.py       # CLI for infrastructure management
└── jarvis-venv/            # Specialized Python 3.10 environment
```

## [Section] : Infrastructure Management
The system uses a **Discovery-Based Loadout** approach. Models are kept resident in VRAM to eliminate loading lag.

### 4-State Health Model
*   **`ON`**: Port open, service initialized and warmed up (Ready for inference).
*   **`OFF`**: Port closed.
*   **`STARTUP`**: Port open, but service is still loading weights or warming up (HTTP 503).
*   **`BUSY`**: Port open, but service is currently processing another request.

### Key Tools
- **`manage_loadout.py --status`**: A color-coded dashboard showing the 4-state health of all components.
- **`manage_loadout.py --apply [preset]`**: Restores the infrastructure to a specific state (e.g., `default`, `turbo_ultra`) by starting only missing services.
- **Smart Tests**: Functional tests probe the cluster first. If a model is already `ON`, the test executes in sub-seconds. If `OFF/STARTUP`, it handles the full lifecycle (Start ➔ Warmup ➔ Test ➔ Kill).

## [Section] : Testing Philosophy & Structure
Jarvis uses a "Smart Discovery" testing pattern designed to balance developer speed with infrastructure reliability.

### 1. Functional Logic (`tests.py`)
Each domain (STT, TTS, S2S) contains a `tests.py` file. This is **stateless logic**.
- It defines the actual test scenarios (e.g., Polish transcription, English synthesis).
- It assumes the required server is already running on its assigned port.
- It reports results in both human-readable tables and machine-readable JSON (captured by orchestrators).

### 2. The Isolated Approach (`isolated_*.py`)
These scripts manage the **Infrastructure Lifecycle** for a specific model or loadout.
- **Smart Discovery**: They first probe the cluster health. If the required service is already `ON`, they run the functional tests and exit immediately, leaving the service active.
- **Clean Lifecycle**: If the service is `OFF`, they handle the full sequence: **Start ➔ Warmup ➔ Test ➔ Kill**. This ensures a pristine environment for benchmarking "cold starts."

### 3. Orchestration Levels
- **Health Check (`run_health_check.py`)**: A rapid smoke test. It runs a single representative "Isolated" script from each domain to verify the system is fundamentally sound.
- **Extensive Comparison (`run_extensive_comparison.py`)**: A deep benchmark. It iterates through *every* available model variant and loadout, producing a consolidated performance report across the entire hardware capability.

## [Section] : Hardware Compatibility
Running on an RTX 5090 requires specific **PyTorch Nightly** builds with CUDA 12.8 support.
- **Python**: 3.10
- **NumPy**: Pinned to 1.25.2
- **Pillow**: Pinned to 11.3.0
- **Torch Index**: `https://download.pytorch.org/whl/nightly/cu128`

---
*Last Updated: February 8, 2026*