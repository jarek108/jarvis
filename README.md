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

### 1. Environment Setup
Jarvis requires a specific Python 3.10 environment and CUDA 12.8+ (for RTX 5090 support).
```powershell
# See docs/HARDWARE_GUIDE.md for specific dependency version requirements
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

- **[Project Overview](docs/PROJECT_OVERVIEW.md)**: System architecture and component breakdown.
- **[Testing Procedures](docs/TESTING_PROCEDURES.md)**: Standard operating procedures for benchmarks and the Refactor Guard.
- **[Model Integration](docs/MODEL_INTEGRATION.md)**: Details on Ollama and vLLM integration.
- **[Hardware Guide](docs/HARDWARE_GUIDE.md)**: RTX 5090 / Blackwell specific compatibility and library versions.
- **[Utilities Breakdown](docs/UTILS_BREAKDOWN.md)**: Description of general and test utility modules.

---
*For AI-assisted development instructions, see [GEMINI.MD](GEMINI.MD).*
