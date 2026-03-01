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
    print("🚀 Bootstrapping Jarvis Environment...
")
    
    venv_dir = "jarvis-venv"
    
    # 1. Create VENV if it doesn't exist
    if not os.path.exists(venv_dir):
        print(f"📦 Creating fresh virtual environment in '{venv_dir}'...")
        # Use the built-in venv module to create the environment
        venv.create(venv_dir, with_pip=True)
    else:
        print(f"✅ Virtual environment '{venv_dir}' already exists.")

    # Determine the path to the venv python executable based on OS
    if os.name == 'nt':  # Windows
        python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
    else:                # macOS / Linux
        python_exe = os.path.join(venv_dir, "bin", "python")

    if not os.path.exists(python_exe):
        print(f"❌ Error: Could not find Python executable at {python_exe}")
        sys.exit(1)

    # 2. Upgrade pip
    print("
📦 Upgrading pip...")
    run_cmd([python_exe, "-m", "pip", "install", "--upgrade", "pip"])

    # 3. Install core dependencies (including strict CUDA versions)
    print("
📦 Installing Core Stack (CUDA 12.4)...")
    run_cmd([python_exe, "-m", "pip", "install", "-r", "requirements.txt"])

    # 4. Install conflicted packages without dependencies
    print("
📦 Surgically installing Chatterbox TTS (bypassing conflicts)...")
    run_cmd([python_exe, "-m", "pip", "install", "chatterbox_tts", "--no-deps"])

    print("
✅ Environment Ready! You can now run the Jarvis Client.")

if __name__ == "__main__":
    main()
