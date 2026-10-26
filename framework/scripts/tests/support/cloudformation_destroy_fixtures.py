"""Synthetic destroy backend shared by scheduler units and real Controller integrations."""

import importlib.util
import threading
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "destroy", Path(__file__).resolve().parents[2] / "cloudformation-destroy.py"
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TARGET = {
    "awsAccountId": "123456789012",
    "awsRegion": "ap-northeast-1",
    "iacEngine": "cloudformation",
}


def rejects(action, fragment):
    with pytest.raises((ValueError, M.Blocked)) as error:
        action()
    assert fragment in str(error.value), str(error.value)


def stack_id(name):
    return (
        f"arn:aws:cloudformation:ap-northeast-1:123456789012:stack/{name}/uuid-{name}"
    )


class Fake(M.AwsBackend):
    def __init__(self, names, outcomes=None, absent=(), exports=None):
        self.target = dict(TARGET)
        self.names = names
        self.calls = []
        self.deleted = []
        self.running = set()
        self.maximum = 0
        self.outcomes = outcomes or {}
        self.absent = set(absent)
        self.export_imports = exports or {}
        self.overrides = {}
        self.completed = set()
        self.lock = threading.Lock()
        self.profile = None
        self.polls = Counter()
        self.retained = set()
        self.hook = None

    def aws(self, operation, *arguments):
        with self.lock:
            self.calls.append((operation, arguments))
            assert operation in M.AwsBackend.READS | {
                "delete-stack",
                "get-caller-identity",
            }, operation
            if operation == "get-caller-identity":
                return {
                    "Account": self.target.get(
                        "awsExecutionAccountId", self.target["awsAccountId"]
                    )
                }
            if operation == "list-imports":
                return {"Imports": self.export_imports[arguments[1]][1]}
            identity = arguments[1]
            name = identity.split("/")[1] if identity.startswith("arn:") else identity
            if operation == "describe-stacks":
                if name in self.absent or name in self.completed:
                    return None
                actual = "CREATE_COMPLETE"
                if name in self.running:
                    self.polls[name] += 1
                    sequence = self.outcomes.get(
                        name, ["DELETE_IN_PROGRESS", "DELETE_COMPLETE"]
                    )
                    actual = sequence[min(self.polls[name] - 1, len(sequence) - 1)]
                    if actual == "DELETE_COMPLETE":
                        self.running.remove(name)
                        self.completed.add(name)
                    elif actual == "DELETE_FAILED":
                        self.running.remove(name)
                stack = {
                    "StackName": name,
                    "StackId": stack_id(name),
                    "StackStatus": actual,
                    "EnableTerminationProtection": False,
                    "ParentId": None,
                    "RootId": None,
                    "Outputs": [
                        {
                            "OutputKey": export,
                            "OutputValue": "value",
                            "ExportName": export,
                        }
                        for export, (producer, _) in self.export_imports.items()
                        if producer == name
                    ],
                }
                return {"Stacks": [stack | self.overrides.get(name, {})]}
            if operation == "delete-stack":
                assert identity == stack_id(name), "delete must use pinned StackId"
                assert "--deletion-mode" not in arguments
                assert name not in self.running
                self.running.add(name)
                self.deleted.append(name)
                self.maximum = max(self.maximum, len(self.running))
                if self.hook:
                    self.hook(name)
                return {}
            if operation == "describe-stack-events":
                return {
                    "StackEvents": [
                        {
                            "ResourceStatus": "DELETE_SKIPPED",
                            "LogicalResourceId": "Retained",
                        }
                    ]
                    if name in self.retained
                    else []
                }
            raise AssertionError(operation)


def session(orders):
    return {
        "states": {
            name: {
                "StackName": name,
                "DeployOrder": order,
                "status": "NOT_STARTED",
                "observedSynced": False,
            }
            for name, order in orders.items()
        }
    }


def execute(orders, limit=1, fake=None):
    fake = fake or Fake(list(orders))
    state = session(orders)
    try:
        M.preflight(state, fake, limit, lambda: None)
        M.dependencies(state, fake, lambda: None)
    except M.Blocked as error:
        state.update(status="BLOCKED", reason=str(error))
        return state, fake
    state["status"] = M.run_session(
        state, fake, limit, lambda: None, lambda *_: None, sleep=lambda _: None
    )
    return state, fake
