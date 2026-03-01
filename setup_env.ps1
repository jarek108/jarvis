<#
.SYNOPSIS
Bootstrap script for the Jarvis virtual environment.
Handles strict CUDA 12.4 dependencies and bypasses conflicting package requirements.
#>

$VenvDir = "jarvis-venv"

Write-Host "🚀 Bootstrapping Jarvis Environment..." -ForegroundColor Cyan

# 1. Create VENV if it doesn't exist
if (-Not (Test-Path -Path $VenvDir)) {
    Write-Host "Creating fresh virtual environment..."
    python -m venv $VenvDir
}

# 2. Upgrade pip to ensure smooth wheel installation
Write-Host "Upgrading pip..."
& ".\$VenvDir\Scripts\python.exe" -m pip install --upgrade pip

# 3. Install core dependencies (including strict CUDA versions)
Write-Host "Installing Core Stack (CUDA 12.4)..."
& ".\$VenvDir\Scripts\python.exe" -m pip install -r requirements.txt

# 4. Install conflicted packages without dependencies
Write-Host "Surgically installing Chatterbox TTS..."
& ".\$VenvDir\Scripts\python.exe" -m pip install chatterbox_tts --no-deps

Write-Host "✅ Environment Ready!" -ForegroundColor Green
