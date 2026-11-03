"""Best-effort Scan liveness, separate from the Scan artifact."""

import json
import sys
import threading
import time
from datetime import datetime, timezone

from utils.file_operations import atomic_replace_file

STAGES = (
    "preflight",
    "mechanical",
    "diagnostics",
    "naming",
    "review_materials",
    "iac_comparison",
    "cfn_lint",
    "aggregation",
    "finalizing",
)


def now():
    return datetime.now(timezone.utc).isoformat()


class Progress:
    def __init__(self, path=None, interval=30):
        self.path = path
        self.interval = interval
        self.started = time.monotonic()
        self.stage_started = self.started
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.state = {
            "status": "running",
            "started_at": now(),
            "stages": [],
            "total_stages": len(STAGES),
        }
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)

    def _emit(self):
        stamp = now()
        self.state.update(
            heartbeat_at=stamp,
            elapsed_seconds=time.monotonic() - self.started,
            completed_stages=sum(
                s["status"] == "completed" for s in self.state["stages"]
            ),
        )
        if self.state["stages"] and self.state["stages"][-1]["status"] == "running":
            self.state["stages"][-1]["elapsed_seconds"] = (
                time.monotonic() - self.stage_started
            )
        print(
            f"Scan {self.state['status']}: {self.state.get('stage', 'starting')} ({self.state['elapsed_seconds']:.1f}s)",
            file=sys.stderr,
        )
        if self.path is not None:
            try:
                atomic_replace_file(
                    self.path, json.dumps(self.state, ensure_ascii=False) + "\n"
                )
            except (OSError, ValueError) as error:
                print(f"Scan progress write failed: {error}", file=sys.stderr)

    def _heartbeat(self):
        while not self.stop.wait(self.interval):
            with self.lock:
                self._emit()

    def start(self):
        self.stage("preflight")
        self.thread.start()

    def stage(self, name, total=None):
        with self.lock:
            if self.state["stages"]:
                previous = self.state["stages"][-1]
                previous.update(
                    status="completed",
                    ended_at=now(),
                    elapsed_seconds=time.monotonic() - self.stage_started,
                )
            self.stage_started = time.monotonic()
            self.state["stage"] = name
            stage = dict(
                name=name,
                status="running",
                started_at=now(),
                ended_at=None,
                elapsed_seconds=0,
            )
            if total is not None:
                stage.update(completed=0, total=total)
            self.state["stages"].append(stage)
            self._emit()

    def advance(self):
        with self.lock:
            self.state["stages"][-1]["completed"] += 1

    def finish(self, status):
        self.stop.set()
        self.thread.join()
        with self.lock:
            self.state["status"] = status
            self.state["ended_at"] = now()
            if self.state["stages"]:
                self.state["stages"][-1].update(
                    status=status,
                    ended_at=now(),
                    elapsed_seconds=time.monotonic() - self.stage_started,
                )
            self._emit()
