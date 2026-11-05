"""Explicit Deploy and update checkpoints, including private completed candidates."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import task_contract_core as tasks
import worktree_task as wt
from contracts.validation import VALIDATION_FAIL, VALIDATION_PASS
from deploy import contracts, git_publication, inputs, worktree
from deploy.cli_guidance import DeployStepBlocked
from model.observed import verify_observed_outputs
from model.sources import source_scope
from utils.aws_mappings import definition_root
from validation.findings import Findings
from validation.runner import Validator
from validation.task import TaskValidation


def validate(
    backend: SimpleNamespace, *, scope_checked=False, changed=None, task_paths=None
) -> None:
    """Use existing scoped Model/view checks, without completing the running Task."""
    root = backend.root
    findings = Findings(root)
    final_candidate = None
    if task_paths is not None:
        task = tasks.read_task_snapshot(
            root, backend.run_context["taskFile"], live=True
        )
        head = wt.output(root, "rev-parse", "HEAD")
        final_candidate = wt.FinalCandidate(
            root,
            definition_root(root),
            task.name,
            task.text,
            head,
            head,
            frozenset(wt.changed_paths(root) | task_paths),
            task.scope,
        )
    checks = TaskValidation(root, findings, final_candidate=final_candidate)
    if not scope_checked:
        checks.check_task_scope()
        checks.check_task_type_requirements()
    if findings.errors:
        raise DeployStepBlocked(
            "checkpoint Task authority: " + "; ".join(findings.errors)
        )
    if changed is None:
        changed = wt.changed_paths(root)
    sources = {p for p in changed if p.startswith("model/")}
    if sources:
        verify_observed_outputs(
            {root / p: wt.subprocess_bytes(root, "HEAD", p) for p in sources},
            {root / p: (root / p).read_text(encoding="utf-8") for p in sources},
        )
    scopes = {
        tuple(p.split("/")[2:4]) + (p.split("/")[4].removesuffix(".md"),)
        for p in backend.run_context["checkpointPending"]["after"]
        if p.startswith("docs/designs/") and p.endswith(".md") and p in changed
    }
    scopes.update(
        (backend.environment, backend.directory, service)
        for name in backend.run_context["checkpointPending"]["stacks"]
        for service in backend.states[name].get("observedServices", [])
    )
    for relative in sources:
        source = source_scope(root, root / relative)
        scopes.add((source.environment, source.target, source.service))
    if scopes:
        validator = Validator(
            root,
            scopes,
            cache=False,
            model_validation="change",
            final_candidate=final_candidate,
        )
        validator.run()
        if validator.report():
            validator.display_report()
            raise DeployStepBlocked("checkpoint scoped Model/view validation failed")


def checkpoint(backend: SimpleNamespace, names: list[str]) -> dict:
    if backend.phase == "deploy":
        return snapshot_checkpoint(backend, names)
    if backend.phase != "update":
        raise DeployStepBlocked(
            "checkpoint requires the current deploy or update phase"
        )
    return update_checkpoint(backend, names)


def verify_update_receipts(root, target, state, context, names, receipts, text, states):
    """Verify retained Update evidence and exact Model/View content without base ancestry."""
    base = wt.base_worktree(root, state)
    latest = wt.output(base, "rev-parse", "HEAD")
    head = wt.output(target, "rev-parse", "HEAD")
    if any(p.startswith(("model/", "docs/designs/")) for p in wt.changed_paths(target)):
        raise DeployStepBlocked(
            "checkpoint Model/View has unsaved changes; retain candidate"
        )
    units = {unit["name"]: unit for unit in context["stepUnits"]}
    for name in names:
        receipt = receipts[name]
        if (
            receipt.get("taskDigest") != tasks.task_digest(text)
            or receipt.get("taskDigest") != context.get("taskDigest")
            or name not in context["inputDigests"]
            or receipt.get("inputDigest") != context["inputDigests"][name]
            or name not in units
            or receipt.get("unit") != units[name]
            or receipt.get("stackId") != states[name].get("stackId")
            or receipt.get("stackStatus") != states[name].get("stackStatus", "UNKNOWN")
            or receipt.get("deployStatus") != states[name].get("status")
            or receipt.get("coverage") != states[name].get("observedCoverage", {})
            or receipt.get("services") != states[name].get("observedServices", [])
        ):
            raise DeployStepBlocked(
                "checkpoint receipt Task, Stack or input evidence differs"
            )
        commit = receipt.get("commit")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise DeployStepBlocked("checkpoint receipt has no valid commit")
        for revision in (latest, head):
            result = wt.git(
                target,
                "diff",
                "--quiet",
                "--no-ext-diff",
                commit,
                revision,
                "--",
                "model/",
                "docs/designs/",
                check=False,
            )
            if result.returncode:
                raise DeployStepBlocked(
                    "checkpoint Model/View content cannot be verified"
                )
    if (
        wt.output(base, "rev-parse", "HEAD") != latest
        or wt.output(target, "rev-parse", "HEAD") != head
    ):
        raise DeployStepBlocked(
            "checkpoint base or Task changed during receipt verification"
        )


def update_task_iac_paths(target, state, task, context):
    """Recover only Task-owned IaC changes backed by the existing checkpoint receipt."""
    paths = wt.committed_task_paths(target, task.name)
    if paths is None:
        raise DeployStepBlocked("checkpoint requires a managed Task boundary")
    iac = {p for p in paths if p.startswith("infra/")}
    units = {unit["name"]: unit for unit in context["stepUnits"]}
    for name, receipt in state.get("deployCheckpoints", {}).items():
        base = receipt.get("taskBase")
        source = receipt.get("taskHead")
        if base is None and source is None:
            continue
        if (
            receipt.get("taskDigest") != task.task_digest
            or receipt.get("taskDigest") != context.get("taskDigest")
            or name not in units
            or receipt.get("unit") != units[name]
            or name not in context["inputDigests"]
            or receipt.get("inputDigest") != context["inputDigests"][name]
            or not isinstance(base, str)
            or not re.fullmatch(r"[0-9a-f]{40,64}", base)
            or not isinstance(source, str)
            or not re.fullmatch(r"[0-9a-f]{40,64}", source)
            or wt.git(
                target, "merge-base", "--is-ancestor", base, source, check=False
            ).returncode
        ):
            raise DeployStepBlocked("checkpoint Task IaC evidence is invalid")
        owned = {
            p
            for p in wt.paths(
                target, "diff", "--no-renames", "--name-only", "-z", base, source
            )
            if p.startswith("infra/")
        }
        if owned & wt.paths(
            target, "diff", "--no-renames", "--name-only", "-z", source, "HEAD"
        ):
            raise DeployStepBlocked(
                "checkpoint Task IaC evidence differs from current inputs"
            )
        declared = tasks.paths_in(task.text, "## Modified files")
        allowed = tasks.paths_in(task.text, "## Allowed paths")
        if owned - declared or any(
            not any(tasks.matches(p, pattern) for pattern in allowed) for p in owned
        ):
            raise DeployStepBlocked("checkpoint Task IaC evidence exceeds Task scope")
        iac.update(owned)
    return iac


def validate_update_candidate(target, tree, base, task, context):
    """Validate the latest-base Model/View candidate with the proven Task changes."""
    state = wt.load(target, Path(task.name).stem)[3]
    task_paths = update_task_iac_paths(target, state, task, context)
    with tempfile.TemporaryDirectory(
        prefix="blueprint-update-checkpoint-"
    ) as directory:
        stage = Path(directory).resolve() / "repository"
        wt.git(
            target,
            "clone",
            "--quiet",
            "--shared",
            "--no-checkout",
            str(target),
            str(stage),
        )
        wt.git(stage, "checkout", "--quiet", "--detach", base)
        wt.git(stage, "read-tree", "--reset", "-u", tree)
        destination = stage / task.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(task.raw)
        with tasks.selected_task(stage, task.name):
            git_publication.require_observation_delta(stage, base)
            changed = (
                wt.paths(stage, "diff", "--no-renames", "--name-only", "-z", base, tree)
                | task_paths
            )
            candidate = wt.FinalCandidate(
                stage,
                definition_root(target),
                task.name,
                task.text,
                base,
                base,
                frozenset(changed),
                task.scope,
                deploy_source_root=target,
            )
            deployment_paths = (
                inputs.task_deployment_input_paths(stage) if task.scope else []
            )
            validator = Validator(
                stage,
                set(task.scope),
                cache=False,
                definitions_root=definition_root(target),
                final_candidate=candidate,
                model_validation="change",
                iac_paths=deployment_paths,
                task_iac_paths=deployment_paths,
            )
            validator.run()
            if validator.display_report():
                raise DeployStepBlocked(
                    "Update checkpoint latest-base candidate validation failed"
                )


def synchronize_update_candidate(
    root, target, path, state, intent, task, source, latest, context
):
    """Validate a private replay and retain its intent before moving the Task branch."""
    sync = intent.get("sync")
    if sync is None:
        for relative, expected in context.get("consumedInputs", {}).items():
            try:
                actual = hashlib.sha256(
                    wt.subprocess_bytes(target, latest, relative)
                ).hexdigest()
            except ValueError as error:
                raise DeployStepBlocked(
                    "checkpoint base is missing an execution input: " + relative
                ) from error
            if actual != expected:
                raise DeployStepBlocked(
                    "checkpoint base execution input differs: " + relative
                )
        old = intent["head"]
        common = wt.git(target, "merge-base", old, latest, check=False)
        if common.returncode:
            raise DeployStepBlocked(
                "checkpoint Task and base have no provable common history"
            )
        task_paths = wt.paths(
            target,
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            common.stdout.strip(),
            old,
        )
        differing = wt.paths(
            target, "diff", "--name-only", "--no-renames", "-z", old, latest
        )
        if task_paths & differing:
            raise DeployStepBlocked(
                "base does not contain the saved Task changes; retain checkpoint candidate"
            )
        synthetic = wt.output(
            target,
            "-c",
            "user.name=Blueprint verification",
            "-c",
            "user.email=blueprint-verification@invalid",
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            latest + "^{tree}",
            "-p",
            old,
            "-m",
            "Checkpoint verification",
        )
        result = wt.git(
            target, "merge-tree", "--write-tree", synthetic, source, check=False
        )
        if result.returncode or not result.stdout.splitlines():
            raise DeployStepBlocked(
                "checkpoint conflicts with latest base; retain checkpoint candidate"
            )
        tree = result.stdout.splitlines()[0]
        if not re.fullmatch(r"[0-9a-f]{40,64}", tree):
            raise DeployStepBlocked("cannot determine checkpoint candidate tree")
        validate_update_candidate(target, tree, latest, task, context)
        if (
            wt.output(target, "rev-parse", "HEAD") != source
            or wt.changed_paths(target)
            or wt.output(wt.base_worktree(root, state), "rev-parse", "HEAD") != latest
        ):
            raise DeployStepBlocked(
                "checkpoint or base changed during candidate validation"
            )
        sync = intent["sync"] = {"base": latest, "source": source, "tree": tree}
        wt.save(path, state)
    if sync["base"] != latest:
        raise DeployStepBlocked(
            "base changed during checkpoint synchronization; retain candidate"
        )
    head = wt.output(target, "rev-parse", "HEAD")
    if head == sync["source"]:
        wt.idle_git(target)
        result = wt.git(
            target,
            "-c",
            "rebase.updateRefs=false",
            "rebase",
            "--no-autostash",
            "--no-fork-point",
            "--reapply-cherry-picks",
            "--empty=keep",
            "--onto",
            latest,
            intent["head"],
            check=False,
        )
        if result.returncode:
            raise DeployStepBlocked(
                "checkpoint rebase failed; retain candidate and Git operation: "
                + (result.stderr.strip() or result.stdout.strip())
            )
        head = wt.output(target, "rev-parse", "HEAD")
    wt.idle_git(target)
    if (
        wt.changed_paths(target)
        or wt.output(target, "rev-parse", "HEAD^{tree}") != sync["tree"]
    ):
        raise DeployStepBlocked("checkpoint replay differs from validated candidate")
    if sync["source"] == intent["head"]:
        if head != latest:
            raise DeployStepBlocked("empty checkpoint replay differs from base")
    else:
        old_parent, new_parent = wt.verify_rebase_commits(
            target, [sync["source"]], [head], intent["head"], latest
        )
        if old_parent != sync["source"] or new_parent != head:
            raise DeployStepBlocked(
                "checkpoint replay history differs from saved intent"
            )
    return head


def update_checkpoint(backend: SimpleNamespace, names: list[str]) -> dict:
    root, _, path, state = wt.load(backend.root, backend.root.name)
    target = wt.task_worktree(root, state)
    context = backend.run_context
    pending = context.get("checkpointPending")
    if target != backend.root or not names or len(names) != len(set(names)):
        raise DeployStepBlocked(
            "checkpoint needs exact managed Task and distinct StackNames"
        )
    with wt.lifecycle_lock(root):
        root, _, path, state = wt.load(root, backend.root.name)
        if wt.task_worktree(root, state) != target:
            raise DeployStepBlocked("checkpoint Task ownership changed")
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        if (
            tasks.status(text) != "running"
            or state.get("merged")
            or state.get("deployRepair")
            or state.get("iacRepair", {}).get("requestPath")
            or state.get("python_setup", {}).get("status") != "ready"
            or path.with_suffix(".setup-lock").exists()
        ):
            raise DeployStepBlocked(
                "normal checkpoint requires ready running Deploy Task"
            )
        backend.guard()
        receipts = state.setdefault("deployCheckpoints", {})
        intent = state.get("stackCheckpointIntent")
        if not pending:
            if intent:
                raise DeployStepBlocked(
                    "checkpoint intent remains without its candidate"
                )
            if all(n in receipts for n in names):
                verify_update_receipts(
                    root, target, state, context, names, receipts, text, backend.states
                )
                return {n: receipts[n] for n in names}
            raise DeployStepBlocked(
                "no synchronized checkpoint candidate for requested Stacks"
            )
        if set(names) != set(pending["stacks"]) or pending.get("after") is None:
            raise DeployStepBlocked(
                "checkpoint must include the complete synchronized candidate"
            )
        if (
            context.get("pendingObserved")
            or context.get("pendingGeneration")
            or context.get("generationError")
        ):
            raise DeployStepBlocked(
                "required generation remains pending; inspect pendingGeneration"
            )
        if any(not backend.states[n].get("observedSynced") for n in names):
            raise DeployStepBlocked(
                "checkpoint requires a complete adopted observation for every selected Stack"
            )
        if (
            not intent
            and all(n in receipts for n in names)
            and not wt.changed_paths(target)
        ):
            verify_update_receipts(
                root, target, state, context, names, receipts, text, backend.states
            )
            changed = {
                p
                for p in pending["before"].keys() | pending["after"].keys()
                if pending["before"].get(p) != pending["after"].get(p)
            }
            for name in names:
                for relative in changed:
                    try:
                        actual = hashlib.sha256(
                            wt.subprocess_bytes(
                                target, receipts[name]["commit"], relative
                            )
                        ).hexdigest()
                    except ValueError:
                        actual = None
                    if actual != pending["after"].get(relative):
                        raise DeployStepBlocked(
                            "checkpoint receipt cannot prove the pending candidate"
                        )
            for name in names:
                backend.states[name].pop("checkpointRequired", None)
                backend.states[name]["checkpointed"] = True
            context.pop("checkpointPending", None)
            backend.save()
            return {name: receipts[name] for name in names}
        if (
            not (intent and intent.get("sync"))
            and contracts.validation_snapshot(target) != pending["after"]
        ):
            raise DeployStepBlocked("checkpoint candidate changed after sync")
        base = wt.base_worktree(root, state)
        wt.idle_git(target)
        head = wt.output(target, "rev-parse", "HEAD")
        latest = wt.output(base, "rev-parse", "HEAD")
        if intent is None:
            inherited = wt.paths(
                target, "diff", "--name-only", "--no-renames", "-z", latest, head
            )
            repair = state.get("iacRepair", {})
            delegated = (
                (
                    repair.get("commit") == head
                    and repair.get("parentTip") == latest
                    and contracts.accepted_changes(target, text, inherited) == inherited
                )
                if latest != head
                else False
            )
            if head != state["tip"]:
                raise DeployStepBlocked(
                    "Task has unexpected commits; retain checkpoint candidate"
                )
            changed = wt.changed_paths(target)
            expected = {
                p
                for p in pending["before"].keys() | pending["after"].keys()
                if pending["before"].get(p) != pending["after"].get(p)
            }
            if changed != expected or any(
                not p.startswith(("model/", "docs/designs/")) for p in changed
            ):
                raise DeployStepBlocked(
                    "checkpoint includes changes outside synchronized Model/views"
                )
            task = tasks.read_task_snapshot(target, state["task_file"], live=True)
            task_paths = update_task_iac_paths(target, state, task, context)
            validate(backend, task_paths=task_paths)
            backend.guard()
            if (
                contracts.validation_snapshot(target) != pending["after"]
                or wt.changed_paths(target) != changed
            ):
                raise DeployStepBlocked(
                    "checkpoint candidate changed during validation"
                )
            wt.git(target, "diff", "--check")
            wt.git(target, "diff", "--cached", "--check")
            if changed:
                wt.git(
                    target,
                    "add",
                    "--",
                    *[f":(top,literal){p}" for p in sorted(changed)],
                )
            provenance = next(
                (
                    (r["taskBase"], r["taskHead"])
                    for r in receipts.values()
                    if r.get("taskBase") and r.get("taskHead")
                ),
                (wt.task_start_commit(target, state["task_file"]), head),
            )
            intent = {
                "head": head,
                "base": latest,
                "tree": wt.output(target, "write-tree"),
                "stacks": sorted(names),
                "taskDigest": context["taskDigest"],
                "candidate": copy.deepcopy(pending["after"]),
                "changed": sorted(changed),
                "delegated": delegated,
                "taskBase": provenance[0],
                "taskHead": provenance[1],
                "message": f"task({state['task_id']}): deploy checkpoint "
                + ", ".join(sorted(names)),
            }
            state["stackCheckpointIntent"] = intent
            wt.save(path, state)
        if (
            intent["stacks"] != sorted(names)
            or intent["taskDigest"] != context["taskDigest"]
            or intent["candidate"] != pending["after"]
            or not intent.get("sync")
            and wt.output(target, "write-tree") != intent["tree"]
        ):
            raise DeployStepBlocked("checkpoint intent changed; retain candidate")
        if head == intent["head"] and not intent.get("sync"):
            if latest != intent["base"] and intent.get("delegated"):
                raise DeployStepBlocked(
                    "delegated repair base changed; retain checkpoint intent"
                )
            if intent["changed"]:
                wt.git(target, "commit", "-m", intent["message"])
        commit = wt.output(target, "rev-parse", "HEAD")
        if not intent.get("sync") and (
            wt.changed_paths(target)
            or wt.output(target, "rev-parse", "HEAD^{tree}") != intent["tree"]
            or commit != intent["head"]
            and (
                wt.output(target, "rev-parse", "HEAD^") != intent["head"]
                or wt.output(target, "log", "-1", "--format=%s") != intent["message"]
            )
        ):
            raise DeployStepBlocked(
                "checkpoint commit is not the saved exact candidate"
            )
        if intent.get("sync"):
            commit = synchronize_update_candidate(
                root,
                target,
                path,
                state,
                intent,
                tasks.read_task_snapshot(target, state["task_file"], live=True),
                commit,
                intent["sync"]["base"],
                context,
            )
            if latest != intent["base"]:
                intent["head"] = intent["sync"]["base"]
                intent["tree"] = intent["sync"]["tree"]
                intent["base"] = latest
                intent.pop("sync")
        elif latest != intent["base"]:
            if intent.get("delegated"):
                raise DeployStepBlocked(
                    "delegated repair base changed; retain checkpoint candidate"
                )
            intent["base"] = latest
        if (
            not intent.get("sync")
            and intent["head"] != intent["base"]
            and not intent.get("delegated")
        ):
            commit = synchronize_update_candidate(
                root,
                target,
                path,
                state,
                intent,
                tasks.read_task_snapshot(target, state["task_file"], live=True),
                commit,
                intent["base"],
                context,
            )
        base = wt.base_worktree(root, state)
        if wt.output(base, "rev-parse", "HEAD") not in {intent["base"], commit}:
            raise DeployStepBlocked(
                "base advanced before merge; retain commit for review"
            )
        backend.guard()
        if (
            not intent.get("sync")
            and contracts.validation_snapshot(target) != intent["candidate"]
            or wt.changed_paths(target)
            or wt.output(target, "rev-parse", "HEAD") != commit
        ):
            raise DeployStepBlocked(
                "validated checkpoint changed immediately before merge"
            )
        base = wt.base_worktree(root, state)
        if wt.output(base, "rev-parse", "HEAD") not in {intent["base"], commit}:
            raise DeployStepBlocked("base changed immediately before checkpoint merge")
        if wt.output(base, "rev-parse", "HEAD") != commit:
            wt.git(base, "merge", "--ff-only", "--no-autostash", commit)
        if wt.output(base, "rev-parse", "HEAD") != commit:
            raise DeployStepBlocked("checkpoint merge differs from intended commit")
        for name in names:
            unit = next(u for u in context["stepUnits"] if u["name"] == name)
            receipts[name] = {
                "commit": commit,
                "taskDigest": context["taskDigest"],
                "taskBase": intent["taskBase"],
                "taskHead": intent["taskHead"],
                "inputDigest": context["inputDigests"].get(name),
                "unit": copy.deepcopy(unit),
                "stackId": backend.states[name].get("stackId"),
                "stackStatus": backend.states[name].get("stackStatus", "UNKNOWN"),
                "deployStatus": backend.states[name]["status"],
                "coverage": copy.deepcopy(
                    backend.states[name].get("observedCoverage", {})
                ),
                "services": backend.states[name].get("observedServices", []),
            }
        state["tip"] = commit
        if intent.get("sync"):
            state["validation_base"] = intent["base"]
        state.pop("stackCheckpointIntent", None)
        wt.save(path, state)
        # Journal acknowledgement follows the durable lifecycle receipt, so retry is idempotent.
        for name in names:
            backend.states[name].pop("checkpointRequired", None)
            backend.states[name]["checkpointed"] = True
        context.pop("checkpointPending", None)
        backend.save()
        return {n: receipts[n] for n in names}


def final_checkpoint(backend, primary, path, state, pending):
    """Validate completed bytes privately, then adopt and commit that same candidate."""
    target, context = backend.root, backend.run_context
    final = pending["final"]
    task = tasks.read_task_snapshot(target, state["task_file"], live=True)
    if (
        final.get("taskAfter")
        != tasks.set_status(final.get("taskBefore", ""), "completed")
        or tasks.status(final["taskBefore"]) != "running"
        or task.text not in {final["taskBefore"], final["taskAfter"]}
        or task.task_digest != state["deployIdentity"]["taskDigest"]
    ):
        raise DeployStepBlocked(
            "saved final Task differs from its exact running-to-completed contract"
        )
    candidate = replace(
        task,
        text=final["taskAfter"],
        raw=final["taskAfter"].encode("utf-8"),
        raw_digest=hashlib.sha256(final["taskAfter"].encode("utf-8")).hexdigest(),
    )
    blockers = worktree.final_blockers(context)
    if blockers:
        raise DeployStepBlocked("final checkpoint requires: " + json.dumps(blockers))
    if pending.get("after") is None:
        raise DeployStepBlocked(
            "finish final sync observation/generation before checkpoint"
        )
    current = contracts.validation_snapshot(target)
    if {p: v for p, v in current.items() if p != task.name} != {
        p: v for p, v in pending["after"].items() if p != task.name
    }:
        raise DeployStepBlocked("final Model/View candidate changed after sync")
    changed = git_publication.output_changes(target, state)
    expected = {
        p
        for p in pending["before"].keys() | pending["after"].keys()
        if pending["before"].get(p) != pending["after"].get(p)
    } - {task.name}
    if (
        changed - {task.name}
        and changed - {task.name} != expected
        or any(
            not p.startswith(("model/", "docs/designs/")) for p in changed - {task.name}
        )
    ):
        raise DeployStepBlocked(
            "final checkpoint includes changes outside synchronized Model/View"
        )
    backend.guard()
    head = wt.output(target, "rev-parse", "HEAD")
    index = wt.output(target, "write-tree")
    intent = copy.deepcopy(state.get("deployCheckpointIntent"))
    validated = final.get("validated")
    if validated is None:
        if task.status != "running" or head != state["tip"] or intent:
            raise DeployStepBlocked(
                "final validation requires the original running Task and source HEAD"
            )
        context["snapshotValidation"] = VALIDATION_FAIL
        backend.save()
        tree = git_publication.final_tree(target, changed, candidate)
        git_publication.validate_candidate(target, tree, head, candidate)
        if (
            tasks.read_task_snapshot(target, task.name, live=True).raw != task.raw
            or wt.output(target, "rev-parse", "HEAD") != head
            or wt.output(target, "write-tree") != index
            or contracts.validation_snapshot(target) != current
            or json.loads(path.read_text(encoding="utf-8")).get(
                "deployCheckpointIntent"
            )
            != intent
        ):
            raise DeployStepBlocked(
                "final Task/inputs/HEAD/index/candidate changed during validation"
            )
        validated = {"tree": tree, "head": head, "index": index}
        final["validated"] = validated
        context["snapshotValidation"] = VALIDATION_PASS
        backend.save()
    else:
        committed = (
            head != validated["head"]
            and wt.output(target, "rev-parse", "HEAD^") == validated["head"]
            and wt.output(target, "rev-parse", "HEAD^{tree}") == validated["tree"]
            and (
                head == state["tip"]
                or intent
                and intent["head"] == validated["head"]
                and intent["tree"] == validated["tree"]
            )
        )
        if (
            context.get("snapshotValidation") != VALIDATION_PASS
            or head != validated["head"]
            and not committed
            or index not in {validated["index"], validated["tree"]}
            or intent
            and intent["tree"] != validated["tree"]
        ):
            raise DeployStepBlocked(
                "saved final candidate HEAD/index or validation changed"
            )
    if (
        git_publication.final_tree(
            target, git_publication.output_changes(target, state), candidate
        )
        != validated["tree"]
    ):
        raise DeployStepBlocked(
            "saved final candidate bytes changed before Task adoption"
        )
    # Recheck fixed inputs and authority immediately before adopting the verified Task.
    backend.guard()
    if tasks.read_task_snapshot(target, task.name, live=True).raw != task.raw:
        raise DeployStepBlocked("final Task changed before adoption")
    if task.status == "running":
        tasks.atomic_files(
            {target / task.name: candidate.text}, staging_directory=target
        )
        tasks.invalidate_task_reads(target)
    current = contracts.validation_snapshot(target)
    preflight = {
        "task": candidate.raw,
        "head": head,
        "index": index,
        "changed": git_publication.output_changes(target, state),
        "candidate": current,
        "intent": intent,
        "tree": validated["tree"],
    }
    commit = git_publication.checkpoint(target, path, state, preflight=preflight)
    if wt.output(target, "rev-parse", commit + "^{tree}") != validated["tree"]:
        raise DeployStepBlocked("source commit differs from validated final tree")
    receipts = state.setdefault("deployCheckpoints", {})
    for name in pending["stacks"]:
        receipts[name] = checkpoint_receipt(backend, state, name, commit)
    publication = state.setdefault(
        "deployPublication",
        {"publishedSource": state["start"], "status": "PENDING"},
    )
    publication["finalCandidate"] = {
        "source": commit,
        "tree": validated["tree"],
        "taskBefore": final["taskBefore"],
        "taskAfter": final["taskAfter"],
    }
    wt.save(path, state)
    for name in pending["stacks"]:
        backend.states[name].pop("checkpointRequired", None)
        backend.states[name]["checkpointed"] = True
    context.pop("checkpointPending")
    backend.task_status = "completed"
    backend.save()
    return {name: receipts[name] for name in pending["stacks"]}


def checkpoint_receipt(backend, state, name, commit):
    context, target = backend.run_context, backend.root
    unit = next(u for u in context["stepUnits"] if u["name"] == name)
    return {
        "commit": commit,
        "identity": copy.deepcopy(state["deployIdentity"]),
        "tree": wt.output(target, "rev-parse", commit + "^{tree}"),
        "inputs": {
            p.relative_to(target).as_posix(): context["consumedInputs"][
                p.relative_to(target).as_posix()
            ]
            for p in backend.deployment_input_paths([unit])
        },
        "taskDigest": context["taskDigest"],
        "inputDigest": context["inputDigests"].get(name),
        "unit": copy.deepcopy(unit),
        "stackId": backend.states[name].get("stackId"),
        "stackStatus": backend.states[name].get("stackStatus", "UNKNOWN"),
        "deployStatus": backend.states[name]["status"],
        "coverage": copy.deepcopy(backend.states[name].get("observedCoverage", {})),
        "services": backend.states[name].get("observedServices", []),
    }


def snapshot_checkpoint(backend: SimpleNamespace, names: list[str]) -> dict:
    """Keep the existing synchronized candidate barrier, then publish Git separately."""
    root, _, path, state = wt.load(backend.root, backend.root.name)
    target, context = backend.root, backend.run_context
    with wt.lifecycle_lock(root):
        state = worktree.require(target)
        if state is None:
            raise DeployStepBlocked("checkpoint requires a Deploy Task")
        pending = context.get("checkpointPending")
        receipts = state.setdefault("deployCheckpoints", {})
        if (not names and not (pending or {}).get("final")) or len(names) != len(
            set(names)
        ):
            raise DeployStepBlocked(
                "checkpoint requires distinct StackNames or the saved final candidate"
            )
        if pending and pending.get("final"):
            if set(names) != set(pending["stacks"]):
                raise DeployStepBlocked(
                    "checkpoint must retain the saved final Stack scope"
                )
            return final_checkpoint(backend, root, path, state, pending)
        if pending is None:
            if not set(names) <= receipts.keys():
                raise DeployStepBlocked(
                    "no synchronized checkpoint candidate for requested Stacks"
                )
            return {n: receipts[n] for n in names}
        if set(names) != set(pending["stacks"]) or pending.get("after") is None:
            raise DeployStepBlocked(
                "checkpoint must include the complete synchronized candidate"
            )
        if (
            context.get("pendingObserved")
            or context.get("pendingGeneration")
            or context.get("generationError")
        ):
            raise DeployStepBlocked(
                "required generation remains pending; inspect pendingGeneration"
            )
        if any(not backend.states[n].get("observedSynced") for n in names):
            raise DeployStepBlocked(
                "checkpoint requires a complete adopted observation for every selected Stack"
            )
        if contracts.validation_snapshot(target) != pending["after"]:
            raise DeployStepBlocked("checkpoint candidate changed after sync")
        changed = git_publication.output_changes(target, state)
        expected = {
            p
            for p in pending["before"].keys() | pending["after"].keys()
            if pending["before"].get(p) != pending["after"].get(p)
        }
        # A saved source commit may already contain this candidate after an interrupted acknowledgement.
        if (
            changed
            and changed != expected
            or any(not p.startswith(("model/", "docs/designs/")) for p in changed)
        ):
            raise DeployStepBlocked(
                "checkpoint includes changes outside synchronized Model/views"
            )
        context["snapshotValidation"] = VALIDATION_FAIL
        backend.save()
        task = tasks.read_task_snapshot(target, state["task_file"], live=True)
        preflight = {
            "task": task.raw,
            "head": wt.output(target, "rev-parse", "HEAD"),
            "index": wt.output(target, "write-tree"),
            "changed": changed,
            "candidate": copy.deepcopy(pending["after"]),
            "intent": copy.deepcopy(state.get("deployCheckpointIntent")),
        }
        try:
            git_publication.check_scope(target, state["task_file"])
            validate(backend, scope_checked=True, changed=changed)
        except Exception:
            backend.save()
            raise
        context["snapshotValidation"] = VALIDATION_PASS
        backend.save()
        backend.guard()
        if (
            pending["after"] != preflight["candidate"]
            or contracts.validation_snapshot(target) != preflight["candidate"]
            or json.loads(path.read_text(encoding="utf-8")).get(
                "deployCheckpointIntent"
            )
            != preflight["intent"]
        ):
            raise DeployStepBlocked("checkpoint candidate changed during validation")
        commit = git_publication.checkpoint(target, path, state, preflight=preflight)
        for name in names:
            receipts[name] = checkpoint_receipt(backend, state, name, commit)
        wt.save(path, state)
        for name in names:
            backend.states[name].pop("checkpointRequired", None)
            backend.states[name]["checkpointed"] = True
        context.pop("checkpointPending", None)
        backend.save()
    return {n: receipts[n] for n in names}
