import json
import sys
from typing import Dict, Any, Callable, Optional, List

class BaseReporter:
    def report(self, result: Dict[str, Any]):
        raise NotImplementedError

class StdoutReporter(BaseReporter):
    """Writes results to stdout with a machine-readable prefix."""
    def report(self, result: Dict[str, Any]):
        sys.stdout.write(f"SCENARIO_RESULT: {json.dumps(result)}\n")
        sys.stdout.flush()

class AccumulatingReporter(BaseReporter):
    """Collects results in memory and optionally triggers a callback."""
    def __init__(self, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.results: List[Dict[str, Any]] = []
        self.callback = callback

    def report(self, result: Dict[str, Any]):
        self.results.append(result)
        if self.callback:
            self.callback(result)
