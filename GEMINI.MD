# Gemini CLI: Jarvis Assistant Developer Guide

> **Note:** For general project overview, architecture, and user instructions, see the [README.md](README.md).

## [Section] : Infrastructure Management
- **Check Cluster Health**: `python manage_loadout.py --status` (Shows ON, OFF, STARTUP, BUSY)
- **Activate Preset**: `python manage_loadout.py --apply [preset_name]` (Pulls from `/loadouts/*.yaml`)
- **Kill All Services**: `python manage_loadout.py --kill all` (Clears STT, TTS, Ollama, and vLLM Docker)
- **Debug Startup**: Add `--loud` to any `manage_loadout.py` command to show server windows.

## [Section] : Testing Workflow
- **Refactor Guard**: `python tests/runner.py tests/plans/ALL_fast.yaml --plumbing` (Run after ANY code change!)
- **Domain Testing**: `python tests/runner.py tests/plans/[DOMAIN]_fast.yaml` (Start here for features)
- **Specific Setup**: `python tests/runner.py --domain sts --setup tiny_ol_qwen_0.5`
- **Fast Health Check**: `python tests/runner.py tests/plans/ALL_fast.yaml` (Verify on hardware)
- **Exhaustive Sweep**: `python tests/runner.py tests/plans/ALL_exhaustive.yaml` (Final benchmarks)
- **Mock Mode**: Add `--mock` to any plan to simulate execution for UI/Artifact testing.
- **Plumbing Mode**: Add `--plumbing` to run actual servers with lightweight stubs (No GPU required).

## [Section] : Naming Conventions
- **Prefixes**: Use `ol_` for Ollama and `vl_` or `vllm:` for vLLM in test setups.
- **Suffixes**: Use `#stream` to enable streaming mode (e.g., `OL_qwen2.5:0.5b#stream`).
- **Reporting**: Reports in `tests/artifacts/` use the setup name as the primary key.
- **Filename Sanitization**: When model names are used in file paths (e.g., output audio files), ensure they are sanitized to remove illegal characters like `/` and `:` to maintain cross-platform compatibility (e.g., `qwen/qwen2` becomes `qwen--qwen2`).

## [Section] : Network Convention
| Service | Port Range | Engine |
| :--- | :--- | :--- |
| **STT** | `8100 - 8109` | faster-whisper |
| **TTS** | `8200 - 8209` | chatterbox |
| **vLLM** | `8300` | Docker / OpenAI API |
| **Ollama** | `11434` | Native / Ollama API |
| **sts** | `8002` | Pipeline Orchestrator |

## [Section] : Strict Path Policy (Anti-Bloat)
Jarvis **requires** specific environment variables to be set. It will **exit immediately** if they are missing to prevent accidental model downloads to the C: drive.
- **`HF_HOME`**: Must point to your HuggingFace cache (e.g., `D:\ML_Cache\huggingface`).
- **`OLLAMA_MODELS`**: Must point to your Ollama model store (e.g., `D:\Ollama\models`).
- **Why?**: This standardizes storage across all tools (Jarvis, native Python, Docker) and keeps the system drive clean.

## [Section] : Hardware Note (RTX 5090)
- **vLLM VRAM**: Configured via `config.yaml` using a "GB-first" mapping strategy (default 3.0GB for Qwen 0.5B).
- **Cleanup**: Always use `--kill all` to ensure Docker releases GPU memory.
- **NumPy**: Keep at `1.25.2` for Chatterbox compatibility.

## [Section] : Assistant Persona & Tone
- **Honesty over Flattery**: Do not be sycophantic. Be critical when needed and call out good ideas only when you really feel they are good.
