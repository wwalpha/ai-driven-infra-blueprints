"""Independent Deploy invocations with lazy, immutable current-worktree inputs."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import SimpleNamespace

from model.dependency_index import revision as file_revision
from task_contract_core import TaskSnapshot, task_reads, task_snapshot
from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint
from utils.type_contracts import JsonValue as JsonValue

from deploy import (
    worktree,
)
from deploy.typing import (
    DeployRunContext,
    StackUnit,
    Target,
)


def active_scope(
    root: Path,
    requested: Iterable[str],
    environment: str,
    account: str,
    alias: str | None = None,
    *,
    snapshot: TaskSnapshot | None = None,
    allow_saved: bool = False,
) -> str:
    snapshot = snapshot or task_snapshot(root)
    text = snapshot.text
    if snapshot.status != "running" and not (
        allow_saved and snapshot.status == "completed"
    ):
        raise Blocked("completed task cannot deploy")
    for line in (
        "- Task type: `infrastructure`",
        "- AWS API execution: `allowed`",
        "- Deploy/apply: `allowed`",
        f"- Target environment: `{environment}`",
        f"- Target AWS account: `{account}`",
    ):
        if line not in text.splitlines():
            raise Blocked(f"active task must explicitly contain {line}")
    if not any(
        f"- Infrastructure phase: `{phase}`" in text.splitlines()
        for phase in ("deploy", "update")
    ):
        raise Blocked("controller requires infrastructure deploy/update phase")
    if alias and f"- Target alias: `{alias}`" not in text.splitlines():
        raise Blocked("requested alias must exactly match active task Target alias")
    scopes = [
        line for line in text.splitlines() if line.startswith("- Deployment scope:")
    ]
    if len(scopes) != 1 or set(re.findall(r"`([^`]+)`", scopes[0])) != set(requested):
        raise Blocked(
            "requested StackName scope must exactly match active task Deployment scope"
        )
    return (
        "update"
        if "- Infrastructure phase: `update`" in text.splitlines()
        else "deploy"
    )


def current_manifest(
    root: Path, run_context: DeployRunContext, backend: SimpleNamespace
) -> dict[str, str]:
    return {
        relative: backend.file_digest(root / relative, fresh=True)
        for relative in run_context["consumedInputs"]
    }


def _callback_claim_inputs(root, run_context, backend, save, /, unit):
    name = unit["name"]
    paths = backend.deployment_input_paths([unit])
    if getattr(backend, "phase", None) == "deploy" and paths:
        revision = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--",
                *[p.relative_to(root).as_posix() for p in paths],
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if revision.returncode or revision.stdout.strip():
            raise Blocked("deploy inputs must be committed before use: " + name)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if file_revision(path) != run_context["inputIdentities"][relative]:
            raise Blocked("deployment inputs changed before first use: " + relative)
    digest = backend.input_digest(unit, fresh=True)
    expected = run_context["inputDigests"].get(name)
    if expected is not None and digest != expected:
        raise Blocked("prepared/executed unit IaC changed: " + name)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if file_revision(path) != run_context["inputIdentities"][relative]:
            raise Blocked("deployment inputs changed while claiming: " + relative)
        run_context["consumedInputs"][relative] = backend.file_digest(path)
    run_context["inputDigests"][name] = digest
    save()


def _callback_run_guard(
    args, backend, context, root, selected, run_context, target, /
) -> TaskSnapshot:
    with task_reads(root, live=True):
        snapshot = task_snapshot(root, executable=False)
        worktree.require(root, snapshot)
        active_scope(
            root,
            args.stack,
            args.environment,
            selected["awsAccountId"],
            args.alias,
            snapshot=snapshot,
            allow_saved=getattr(args, "action", None)
            in {"sync", "checkpoint", "status"},
        )
        if (
            context.load_target(root, args.environment, args.aws_account_id, args.alias)
            != target
        ):
            raise Blocked("project target changed before mutation")
        if snapshot.task_digest != run_context["taskDigest"]:
            raise Blocked("task contract changed before mutation")
        if (
            current_manifest(root, run_context, backend)
            != run_context["consumedInputs"]
        ):
            raise Blocked("unauthorized IaC change outside accepted input revision")
        return snapshot


# Runtime bootstrap does not change IaC or grant a validation/hash exception.
def _callback_run_refresh_validation(backend, unit_digests, /, unit):
    # Runtime bootstrap does not change IaC or grant a validation/hash exception.
    backend.load_inputs(unit)
    if backend.input_digest(unit, fresh=True) != unit_digests[unit["name"]]:
        raise Blocked("runtime recovery changed immutable IaC inputs")


def new_context(
    root: Path,
    task: TaskSnapshot,
    target: Target,
    environment: str,
    directory: str,
    units: Sequence[StackUnit],
    backend: SimpleNamespace,
) -> DeployRunContext:
    context = DeployRunContext(
        repository=str(root),
        taskFile=task.name,
        taskDigest=task.task_digest,
        target=target,
        environment=environment,
        directory=directory,
        inputDigest=fingerprint([str(root), target, environment, units]),
        states={u["name"]: {"status": "NOT_STARTED"} for u in units},
        inputDigests={},
        consumedInputs={},
        inputIdentities={
            p.relative_to(root).as_posix(): file_revision(p)
            for p in backend.deployment_input_paths(units)
        },
        metrics={"observedSyncSeconds": 0, "inputLoadSeconds": 0},
    )
    return context
