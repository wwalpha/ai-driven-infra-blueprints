"""Narrow preparation corrections through the current Task, never AWS replay."""

import copy
import hashlib
import re
from functools import partial
from types import SimpleNamespace

import task_contract_core as tasks
import worktree_state as ws
from contracts.deploy import DEPLOY_SUCCESS
from contracts.target import AWS_ACCOUNT_ID_KEY, IAC_ENGINE_KEY
from model.dependency_index import revision as file_revision
from model.render import owned_artifacts
from model.sources import load_model, publication_lock, source_scope
from utils.file_operations import atomic_files, sha
from utils.local_evidence import evidence_store, read_sealed, sealed, write_sealed
from utils.project_targets import load_target_directory
from validation.findings import Findings
from validation.task import TaskValidation

from deploy import (
    completion,
    contracts,
    correction_scope,
    deferred,
    generation_resume,
    handoff,
    inputs,
    observed_resume,
    operation_journal,
    run_context,
    worktree,
)
from deploy import progress as deploy_progress


def original_contract(state):
    text = state.get("deployContract")
    if (
        not isinstance(text, str)
        or tasks.task_digest(text) != state["deployIdentity"]["taskDigest"]
    ):
        raise ws.Blocked("fixed Deploy contract evidence is missing or inconsistent")
    return text


def unchanged_authority(before, after):
    # Do not use task_digest: it deliberately excludes destructive-change consent.
    return re.sub(
        r"^## (?:Validation scope|Modified files|Allowed paths)\n.*?(?=^## |\Z)",
        "",
        tasks.set_status(before, "running"),
        flags=re.M | re.S,
    ) == re.sub(
        r"^## (?:Validation scope|Modified files|Allowed paths)\n.*?(?=^## |\Z)",
        "",
        tasks.set_status(after, "running"),
        flags=re.M | re.S,
    )


def output_paths(root, snapshot):
    result = set()
    for environment, directory, service in snapshot.scope or ():
        source = root / f"model/{environment}/{directory}/{service}.properties"
        model = load_model(source)
        result.update(
            p.relative_to(root).as_posix()
            for p in model.dependencies
            if p.is_relative_to(source.parent) and source_scope(root, p).path == source
        )
        design = root / f"docs/designs/{environment}/{directory}/{service}.md"
        result.update(
            p.relative_to(root).as_posix()
            for p in (design, *owned_artifacts(design, model.values))
        )
    return result


def check_candidate(root, task, original, candidate, state, context, approved):
    tasks.preflight_contract(root, task.name, candidate)
    if (
        task.status != "suspend"
        or tasks.status(candidate) != "suspend"
        or tasks.section(task.text, "## Suspension reason")
        != tasks.section(candidate, "## Suspension reason")
        or not worktree.is_deploy(original)
        or not unchanged_authority(original, task.text)
        or not unchanged_authority(original, candidate)
        or not unchanged_authority(task.text, candidate)
    ):
        raise ws.Blocked(
            "correction requires suspended same Deploy authority, Goal, target and consent"
        )
    consumers = correction_scope.additions(
        root, task, original, candidate, state, context, approved
    )
    added = set()
    for heading in ("## Modified files", "## Allowed paths"):
        old, new = tasks.paths_in(original, heading), tasks.paths_in(candidate, heading)
        live = tasks.paths_in(task.text, heading)
        if not old <= live <= new or not old <= new:
            raise ws.Blocked("correction permits only omitted exact output paths")
        for relative in new - old:
            tasks.safe_path(root, relative)
        added.update(new - old)
    snapshot = tasks.replace(task, text=candidate)
    paths = (
        correction_scope.output_paths(root, snapshot, consumers)
        if consumers or snapshot.scope != tasks.replace(task, text=original).scope
        else output_paths(root, task)
    )
    if (
        (not added and snapshot.scope == task.scope)
        or added - paths
        or added & set(context.get("inputIdentities", {}))
    ):
        raise ws.Blocked(
            "correction paths must be necessary exact Model/Views in the proven service scope"
        )
    findings = Findings(root)
    TaskValidation(root, findings, contract_file=task.name).check_task_scope(candidate)
    if findings.errors:
        raise ws.Blocked("corrected Task scope: " + "; ".join(findings.errors))
    return consumers


def check_state(root, state, progress, task, consumers=(), candidate=None):
    identity = state["deployIdentity"]
    context = progress["runContext"] if progress else None
    if context is None:
        raise ws.Blocked("saved fixed execution input evidence is missing")
    if (
        identity.get("taskFile") != task.name
        or {(env, directory) for env, directory, _ in task.scope or ()}
        != {(identity["environment"], context.get("directory"))}
        or identity["target"].get(IAC_ENGINE_KEY) != "cloudformation"
    ):
        raise ws.Blocked("fixed Deploy identity differs from the Task target/snapshot")
    run_context.active_scope(
        root,
        identity["stacks"],
        identity["environment"],
        identity["target"][AWS_ACCOUNT_ID_KEY],
        identity["target"].get("alias"),
        snapshot=tasks.replace(task, text=tasks.set_status(task.text, "running")),
    )
    if context.get("inputDigest") != inputs.fingerprint(
        [str(root), identity["target"], identity["environment"], context["stepUnits"]]
    ):
        raise ws.Blocked("saved run input identity is inconsistent")
    failure_path = None
    if context.get("currentFailure"):
        failure = context["currentFailure"]
        if not isinstance(failure, str):
            raise ws.Blocked(
                "currentFailure has no readable failure evidence; retain and review it"
            )
        failure_path = handoff.external(root, failure)
        store = evidence_store(root, create=False)
        if failure_path.parent != store or not re.fullmatch(
            r"deploy-failure-[a-zA-Z0-9-]+\.json", failure_path.name
        ):
            raise ws.Blocked("currentFailure evidence location is unknown")
        try:
            operation_journal.private_path(failure_path)
            record = read_sealed(root, failure_path)
        except OSError as error:
            raise ws.Blocked(
                "currentFailure evidence is missing or unreadable"
            ) from error
        if (
            record.get("taskDigest") != identity["taskDigest"]
            or record.get("taskFile") != task.name
            or record.get("repository") != str(root)
            or record.get("target") != identity["target"]
            or record.get("environment") != identity["environment"]
            or record.get("directory") != context["directory"]
        ):
            raise ws.Blocked(
                "currentFailure ownership differs; retain evidence and review existing repair/discard operation"
            )
        failures = record.get("states")
        if not candidate or not isinstance(failures, dict) or not failures:
            raise ws.Blocked("currentFailure scope cause cannot be proven")
        if set(failures) != {
            name
            for name, item in context["states"].items()
            if item.get("status") in {"FAILED", "BLOCKED"}
        }:
            raise ws.Blocked("currentFailure does not cover every current failure")
        owners = correction_scope.ownership(root, state, context)
        before = tasks.replace(task, text=original_contract(state)).scope or frozenset()
        after = tasks.replace(task, text=candidate).scope or frozenset()
        for name, saved in failures.items():
            current = copy.deepcopy(context["states"].get(name))
            if not isinstance(current, dict) or not isinstance(saved, dict):
                raise ws.Blocked("currentFailure Stack evidence is unknown")
            current.pop("approvedChangeDigest", None)
            saved = {
                key: value
                for key, value in saved.items()
                if key in operation_journal.OPERATION_FIELDS
                or key
                in {
                    "currentStack",
                    "reason",
                }
            }
            detail = saved.get("failure", {})
            if not isinstance(detail, dict):
                raise ws.Blocked("currentFailure classification is invalid")
            missing = detail.get("owners")
            if (
                current != saved
                or saved.get("status") != "BLOCKED"
                or detail.get("stage") != "PREPARATION"
                or detail.get("classification") != "OWNER_SCOPE_MISSING"
                or detail.get("executionState") != "NOT_SUBMITTED"
                or not isinstance(missing, list)
                or not missing
            ):
                raise ws.Blocked("currentFailure is not a proven scope failure")
            if saved.get("executionEvidence") or saved.get("attemptResult") == "UNKNOWN":
                raise ws.Blocked("current execution outcome is unknown")
            for item in missing:
                if not isinstance(item, dict) or set(item) != {
                    "logicalId",
                    "service",
                    "resource",
                }:
                    raise ws.Blocked("currentFailure owner evidence is invalid")
                key = (identity["environment"], context["directory"], item["service"])
                if (
                    owners.get(name, {}).get(item["logicalId"])
                    != {"service": item["service"], "resource": item["resource"]}
                    or key in before
                    or key not in after
                ):
                    raise ws.Blocked(
                        "currentFailure owner is not covered by correction"
                    )
    if context.get("generationError") and not context.get("pendingGeneration"):
        raise ws.Blocked(
            "generationError has no retained generation Intent; safe correction cannot be proven"
        )
    store = evidence_store(root, create=False)
    retained = set()
    history = context.get("resolvedScopeFailures", [])
    if not isinstance(history, list):
        raise ws.Blocked("resolved scope failure history is invalid")
    for entry in history:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"evidence", "sha256", "taskDigest", "correctedTaskDigest"}
            or not all(isinstance(value, str) and value for value in entry.values())
        ):
            raise ws.Blocked("resolved scope failure history is inconsistent")
        retained_path = handoff.external(root, entry["evidence"])
        if retained_path.parent != store or retained_path in retained:
            raise ws.Blocked("resolved scope failure evidence location is invalid")
        try:
            operation_journal.private_path(retained_path)
            retained_record = read_sealed(root, retained_path)
            digest = sha(retained_path)
        except OSError as error:
            raise ws.Blocked("resolved scope failure evidence is missing") from error
        if (
            digest != entry["sha256"]
            or retained_record.get("taskDigest") != entry["taskDigest"]
            or retained_record.get("taskFile") != task.name
            or retained_record.get("repository") != str(root)
            or retained_record.get("target") != identity["target"]
            or retained_record.get("environment") != identity["environment"]
            or retained_record.get("directory") != context["directory"]
        ):
            raise ws.Blocked("resolved scope failure evidence changed")
        retained.add(retained_path)
    if (
        any(store.glob("deploy-repair-*"))
        or any(
            p != failure_path and p not in retained
            for p in store.glob("deploy-failure-*")
        )
        or any(store.glob("deploy-cleanup-*"))
    ):
        raise ws.Blocked(
            "retain and review repair handoff/failure evidence before correction"
        )
    if context.get("repository") != str(root):
        raise ws.Blocked("saved progress repository changed")
    plan = context.get("pendingObserved") or {}
    for relative, digest in context.get("modelInputs", {}).items():
        path = tasks.safe_path(root, relative)
        permitted = {digest}
        if relative in plan.get("beforeManifest", {}):
            permitted = {
                plan["beforeManifest"][relative],
                plan["afterManifest"][relative],
            }
        if not path.is_file() or sha(path) not in permitted:
            raise ws.Blocked("saved Model input changed: " + relative)
    target = load_target_directory(root, identity["environment"], context["directory"])
    if target != identity["target"]:
        raise ws.Blocked("fixed Deploy target/Account/Region changed")
    _, units = inputs.load_units(
        root, identity["environment"], context["directory"], identity["stacks"]
    )
    if units != context["stepUnits"]:
        raise ws.Blocked("fixed Deploy execution units changed")
    for name, item in context["states"].items():
        if (
            item.get("status")
            not in {"NOT_STARTED", DEPLOY_SUCCESS, "FAILED", "SETTLED", "BLOCKED"}
            or completion.current_category(item) in {"RUNNING", "UNKNOWN"}
            and item.get("currentStack")
            or item.get("attemptResult") == "UNKNOWN"
        ):
            raise ws.Blocked("unresolved or active AWS request: " + name)
    expected = {
        p.relative_to(root).as_posix()
        for p in inputs.deployment_input_paths(
            root, identity["environment"], context["directory"], target, units
        )
    }
    manifests = context.get("inputIdentities", {})
    if set(manifests) != expected or not set(context["consumedInputs"]) <= expected:
        raise ws.Blocked("fixed execution input file set is incomplete or changed")
    if set(context["inputDigests"]) - set(identity["stacks"]):
        raise ws.Blocked("saved execution digest belongs to another Stack")
    for relative in expected:
        path = tasks.safe_path(root, relative)
        if (
            not path.is_file()
            or file_revision(path) != manifests[relative]
            or relative in context["consumedInputs"]
            and sha(path) != context["consumedInputs"][relative]
        ):
            raise ws.Blocked("fixed execution input changed: " + relative)
    for unit in units:
        paths = inputs.deployment_input_paths(
            root, identity["environment"], context["directory"], target, [unit]
        )
        digest = inputs.fingerprint([sha(p) for p in paths])
        if (
            unit["name"] in context["inputDigests"]
            and context["inputDigests"][unit["name"]] != digest
        ):
            raise ws.Blocked("fixed execution digest changed: " + unit["name"])
    completion.verify_observation_delta(root)


def pending_identity(root, task, candidate, state, saved, consumers, *, journal=None):
    """Validate the same signed candidates under the corrected, still fixed authority."""
    context = saved["runContext"]
    original = original_contract(state)
    old_bytes = hashlib.sha256(
        tasks.set_status(original, "running").encode("utf-8")
    ).hexdigest()
    plans = list(context.get("pendingGeneration", {}).values())
    if context.get("pendingObserved"):
        plans.append(context["pendingObserved"])
    if any(plan["identity"].get("taskBytes") != old_bytes for plan in plans):
        raise ws.Blocked(
            "pending publication Task bytes differ from the fixed original contract"
        )
    running = tasks.set_status(candidate, "running")
    raw = running.encode("utf-8")
    snapshot = tasks.replace(
        task, text=running, raw=raw, raw_digest=hashlib.sha256(raw).hexdigest()
    )
    with (
        tasks.selected_task(root, task.name),
        tasks.task_reads(root, snapshot=snapshot),
    ):
        observed_resume.reauthorize(
            SimpleNamespace(
                root=root,
                run_context=context,
                target=context["target"],
                environment=context["environment"],
                directory=context["directory"],
            ),
            snapshot,
            preserve_candidates=True,
        )
        if context.get("pendingObserved"):
            plan = observed_resume.validate_plan(
                root,
                context,
                context["target"],
                context["environment"],
                context["directory"],
            )
            if not set(plan["evidence"]) <= set(context["states"]) or plan[
                "evidence"
            ] != observed_resume.evidence(context["states"], plan["evidence"]):
                raise ws.Blocked("pending Observed AWS execution evidence changed")
            observed_resume.classify(
                observed_resume.manifest(
                    {
                        p.relative_to(root).as_posix(): b
                        for p, b in observed_resume.plan_snapshot(root, plan).items()
                    }
                ),
                plan["beforeManifest"],
                plan["afterManifest"],
                mixed=journal is not None,
            )
            observed_resume.check_generated(root, plan, mixed=journal is not None)
            correction_scope.pending_outputs(root, state, context, consumers)
        generation_resume.validate(
            root,
            context,
            context["target"],
            context["environment"],
            context["directory"],
        )
        for record in context.get("pendingGeneration", {}).values():
            observed_resume.check_generated(root, record, mixed=journal is not None)
        if journal is not None:
            if context.get("pendingObserved"):
                observed_resume._callback_reconcile_recovery(
                    context["directory"],
                    context["environment"],
                    root,
                    context,
                    context["target"],
                    journal,
                    snapshot=snapshot,
                )
            elif context.get("pendingGeneration"):
                generation_resume.recover_journal(
                    root,
                    context,
                    context["target"],
                    context["environment"],
                    context["directory"],
                    journal,
                )
            else:
                raise ws.Blocked(
                    "publication journal has no retained Deploy Intent; preserve it for existing recovery"
                )


def guard_snapshot(root, state):
    manifest = {
        k: v
        for k, v in contracts.validation_snapshot(root).items()
        if k != state["task_file"]
    }
    store = evidence_store(root, create=False)
    return {
        "head": contracts.output(root, "rev-parse", "HEAD"),
        "index": ws.git(root, "ls-files", "--stage", "-z").stdout,
        "inputs": manifest,
        "fileIdentities": {
            p: file_revision(root / p) if (root / p).is_file() else None
            for p in manifest
        },
        "repairEvidence": sorted(
            [p.name, sha(p) if p.is_file() else None]
            for pattern in ("deploy-repair-*", "deploy-failure-*", "deploy-cleanup-*")
            for p in store.glob(pattern)
        ),
    }


def local_state(saved):
    return {
        "task_file": saved["identity"]["taskFile"],
        "deployIdentity": saved["identity"],
        "deployContract": saved["runContext"].get("deployContract"),
    }


def recover_local_correction(root, name, source, path, intent_path):
    intent = read_sealed(root, intent_path)
    task_path = tasks.safe_path(root, name)
    if (
        intent["afterTask"] != source
        or guard_snapshot(root, {"task_file": name}) != intent["guard"]
        or task_path.read_bytes().decode("utf-8") not in (intent["beforeTask"], source)
        or path.read_bytes().decode("utf-8") not in (intent["beforeProgress"], intent["afterProgress"])
    ):
        raise ws.Blocked("unfinished contract correction changed; retain its evidence")
    atomic_files({task_path: intent["beforeTask"], path: intent["beforeProgress"]})
    intent_path.unlink()
    tasks.invalidate_task_reads(root)


def review_local_correction(root, name, path, candidate, approved, *, journal=None):
    task = tasks.read_task_snapshot(root, name, live=True)
    # The live suspended Task may already include the Human's proposed exact additions.
    saved = read_sealed(root, path)
    state = local_state(saved)
    saved = deploy_progress.read_progress(root, state, name)
    original = original_contract(state)
    context = saved["runContext"]
    consumers = check_candidate(root, task, original, candidate, state, context, approved)
    check_state(root, state, saved, task, consumers, candidate)
    pending_identity(root, task, candidate, state, saved, consumers, journal=journal)
    return task, saved, consumers


def correct_local(root, name, source, path, approved):
    source = source.resolve()
    if source.is_relative_to(root):
        raise ws.Blocked("contract correction candidate must be outside the repository")
    source_raw = source.read_bytes()
    candidate = source_raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    intent_path = deploy_progress.correction_path(path)
    with (
        operation_journal.locked(path),
        handoff.repair_lock(root),
    ):
        if intent_path.exists() or intent_path.is_symlink():
            recover_local_correction(root, name, candidate, path, intent_path)
        recovery = partial(review_local_correction, root, name, path, candidate, approved)
        with publication_lock(root, recovery_check=partial(recover_local_publication, recovery)):
            guard = guard_snapshot(root, {"task_file": name})
            before = path.read_bytes().decode("utf-8")
            task, saved, consumers = recovery()
            context = saved["runContext"]
            identity = saved["identity"]
            revised = tasks.task_digest(candidate)
            failure = context.pop("currentFailure", None)
            if failure:
                context.setdefault("resolvedScopeFailures", []).append({
                    "evidence": failure,
                    "sha256": sha(handoff.external(root, failure)),
                    "taskDigest": identity["taskDigest"],
                    "correctedTaskDigest": revised,
                })
            for item in context["states"].values():
                for record in item.get("deferredConsumers", []):
                    for consumer in consumers:
                        if deferred.key(record) == deferred.key(consumer):
                            record.update(consumer, approved=True)
            identity["taskDigest"] = revised
            context.update(taskDigest=revised, deployContract=candidate, snapshotValidation="NOT_RUN")
            after = sealed(root, saved)
            tasks.verify_snapshot(task)
            if (
                source.read_bytes() != source_raw
                or path.read_bytes().decode("utf-8") != before
                or guard_snapshot(root, {"task_file": name}) != guard
            ):
                raise ws.Blocked("contract correction inputs changed before save")
            write_sealed(root, intent_path, {
                "beforeTask": task.raw.decode("utf-8"), "afterTask": candidate,
                "beforeProgress": before, "afterProgress": after, "guard": guard,
            })
            atomic_files({task.path: candidate, path: after})
            intent_path.unlink()
            tasks.invalidate_task_reads(root)


def recover_local_publication(review, journal):
    review(journal=journal)


def correct(root, name, source, approved=()):
    name = tasks.normalize_selector(name)
    path = deploy_progress.progress_path(root, name)
    if path.exists() or path.is_symlink() or deploy_progress.correction_path(path).exists():
        return correct_local(root, name, source, path, approved)
    raise ws.Blocked("saved fixed Deploy progress evidence is missing")
