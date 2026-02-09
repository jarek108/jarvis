# Hardware & Environment Compatibility Guide (RTX 5090)

This document summarizes the specific library versions required to run the Jarvis voice assistant on an **NVIDIA RTX 5090 (Blackwell architecture)**.

## Key Versions

| Component | Version | Justification |
| :--- | :--- | :--- |
| **Operating System** | Windows 10/11 (win32) | Project environment. |
| **Python** | 3.10.x | Compatibility with `chatterbox-tts` and `faster-whisper`. |
| **PyTorch** | `2.11.0.dev20260206+cu128` | **CRITICAL:** RTX 5090 (`sm_120`) requires CUDA 12.8+ support found in Nightly builds. Stable 2.5/2.6 (CUDA 12.1/12.4) fails with "no kernel image". |
| **CUDA** | 12.8 (via Torch Nightly) | Required for Blackwell GPU architecture. |
| **TorchAudio** | `2.11.0.dev20260206+cu128` | Must match PyTorch version/index. |
| **TorchVision** | `0.26.0.dev20260206+cu128` | Must match PyTorch version/index. |
| **NumPy** | `1.25.2` | **FORCED:** `chatterbox-tts` requires `< 1.26.0`. Pipecat-ai prefers higher but works with this version. |
| **Pillow** | `11.3.0` | **FORCED:** `pipecat-ai` requires `< 12.0.0`. |
| **Pipecat-ai** | `0.0.101` | Core orchestration framework. |

## Dependency Conflict Resolution

1.  **RTX 5090 "No Kernel Image" Error:**
    Standard PyTorch releases do not yet include the Blackwell compute kernels. We switched to the **Nightly Index** (`https://download.pytorch.org/whl/nightly/cu128`) to resolve this.

2.  **The NumPy Conflict:**
    `pipecat-ai` tries to install NumPy 2.x, but `chatterbox-tts` (Resemble AI) has a strict check for NumPy 1.x (specifically `< 1.26.0`). We manually pinned `1.25.2` to satisfy both.

3.  **Chatterbox strict Torch check:**
    `chatterbox-tts` originally requested `torch==2.6.0`. Since the 5090 required the Nightly version (`2.11.0.dev`), we performed a `--force-reinstall` to bypass the strict equality check while maintaining system functionality.

## Reinstallation Command
If the environment needs to be rebuilt, use this specific order:
```powershell
# 1. Install GPU compute stack
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128 --force-reinstall

# 2. Fix downstream conflicts
pip install "numpy<1.26.0,>=1.24.0" "pillow<12.0,>=11.1.0"
```
