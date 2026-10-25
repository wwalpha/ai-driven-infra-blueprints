"""Plan/accept one external input revision, then recover pinned AWS state separately."""

import copy
from pathlib import Path

import worktree_task as _imports_worktree_task
from utils.cloudformation.inputs import Blocked
from utils.sealed_evidence import read_sealed

import deploy.contracts as _dependency_deploy_contracts
import deploy.scheduler as _imports_deploy_scheduler
from deploy import handoff, recovery


def accept(root, result_path, session, backend, units, current_units, current_manifest):
    result_path = handoff.external(root, result_path)
    result = read_sealed(root, result_path)
    canonical = handoff.external(
        root, Path(result["requestPath"]).with_name("result.json")
    )
    if read_sealed(root, canonical) != result:
        raise Blocked("result differs from its helper-issued canonical receipt")
    result_path = canonical
    workflow = session["workflow"]
    accepted = workflow["accepted"]
    if str(result_path) in accepted:
        if (
            accepted[-1] != str(result_path)
            or session.get("pendingRequest")
            or result["revision"] + 1 != session["inputRevision"]
        ):
            raise Blocked("old result is not the current acceptance recovery")
        if (
            current_manifest != session["infraManifest"]
            or current_units != session["unitDigests"]
        ):
            raise Blocked("accepted repair inputs changed")
        return  # Intent and revision were already accepted. Never reset/execute a second time.
    request = session.get("pendingRequest")
    if not request or any(result.get(key) != value for key, value in request.items()):
        raise Blocked("result does not match the unconsumed request")
    if (
        result.get("result") != "VALIDATED_CANDIDATE"
        or result["revision"] != session["inputRevision"]
    ):
        raise Blocked("repair result revision/order invalid")
    if (
        result["workflowId"] != workflow["workflowId"]
        or result["repository"] != str(root)
        or result["taskFile"] != session["taskFile"]
        or result["taskDigest"] != session["taskDigest"]
    ):
        raise Blocked("repair result Task/workflow mismatch")
    attempt = workflow["attempts"].get(result["attemptId"])
    if (
        not attempt
        or attempt["requestId"] != request["requestId"]
        or attempt["stage"] != "STATIC_PASSED"
        or workflow["reserved"] > workflow["budget"]
    ):
        raise Blocked("repair attempt/validation/budget mismatch")
    if set(result["changes"]) - set(request["allowedPaths"]) or not result["changes"]:
        raise Blocked("repair changed paths differ from permitted IaC")
    if current_manifest.keys() != session["infraManifest"].keys():
        raise Blocked("repair changed the declared input set")
    changed = {
        p
        for p in current_manifest
        if current_manifest[p] != session["infraManifest"][p]
    }
    if changed != set(result["changes"]):
        raise Blocked("unrecorded or ineffective extra repair changes")
    for relative, record in result["changes"].items():
        if (
            session["infraManifest"][relative] != record["before"]
            or current_manifest[relative] != record["after"]
        ):
            raise Blocked("repair before/after bytes changed")
    verify_integration_owner(root, request, result_path, result)
    output = _dependency_deploy_contracts.output
    paths = _dependency_deploy_contracts.paths
    if (
        output(root, "rev-parse", "HEAD") != result["commit"]
        or output(root, "rev-parse", result["commit"] + "^") != result["parentTip"]
        or paths(
            root,
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            result["parentTip"],
            result["commit"],
        )
        != changed
    ):
        raise Blocked("repair integration history/parent lifecycle mismatch")
    if (
        _dependency_deploy_contracts.validation_snapshot(root)
        != result["validation"]["snapshot"]
    ):
        raise Blocked(
            "validation dependencies or file set changed after child validation"
        )
    handoff.verify_inputs(root, session, child_paths=changed)
    effective = handoff.effective(
        root, units, backend.paths, backend.deployment_input_paths
    )
    if result.get("effectiveInputs") != {
        "before": session["effectiveDigests"],
        "after": effective,
    }:
        raise Blocked("effective input receipt does not match current inputs")
    affected = {
        unit["name"]
        for unit in units
        if set(
            p.relative_to(root).as_posix()
            for p in backend.deployment_input_paths([unit])
        )
        & changed
    }
    if not affected or any(
        effective[name] == session["effectiveDigests"][name] for name in affected
    ):
        raise Blocked(
            "repair has no effective input change (comments/formatting do not count)"
        )
    for name in affected:
        failed = {
            o.get("effectiveDigest")
            for o in session.get("failureObservations", [])
            if o["stack"] == name
        }
        if effective[name] in failed:
            raise Blocked("known failed effective input resubmitted")
    # Declared Import/Export dependencies only; never scan Model mappings to start deploy.
    consumers = copy.deepcopy(session.get("declaredConsumers", {}))
    for unit in units:
        backend.load_inputs(unit)
    new_consumers = handoff.dependencies(backend, units)
    for name, values in new_consumers.items():
        consumers[name] = sorted(set(consumers.get(name, [])) | set(values))
    if consumers.get("__unresolved__"):
        raise Blocked(
            "unresolved declared input consumers need diagnosis before acceptance"
        )
    queue = list(affected)
    while queue:
        name = queue.pop()
        for consumer in consumers.get(name, []):
            if consumer not in affected:
                affected.add(consumer)
                queue.append(consumer)
    if any(session["states"][name]["status"] == "SUCCESS" for name in affected):
        workflow["status"] = "WAITING_HUMAN"
        handoff.save(Path(request["session"]), session)
        raise Blocked(
            "repair affects a successful Stack/shared input; scope confirmation required"
        )
    if any(
        s["status"] == "RUNNING" or s.get("pollError")
        for s in session["states"].values()
    ):
        raise Blocked(
            "observe/drain known or uncertain operations before repair acceptance"
        )
    planned = copy.deepcopy(session)
    for name in affected:
        state = planned["states"][name]
        if state["status"] == "FAILED":
            if (
                state.get("stackStatus")
                not in {"ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}
                or not state.get("executionEvidence")
                or not state.get("failureTemplateSafety")
            ):
                raise Blocked(
                    "failed AWS operation has no original safe recovery evidence"
                )
            state["externalRepair"] = request["requestId"]
            state["recoveryPending"] = True
        else:
            # Approval waits, read/auth errors, and unknown submissions never enter this path.
            if state["status"] == "BLOCKED" and state.get("failure", {}).get(
                "classification"
            ) not in {"IAC_CANDIDATE", "INPUT_CANDIDATE"}:
                raise Blocked("BLOCKED reason is not the repaired IaC failure")
            shell = {
                key: state.get(key)
                for key in (
                    "stackId",
                    "changeSetId",
                    "operationType",
                    "absentBeforeCreate",
                )
            }
            recovery.archive_failure(state)
            archive = state.get("failureArchive", [])
            state.clear()
            state.update(status="NOT_STARTED", failureArchive=archive)
            if shell["stackId"] and shell["operationType"] == "CREATE":
                if not shell["changeSetId"] or not shell["absentBeforeCreate"]:
                    raise Blocked("unexecuted CREATE shell lacks original ownership")
                state.update(stackId=shell["stackId"], preExecutionRecovery=shell)
    planned["infraManifest"] = dict(current_manifest)
    planned["unitDigests"] = dict(current_units)
    planned["effectiveDigests"] = effective
    planned["declaredConsumers"] = new_consumers
    planned["inputRevision"] += 1
    planned["workflow"]["accepted"].append(str(result_path))
    planned["workflow"]["attempts"][request["attemptId"]].update(
        stage="ACCEPTED", acceptedRevision=planned["inputRevision"]
    )
    planned["workflow"]["status"] = "CANDIDATE_ACCEPTED"
    planned.pop("pendingRequest")
    # Caller persists this complete plan atomically under the target controller and handoff locks.
    session.clear()
    session.update(planned)
    backend.hashes.clear()
    backend.templates.clear()
    backend.expected_digests = session["unitDigests"]


def verify_integration_owner(root, request, result_path, result):
    """Managed delivery adapter; receipt/history/content validation stays in accept."""
    load = _imports_worktree_task.load
    task_worktree = _imports_worktree_task.task_worktree
    _, _, _, lifecycle = load(root, Path(request["taskFile"]).stem)
    if task_worktree(root, lifecycle) != root or lifecycle.get(
        "deployIntegrationIntent", {}
    ) != {
        "requestId": request["requestId"],
        "parentTip": result["parentTip"],
        "commit": result["commit"],
        "result": str(result_path),
    }:
        raise Blocked("repair integration history/parent lifecycle mismatch")


def recover(backend, unit, state):
    if state.get("preExecutionRecovery"):
        recovery.require_authorized(backend.root)
        recovery.archive_failure(state)
        backend.save()
        recovery.cleanup_unexecuted(
            backend.aws, backend.save, backend.wait_cleanup, state
        )
        backend.reset_after_cleanup(state)
        backend.load_inputs(unit)
        return
    if not state.get("recoveryPending"):
        return
    recovery.require_authorized(backend.root)
    if state.get("cleanupStatus") not in {
        "DELETE_INTENT",
        "DELETE_COMPLETE",
    } or state.get("cleanupStackId") != state.get("stackId"):
        evidence = state["executionEvidence"]
        if (
            state.get("operationStackId") != state.get("stackId")
            or evidence["StackId"] != state["stackId"]
            or evidence["clientToken"] != state["clientToken"]
        ):
            raise Blocked("original failure operation identity changed")
        stack = backend.aws("describe_stacks", StackName=state["stackId"])["Stacks"][0]
        if (
            stack["StackId"] != state["stackId"]
            or stack["StackStatus"] != state["stackStatus"]
        ):
            raise Blocked("live failed Stack changed; do not retry execute")
        events = backend.aws("describe_stack_events", StackName=state["stackId"])[
            "StackEvents"
        ]
        if not any(
            e.get("StackId") == state["stackId"]
            and e.get("ClientRequestToken") == state["clientToken"]
            and e.get("ResourceType") == "AWS::CloudFormation::Stack"
            and e.get("ResourceStatus") == state["stackStatus"]
            for e in events
        ):
            raise Blocked("live original failure token/evidence not confirmed")
    recovery.archive_failure(state)
    backend.save()
    backend.cleanup_failed_create(
        unit, state
    )  # Reads ORIGINAL template safety, never corrected policy.
    state.pop("recoveryPending", None)
    backend.reset_after_cleanup(
        state
    )  # New input always discards old delivery and approval.
    backend.load_inputs(unit)


def _observe_only_no_mutation():
    raise Blocked("observation-only resume cannot mutate AWS or publish Models")


def observe_only(backend, units, limit, path, session):
    """Explicit observation of original execution tokens."""
    run_group = _imports_deploy_scheduler.run_group
    backend.states, backend.session = session["states"], session
    backend.save = lambda: handoff.save(path, session)
    no_mutation = _observe_only_no_mutation
    backend.guard = no_mutation
    for unit in units:
        backend.templates[unit["name"]] = ({}, {})
    running = [
        unit for unit in units if session["states"][unit["name"]]["status"] == "RUNNING"
    ]
    if running:
        run_group(
            running, limit, session["states"], backend, backend.save, drain_only=True
        )
    backend.save()
    return (
        2
        if any(
            state["status"] == "RUNNING" or state.get("pollError")
            for state in session["states"].values()
        )
        else 0
    )
