"""Checkpoint Deploy outputs and publish only their snapshot delta under the Git lock."""

import copy
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

from deploy import worktree


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
        source = checkpoint(root, path, state)
        task = tasks.read_task_snapshot(root, state["task_file"], live=True)
        publication = state.setdefault(
            "deployPublication",
            {"publishedSource": state["start"], "status": "PENDING"},
        )
        if automatic and publication["status"] == "CONFLICT":
            publication["pendingSource"] = source
            wt.save(path, state)
            return copy.deepcopy(publication)
        base_root = wt.base_worktree(primary, state)
        latest = wt.output(base_root, "rev-parse", "HEAD")
        intent = publication.get("intent")
        if intent:
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
            return copy.deepcopy(publication)
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
                return copy.deepcopy(publication)
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
            or wt.changed_paths(root)
            or tasks.read_task_snapshot(root, task.name, live=True).raw != task.raw
        ):
            raise ws.Blocked(
                "Git publication inputs changed during candidate validation"
            )
        if tree == wt.output(root, "rev-parse", latest + "^{tree}") and wt.ancestor(
            root, source, state["base"]
        ):
            publication.update(status="SUCCESS", publishedSource=source, commit=latest)
            wt.save(path, state)
            return copy.deepcopy(publication)
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
        return copy.deepcopy(publication)


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
        context["gitPublication"] = {"status": "PENDING", "error": str(error)}
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
        return {"status": "PENDING", "error": str(error)}


def finalize(where, task_id):
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
