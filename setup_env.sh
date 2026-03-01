#!/bin/bash

# Bootstraps the Jarvis virtual environment for Linux/macOS.
# Handles strict CUDA 12.4 dependencies and bypasses conflicting package requirements.

VENV_DIR="jarvis-venv"
PYTHON_EXE="./$VENV_DIR/bin/python"

echo -e "\033[0;36m🚀 Bootstrapping Jarvis Environment...\033[0m"

# 1. Create VENV if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating fresh virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# 2. Upgrade pip to ensure smooth wheel installation
echo "Upgrading pip..."
$PYTHON_EXE -m pip install --upgrade pip

# 3. Install core dependencies (including strict CUDA versions)
echo "Installing Core Stack (CUDA 12.4)..."
$PYTHON_EXE -m pip install -r requirements.txt

# 4. Install conflicted packages without dependencies
echo "Surgically installing Chatterbox TTS..."
$PYTHON_EXE -m pip install chatterbox_tts --no-deps

echo -e "\033[0;32m✅ Environment Ready!\033[0m"
