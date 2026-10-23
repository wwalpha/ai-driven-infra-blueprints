"""Existing invocation-owned deployment timing."""
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class Timing:
    """Invocation-owned, thread-safe diagnostics outside the repository."""
    def __init__(self, root, path=None):
        self.path = Path(path).resolve() if path else None
        self.lock = Lock()
        if self.path:
            if self.path.is_relative_to(root.resolve()):
                raise ValueError("deployment timing must be outside repository")
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def phase(self, name, started=None, **fields):
        started, result = time.perf_counter() if started is None else started, "PASS"
        try:
            yield
        except BaseException:
            result = "FAIL"
            raise
        finally:
            if self.path:
                event = {"phase": name, "seconds": time.perf_counter() - started,
                         "result": result, "utc": datetime.now(timezone.utc).isoformat(),
                         "pid": os.getpid(), "python": sys.executable, **fields}
                with self.lock, self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
