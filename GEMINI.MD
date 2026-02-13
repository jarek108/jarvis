# Gemini CLI: Jarvis Assistant Developer Guide

## [Section] : Infrastructure Management
- **Check Cluster Health**: `python manage_loadout.py --status` (Shows ON, OFF, STARTUP, BUSY)
- **Activate Preset**: `python manage_loadout.py --apply [preset_name]` (Pulls from `/loadouts/*.yaml`)
- **Kill All Services**: `python manage_loadout.py --kill all` (Clears STT, TTS, Ollama, and vLLM Docker)
- **Debug Startup**: Add `--loud` to any `manage_loadout.py` command to show server windows.

## [Section] : Testing Workflow
- **Domain Testing**: `python tests/runner.py --domain [sts|stt|tts|llm|vlm]`
- **Specific Setup**: `python tests/runner.py --domain sts --setup tiny_ol_qwen_0.5`
- **Soft Downloads**: By default, tests skip missing models (**MISSING** status). 
- **Force Download**: Use `--force-download` to pull missing Ollama/vLLM models.
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

## [Section] : Hardware Note (RTX 5090)
- **vLLM VRAM**: Allocated at 90% by default.
- **Cleanup**: Always use `--kill all` to ensure Docker releases GPU memory.
- **NumPy**: Keep at `1.25.2` for Chatterbox compatibility.

## [Section] : Assistant Persona & Tone
- **Honesty over Flattery**: Do not be sycophantic. Be critical when needed and call out good ideas only when you really feel they are good.
