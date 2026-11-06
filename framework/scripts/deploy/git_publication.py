"""Deploy checkpoint validation helpers."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import task_contract_core as tasks
import worktree_state as ws
import worktree_task as wt
from model.observed import verify_observed_outputs
from utils.aws_mappings import definition_root
from validation.findings import Findings
from validation.runner import Validator
from validation.task import TaskValidation

from deploy import contracts, inputs, worktree


def check_scope(root, task_file):
    wt._run_model_guard(root, task_file, deploy_scope=True)


def check_scope_in_process(root, task_file):
    baseline = ws.deploy_start_commit(root, task_file, required=True)
    require_observation_delta(root, baseline)
    findings = Findings(root)
    task = TaskValidation(root, findings, contract_file=task_file)
    task.baseline = baseline
    task.baseline_fixed = True
    task.check_task_scope()
    task.check_task_type_requirements()
    if findings.errors:
        raise ValueError("; ".join(findings.errors))


def require_observation_delta(root, baseline):
    sources = {
        relative
        for relative in wt.paths(
            root, "diff", "--no-renames", "--name-only", "-z", baseline, "--", "model"
        )
        if relative.endswith(".properties")
    }
    sources |= {
        p
        for p in wt.changed_paths(root)
        if p.startswith("model/") and p.endswith(".properties")
    }
    before = {root / p: ws.subprocess_bytes(root, baseline, p) for p in sources}
    after = {
        root / p: tasks.safe_path(root, p).read_text(encoding="utf-8") for p in sources
    }
    verify_observed_outputs(before, after)


def task_tracked(root, task_file):
    return task_file in wt.paths(root, "ls-files", "--cached", "-z", "--", task_file)


def output_changes(root, state):
    changed = wt.changed_paths(root)
    if state["task_file"] in changed and not task_tracked(root, state["task_file"]):
        changed.discard(state["task_file"])
    return changed


def final_tree(root, changed, task):
    """Prepare the exact source tree with a private index; never force-add a Task."""
    with tempfile.TemporaryDirectory(prefix="blueprint-deploy-index-") as directory:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        environment["GIT_INDEX_FILE"] = str(Path(directory) / "index")
        subprocess.run(
            ["git", "read-tree", "HEAD"],
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
        )
        if changed - {task.name}:
            subprocess.run(
                [
                    "git",
                    "add",
                    "--",
                    *[f":(top,literal){p}" for p in sorted(changed - {task.name})],
                ],
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
            )
        if task_tracked(root, task.name):
            oid = (
                subprocess.run(
                    ["git", "hash-object", "-w", "--stdin"],
                    cwd=root,
                    input=task.raw,
                    check=True,
                    capture_output=True,
                )
                .stdout.decode()
                .strip()
            )
            mode = wt.output(root, "ls-tree", "HEAD", "--", task.name).partition(" ")[0]
            subprocess.run(
                ["git", "update-index", "--cacheinfo", mode, oid, task.name],
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
            )
        return subprocess.run(
            ["git", "write-tree"],
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout.strip()


def checkpoint(root, path, state, *, preflight):
    task = tasks.read_task_snapshot(root, state["task_file"], live=True)
    worktree.require(root, task)
    changed = output_changes(root, state)
    before = {
        p: tasks.safe_path(root, p).read_bytes() if (root / p).is_file() else None
        for p in changed
    }
    if (
        task.raw != preflight["task"]
        or changed != preflight["changed"]
        or wt.output(root, "rev-parse", "HEAD") != preflight["head"]
        or wt.output(root, "write-tree") != preflight["index"]
        or contracts.validation_snapshot(root) != preflight["candidate"]
    ):
        raise ws.Blocked("Deploy checkpoint inputs changed during preflight")
    if not changed and not state.get("deployCheckpointIntent"):
        return wt.output(root, "rev-parse", "HEAD")
    if (
        changed != output_changes(root, state)
        or any(
            (tasks.safe_path(root, p).read_bytes() if (root / p).is_file() else None)
            != raw
            for p, raw in before.items()
        )
        or tasks.read_task_snapshot(root, state["task_file"], live=True).raw != task.raw
    ):
        raise ws.Blocked("Deploy checkpoint inputs changed during validation")
    intent = state.get("deployCheckpointIntent")
    head = wt.output(root, "rev-parse", "HEAD")
    if intent is None:
        if head != state["tip"]:
            raise ws.Blocked("unexpected Deploy checkpoint HEAD")
        wt.git(root, "diff", "--check")
        wt.git(root, "diff", "--cached", "--check")
        if not changed:
            return head
        wt.git(root, "add", "--", *[f":(top,literal){p}" for p in sorted(changed)])
        if preflight.get("tree") and wt.output(root, "write-tree") != preflight["tree"]:
            raise ws.Blocked(
                "checkpoint tree differs from the validated final candidate"
            )
        intent = dict(
            head=head,
            tree=wt.output(root, "write-tree"),
            message=f"task({state['task_id']}): Deploy observed checkpoint",
        )
        state["deployCheckpointIntent"] = intent
        wt.save(path, state)
    if head == intent["head"]:
        if wt.output(root, "write-tree") != intent["tree"]:
            raise ws.Blocked("Deploy checkpoint index changed after intent")
        wt.git(root, "commit", "-m", intent["message"])
    head = wt.output(root, "rev-parse", "HEAD")
    if (
        wt.output(root, "rev-parse", "HEAD^") != intent["head"]
        or wt.output(root, "rev-parse", "HEAD^{tree}") != intent["tree"]
        or output_changes(root, state)
    ):
        raise ws.Blocked("Deploy checkpoint differs from its saved intent")
    state["tip"] = head
    state.pop("deployCheckpointIntent", None)
    wt.save(path, state)
    return head


def validate_candidate(root, tree, base, task):
    """Use the existing scoped validator on a disposable Git snapshot, never on main."""
    interpreter, environment = wt.python_env.runtime(root)
    with tempfile.TemporaryDirectory(
        prefix="blueprint-deploy-publication-"
    ) as directory:
        stage = (Path(directory) / "repository").resolve()
        wt.git(
            root, "clone", "--quiet", "--shared", "--no-checkout", str(root), str(stage)
        )
        wt.git(stage, "checkout", "--quiet", "--detach", base)
        wt.git(stage, "read-tree", "--reset", "-u", tree)
        destination = stage / task.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(task.raw)
        result = subprocess.run(
            [
                str(interpreter),
                "-B",
                "-c",
                f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); "
                "from pathlib import Path; from deploy.git_publication import validate_snapshot; "
                "raise SystemExit(validate_snapshot(Path(sys.argv[1]), Path(sys.argv[2]), *sys.argv[3:]))",
                str(root),
                str(stage),
                base,
                tree,
                task.name,
            ],
            cwd=stage,
            env=environment,
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode:
            raise ws.Blocked(
                "Git publication candidate validation failed: "
                + result.stdout
                + result.stderr
            )


def validate_snapshot(root, stage, base, tree, task_file):
    with tasks.selected_task(stage, task_file):
        require_observation_delta(stage, base)
        task = tasks.task_snapshot(stage, executable=False)
        changed = wt.paths(
            stage, "diff", "--no-renames", "--name-only", "-z", base, tree
        )
        if task.status == "completed":
            start = ws.deploy_start_commit(root, task_file, required=True)
            changed |= wt.paths(
                root, "diff", "--no-renames", "--name-only", "-z", start, "HEAD"
            )
        candidate = wt.FinalCandidate(
            stage,
            definition_root(root),
            task_file,
            task.text,
            base,
            base,
            frozenset(changed),
            task.scope,
            deploy_source_root=root,
        )
        validator = Validator(
            stage,
            set(task.scope),
            cache=False,
            definitions_root=definition_root(root),
            final_candidate=candidate,
            model_validation="change",
            iac_paths=inputs.task_deployment_input_paths(stage) if task.scope else [],
            task_iac_paths=inputs.task_deployment_input_paths(stage)
            if task.scope
            else [],
        )
        validator.run()
        return validator.display_report()


def checkpoint_source(root, state, progress, source=None):
    """Verify saved local receipts without synchronizing or committing any candidate."""
    source = source or state["tip"]
    identity = state["deployIdentity"]
    units = {unit["name"]: unit for unit in progress["runContext"]["stepUnits"]}
    context = progress["runContext"]
    final = state.get("deployPublication", {}).get("finalCandidate", {})
    final_source = final.get("source") == source
    receipts = state.get("deployCheckpoints", {})
    if final_source:
        task = tasks.read_task_snapshot(root, state["task_file"], live=True)
        if (
            task.text != final.get("taskAfter")
            or tasks.status(final.get("taskBefore", "")) != "running"
            or task.status != "completed"
            or task.task_digest != identity["taskDigest"]
            or final.get("taskAfter")
            != tasks.set_status(final["taskBefore"], "completed")
        ):
            raise ws.Blocked(
                "final source Task differs from its verified status transition"
            )
        # The complete final candidate proves its own inputs, independent of intermediate receipts.
        receipts = {
            name: {
                "commit": source,
                "tree": final.get("tree"),
                "identity": identity,
                "taskDigest": task.task_digest,
                "unit": unit,
                "inputDigest": context["inputDigests"].get(name),
                "inputs": {
                    path.relative_to(root).as_posix(): context.get(
                        "consumedInputs", {}
                    ).get(path.relative_to(root).as_posix())
                    for path in inputs.deployment_input_paths(
                        root,
                        identity["environment"],
                        context["directory"],
                        identity["target"],
                        [unit],
                    )
                },
            }
            for name, unit in units.items()
        }
    if not receipts or set(units) != set(identity["stacks"]):
        raise ws.Blocked("Git publication requires saved checkpoint evidence")
    for name, entry in receipts.items():
        if (
            name not in units
            or entry.get("identity") != identity
            or entry.get("taskDigest") != identity["taskDigest"]
            or entry.get("unit") != units[name]
            or not entry.get("inputDigest")
            or entry["inputDigest"] != progress["runContext"]["inputDigests"].get(name)
            or (
                entry["commit"] != state["tip"]
                and not wt.ancestor(root, entry["commit"], state["branch"])
            )
            or entry.get("tree")
            != wt.output(root, "rev-parse", entry["commit"] + "^{tree}")
        ):
            raise ws.Blocked(
                "saved checkpoint Task/Target/Stack evidence changed: " + name
            )
        paths = inputs.deployment_input_paths(
            root,
            identity["environment"],
            progress["runContext"]["directory"],
            identity["target"],
            [units[name]],
        )
        manifest = entry.get("inputs", {})
        if (
            set(manifest) != {p.relative_to(root).as_posix() for p in paths}
            or inputs.fingerprint(
                [manifest[p.relative_to(root).as_posix()] for p in paths]
            )
            != entry["inputDigest"]
        ):
            raise ws.Blocked("saved checkpoint input manifest changed: " + name)
        for relative, digest in manifest.items():
            if (
                inputs.file_digest({}, tasks.safe_path(root, relative), fresh=True)
                != digest
                or hashlib.sha256(
                    ws.subprocess_bytes(root, entry["commit"], relative)
                ).hexdigest()
                != digest
            ):
                raise ws.Blocked("saved checkpoint inputs changed: " + relative)
    if source not in {entry["commit"] for entry in receipts.values()}:
        raise ws.Blocked("publication source is not a saved checkpoint commit")
    return source
