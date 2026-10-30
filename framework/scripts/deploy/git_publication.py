"""Checkpoint Deploy outputs and publish only their snapshot delta under the Git lock."""

import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import task_contract_core as tasks
import worktree_state as ws
import worktree_task as wt
from model.format import parse
from model.observed import verify_observed_outputs
from utils.aws_mappings import definition_root
from validation.runner import Validator

from deploy import contracts, inputs, worktree


def check_scope(root, task_file):
    interpreter, environment = wt.python_env.runtime(root)
    result = subprocess.run(
        [
            str(interpreter),
            "-B",
            "-c",
            f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); "
            "from pathlib import Path; from validation.findings import Findings; "
            "from validation.task import TaskValidation; from task_contract_core import selected_task; "
            "from deploy.git_publication import require_observation_delta; from worktree_state import deploy_start_commit; "
            "root=Path.cwd()\n"
            "with selected_task(root, sys.argv[1]):\n"
            " require_observation_delta(root, deploy_start_commit(root, sys.argv[1], required=True))\n"
            " f=Findings(root); t=TaskValidation(root,f); t.check_task_scope(); t.check_task_type_requirements()\n"
            " if f.errors: raise ValueError('; '.join(f.errors))",
            task_file,
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise ws.Blocked(
            "Deploy checkpoint scope/Model check failed: "
            + result.stderr
            + result.stdout
        )


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


def checkpoint(root, path, state):
    task = tasks.read_task_snapshot(root, state["task_file"], live=True)
    worktree.require(root, task)
    changed = wt.changed_paths(root)
    if not changed and not state.get("deployCheckpointIntent"):
        return wt.output(root, "rev-parse", "HEAD")
    before = {
        p: tasks.safe_path(root, p).read_bytes() if (root / p).is_file() else None
        for p in changed
    }
    check_scope(root, state["task_file"])
    wt._run_model_guard(root, state["task_file"])
    if (
        changed != wt.changed_paths(root)
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
        or wt.changed_paths(root)
    ):
        raise ws.Blocked("Deploy checkpoint differs from its saved intent")
    state["tip"] = head
    state.pop("deployCheckpointIntent", None)
    wt.save(path, state)
    return head


def blob(root, revision, relative):
    result = wt.git(root, "show", revision + ":" + relative, check=False)
    return result.stdout if not result.returncode else None


def conflicts(root, baseline, base, source, files):
    result = []
    for relative in files:
        record = {
            "path": relative,
            "base": base,
            "source": source,
            "snapshot": baseline,
            "impact": {"gitPublication": "BLOCKED", "awsEvidence": "RETAINED"},
        }
        if relative.startswith("model/") and relative.endswith(".properties"):
            versions = [blob(root, rev, relative) for rev in (baseline, base, source)]
            old, current, deployed = [
                parse(raw).values if raw is not None else {} for raw in versions
            ]
            record["items"] = [
                {
                    "key": key,
                    "snapshot": old.get(key),
                    "base": current.get(key),
                    "deployed": deployed.get(key),
                }
                for key in sorted(old.keys() | deployed.keys())
                if old.get(key) != deployed.get(key) and key.startswith("observed.")
            ]
        result.append(record)
    return result


def validate_candidate(root, tree, base, task):
    """Use the existing scoped validator on a disposable Git snapshot, never on main."""
    interpreter, environment = wt.python_env.runtime(root)
    with tempfile.TemporaryDirectory(
        prefix="blueprint-deploy-publication-"
    ) as directory:
        stage = Path(directory) / "repository"
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
        task = tasks.task_snapshot(stage)
        candidate = wt.FinalCandidate(
            stage,
            definition_root(root),
            task_file,
            task.text,
            base,
            base,
            frozenset(
                wt.paths(stage, "diff", "--no-renames", "--name-only", "-z", base, tree)
            ),
            task.scope,
            deploy_source_root=root,
        )
        validator = Validator(
            stage,
            set(task.scope),
            cache=False,
            definitions_root=definition_root(root),
            final_candidate=candidate,
        )
        validator.run()
        return validator.report()


def resolved_tree(root, base, source, publication, resolution):
    resolution = Path(resolution)
    if not resolution.is_absolute() or resolution.resolve().is_relative_to(
        ws.repository(root)[2]
    ):
        raise ws.Blocked(
            "Git conflict resolution must be an external absolute JSON path"
        )
    document = json.loads(resolution.read_text(encoding="utf-8"))
    if (
        not isinstance(document.get("approval"), str)
        or not document["approval"].strip()
        or document.get("base") != base
        or document.get("source") != source
    ):
        raise ws.Blocked(
            "Git resolution requires explicit Human approval of the current base/source"
        )
    files = document.get("files", {})
    if set(files) != {r["path"] for r in publication["conflicts"]}:
        raise ws.Blocked(
            "Human resolution must name exactly the current conflicting files"
        )
    # A private index prevents conflict stages or candidate edits reaching either checkout.
    with tempfile.TemporaryDirectory(
        prefix="blueprint-deploy-resolution-"
    ) as directory:
        environment = {
            k: v
            for k, v in wt.python_env.runtime(root)[1].items()
            if not k.startswith("GIT_")
        }
        environment["GIT_INDEX_FILE"] = str(Path(directory) / "index")
        command = ["git", "read-tree", publication["conflictTree"]]
        subprocess.run(
            command, cwd=root, env=environment, check=True, capture_output=True
        )
        for relative, text in files.items():
            tasks.safe_path(root, relative)
            mode = wt.output(root, "ls-tree", source, "--", relative).partition(" ")[0]
            if mode not in {"100644", "100755"} or not isinstance(text, str):
                raise ws.Blocked("Git resolution requires a regular Task output file")
            if relative.startswith("infra/") and text not in {
                blob(root, base, relative),
                blob(root, source, relative),
            }:
                raise ws.Blocked(
                    "IaC conflict corrections require the authorized Implement workflow"
                )
            oid = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=root,
                input=text,
                encoding="utf-8",
                capture_output=True,
                check=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "update-index", "--add", "--cacheinfo", mode, oid, relative],
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
            )
        tree = subprocess.run(
            ["git", "write-tree"],
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout.strip()
    return tree


def checkpoint_source(root, state, progress, source=None):
    """Verify saved local receipts without synchronizing or committing any candidate."""
    source = source or state["tip"]
    identity = state["deployIdentity"]
    units = {unit["name"]: unit for unit in progress["stepUnits"]}
    receipts = state.get("deployCheckpoints", {})
    if not receipts or set(units) != set(identity["stacks"]):
        raise ws.Blocked(
            "Stepwise publication requires saved Stack checkpoint evidence"
        )
    for name, entry in receipts.items():
        if (
            name not in units
            or entry.get("identity") != identity
            or entry.get("taskDigest") != identity["taskDigest"]
            or entry.get("unit") != units[name]
            or not entry.get("inputDigest")
            or entry["inputDigest"] != progress["inputDigests"].get(name)
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
            progress["directory"],
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
    if source in {entry["commit"] for entry in receipts.values()}:
        return source
    final = state.get("deployTaskCheckpoint", {})
    if final.get("commit") != source:
        raise ws.Blocked("publication source is not a saved checkpoint commit")
    task = tasks.read_task_snapshot(root, state["task_file"], live=True)
    if (
        final.get("parent") not in {entry["commit"] for entry in receipts.values()}
        or final.get("taskDigest") != task.task_digest
        or task.status != "completed"
        or wt.output(root, "rev-parse", source + "^") != final["parent"]
        or wt.paths(
            root, "diff", "--no-renames", "--name-only", "-z", final["parent"], source
        )
        != {task.name}
        or ws.subprocess_bytes(root, source, task.name) != task.raw
    ):
        raise ws.Blocked("publication source is not a saved checkpoint commit")
    return source


def require_checkpoint_intent(root, state, progress, intent):
    checkpoint_source(root, state, progress, intent["source"])
    if wt.output(root, "rev-list", "--parents", "-1", intent["commit"]).split() != [
        intent["commit"],
        intent["base"],
        intent["source"],
    ]:
        raise ws.Blocked("Git publication intent differs from its saved checkpoint")


def describe(root, state, progress, error=None):
    """Expose only proven Git recovery operations; this function performs no saves."""
    result = copy.deepcopy(state.get("deployPublication", {"status": "PENDING"}))
    result["nextActions"] = []
    result["retryable"] = False
    if error is not None:
        result["error"] = str(error)
    if progress is None or type(progress.get("stepwise")) is not bool:
        result.update(
            status="PENDING",
            requiresReview=True,
            reason="Deploy publication mode has no durable evidence",
        )
        return result
    if not progress["stepwise"]:
        return result
    pending = progress.get("checkpointPending")
    result["identity"] = copy.deepcopy(progress["identity"])
    result["checkpointRequired"] = pending["stacks"] if pending else []
    result["checkpoints"] = [
        {
            "stack": name,
            "commit": entry["commit"],
            "inputDigest": entry.get("inputDigest"),
            "tree": entry.get("tree"),
        }
        for name, entry in state.get("deployCheckpoints", {}).items()
    ]
    if result["status"] == "CONFLICT":
        result.update(
            requiresReview=True,
            humanApprovalRequired=True,
            reason="Git conflicts require explicit Human judgment; AWS success is retained",
        )
        result["nextActions"] = [
            {
                "action": "review-publication-conflict",
                "command": None,
                "humanApprovalRequired": True,
                "base": result.get("base"),
                "source": result.get("source"),
                "conflicts": result.get("conflicts", []),
            }
        ]
        return result
    try:
        if state.get("deployCheckpointIntent"):
            raise ws.Blocked(
                "finish the saved checkpoint operation before Git publication"
            )
        source = checkpoint_source(root, state, progress)
        result["pendingSource"] = source
        if (
            result.get("publishedSource") == source
            and result.get("commit")
            and wt.ancestor(root, result["commit"], state["base"])
        ):
            result.update(status="SUCCESS")
            result.pop("pendingSource", None)
            result.pop("error", None)
            return result
        if (
            pending
            and not set(pending["stacks"]) <= state.get("deployCheckpoints", {}).keys()
        ):
            raise ws.Blocked(
                "finish the pending Stack checkpoint before Git publication"
            )
        # A dirty/unavailable base or an inconsistent retained intent needs review before retry.
        base_root = wt.base_worktree(root, state)
        intent = result.get("intent")
        if intent:
            require_checkpoint_intent(root, state, progress, intent)
        if (
            intent
            and wt.output(base_root, "rev-parse", "HEAD") != intent["base"]
            and not wt.ancestor(root, intent["commit"], state["base"])
        ):
            raise ws.Blocked(
                "base changed during pending Git publication; review retained intent"
            )
        result.update(status="PENDING", retryable=True, requiresReview=False)
        result["nextActions"] = [
            {
                "action": "deploy-publish",
                "command": [
                    "python3",
                    "-B",
                    "framework/scripts/worktree_task.py",
                    "deploy-publish",
                    "--task-id",
                    state["task_id"],
                ],
                "cwd": str(root),
                "source": source,
            }
        ]
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as problem:
        result.update(status="PENDING", requiresReview=True, reason=str(problem))
    return result


def publish(where, task_id, resolution=None, *, automatic=False):
    primary, _, path, state = wt.load(where, task_id)
    root = Path(state["worktree"])
    with wt.lifecycle_lock(primary):
        state = wt.load(primary, task_id)[3]
        worktree.require(
            root, tasks.read_task_snapshot(root, state["task_file"], live=True)
        )
        progress = worktree.read_progress(root, state)
        if progress is None:
            raise ws.Blocked("Git publication requires signed Deploy progress")
        if type(progress.get("stepwise")) is not bool:
            raise ws.Blocked(
                "Git publication requires a persisted Deploy mode; review original Task evidence"
            )
        stepwise = progress["stepwise"]
        if stepwise and state.get("deployCheckpointIntent"):
            raise ws.Blocked(
                "finish the saved checkpoint operation before Git publication"
            )
        source = (
            checkpoint_source(root, state, progress)
            if stepwise
            else checkpoint(root, path, state)
        )
        snapshot = contracts.validation_snapshot(root) if stepwise else None
        index = wt.output(root, "write-tree") if stepwise else None
        task = tasks.read_task_snapshot(root, state["task_file"], live=True)
        publication = state.setdefault(
            "deployPublication",
            {"publishedSource": state["start"], "status": "PENDING"},
        )
        if automatic and publication["status"] == "CONFLICT":
            publication["pendingSource"] = source
            wt.save(path, state)
            return describe(root, state, progress)
        base_root = wt.base_worktree(primary, state)
        latest = wt.output(base_root, "rev-parse", "HEAD")
        intent = publication.get("intent")
        if intent:
            if stepwise:
                require_checkpoint_intent(root, state, progress, intent)
            if latest == intent["commit"] or wt.ancestor(
                primary, intent["commit"], state["base"]
            ):
                publication.update(
                    status="SUCCESS",
                    publishedSource=intent["source"],
                    commit=intent["commit"],
                )
                publication.pop("intent")
                wt.save(path, state)
            elif latest != intent["base"]:
                raise ws.Blocked(
                    "base changed during pending Git publication; review retained intent"
                )
            else:
                wt.git(
                    base_root, "merge", "--ff-only", "--no-autostash", intent["commit"]
                )
                publication.update(
                    status="SUCCESS",
                    publishedSource=intent["source"],
                    commit=intent["commit"],
                )
                publication.pop("intent")
                wt.save(path, state)
        latest = wt.output(base_root, "rev-parse", "HEAD")
        baseline = publication["publishedSource"]
        if publication.get("commit") and not wt.ancestor(
            primary, publication["commit"], state["base"]
        ):
            baseline = state["start"]
        elif source == baseline and publication.get("commit"):
            return describe(root, state, progress)
        merged = wt.git(
            root,
            "merge-tree",
            "--write-tree",
            "--name-only",
            "-z",
            "--merge-base=" + baseline,
            latest,
            source,
            check=False,
        )
        parts = merged.stdout.split("\0")
        tree = parts[0]
        if merged.returncode not in {0, 1} or not tree:
            raise ws.Blocked("cannot prepare Git publication: " + merged.stderr)
        if merged.returncode or publication["status"] == "CONFLICT":
            names = parts[1 : parts.index("", 1)] if merged.returncode else []
            publication.update(
                status="CONFLICT",
                base=latest,
                source=source,
                conflictTree=tree,
                conflicts=conflicts(root, baseline, latest, source, names),
            )
            wt.save(path, state)
            if resolution is None:
                return describe(root, state, progress)
            tree = resolved_tree(root, latest, source, publication, resolution)
        changed = wt.paths(
            root, "diff", "--no-renames", "--name-only", "-z", latest, tree
        )
        task_paths = wt.paths(
            root, "diff", "--no-renames", "--name-only", "-z", baseline, source
        )
        if changed - task_paths:
            raise ws.Blocked("Git publication includes changes outside this Task delta")
        validate_candidate(root, tree, latest, task)
        if (
            wt.output(base_root, "rev-parse", "HEAD") != latest
            or wt.changed_paths(base_root)
            or wt.output(root, "rev-parse", "HEAD") != source
            or (
                contracts.validation_snapshot(root) != snapshot
                or wt.output(root, "write-tree") != index
                if stepwise
                else wt.changed_paths(root)
            )
            or tasks.read_task_snapshot(root, task.name, live=True).raw != task.raw
            or worktree.read_progress(root, state) != progress
        ):
            raise ws.Blocked(
                "Git publication inputs changed during candidate validation"
            )
        if tree == wt.output(root, "rev-parse", latest + "^{tree}") and wt.ancestor(
            root, source, state["base"]
        ):
            publication.update(status="SUCCESS", publishedSource=source, commit=latest)
            wt.save(path, state)
            return describe(root, state, progress)
        # An explicit merge parent preserves the fixed Task branch for ordinary safe cleanup.
        # The tree contains only the reviewed delta; no old Task history is rebased.
        candidate = wt.output(
            root,
            "commit-tree",
            tree,
            "-p",
            latest,
            "-p",
            source,
            "-m",
            f"task({task_id}): publish Deploy observations",
        )
        publication["intent"] = dict(base=latest, source=source, commit=candidate)
        wt.save(path, state)
        wt.git(base_root, "merge", "--ff-only", "--no-autostash", candidate)
        if wt.output(base_root, "rev-parse", "HEAD") != candidate:
            raise ws.Blocked("Git publication merge differs from its exact candidate")
        publication.update(status="SUCCESS", publishedSource=source, commit=candidate)
        for key in ("intent", "conflicts", "conflictTree", "pendingSource", "error"):
            publication.pop(key, None)
        wt.save(path, state)
        return describe(root, state, progress)


def retained(root, task_id, error):
    try:
        state = wt.load(root, task_id)[3]
        return describe(root, state, worktree.read_progress(root, state), error)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as problem:
        return {
            "status": "PENDING",
            "retryable": False,
            "requiresReview": True,
            "error": str(error),
            "reason": str(problem),
            "nextActions": [],
        }


def sync(backend):
    if getattr(backend, "phase", None) != "deploy":
        return
    context = backend.run_context
    try:
        context["gitPublication"] = publish(
            backend.root, Path(context["taskFile"]).stem, automatic=True
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        # Git must never change AWS SUCCESS or block another independent Stack's Model save.
        context["gitPublication"] = retained(
            backend.root, Path(context["taskFile"]).stem, error
        )
    backend.save()


def retry(root, task):
    state = worktree.require(root, task)
    if worktree.read_progress(root, state) is None:
        return None
    try:
        return publish(root, state["task_id"], automatic=True)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        return retained(root, state["task_id"], error)


def task_checkpoint(root, path, state, task, progress):
    """Resume a legacy contract-only candidate; ordinary sync already includes completion."""
    if progress.get("stepwise") is not True:
        return
    if (
        task.status == "completed"
        and not wt.changed_paths(root)
        and not state.get("deployCheckpointIntent")
    ):
        checkpoint_source(root, state, progress)
        return
    if (
        task.status != "completed"
        or progress.get("checkpointPending")
        or progress["pendingObserved"]
        or progress["pendingGeneration"]
        or any(not saved.get("observedSynced") for saved in progress["states"].values())
        or wt.changed_paths(root) - {task.name}
    ):
        raise ws.Blocked(
            "final Deploy checkpoint requires completed Stack barriers and only its contract change"
        )
    final = state.get("deployTaskCheckpoint")
    if final and final.get("commit") == state["tip"]:
        checkpoint_source(root, state, progress)
        return
    parent = final["parent"] if final else state["tip"]
    checkpoint_source(root, state, progress, parent)
    publication = state.get("deployPublication", {})
    if (
        publication.get("status") != "SUCCESS"
        or publication.get("publishedSource") != parent
        or not wt.ancestor(root, publication["commit"], state["base"])
    ):
        raise ws.Blocked("publish all Stack checkpoints before final Task commit")
    raw_hash = hashlib.sha256(task.raw).hexdigest()
    expected = {"parent": parent, "taskDigest": task.task_digest, "rawHash": raw_hash}
    if final is not None and final != expected:
        raise ws.Blocked("final Task checkpoint differs from its saved intent")
    state["deployTaskCheckpoint"] = expected
    wt.save(path, state)
    intent = state.get("deployCheckpointIntent")
    if intent and wt.paths(
        root, "diff", "--no-renames", "--name-only", "-z", parent, intent["tree"]
    ) != {task.name}:
        raise ws.Blocked("final Task checkpoint intent contains non-contract changes")
    commit = checkpoint(root, path, state)
    if commit == parent:
        state.pop("deployTaskCheckpoint")
    else:
        expected["commit"] = commit
        checkpoint_source(root, state, progress)
    wt.save(path, state)


def finalize(where, task_id):
    primary, _, path, state = wt.load(where, task_id)
    with wt.lifecycle_lock(primary):
        state = wt.load(primary, task_id)[3]
        root = Path(state["worktree"])
        task = tasks.read_task_snapshot(root, state["task_file"], live=True)
        if task.status != "completed":
            raise ws.Blocked("Deploy Task must complete its validation before cleanup")
        worktree.require(root, task)
        progress = worktree.read_progress(root, state)
        if progress is None:
            raise ws.Blocked("final Deploy checkpoint requires signed progress")
        task_checkpoint(root, path, state, task, progress)
    result = publish(where, task_id)
    if result["status"] != "SUCCESS":
        raise ws.Blocked("Deploy Git publication requires Human conflict review")
    primary, _, path, state = wt.load(where, task_id)
    with wt.lifecycle_lock(primary):
        root = Path(state["worktree"])
        task = tasks.read_task_snapshot(root, state["task_file"], live=True)
        if task.status != "completed":
            raise ws.Blocked("Deploy Task must complete its validation before cleanup")
        worktree.require_complete(root, task)
        if result["publishedSource"] != state["tip"] or not wt.ancestor(
            primary, result["commit"], state["base"]
        ):
            raise ws.Blocked("Deploy publication changed before cleanup")
        state.update(commit=state["tip"], verified=True, merged=result["commit"])
        wt.save(path, state)
        return state
