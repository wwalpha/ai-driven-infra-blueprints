"""Local CLI-Deploy context and validation; never retrieve or mutate AWS."""

import re
from contextlib import contextmanager
from contextvars import ContextVar

import task_contract_core as tasks
from contracts.target import (
    AWS_ACCOUNT_ID_KEY,
    AWS_EXECUTION_ACCOUNT_ID_KEY,
    AWS_REGION_KEY,
)

from utils.project_targets import load_target_directory
from utils.script_loader import module

_staged_roots = ContextVar("cli_deploy_staged_roots", default=None)
_generation_task = ContextVar("cli_deploy_generation_task", default=None)


@contextmanager
def staged_root(stage, root):
    token = _staged_roots.set({**(_staged_roots.get() or {}), stage.resolve(): root})
    try:
        yield
    finally:
        _staged_roots.reset(token)


@contextmanager
def generation_task(root, snapshot):
    token = _generation_task.set((root.resolve(), snapshot))
    try:
        yield
    finally:
        _generation_task.reset(token)


def field(text, name):
    values = [
        line.removeprefix(f"- {name}: ")
        for line in tasks.section(text, "## Task contract")
        if line.startswith(f"- {name}:")
    ]
    if len(values) != 1 or not re.fullmatch(r"`[^`\r\n]+`", values[0]):
        raise ValueError(f"CLI Deploy requires one explicit {name}")
    return values[0][1:-1]


def is_cli(text):
    contract = tasks.section(text, "## Task contract")
    if not any(line.startswith("- Deploy execution method:") for line in contract):
        return False
    method = field(text, "Deploy execution method")
    if method not in {"sdk", "cli"}:
        raise ValueError("Deploy execution method must be sdk or cli")
    if method == "cli" and not {
        "- Task type: `infrastructure`",
        "- Infrastructure phase: `deploy`",
    }.issubset(contract):
        raise ValueError("CLI Deploy requires infrastructure/deploy")
    return method == "cli"


def partition(root, target, *, text=None):
    root = (_staged_roots.get() or {}).get(root.resolve(), root)
    if text is None:
        current = _generation_task.get()
        if current is not None and current[0] == root.resolve():
            snapshot = current[1]
            if snapshot is None:
                return None
            text = snapshot.text
        else:
            if tasks.task_path(root, required=False) is None:
                return None
            text = tasks.task_snapshot(root, executable=False).text
    if not is_cli(text):
        return None
    account = target.get(AWS_EXECUTION_ACCOUNT_ID_KEY, target.get(AWS_ACCOUNT_ID_KEY))
    if field(text, "CLI AWS account") != account or field(
        text, "CLI AWS region"
    ) != target.get(AWS_REGION_KEY):
        raise ValueError("CLI AWS context differs from the selected Model target")
    value = field(text, "CLI AWS partition")
    if re.fullmatch(r"aws(?:-[a-z]+)*", value) is None:
        raise ValueError("CLI AWS partition must come from confirmed STS identity")
    return value


def require_local_completion(root, snapshot, *, base=None):
    if not is_cli(snapshot.text):
        raise ValueError("local CLI completion requires the CLI execution method")
    if not snapshot.scope:
        raise ValueError("CLI Deploy requires a scoped target")
    for environment, directory in {(e, d) for e, d, _ in snapshot.scope}:
        partition(
            root,
            load_target_directory(root, environment, directory),
            text=snapshot.text,
        )
    if base is None:
        progress = module("deploy/progress.py", "deploy.progress")
        path = progress.progress_path(root, snapshot.name)
        if path.exists() or path.is_symlink():
            raise ValueError("SDK-bound Tasks cannot switch to CLI completion")
        completion = module("deploy/completion.py", "deploy.completion")
        completion.verify_observation_delta(root)
        return
    wt = module("worktree_task.py", "worktree_task")
    verify_observed_outputs = module("model/observed.py", "model.observed").verify_observed_outputs
    changed = wt.paths(root, "diff", "--name-only", "--no-renames", "-z", base, "--") | wt.changed_paths(root)
    if "project.json" in changed:
        raise ValueError("CLI Deploy cannot change project configuration")
    sources = {root / p for p in changed if p.startswith("model/")}
    verify_observed_outputs(
        {p: wt.subprocess_bytes(root, base, p.relative_to(root).as_posix()) for p in sources},
        {p: p.read_text(encoding="utf-8") for p in sources},
    )


def validate_candidate(root, task_file, base):
    wt = module("worktree_task.py", "worktree_task")
    Validator = module("validation/runner.py", "validation.runner").Validator
    definition_root = module(
        "utils/aws_mappings.py", "utils.aws_mappings"
    ).definition_root
    snapshot = tasks.task_snapshot(root, task_file, executable=False, live=True)
    require_local_completion(root, snapshot, base=base)
    if snapshot.status != "completed" or not snapshot.scope:
        raise ValueError("CLI publication requires a completed, scoped candidate")
    candidate = wt.FinalCandidate(
        root,
        definition_root(root),
        task_file,
        snapshot.text,
        base,
        wt.output(root, "rev-parse", "HEAD"),
        frozenset(
            wt.paths(root, "diff", "--name-only", "--no-renames", "-z", base, "HEAD")
        ),
        snapshot.scope,
    )
    validator = Validator(
        root,
        set(snapshot.scope),
        cache=False,
        model_validation="change",
        final_candidate=candidate,
    )
    validator.run()
    if validator.report():
        validator.display_report()
        raise ValueError("CLI latest-base Snapshot validation failed")
