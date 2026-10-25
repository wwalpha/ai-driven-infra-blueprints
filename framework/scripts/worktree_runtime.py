"""Registered-Python Model guards and deployment repair operations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import deploy.contracts as _imports_deploy_contracts
import deploy.handoff as _imports_deploy_handoff
import deploy.inputs as _imports_deploy_inputs
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
import worktree_state
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


def bind_deploy_workflow(where, session_path, session, ledger, *, activate=False):
    """Prevent a new Task from resetting an overlapping unfinished deploy workflow."""
    fingerprint = _imports_utils_json_format.fingerprint
    # Pure session units have no Git; production deploy already requires clean Git inputs.
    if not (where / ".git").exists():
        return
    managed_task_state = worktree_state.managed_task_state
    root, _, primary = wt.repository(where)
    directory = wt.metadata_directory(primary) / "deploy-workflows"
    target = session["target"]
    key = fingerprint(
        [
            target.get("awsExecutionAccountId", target["awsAccountId"]),
            target["awsRegion"],
        ]
    )
    file = directory / (key + ".json")
    if directory.is_symlink() or file.is_symlink():
        raise wt.Blocked("deploy workflow registry must not use symlinks")
    if not activate and not file.exists():
        return
    managed_task_state(root, session["taskFile"])
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "registry.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise wt.Blocked(
            "deploy workflow registry busy/interrupted; retain for review"
        ) from None
    try:
        owners = read_sealed(primary, file) if file.exists() else []
        current = {
            "workflowId": session["workflow"]["workflowId"],
            "repository": str(root),
            "taskFile": session["taskFile"],
            "session": str(session_path),
            "ledger": str(ledger),
            "scope": sorted(session["states"]),
        }
        existing = False
        for owner in owners:
            if owner["workflowId"] == current["workflowId"]:
                if owner != current:
                    raise wt.Blocked("deploy workflow ownership/Stack scope changed")
                existing = True
                continue
            if not set(owner["scope"]) & set(current["scope"]):
                continue
            previous_ledger = Path(owner["ledger"])
            if previous_ledger.with_name(previous_ledger.name + ".intent").exists():
                raise wt.Blocked(
                    "recover original workflow save intent before another Task"
                )
            previous = read_sealed(Path(owner["repository"]), previous_ledger)
            if (
                previous["workflowId"] != owner["workflowId"]
                or previous["session"] != owner["session"]
            ):
                raise wt.Blocked("previous deploy workflow identity cannot be verified")
            state = previous["state"]
            finished = state["workflow"].get("status") == "COMPLETE" and not state.get(
                "pendingRequest"
            )
            if not finished or any(
                s["status"] == "RUNNING"
                or s.get("pollError")
                or s.get("cleanupStatus") == "DELETE_INTENT"
                or s["status"] == "SUCCESS"
                and not s.get("observedSynced")
                for s in state["states"].values()
            ):
                raise wt.Blocked(
                    "unfinished deploy workflow owns overlapping Stacks; resume/inherit its retained history: "
                    + owner["session"]
                )
        if activate and not existing:
            owners.append(current)
            write_sealed(primary, file, owners)
    finally:
        lock.rmdir()


def deploy_request(where, request_path):
    """Read the sealed handoff through the parent seal and verify its live checkpoint."""
    task_digest = _imports_deploy_contracts.task_digest
    external = _imports_deploy_handoff.external
    request_path = external(Path(where), request_path)
    envelope = json.loads(request_path.read_text(encoding="utf-8"))
    parent = Path(envelope["payload"]["repository"])
    request = read_sealed(parent, request_path)
    root, _, path, state = wt.load(parent, Path(request["taskFile"]).stem)
    if (
        wt.task_worktree(root, state) != parent
        or request.get("parentBranch") != state["branch"]
    ):
        raise wt.Blocked("repair request parent ownership mismatch")
    session = json.loads(Path(request["session"]).read_text(encoding="utf-8"))
    locked = _imports_deploy_handoff.locked
    restore = _imports_deploy_handoff.restore
    with locked(Path(request["session"])):
        restore(parent, Path(request["session"]), session)
    if (
        session.get("pendingRequest") != request
        or session["inputRevision"] != request["revision"]
        or session["workflow"]["workflowId"] != request["workflowId"]
    ):
        raise wt.Blocked("stale/consumed repair request")
    text = tasks.read_task_snapshot(parent, request["taskFile"], live=True).text
    normalized = tasks.set_status(text, "running")
    if task_digest(normalized) != request["taskDigest"]:
        raise wt.Blocked("parent contract changed outside suspension/resume")
    if (
        wt.changed_paths(parent)
        or wt.output(parent, "rev-parse", "HEAD") != request["parentTip"]
    ):
        # An interrupted child merge is checked separately against its exact integration intent.
        if not state.get("deployIntegrationIntent"):
            raise wt.Blocked("parent checkpoint changed")
    return root, path, state, session, request


def deploy_checkpoint(where, task_id, session_path):
    """Checkpoint only proven parent changes, without completing an unfinished deploy."""

    handoff = _imports_deploy_handoff
    task_digest = _imports_deploy_contracts.task_digest
    root, _, path, state = wt.load(where, task_id)
    target = wt.task_worktree(root, state)
    session_path = handoff.external(target, session_path)
    with wt.lifecycle_lock(root), handoff.locked(session_path):
        session = json.loads(session_path.read_text(encoding="utf-8"))
        handoff.restore(target, session_path, session)
        request = session.get("pendingRequest")
        if (
            not request
            or request["repository"] != str(target)
            or request["taskFile"] != state["task_file"]
        ):
            raise wt.Blocked("checkpoint needs this parent pending request")
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        if (
            tasks.status(text) != "running"
            or task_digest(text) != session["taskDigest"]
        ):
            raise wt.Blocked("checkpoint requires unchanged running parent Task")
        if session.get("observedError") or any(
            s["status"] == "RUNNING"
            or s.get("pollError")
            or s["status"] == "SUCCESS"
            and not s.get("observedSynced")
            for s in session["states"].values()
        ):
            raise wt.Blocked("drain and synchronize peers before checkpoint")
        handoff.verify_inputs(target, session)
        Findings = _imports_validation_findings.Findings
        TaskValidation = _imports_validation_task.TaskValidation
        with tasks.selected_task(target, state["task_file"]):
            findings = Findings(target)
            check = TaskValidation(target, findings)
            check.check_task_scope()
            check.check_task_type_requirements()
            check.check_issue_gate()
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
        integration = state.get("deployIntegrationIntent")
        if integration:
            if integration.get("result") not in session["workflow"]["accepted"]:
                raise wt.Blocked("previous child integration has not been accepted")
            state.setdefault("deployIntegrations", []).append(
                state.pop("deployIntegrationIntent")
            )
        state["tip"] = tip
        state.setdefault("deployCheckpoints", []).append(intent)
        state.pop("repairCheckpointIntent", None)
        request.update(
            parentTip=tip, parentBranch=state["branch"], parentStart=state["start"]
        )
        directory = session_path.with_name(session_path.name + ".files") / (
            "repair-" + request["requestId"]
        )
        directory.mkdir(parents=True, exist_ok=True)
        request["requestPath"] = str(directory / "request.json")
        # Both files are recoverable from the persisted checkpoint/intent on retry.
        wt.save(path, state)
        handoff.save(session_path, session)
        write_sealed(target, Path(request["requestPath"]), request)
        return request


def deploy_snapshot(target):
    return _imports_deploy_contracts.validation_snapshot(target)


def deploy_validate(where, task_id, request_path):
    handoff = _imports_deploy_handoff
    root, _, path, state = wt.load(where, task_id)
    target = wt.task_worktree(root, state)
    _, _, parent_state, session, request = wt.deploy_request(target, request_path)
    if (
        state.get("deployRepair") != request["requestPath"]
        or state["start"] != request["parentTip"]
    ):
        raise wt.Blocked("child lifecycle does not belong to this request")
    with wt.lifecycle_lock(root), handoff.locked(Path(request["session"])):
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
            session,
            child_paths=request["allowedPaths"],
            contract_file=state["task_file"],
        )
        before = wt.deploy_snapshot(target)
        attempt = session["workflow"]["attempts"][request["attemptId"]]
        if attempt.get("staticRuns", 0) >= 3:
            raise wt.Blocked("implement static repair limit reached; WAITING_HUMAN")
        attempt["staticRuns"] = attempt.get("staticRuns", 0) + 1
        attempt["stage"] = "STATIC_VALIDATING"
        handoff.save(Path(request["session"]), session)
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
            f"static-{attempt['staticRuns']}.log"
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
        candidate_error = None
        if not outcome.returncode and before == after:
            deployment_input_paths = _imports_deploy_inputs.deployment_input_paths
            load_units = _imports_deploy_inputs.load_units
            unit_paths = _imports_deploy_inputs.paths
            with tasks.selected_task(target, state["task_file"]):
                _, candidate_units = load_units(
                    target,
                    session["environment"],
                    session["directory"],
                    list(session["states"]),
                )
            candidate_effective = handoff.effective(
                target,
                candidate_units,
                lambda u: unit_paths(
                    target,
                    session["environment"],
                    session["directory"],
                    session["target"],
                    u,
                ),
                lambda us: deployment_input_paths(
                    target,
                    session["environment"],
                    session["directory"],
                    session["target"],
                    us,
                ),
            )
            changed_inputs = wt.changed_paths(target)
            direct = {
                name
                for name, inputs in session["unitInputPaths"].items()
                if set(inputs) & changed_inputs
            }
            previous_ids = {
                o["observationId"]
                for p in attempt["problemIds"]
                for o in session["workflow"]["problems"][p]["observations"]
            }
            if not direct or any(
                candidate_effective[name] == session["effectiveDigests"][name]
                or candidate_effective[name]
                in {
                    o.get("effectiveDigest")
                    for o in session.get("failureObservations", [])
                    if o["stack"] == name and o["observationId"] in previous_ids
                }
                for name in direct
            ):
                candidate_error = (
                    "unchanged or known failed effective inputs for this problem"
                )
        if (
            outcome.returncode
            or before != after
            or candidate_error
            or tasks.read_task_snapshot(target, state["task_file"], live=True).text
            != text
        ):
            attempt["staticFailures"] += 1
            attempt["stage"] = "STATIC_FAILED"
            if attempt["staticRuns"] >= 3:
                session["workflow"]["status"] = "WAITING_HUMAN"
            handoff.save(Path(request["session"]), session)
            tasks.suspend(
                target,
                state["task_file"],
                "repair static validation failed/inputs changed; " + str(log),
            )
            raise wt.Blocked(
                (candidate_error or "repair static validation failed or inputs changed")
                + "; "
                + str(log)
            )
        receipt = dict(
            requestId=request["requestId"],
            attemptId=request["attemptId"],
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
        attempt["stage"] = "STATIC_PASSED"
        wt.save(path, state)
        handoff.save(Path(request["session"]), session)
        return receipt


def deploy_finalize(where, task_id):
    """FF-only delivery to the pinned suspended parent, with durable merge intent/result."""
    handoff = _imports_deploy_handoff
    sha = _imports_deploy_contracts.sha
    subprocess_bytes = _imports_deploy_contracts.subprocess_bytes
    root, _, path, state = wt.load(where, task_id)
    target = wt.task_worktree(root, state)
    _, parent_path, parent_state, session, request = wt.deploy_request(
        target, state["deployRepair"]
    )
    parent = Path(request["repository"])
    with wt.lifecycle_lock(root), handoff.locked(Path(request["session"])):
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
            session,
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
                "before": __import__("hashlib")
                .sha256(subprocess_bytes(target, request["parentTip"], p))
                .hexdigest(),
                "after": sha(target / p),
                "beforeBlob": wt.output(
                    target, "rev-parse", request["parentTip"] + ":" + p
                ),
                "afterBlob": wt.output(target, "rev-parse", commit + ":" + p),
            }
            for p in sorted(changed)
        }
        deployment_input_paths = _imports_deploy_inputs.deployment_input_paths
        load_units = _imports_deploy_inputs.load_units
        input_paths = _imports_deploy_inputs.paths
        with tasks.selected_task(target, state["task_file"]):
            _, units = load_units(
                target,
                session["environment"],
                session["directory"],
                list(session["states"]),
            )
        effective_after = handoff.effective(
            target,
            units,
            lambda unit: input_paths(
                target,
                session["environment"],
                session["directory"],
                session["target"],
                unit,
            ),
            lambda selected: deployment_input_paths(
                target,
                session["environment"],
                session["directory"],
                session["target"],
                selected,
            ),
        )
        result = {
            **request,
            "effectiveInputs": {
                "before": session["effectiveDigests"],
                "after": effective_after,
            },
            "commit": commit,
            "changes": changes,
            "childTask": state["task_file"],
            "childContract": text,
            "validation": validation,
            "expected": session["workflow"]["attempts"][request["attemptId"]].get(
                "expectation"
            ),
            "result": "VALIDATED_CANDIDATE",
        }
        result_path = Path(request["requestPath"]).with_name("result.json")
        write_sealed(parent, result_path, result)
        parent_state["tip"] = commit
        parent_state["deployIntegrationIntent"]["result"] = str(result_path)
        wt.save(parent_path, parent_state)
        state["merged"] = commit
        wt.save(path, state)
        return {**state, "repair_result": str(result_path)}
