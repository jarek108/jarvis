import sys
import io

# --- SHARED UI CONSTANTS ---
CYAN = "\033[96m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
LINE_LEN = 120

def ensure_utf8_output():
    """Forces UTF-8 for console output on Windows to prevent UnicodeEncodeErrors."""
    if sys.platform == "win32":
        if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        if not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8':
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class LiveFilter(io.StringIO):
    """Captures everything, but only writes non-machine lines to the real stdout in TTY mode."""
    def __init__(self):
        super().__init__()
        ensure_utf8_output()
        self.out = sys.stdout

    def write(self, s):
        for line in s.splitlines(keepends=True):
            is_machine = line.startswith("SCENARIO_RESULT: ") or line.startswith("LIFECYCLE_RECEIPT: ") or line.startswith("VRAM_AUDIT_RESULT: ")
            if not is_machine or not self.out.isatty():
                self.out.write(line)
                self.out.flush()
        return super().write(s)

def fmt_with_chunks(text, chunks):
    """Adds (timestamp) markers to text based on chunk data."""
    if not chunks: return text
    out = []
    last_end = 0.0
    for c in chunks:
        out.append(f"{c['text']} ({last_end:.2f} → {c['end']:.2f}s)")
        last_end = c['end']
    return " ".join(out)
