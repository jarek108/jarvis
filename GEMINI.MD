# Gemini CLI: Jarvis Assistant Developer Guide

## [Section] : Infrastructure Management
- **Check Cluster Health**: `python manage_loadout.py --status` (Shows ON, OFF, STARTUP, BUSY)
- **Activate Preset**: `python manage_loadout.py --apply [preset_name]` (e.g., `default`, `eng_turbo`)
- **Kill All Services**: `python manage_loadout.py --kill all`
- **Debug Startup**: Add `--loud` to any `manage_loadout.py` command to show server windows.

## [Section] : Testing Workflow
- **Quick Verification**: `python tests/run_health_check.py` (Checks STT-Base, TTS-Eng, and S2S-Default. Always use this for normal checks)
- **Full Benchmark**: `python tests/run_extensive_comparison.py` (Full sweep of all model sizes and loadouts. Only on explicit user request)
- **Isolated Testing**: 
    - Domain: `tests/[stt|tts]/whisper|chatterbox/isolated_[variant].py`
    - Pipeline: `tests/s2s/isolated_[loadout].py`
    - These scripts probe for existing services before attempting a transient lifecycle.

## [Section] : S2S Server Usage
- **Manual Start**: `python servers/s2s_server.py --loadout default`
- **Warmup Logic**: The S2S server remains in `STARTUP` (503) state until STT, TTS, and LLM are fully initialized and warmed up with dummy requests.

## [Section] : Naming Conventions
- **STT**: `faster-whisper-[size]` (e.g., `faster-whisper-tiny`)
- **TTS**: `chatterbox-[variant]` (e.g., `chatterbox-multilingual`, `chatterbox-turbo`)
- **LLM**: Refer to Ollama model strings (e.g., `gpt-oss:20b`)

## [Section] : Hardware Note (RTX 5090)
- Ensure PyTorch Nightly is used for CUDA 12.8 support.
- Keep NumPy at `1.25.2` to satisfy Chatterbox constraints.

## [Section] : Assistant Persona & Tone
- **Honesty over Flattery**: Do not be sycophantic. Be critical when needed and call out good ideas only when you really feel they are good.

## [Section] : UI & UX Principles
- **Consolidated Overview**: In UI, logging, and testing, prefer short consolidated defaults that allow a wide overview at any point without too many details or prolonged waits.