"""Best-effort Scan liveness, separate from the Scan artifact."""

import json
import sys
import threading
import time
from datetime import datetime, timezone

from utils.file_operations import atomic_replace_file
from utils.json_format import strict_json

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


def read_progress(path):
    state = strict_json(path.read_bytes())
    if not isinstance(state, dict):
        raise ValueError("invalid Issue Scan progress file")
    legacy = "kind" not in state and "version" not in state
    legacy_fields = {
        "status",
        "started_at",
        "stages",
        "total_stages",
        "stage",
        "heartbeat_at",
        "elapsed_seconds",
        "completed_stages",
    }
    if (
        (
            legacy
            and (
                not legacy_fields <= state.keys()
                or state.keys() - legacy_fields - {"ended_at"}
            )
        )
        or (
            not legacy
            and (
                state.get("kind") != "issues-scan-progress"
                or type(state.get("version")) is not int
                or state["version"] != 1
            )
        )
        or state.get("status") not in ("running", "completed", "failed")
        or not isinstance(state.get("started_at"), str)
        or not isinstance(state.get("heartbeat_at"), str)
        or not isinstance(state.get("stages"), list)
        or not state["stages"]
        or not isinstance(state["stages"][-1], dict)
        or state.get("stage") != state["stages"][-1].get("name")
        or state.get("status") != state["stages"][-1].get("status")
        or type(state.get("elapsed_seconds")) not in (int, float)
        or type(state.get("total_stages")) is not int
        or state["total_stages"] != len(STAGES)
        or type(state.get("completed_stages")) is not int
        or not 0 <= state["completed_stages"] <= len(state["stages"]) <= len(STAGES)
        or any(
            not isinstance(stage, dict)
            or stage.get("name") not in STAGES
            or stage.get("status") not in ("running", "completed", "failed")
            or not isinstance(stage.get("started_at"), str)
            or (
                "completed" in stage
                and (
                    type(stage["completed"]) is not int
                    or type(stage.get("total")) is not int
                    or not 0 <= stage["completed"] <= stage["total"]
                )
            )
            for stage in state["stages"]
        )
        or state["completed_stages"]
        != sum(stage["status"] == "completed" for stage in state["stages"])
    ):
        raise ValueError("invalid Issue Scan progress file")
    return state


def now():
    return datetime.now(timezone.utc).isoformat()


class Progress:
    def __init__(self, path=None, interval=30):
        self.path = path
        if path is not None and path.exists():
            read_progress(path)
        self.interval = interval
        self.started = time.monotonic()
        self.stage_started = self.started
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.state = {
            "kind": "issues-scan-progress",
            "version": 1,
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
        self._write()

    def _write(self):
        if self.path is not None:
            try:
                if self.path.exists():
                    read_progress(self.path)
                atomic_replace_file(
                    self.path, json.dumps(self.state, ensure_ascii=False) + "\n"
                )
            except (OSError, ValueError, TypeError) as error:
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
            self._write()

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
