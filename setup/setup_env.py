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
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    venv_dir = os.path.join(project_root, "jarvis-venv")
    requirements_path = os.path.join(script_dir, "requirements.txt")
    
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

    # 2. Upgrade pip, setuptools, and wheel
    print("\n📦 Upgrading pip, setuptools, and wheel...")
    run_cmd([python_exe, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    # 3. Install core dependencies
    print("\n📦 Installing Project Requirements...")
    run_cmd([python_exe, "-m", "pip", "install", "-r", requirements_path])

    # 4. Surgically Overwrite PyTorch with Nightly CUDA Stack (Blackwell Support)
    print("\n📦 Optimizing PyTorch for NVIDIA Blackwell (RTX 5090 / CUDA 12.8)...")
    run_cmd([
        python_exe, "-m", "pip", "install", "--pre",
        "torch", "torchvision", "torchaudio",
        "--index-url", "https://download.pytorch.org/whl/nightly/cu128",
        "--force-reinstall"
    ])

    print("\n✅ Environment Ready! You can now run the Jarvis Client.")

if __name__ == "__main__":
    main()
