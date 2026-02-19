# Jarvis Assistant: High-Performance STS & VLM Infrastructure

Jarvis is a low-latency, modular Speech-to-Speech (STS) and Vision-Language (VLM) assistant framework optimized for the **NVIDIA RTX 5090 (Blackwell)**. It orchestrates cutting-edge AI models into a unified pipeline capable of real-time voice interaction and visual analysis.

## 🚀 Key Features

- **Multi-Modal Brain**: Support for Large Language Models (LLM) and Vision-Language Models (VLM) via Ollama and vLLM.
- **Fast Transcription**: Optimized Speech-to-Text (STT) powered by `faster-whisper`.
- **Natural Voice**: High-quality Text-to-Speech (TTS) using the `Chatterbox` engine.
- **Hierarchical Dashboard**: Real-time TUI dashboard for monitoring benchmarks, logs, and VRAM usage.
- **Benchmarking Suite**: Comprehensive test runner with automated Google Drive reporting and session-based artifact persistence.
- **Refactor Guard**: A high-fidelity "Plumbing Mode" to verify code integrity without requiring GPU resources.

## 📂 Project Structure

- `/servers`: Individual component servers (STT, TTS, STS).
- `/utils`: Core system utilities (Config, Infra, VRAM, Hardware).
- `/tests`: Benchmarking logic, test plans, and domain suites.
- `/loadouts`: Production-ready model configurations.
- `/docs`: Detailed architectural and procedural documentation.

## 🛠️ Quick Start

### 1. Installation
See [docs/QUICKSTART.md](docs/QUICKSTART.md) for detailed environment setup.
```powershell
# Short version (if you have Python 3.10 + CUDA 12.8 ready)
pip install -r requirements.txt 
```

### 2. Infrastructure Management
Use the loadout manager to start or stop the Jarvis cluster.
```powershell
# Apply a specific model preset
python manage_loadout.py --apply base-qwen30-multi

# Check cluster health
python manage_loadout.py --status
```

### 3. Testing & Benchmarking
Run the full-stack health check to ensure everything is working correctly.
```powershell
# Run the Refactor Guard (No GPU required)
python tests/runner.py tests/plans/ALL_fast.yaml --plumbing

# Run real hardware benchmarks
python tests/runner.py tests/plans/ALL_fast.yaml
```

## 📖 Documentation Index

### 🚀 Phase 1: Getting Started
- **[Quickstart](docs/QUICKSTART.md)**: Installation, dependencies, and Hello World.

### ⚙️ Phase 2: Operations
- **[Workflows & Testing](docs/WORKFLOWS.md)**: Running benchmarks, managing loadouts, and the testing hierarchy.
- **[Model Integration](docs/MODEL_INTEGRATION.md)**: Deep dive on Ollama & vLLM lifecycle management.
- **[Troubleshooting](docs/TROUBLESHOOTING.md)**: Common errors and solutions.

### 🧠 Phase 3: Concepts
- **[System Architecture](docs/ARCHITECTURE.md)**: High-level component breakdown.
- **[Performance Analysis](docs/analysis/STREAMING_ANALYSIS.md)**: (Folder) Deep dives into latency, streaming, and startup optimizations.
- **[Native Video Plan](docs/analysis/NATIVE_VIDEO_PLAN.md)**: Strategy for unlocking temporal embeddings in vLLM.

### 📚 Phase 4: Reference
- **[API Reference](docs/API_REFERENCE.md)**: HTTP endpoints and JSON schemas.
- **[Configuration](docs/CONFIGURATION.md)**: `config.yaml` dictionary.
- **[Hardware Matrix](docs/HARDWARE_MATRIX.md)**: GPU and library compatibility guide.

---
*For AI-assisted development instructions, see [GEMINI.MD](GEMINI.MD).*
