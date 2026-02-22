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
See [docs/TUTORIAL_QUICKSTART.md](docs/TUTORIAL_QUICKSTART.md) for detailed environment setup.
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

## 📖 Documentation Index (Diátaxis)

### 🎓 Tutorials (Learning)
- **[Quickstart](docs/TUTORIAL_QUICKSTART.md)**: Installation, dependencies, and Hello World.
- **[Model Onboarding](docs/TUTORIAL_MODEL_ONBOARDING.md)**: Adding new models to the physics database.
- **[Contributing](docs/TUTORIAL_CONTRIBUTING.md)**: Developer setup, commit hygiene, and refactor guards.

### 🛠️ How-to Guides (Tasks)
- **[Benchmarking](docs/HOWTO_BENCHMARK.md)**: Running component tests and performance reports.
- **[Integration Testing](docs/PLAN_E2E_MODULAR.md)**: Verifying the modular system logic and state machine.
- **[Reporting](docs/HOWTO_REPORTING.md)**: Regenerating and synchronizing benchmark data.
- **[Engine Management](docs/HOWTO_ENGINE_MANAGEMENT.md)**: Configuring Ollama and vLLM (Docker) lifecycles.
- **[Troubleshooting](docs/HOWTO_TROUBLESHOOTING.md)**: Common errors, CUDA issues, and log analysis.
- **[Using the GUI](docs/HOWTO_USING_THE_GUI.md)**: Interacting with the Speech-to-Speech assistant client.

### 📚 Concepts (Understanding)
- **[System Architecture](docs/CONCEPT_ARCHITECTURE.md)**: High-level component breakdown and data flow.
- **[Modular Interaction Pipeline](docs/ARCHITECTURE_MODULAR_PIPELINE.md)**: Configurable interaction flows and WebSocket transport.
- **[Operational Concepts](docs/CONCEPT_OPERATIONAL_CONCEPTS.md)**: Behavioral templates, triggers, and stateless turn logic.
- **[Model Physics](docs/CONCEPT_MODEL_PHYSICS.md)**: VRAM management, KV cache scaling, and calibration theory.
- **[Reporting Architecture](docs/CONCEPT_REPORTING.md)**: Artifact lifecycles and the "Turbo Sync" engine.
- **[Streaming Strategy](docs/CONCEPT_STREAMING.md)**: Latency trade-offs between batch and streaming modes.
- **[Vision Strategies](docs/CONCEPT_VLM_STRATEGIES.md)**: How Jarvis handles multi-image and video data.
- **[Persona & Tone](docs/CONCEPT_PERSONA.md)**: Philosophical stance on assistant behavior and honesty.

### 📖 Reference (Information)
- **[API Reference](docs/REFERENCE_API.md)**: HTTP endpoints and JSON schemas.
- **[Reporting & Data](docs/REFERENCE_REPORTING.md)**: CLI flags, JSON schemas, and GDrive structure.
- **[Configuration](docs/REFERENCE_CONFIG.md)**: `config.yaml` dictionary and environment variables.
- **[Hardware Matrix](docs/REFERENCE_HARDWARE.md)**: GPU and library compatibility guide (RTX 5090).
- **[Calibration Database](docs/REFERENCE_CALIBRATION.md)**: Physics YAML schemas and evidence store.

---
*For AI-assisted development instructions, see [GEMINI.MD](GEMINI.MD).*
