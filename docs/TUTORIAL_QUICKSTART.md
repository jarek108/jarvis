# Jarvis Installation & Quickstart

This guide covers the minimal steps to get Jarvis running on a Windows 10/11 system with an NVIDIA GPU (RTX 5090 / Blackwell target).

## 1. Prerequisites

### System Requirements
*   **OS**: Windows 10 or 11 (22H2+)
*   **GPU**: NVIDIA RTX Series (12GB+ VRAM recommended)
*   **RAM**: 32GB+ System Memory
*   **Storage**: NVMe SSD (Models are heavy!)

### Software Stack
1.  **Python 3.10**: Strictly required. (3.11+ breaks `torch-audio` dependencies).
2.  **CUDA Toolkit 12.8+**: Required for Blackwell architecture support.
3.  **Docker Desktop**: With "Use WSL 2 based engine" enabled.
4.  **Ollama**: Installed as a native Windows service.

## 2. Installation

### Clone & Bootstrap
Jarvis provides an automated bootstrap script to handle the complex Blackwell/CUDA 12.8 dependency tree.
```powershell
git clone https://github.com/your/jarvis.git
cd jarvis

# Run the unified setup script
python setup/setup_env.py
```

### Manual Installation (Optional)
If you prefer manual control, you can use the hardware-specific snapshot:
```powershell
python -m venv jarvis-venv
.\jarvis-venv\Scripts\Activate.ps1
pip install -r setup/requirements_5090_snapshot_20260301.txt
```

### Environment Variables
Jarvis enforces strict hygiene. You **must** set these to avoid polluting C: drive.
*   `HF_HOME`: Path to HuggingFace cache (e.g., `D:\ML_Cache\huggingface`)
*   `OLLAMA_MODELS`: Path to Ollama models (e.g., `D:\Ollama\models`)

## 3. Hello World

1.  **Activate Environment:** `.\jarvis-venv\Scripts\Activate.ps1`
2.  **Start Default Cluster:**
    ```powershell
    python manage_loadout.py --apply base-qwen30-multi
    ```
    *(Wait for "JARVIS PIPELINE READY" in the logs window)*

3.  **Run Client:**
    ```powershell
    python jarvis_client.py
    ```
    *   Hold **Spacebar** to talk.
    *   Release to send.

## 4. Verification
Run the fast health check to ensure all subsystems (Docker, Ollama, Audio) are linked.
```powershell
python tests/runner.py tests/plans/ALL_fast.yaml
```
