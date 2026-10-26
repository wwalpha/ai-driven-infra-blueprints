"""Registered-Python Model guards and deployment repair operations."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import deploy.contracts as _imports_deploy_contracts
import deploy.handoff as _imports_deploy_handoff
import model.core as _imports_model_core
import model.sources as _imports_model_sources
import task_contract as tasks
import utils.aws_mappings as _imports_utils_aws_mappings
import utils.json_format as _imports_utils_json_format
import validation.findings as _imports_validation_findings
import validation.loop as _imports_validation_loop
import validation.task as _imports_validation_task
import validation_scope as _imports_validation_scope
import worktree_python as python_env
import worktree_task as wt
from utils.sealed_evidence import read_sealed, write_sealed

deploy_handoff = _imports_deploy_handoff


def prepare_integration(where: Path, task_id: str) -> wt.FinalCandidate:
    """Commit/rebase a private Model-only candidate; never validate, complete or merge."""
    root, _, path, state = wt.load(where, task_id)
    with wt.lifecycle_lock(root):
        if (
            path.with_suffix(".setup-lock").exists()
            or state.get("python_setup", {}).get("status") != "ready"
            or state["merged"]
        ):
            raise wt.Blocked(
                "Model integration requires ready unmerged lifecycle state"
            )
        target = wt.task_worktree(root, state)
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        if not tasks.final_model_task(text) or tasks.status(text) not in {
            "running",
            "completed",
        }:
            raise wt.Blocked(
                "Model integration requires a running/completed Model-only task"
            )
        if tasks.section(text, "## Suspension reason"):
            raise wt.Blocked(
                "running/completed task has an unexpected suspension reason"
            )
        operation = tasks.model_operation(text)
        if operation is not None and operation.action == "import-delete":
            entries = _imports_model_core.entries
            Scope = _imports_model_sources.Scope
            load_model = _imports_model_sources.load_model
            for scope in sorted(operation.source_scopes):
                remaining = set(
                    dict(
                        entries(
                            load_model(Scope(target, *scope)).authoritative,
                            "desired.resource.",
                        )
                    )
                )
                requested = {
                    source.rsplit("/", 1)[1]
                    for source in operation.delete_sources
                    if tuple(source.split("/")[:3]) == scope
                }
                if remaining & requested:
                    raise wt.Blocked(
                        "deletion leaves incomplete: "
                        + "/".join(scope)
                        + ": "
                        + ", ".join(sorted(remaining & requested))
                    )
        latest = wt._prepare_commit(root, path, state, target, None)
        active_scope = _imports_validation_scope.active_scope
        scope = active_scope(target, task_file=state["task_file"])
        if scope is None:
            raise wt.Blocked("Model final candidate requires explicit service scope")
        head = wt.output(target, "rev-parse", "HEAD")
        return wt.FinalCandidate(
            target,
            target,
            state["task_file"],
            text,
            latest,
            head,
            frozenset(
                wt.paths(
                    target, "diff", "--no-renames", "--name-only", "-z", latest, head
                )
            ),
            frozenset(scope),
        )


def validate_final_candidate(candidate: wt.FinalCandidate) -> wt._ValidatedCandidate:
    """Run the existing read-only final loop once, without holding the lifecycle lock."""
    run_loop = _imports_validation_loop.run_loop

    options = SimpleNamespace(
        mode="task",
        all=False,
        task_file=candidate.task_file,
        log_dir=None,
        profile=False,
        jobs=2,
        validation_jobs=4,
        fresh=True,
        write=False,
        staged=False,
        base=None,
        affected=False,
    )
    if (
        wt.changed_paths(candidate.root)
        or wt.output(candidate.root, "rev-parse", "HEAD") != candidate.candidate_head
        or tasks.read_task_snapshot(candidate.root, candidate.task_file, live=True).text
        != candidate.task_text
    ):
        raise wt.Blocked("final candidate changed before validation")
    code = run_loop(candidate.root, options, final_candidate=candidate)
    return wt._ValidatedCandidate(candidate, code)


def deploy_request(where, request_path):
    """Read one pinned request, owned by the current parent Task lifecycle."""
    request_path = deploy_handoff.external(Path(where), request_path)
    envelope = json.loads(request_path.read_text(encoding="utf-8"))
    parent = Path(envelope["payload"]["repository"])
    request = read_sealed(parent, request_path)
    root, _, path, state = wt.load(parent, Path(request["taskFile"]).stem)
    if (
        wt.task_worktree(root, state) != parent
        or request.get("parentBranch") != state["branch"]
    ):
        raise wt.Blocked("repair request parent ownership mismatch")
    pending = state.get("iacRepair", {})
    if pending.get("requestId") != request["requestId"] or pending.get(
        "requestPath"
    ) != str(request_path):
        raise wt.Blocked("stale/consumed one-shot repair request")
    text = tasks.read_task_snapshot(parent, request["taskFile"], live=True).text
    if _imports_deploy_contracts.task_digest(text) != request["taskDigest"]:
        raise wt.Blocked("parent contract changed outside suspension/resume")
    if (
        wt.changed_paths(parent)
        or wt.output(parent, "rev-parse", "HEAD") != request["parentTip"]
    ):
        if not state.get("deployIntegrationIntent"):
            raise wt.Blocked("parent checkpoint changed")
    return root, path, state, request


def deploy_checkpoint(where, task_id, session_path):
    """Checkpoint only proven parent changes, without completing an unfinished deploy."""

    handoff = _imports_deploy_handoff
    task_digest = _imports_deploy_contracts.task_digest
    root, _, path, state = wt.load(where, task_id)
    target = wt.task_worktree(root, state)
    request_path = handoff.external(target, session_path)
    request = read_sealed(target, request_path)
    with wt.lifecycle_lock(root), handoff.locked(request_path):
        if (
            request["repository"] != str(target)
            or request["taskFile"] != state["task_file"]
        ):
            raise wt.Blocked("checkpoint needs this parent's one-shot request")
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        if (
            tasks.status(text) != "running"
            or task_digest(text) != request["taskDigest"]
        ):
            raise wt.Blocked("checkpoint requires unchanged running parent Task")
        if state.get("iacRepair", {}).get("requestId") not in (
            None,
            request["requestId"],
        ):
            raise wt.Blocked(
                "finish the current one-shot handoff before another repair"
            )
        handoff.require_settled(target, request["target"])
        handoff.verify_inputs(target, request)
        Findings = _imports_validation_findings.Findings
        TaskValidation = _imports_validation_task.TaskValidation
        with tasks.selected_task(target, state["task_file"]):
            findings = Findings(target)
            check = TaskValidation(target, findings)
            check.check_task_scope()
            check.check_task_type_requirements()
            if findings.errors:
                raise wt.Blocked(
                    "parent change authority: " + "; ".join(findings.errors)
                )
        changed = wt.changed_paths(target)
        head = wt.output(target, "rev-parse", "HEAD")
        intent = state.get("repairCheckpointIntent")
        if intent:
            if intent["requestId"] != request["requestId"]:
                raise wt.Blocked("checkpoint intent belongs to another request")
            if head != intent["head"]:
                if (
                    changed
                    or wt.output(target, "rev-parse", "HEAD^") != intent["head"]
                    or wt.output(target, "rev-parse", "HEAD^{tree}") != intent["tree"]
                    or wt.output(target, "log", "-1", "--format=%s")
                    != intent["message"]
                ):
                    raise wt.Blocked("checkpoint commit is not the saved intent")
        else:
            if head != state["tip"]:
                raise wt.Blocked("unexpected parent commits before checkpoint")
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
                "requestId": request["requestId"],
                "head": head,
                "tree": wt.output(target, "write-tree"),
                "message": f"task({task_id}): deploy repair checkpoint {request['requestId']}",
            }
            state["repairCheckpointIntent"] = intent
            wt.save(path, state)
        if head == intent["head"] and changed:
            wt.git(target, "commit", "-m", intent["message"])
        tip = wt.output(target, "rev-parse", "HEAD")
        if wt.output(target, "rev-parse", "HEAD^{tree}") != intent[
            "tree"
        ] or wt.changed_paths(target):
            raise wt.Blocked("checkpoint changed during commit")
        state["tip"] = tip
        state.pop("repairCheckpointIntent", None)
        request.update(
            parentTip=tip, parentBranch=state["branch"], parentStart=state["start"]
        )
        request["requestPath"] = str(request_path)
        state["iacRepair"] = {
            "requestId": request["requestId"],
            "requestPath": str(request_path),
        }
        wt.save(path, state)
        write_sealed(target, request_path, request)
        return request


def deploy_snapshot(target):
    return _imports_deploy_contracts.validation_snapshot(target)


def deploy_validate(where, task_id, request_path):
    handoff = _imports_deploy_handoff
    root, _, path, state = wt.load(where, task_id)
    target = wt.task_worktree(root, state)
    _, _, parent_state, request = wt.deploy_request(target, request_path)
    if (
        state.get("deployRepair") != request["requestPath"]
        or state["start"] != request["parentTip"]
    ):
        raise wt.Blocked("child lifecycle does not belong to this request")
    with wt.lifecycle_lock(root), handoff.locked(Path(request["requestPath"])):
        text = wt.deploy_child_contract(target, state, request)
        if (
            tasks.status(text) != "running"
            or wt.output(target, "rev-parse", "HEAD") != state["tip"]
        ):
            raise wt.Blocked(
                "child must be running at its lifecycle tip for validation"
            )
        handoff.verify_inputs(
            target,
            request,
            child_paths=request["allowedPaths"],
            contract_file=state["task_file"],
        )
        before = wt.deploy_snapshot(target)
        if state.get("repairStaticRuns", 0) >= 3:
            raise wt.Blocked("current implement static repair limit reached")
        state["repairStaticRuns"] = state.get("repairStaticRuns", 0) + 1
        wt.save(path, state)
        # Provisioned interpreter, same fixed validator as ordinary implement. No shell/LLM/AWS.
        interpreter, environment = python_env.runtime(target)
        definition_root = _imports_utils_aws_mappings.definition_root
        command = [
            str(interpreter),
            "-B",
            str(definition_root(target) / "framework/scripts/blueprint-loop.py"),
            "--mode",
            "task",
            "--task-file",
            state["task_file"],
            "--fresh",
        ]
        environment[tasks.SELECTOR] = state["task_file"]
        outcome = subprocess.run(
            command, cwd=target, env=environment, capture_output=True, text=True
        )
        log = Path(request["requestPath"]).with_name(
            f"static-{state['repairStaticRuns']}.log"
        )
        # Validator output belongs to the same private external evidence boundary.
        fingerprint = _imports_utils_json_format.fingerprint
        log.write_text(
            json.dumps(
                {
                    "command": command,
                    "exitCode": outcome.returncode,
                    "outputDigest": fingerprint([outcome.stdout, outcome.stderr]),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        after = wt.deploy_snapshot(target)
        if (
            outcome.returncode
            or before != after
            or tasks.read_task_snapshot(target, state["task_file"], live=True).text
            != text
        ):
            tasks.suspend(
                target,
                state["task_file"],
                "repair static validation failed/inputs changed; " + str(log),
            )
            raise wt.Blocked(
                "repair static validation failed/inputs changed; " + str(log)
            )
        receipt = dict(
            requestId=request["requestId"],
            childTask=state["task_file"],
            contract=text,
            snapshot=after,
            command=command,
            log=str(log),
            result="PASS",
            parentTip=request["parentTip"],
            childRoot=str(target),
        )
        validation_path = Path(request["requestPath"]).with_name("validation.json")
        write_sealed(Path(request["repository"]), validation_path, receipt)
        state["deployValidation"] = str(validation_path)
        wt.save(path, state)
        return receipt


def deploy_finalize(where, task_id):
    """FF-only delivery to the pinned suspended parent, with durable merge intent/result."""
    handoff = _imports_deploy_handoff
    sha = _imports_deploy_contracts.sha
    subprocess_bytes = _imports_deploy_contracts.subprocess_bytes
    root, _, path, state = wt.load(where, task_id)
    target = wt.task_worktree(root, state)
    _, parent_path, parent_state, request = wt.deploy_request(
        target, state["deployRepair"]
    )
    parent = Path(request["repository"])
    with wt.lifecycle_lock(root), handoff.locked(Path(request["requestPath"])):
        parent_text = tasks.read_task_snapshot(
            parent, request["taskFile"], live=True
        ).text
        if tasks.status(parent_text) != "suspend":
            raise wt.Blocked("repair integration requires suspended parent")
        wt.integration_task(target, state)
        text = wt.deploy_child_contract(target, state, request)
        validation = read_sealed(parent, Path(state["deployValidation"]))
        if (
            validation["requestId"] != request["requestId"]
            or validation["contract"] != tasks.set_status(text, "running")
            or validation["snapshot"] != wt.deploy_snapshot(target)
        ):
            raise wt.Blocked("validated child contract/inputs changed")
        handoff.verify_inputs(
            parent,
            request,
            child_paths=request["allowedPaths"]
            if parent_state.get("deployIntegrationIntent")
            else (),
        )
        if not state.get("deployCommitIntent"):
            if wt.output(target, "rev-parse", "HEAD") != request["parentTip"]:
                raise wt.Blocked("unexpected child commits")
            changed = wt.changed_paths(target)
            if not changed or changed - set(request["allowedPaths"]):
                raise wt.Blocked("repair changes empty or outside request")
            wt.git(target, "diff", "--check")
            wt.git(target, "diff", "--cached", "--check")
            wt.git(
                target, "add", "--", *[f":(top,literal){p}" for p in sorted(changed)]
            )
            state["deployCommitIntent"] = {
                "parent": request["parentTip"],
                "tree": wt.output(target, "write-tree"),
                "message": f"task({task_id}): verified deploy repair {request['requestId']}",
            }
            wt.save(path, state)
        intent = state["deployCommitIntent"]
        if wt.output(target, "rev-parse", "HEAD") == intent["parent"]:
            wt.git(target, "commit", "-m", intent["message"])
        commit = wt.output(target, "rev-parse", "HEAD")
        if (
            wt.output(target, "rev-parse", "HEAD^") != intent["parent"]
            or wt.output(target, "rev-parse", "HEAD^{tree}") != intent["tree"]
            or wt.output(target, "log", "-1", "--format=%s") != intent["message"]
            or wt.changed_paths(target)
        ):
            raise wt.Blocked("repair commit differs from recorded intent")
        changed = wt.paths(
            target,
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            intent["parent"],
            commit,
        )
        if changed - set(request["allowedPaths"]):
            raise wt.Blocked("repair commit includes other changes")
        state.update(tip=commit, commit=commit, verified=True)
        wt.save(path, state)
        plan = {
            "requestId": request["requestId"],
            "parentTip": request["parentTip"],
            "commit": commit,
        }
        if parent_state.get("deployIntegrationIntent") and any(
            parent_state["deployIntegrationIntent"].get(key) != value
            for key, value in plan.items()
        ):
            raise wt.Blocked("another integration intent is pending")
        parent_state["deployIntegrationIntent"] = plan
        wt.save(parent_path, parent_state)
        if wt.changed_paths(parent) or wt.output(parent, "rev-parse", "HEAD") not in {
            request["parentTip"],
            commit,
        }:
            raise wt.Blocked("parent changed during child integration")
        wt.git(parent, "merge", "--ff-only", "--no-autostash", commit)
        if wt.output(parent, "rev-parse", "HEAD") != commit:
            raise wt.Blocked("repair merge differs from intended commit")
        changes = {
            p: {
                "before": hashlib.sha256(
                    subprocess_bytes(target, request["parentTip"], p)
                ).hexdigest(),
                "after": sha(target / p),
                "beforeBlob": wt.output(
                    target, "rev-parse", request["parentTip"] + ":" + p
                ),
                "afterBlob": wt.output(target, "rev-parse", commit + ":" + p),
            }
            for p in sorted(changed)
        }
        result = {
            "requestId": request["requestId"],
            "taskFile": request["taskFile"],
            "taskDigest": request["taskDigest"],
            "repository": request["repository"],
            "parentTip": request["parentTip"],
            "commit": commit,
            "changes": changes,
            "childTask": state["task_file"],
            "validation": validation,
            "result": "VALIDATED_CANDIDATE",
        }
        result_path = Path(request["requestPath"]).with_name("result.json")
        write_sealed(parent, result_path, result)
        parent_state["iacRepair"] = {
            "requestId": request["requestId"],
            "commit": commit,
            "parentTip": request["parentTip"],
            "changes": changes,
            "taskDigest": request["taskDigest"],
        }
        parent_state["tip"] = commit
        parent_state["deployIntegrationIntent"]["result"] = str(result_path)
        wt.save(parent_path, parent_state)
        state["merged"] = commit
        wt.save(path, state)
        return {**state, "repair_result": str(result_path)}
