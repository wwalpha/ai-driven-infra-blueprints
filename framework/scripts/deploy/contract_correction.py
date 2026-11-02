"""Narrow preparation corrections through the current Task, never AWS replay."""

import copy
import json
import re
from contextlib import ExitStack

import task_contract_core as tasks
import worktree_state as ws
import worktree_task as wt
from model.dependency_index import revision as file_revision
from model.render import owned_artifacts
from model.sources import load_model, publication_lock, source_scope
from utils.file_operations import atomic_files, sha
from utils.local_evidence import evidence_store, read_sealed, sealed
from utils.project_targets import load_target_directory
from validation.findings import Findings
from validation.task import TaskValidation

from deploy import (
    contracts,
    current_request,
    git_publication,
    handoff,
    inputs,
    operation_journal,
    run_context,
    worktree,
)


def original_contract(root, state):
    """Old installations may have the text in Git, but a digest cannot recover it."""
    digest = state["deployIdentity"]["taskDigest"]
    text = state.get("deployContract")
    if text is not None:
        if not isinstance(text, str) or tasks.task_digest(text) != digest:
            raise ws.Blocked("fixed Deploy contract evidence is inconsistent")
        return text
    for revision in dict.fromkeys((state["tip"], state["start"])):
        result = ws.git(root, "show", revision + ":" + state["task_file"], check=False)
        if result.returncode == 0 and tasks.task_digest(result.stdout) == digest:
            return result.stdout
    raise ws.Blocked(
        "original fixed Deploy contract text is unavailable; do not infer it"
    )


def unchanged_authority(before, after):
    # Do not use task_digest: it deliberately excludes destructive-change consent.
    return re.sub(
        r"^## (?:Modified files|Allowed paths)\n.*?(?=^## |\Z)",
        "",
        tasks.set_status(before, "running"),
        flags=re.M | re.S,
    ) == re.sub(
        r"^## (?:Modified files|Allowed paths)\n.*?(?=^## |\Z)",
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


def check_candidate(root, task, original, candidate):
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
    added = set()
    for heading in ("## Modified files", "## Allowed paths"):
        old, new = tasks.paths_in(original, heading), tasks.paths_in(candidate, heading)
        live = tasks.paths_in(task.text, heading)
        if not old <= live <= new or not old <= new:
            raise ws.Blocked("correction permits only omitted exact output paths")
        for relative in new - old:
            tasks.safe_path(root, relative)
        added.update(new - old)
    if not added or added - output_paths(root, task):
        raise ws.Blocked(
            "correction paths must be necessary Model/Views in the unchanged service scope"
        )
    findings = Findings(root)
    TaskValidation(root, findings, contract_file=task.name).check_task_scope(candidate)
    if findings.errors:
        raise ws.Blocked("corrected Task scope: " + "; ".join(findings.errors))


def check_state(root, state, progress, task):
    identity = state["deployIdentity"]
    context = progress["runContext"] if progress else None
    if context is None:
        raise ws.Blocked("saved fixed execution input evidence is missing")
    if (
        identity.get("taskFile") != task.name
        or identity.get("snapshot") != state["start"]
        or {(env, directory) for env, directory, _ in task.scope or ()}
        != {(identity["environment"], context.get("directory"))}
        or identity["target"].get("iacEngine") != "cloudformation"
    ):
        raise ws.Blocked("fixed Deploy identity differs from the Task target/snapshot")
    run_context.active_scope(
        root,
        identity["stacks"],
        identity["environment"],
        identity["target"]["awsAccountId"],
        identity["target"].get("alias"),
        snapshot=tasks.replace(task, text=tasks.set_status(task.text, "running")),
    )
    if context.get("inputDigest") != inputs.fingerprint(
        [str(root), identity["target"], identity["environment"], context["stepUnits"]]
    ):
        raise ws.Blocked("saved run input identity is inconsistent")
    for key in (
        "deployCheckpointIntent",
        "stackCheckpointIntent",
        "deployRepair",
        "deployIntegrationIntent",
        "iacRepair",
    ):
        if state.get(key):
            raise ws.Blocked("contract correction blocked by " + key)
    publication = state.get("deployPublication", {})
    if publication and (
        publication.get("status") != "SUCCESS"
        or publication.get("intent")
        or publication.get("finalCandidate")
        or publication.get("publishedSource") != state["tip"]
    ):
        raise ws.Blocked(
            "finish or review saved Git publication before contract correction"
        )
    for key in (
        "pendingObserved",
        "pendingGeneration",
        "generationError",
        "checkpointPending",
        "currentFailure",
    ):
        if context.get(key):
            raise ws.Blocked("contract correction blocked by retained " + key)
    store = evidence_store(root, create=False)
    if (
        any(store.glob("deploy-repair-*"))
        or any(store.glob("deploy-failure-*"))
        or any(store.glob("deploy-cleanup-*"))
    ):
        raise ws.Blocked(
            "retain and review repair handoff/failure evidence before correction"
        )
    if context.get("repository") != str(root):
        raise ws.Blocked("saved progress repository changed")
    for relative, digest in context.get("modelInputs", {}).items():
        path = tasks.safe_path(root, relative)
        if not path.is_file() or sha(path) != digest:
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
            item.get("requestPending")
            or item.get("requestError")
            or item.get("createUnconfirmed")
            or item.get("status")
            not in {"NOT_STARTED", "SUCCESS", "FAILED", "SETTLED", "BLOCKED"}
            or worktree.current_category(item) in {"RUNNING", "UNKNOWN"}
            and item.get("currentStack")
            or item.get("clientToken")
            and not item.get("endedRequest")
            or current_request.read(current_request.location(target, name)) is not None
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
    if state.get("deployCheckpoints"):
        git_publication.checkpoint_source(root, state, progress)


def guard_snapshot(root, state):
    manifest = {
        k: v
        for k, v in contracts.validation_snapshot(root).items()
        if k != state["task_file"]
    }
    identity = state["deployIdentity"]
    store = evidence_store(root, create=False)
    return {
        "head": wt.output(root, "rev-parse", "HEAD"),
        "index": ws.git(root, "ls-files", "--stage", "-z").stdout,
        "inputs": manifest,
        "fileIdentities": {
            p: file_revision(root / p) if (root / p).is_file() else None
            for p in manifest
        },
        "requests": {
            name: current_request.read(
                current_request.location(identity["target"], name)
            )
            for name in identity["stacks"]
        },
        "repairEvidence": sorted(
            p.name
            for pattern in ("deploy-repair-*", "deploy-failure-*", "deploy-cleanup-*")
            for p in store.glob(pattern)
        ),
    }


def template_owners(root, state, candidate_digest=None):
    """Template ownership is current cleanup evidence, never an AWS authorization."""
    identity = state["deployIdentity"]
    digests = {identity["taskDigest"]}
    if candidate_digest is not None:
        digests.add(candidate_digest)
    result = {}
    directory = operation_journal.location(identity["target"]).parent
    for path in sorted(directory.glob("inputs-*/owner.json")):
        operation_journal.private_path(path.parent, directory=True)
        owner = read_sealed(root, path)
        if not isinstance(owner, dict):
            raise ws.Blocked("temporary template ownership evidence is corrupt")
        if (
            owner.get("repository") != str(root)
            or owner.get("taskFile") != state["task_file"]
        ):
            continue
        if (
            owner.get("target") != identity["target"]
            or owner.get("taskDigest") not in digests
            or not isinstance(owner.get("files"), list)
            or not all(isinstance(name, str) for name in owner["files"])
            or len(set(owner["files"])) != len(owner["files"])
            or not set(owner["files"]) <= {s + ".json" for s in identity["stacks"]}
        ):
            raise ws.Blocked(
                "temporary template owner differs from fixed Deploy authority"
            )
        result[path] = path.read_bytes().decode("utf-8")
    return result


def recover_update(root, path, state, candidate):
    intent = state["deployContractUpdate"]
    before = intent["state"]
    if (
        candidate != intent["afterTask"]
        or state != dict(before, deployContractUpdate=intent)
        or guard_snapshot(root, before) != intent["guard"]
    ):
        raise ws.Blocked(
            "unfinished contract correction inputs changed; retain all evidence"
        )
    task_path, progress_path = (
        tasks.safe_path(root, before["task_file"]),
        worktree.progress_path(root),
    )
    owners = template_owners(root, before, tasks.task_digest(candidate))
    if {str(p) for p in owners} != set(intent["beforeOwners"]):
        raise ws.Blocked("temporary template owner set changed during correction")
    originals = {}
    for file, raw in owners.items():
        if raw not in (
            intent["beforeOwners"][str(file)],
            intent["afterOwners"][str(file)],
        ):
            raise ws.Blocked("temporary template owner changed during correction")
        originals[file] = intent["beforeOwners"][str(file)]
    for file, key in ((task_path, "Task"), (progress_path, "Progress")):
        if file.read_bytes().decode("utf-8") not in (
            intent["before" + key],
            intent["after" + key],
        ):
            raise ws.Blocked(
                "concurrent edit during interrupted contract correction: " + str(file)
            )
    atomic_files(
        {
            task_path: intent["beforeTask"],
            progress_path: intent["beforeProgress"],
            **originals,
            path: json.dumps(before, indent=2) + "\n",
        }
    )
    tasks.invalidate_task_reads(root)


def correct(root, name, source):
    source = source.resolve()
    if source.is_relative_to(root):
        raise ws.Blocked("contract correction candidate must be outside the repository")
    source_raw = source.read_bytes()
    candidate = source_raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    primary, _, path, initial = ws.load(
        root, tasks.normalize_selector(name).removeprefix("tasks/").removesuffix(".md")
    )
    identity = initial.get("deployIdentity")
    if not identity or initial["worktree"] != str(root):
        raise ws.Blocked("correction requires this managed fixed Deploy Task")
    with ExitStack() as locks:
        locks.enter_context(
            operation_journal.locked(worktree.progress_path(root, create=True))
        )
        for stack in sorted(identity["stacks"]):
            locks.enter_context(
                operation_journal.locked(
                    current_request.location(identity["target"], stack)
                )
            )
        locks.enter_context(handoff.repair_lock(root))
        locks.enter_context(publication_lock(root, read_only=True))
        locks.enter_context(wt.lifecycle_lock(primary))
        state = ws.load(root, initial["task_id"])[3]
        if state != initial:
            raise ws.Blocked("Deploy lifecycle changed before correction locks")
        ws.deploy_task_state(root, name, required=True)
        if state.get("deployContractUpdate"):
            recover_update(root, path, state, candidate)
        _, state = ws.deploy_task_state(root, name, required=True)
        if state.get("python_setup", {}).get("status") != "ready":
            raise ws.Blocked("Deploy requires successful managed Python setup")
        task = tasks.read_task_snapshot(root, name, live=True)
        original = original_contract(root, state)
        guard = guard_snapshot(root, state)
        progress_path = worktree.progress_path(root)
        before_progress = (
            progress_path.read_text(encoding="utf-8")
            if progress_path.is_file()
            else None
        )
        progress = worktree.read_progress(root, state)
        owners = template_owners(root, state)
        check_candidate(root, task, original, candidate)
        check_state(root, state, progress, task)
        revised, saved = copy.deepcopy(state), copy.deepcopy(progress)
        new_identity = dict(identity, taskDigest=tasks.task_digest(candidate))
        revised.update(deployIdentity=new_identity, deployContract=candidate)
        saved["identity"] = new_identity
        saved["runContext"]["taskDigest"] = new_identity["taskDigest"]
        saved["runContext"]["snapshotValidation"] = "NOT_RUN"
        for receipt in revised.get("deployCheckpoints", {}).values():
            receipt.update(
                identity=copy.deepcopy(new_identity),
                taskDigest=new_identity["taskDigest"],
            )
        after_progress = sealed(root, saved)
        revised_owners = {
            p: sealed(
                root, dict(read_sealed(root, p), taskDigest=new_identity["taskDigest"])
            )
            for p in owners
        }
        tasks.verify_snapshot(task)
        if (
            source.read_bytes() != source_raw
            or ws.load(root, state["task_id"])[3] != state
            or worktree.read_progress(root, state) != progress
            or progress_path.read_text(encoding="utf-8") != before_progress
            or guard_snapshot(root, state) != guard
            or template_owners(root, state) != owners
        ):
            raise ws.Blocked("contract correction inputs changed before save")
        intent = dict(
            state=state,
            guard=guard,
            beforeTask=task.raw.decode("utf-8"),
            afterTask=candidate,
            beforeProgress=before_progress,
            afterProgress=after_progress,
            beforeOwners={str(p): raw for p, raw in owners.items()},
            afterOwners={str(p): raw for p, raw in revised_owners.items()},
        )
        saving = dict(state, deployContractUpdate=intent)
        wt.save(path, saving)
        try:
            tasks.verify_snapshot(task)
            if (
                progress_path.read_text(encoding="utf-8") != before_progress
                or guard_snapshot(root, state) != guard
                or source.read_bytes() != source_raw
                or ws.load(root, state["task_id"])[3] != saving
                or template_owners(root, state) != owners
            ):
                raise ws.Blocked("contract correction inputs changed during save")
            atomic_files(
                {
                    task.path: candidate,
                    progress_path: after_progress,
                    **revised_owners,
                    path: json.dumps(revised, indent=2) + "\n",
                }
            )
        except BaseException:
            if (
                task.path.read_bytes() == task.raw
                and progress_path.read_text(encoding="utf-8") == before_progress
                and ws.load(root, state["task_id"])[3] == saving
                and template_owners(root, state) == owners
            ):
                wt.save(path, state)
            raise
        finally:
            tasks.invalidate_task_reads(root)
