import sys
import os

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

from ui import JarvisApp

if __name__ == "__main__":
    app = JarvisApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("\n[Client] Exiting gracefully due to KeyboardInterrupt...")
        app.destroy()
        sys.exit(0)
