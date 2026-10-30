"""Explicit Deploy and update checkpoints, including private completed candidates."""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace

import task_contract_core as tasks
import worktree_task as wt
from deploy import contracts, current_request, git_publication, worktree
from deploy.cli_guidance import DeployStepBlocked
from model.observed import verify_observed_outputs
from validation.findings import Findings
from validation.runner import Validator
from validation.task import TaskValidation


def validate(backend: SimpleNamespace, *, scope_checked=False, changed=None) -> None:
    """Use existing scoped Model/view checks, without completing the running Task."""
    root = backend.root
    findings = Findings(root)
    checks = TaskValidation(root, findings)
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
    if scopes:
        validator = Validator(root, scopes, cache=False, model_validation="change")
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
            if all(n in receipts for n in names):
                for name in names:
                    if not wt.ancestor(root, receipts[name]["commit"], state["base"]):
                        raise DeployStepBlocked(
                            "checkpoint receipt is no longer integrated"
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
        if contracts.validation_snapshot(target) != pending["after"]:
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
            if head != state["tip"] or latest != head and not delegated:
                raise DeployStepBlocked(
                    "base advanced or Task has unintegrated commits; review before checkpoint (no automatic rebase)"
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
            validate(backend)
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
            intent = {
                "head": head,
                "base": latest,
                "tree": wt.output(target, "write-tree"),
                "stacks": sorted(names),
                "taskDigest": context["taskDigest"],
                "candidate": copy.deepcopy(pending["after"]),
                "changed": sorted(changed),
                "message": f"task({state['task_id']}): deploy checkpoint "
                + ", ".join(sorted(names)),
            }
            state["stackCheckpointIntent"] = intent
            wt.save(path, state)
        if (
            intent["stacks"] != sorted(names)
            or intent["taskDigest"] != context["taskDigest"]
            or intent["candidate"] != pending["after"]
            or wt.output(target, "write-tree") != intent["tree"]
        ):
            raise DeployStepBlocked("checkpoint intent changed; retain candidate")
        if head == intent["head"]:
            if latest != intent["base"]:
                raise DeployStepBlocked(
                    "base advanced before commit; retain checkpoint intent"
                )
            if intent["changed"]:
                wt.git(target, "commit", "-m", intent["message"])
        commit = wt.output(target, "rev-parse", "HEAD")
        if (
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
        base = wt.base_worktree(root, state)
        if wt.output(base, "rev-parse", "HEAD") not in {intent["base"], commit}:
            raise DeployStepBlocked(
                "base advanced before merge; retain commit for review"
            )
        backend.guard()
        if (
            contracts.validation_snapshot(target) != intent["candidate"]
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
    with ExitStack() as locks:
        for name in sorted(state["deployIdentity"]["stacks"]):
            request_path = current_request.location(backend.target, name)
            locks.enter_context(current_request.journal.locked(request_path))
            if current_request.read(request_path):
                raise DeployStepBlocked(
                    "final checkpoint has an unresolved current request: " + name
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
            context["snapshotValidation"] = "FAIL"
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
            context["snapshotValidation"] = "PASS"
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
                context.get("snapshotValidation") != "PASS"
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
        context["snapshotValidation"] = "FAIL"
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
        context["snapshotValidation"] = "PASS"
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
