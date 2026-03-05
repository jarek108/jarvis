import sys
import os
import argparse

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

from ui import JarvisApp

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Desktop Client")
    parser.add_argument("--mock-all", action="store_true", help="Enable mocking for all models and hardware.")
    args = parser.parse_args()

    if args.mock_all:
        os.environ['JARVIS_MOCK_ALL'] = "1"
        print("[Client] 🧪 MOCK MODE ENABLED")

    app = JarvisApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("\n[Client] Exiting gracefully due to KeyboardInterrupt...")
        app.destroy()
        sys.exit(0)
