### General Utilities

The `utils` directory provides core modules for Jarvis's main functionality: configuration, console output, infrastructure management, LLM handling, and resource monitoring.

*   `config.py`: Loads `config.yaml` and resolves `HF_HOME`, `OLLAMA_MODELS` environment variables, enforcing strict path policies. Used by `infra.py` and `vram.py`.
*   `console.py`: Manages console output, ensuring UTF-8 encoding and providing ANSI color codes for readability.
*   `infra.py`: Manages services: checks ports, starts/stops servers (including vLLM Docker), and monitors health. Relies on `config.py` and `vram.py`.
*   `llm.py`: Handles Large Language Models: checks local availability, pulls models, and warms up services. Interacts with `infra.py` and `config.py`.
*   `vram.py`: Monitors VRAM usage and reports service health. Estimates VRAM per model, queries Ollama, and provides system overview. Uses `infra.py` and `config.py`.

### Test Utilities

The `tests/test_utils` directory contains specialized modules for the testing framework: test orchestration, result collection/reporting, service lifecycle, and visual feedback.

*   `collectors.py`: Gathers and centralizes test results using `BaseReporter` implementations. Feeds into `reporting.py`.
*   `lifecycle.py`: Orchestrates integration test setup/teardown for STT, TTS, LLM services, ensuring model availability. Uses general `utils` and `llm.py`/`vram.py`.
*   `reporting.py`: Manages test output, saves artifacts, and generates Excel reports (including Google Drive upload). Uses `collectors.py`.
*   `session.py`: Initializes new test sessions, creates directories, and captures system/Git info. Depends on `utils.config`.
*   `stubs.py`: Provides a lightweight FastAPI app to emulate LLM services for dependency-free testing in `stub_mode`. Used by `lifecycle.py`.
*   `ui.py`: Captures stdout with `LiveFilter` for clean display; formats text with timestamps for `reporting.py`.
*   `ui_view.py`: Implements `RichDashboard` for an interactive terminal UI, displaying test progress, VRAM, and logs. Uses `rich` library and `utils.vram`.