# Gemini CLI: Jarvis Assistant Developer Guide

## [Section] : Infrastructure Management
- **Check Cluster Health**: `python manage_loadout.py --status` (Shows ON, OFF, STARTUP, BUSY)
- **Activate Preset**: `python manage_loadout.py --apply [preset_name]` (Pulls from `/loadouts/*.yaml`)
- **Kill All Services**: `python manage_loadout.py --kill all` (Clears STT, TTS, Ollama, and vLLM Docker)
- **Debug Startup**: Add `--loud` to any `manage_loadout.py` command to show server windows.

## [Section] : Testing Workflow
- **Domain Testing**: `python tests/runner.py tests/plans/[DOMAIN]_fast.yaml` (Start here!)
- **Specific Setup**: `python tests/runner.py --domain sts --setup tiny_ol_qwen_0.5`
- **Fast Health Check**: `python tests/runner.py tests/plans/ALL_fast.yaml` (Run before commit)
- **Exhaustive Sweep**: `python tests/runner.py tests/plans/ALL_exhaustive.yaml` (Run before release)
- **Mock Mode**: Add `--mock` to any plan to simulate execution for UI/Artifact testing.
- **Debug Mode**: Use `--keep-alive` to prevent cleanup after a test, or `--dirty` to skip initial cleanup.
- **Visual Tweaks**: Use `python tests/generate_report.py --upload` to re-style reports without rerunning tests.

## [Section] : Network Convention
| Service | Port Range | Engine |
| :--- | :--- | :--- |
| **STT** | `8100 - 8109` | faster-whisper |
| **TTS** | `8200 - 8209` | chatterbox |
| **vLLM** | `8300` | Docker / OpenAI API |
| **Ollama** | `11434` | Native / Ollama API |
| **sts** | `8002` | Pipeline Orchestrator |

## [Section] : Naming Conventions
- **Prefixes**: Use `ol_` for Ollama and `vl_` or `vllm:` for vLLM in test setups.
- **Reporting**: Reports in `tests/artifacts/` use the setup name as the primary key.

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
