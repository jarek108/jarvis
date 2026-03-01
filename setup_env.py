import os
import sys
import subprocess
import venv

def run_cmd(cmd, env=None):
    print(f"🔄 Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"❌ Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)

def main():
    print("🚀 Bootstrapping Jarvis Environment...\n")
    
    venv_dir = "jarvis-venv"
    
    # 1. Create VENV if it doesn't exist
    if not os.path.exists(venv_dir):
        print(f"📦 Creating fresh virtual environment in '{venv_dir}'...")
        venv.create(venv_dir, with_pip=True)
    else:
        print(f"✅ Virtual environment '{venv_dir}' already exists.")

    if os.name == 'nt':
        python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_dir, "bin", "python")

    if not os.path.exists(python_exe):
        print(f"❌ Error: Could not find Python executable at {python_exe}")
        sys.exit(1)

    # 2. Upgrade pip
    print("\n📦 Upgrading pip...")
    run_cmd([python_exe, "-m", "pip", "install", "--upgrade", "pip"])

    # 3. Install core dependencies (This will pull generic torch 2.6.0 via chatterbox)
    print("\n📦 Installing Project Requirements...")
    run_cmd([python_exe, "-m", "pip", "install", "-r", "requirements.txt"])

    # 4. Surgically Overwrite PyTorch with CUDA 12.4 Stack
    print("\n📦 Optimizing PyTorch for NVIDIA Blackwell (CUDA 12.4)...")
    run_cmd([
        python_exe, "-m", "pip", "install", 
        "torch==2.5.1+cu124", "torchvision==0.20.1+cu124", "torchaudio==2.5.1+cu124",
        "--index-url", "https://download.pytorch.org/whl/cu124",
        "--force-reinstall"
    ])

    print("\n✅ Environment Ready! You can now run the Jarvis Client.")

if __name__ == "__main__":
    main()
