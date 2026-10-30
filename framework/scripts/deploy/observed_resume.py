"""Exact, operation-owned observation plans around the existing Model transaction."""

import base64
import copy
import hashlib
from functools import partial as _bind_framework_callback
from pathlib import Path

import generation_inputs as _imports_generation_inputs
import model.adapters.observed as _imports_model_adapters_observed
from model.format import parse, patch
from model.observed import verify_observed_outputs
from model.sources import load_model, publication_lock, safe, source_scope
from task_contract_core import (
    matches,
    paths_in,
    task_read_scope,
    task_reads,
    task_snapshot,
    validate_contract,
)
from task_contract_core import task_digest as task_digest
from utils.cloudformation.inputs import Blocked

from deploy import generation_resume
from model import dependency_index


def source_snapshot(root, outputs):
    snapshots = {source_scope(root, path) for path in outputs}
    return {
        path: raw
        for scope in snapshots
        for path, raw in load_model(scope).dependencies.items()
    }


def plan_snapshot(root, plan):
    return {
        root / relative: (root / relative).read_bytes()
        if (root / relative).is_file()
        else None
        for relative in plan["beforeManifest"]
    }


def manifest(snapshot):
    return {
        str(path): None if raw is None else hashlib.sha256(raw).hexdigest()
        for path, raw in snapshot.items()
    }


EVIDENCE_FIELDS = (
    "status",
    "stackStatus",
    "stackId",
    "changeSetId",
    "changeDigest",
    "clientToken",
    "executionEvidence",
    "endedRequest",
)


def evidence(states, names):
    return {
        name: {key: copy.deepcopy(states[name].get(key)) for key in EVIDENCE_FIELDS}
        for name in names
    }


def inventory(root, directories):
    return sorted(
        path.relative_to(root).as_posix()
        for directory in directories
        for path in (root / directory).rglob("*.properties")
    )


def classify(current, before, after, *, mixed=False):
    if current == after:
        return "MODEL_PUBLISHED"
    if current == before:
        return "PREPARED"
    if (
        mixed
        and current.keys() == before.keys() == after.keys()
        and all(current[key] in (before[key], after[key]) for key in current)
    ):
        return "PARTIAL"
    raise Blocked("observed plan cannot explain current bytes or dependency file set")


def generated_plan(root, views):
    """Pin observed_destinations before any Model save or fallible generation."""
    GenerationInputs = _imports_generation_inputs.GenerationInputs
    snapshot = GenerationInputs(root)
    try:
        files = set(views)
        for view in (p for p in views if p.suffix == ".md"):
            files.update(
                snapshot.select(
                    view.with_suffix(""), "*.json", True, ("file", "symlink")
                )
            )
        originals = {}
        for path in files:
            safe(root, path)
            raw = snapshot.read(path)
            originals[path.relative_to(root).as_posix()] = (
                None if raw is None else base64.b64encode(raw).decode("ascii")
            )
        groups = {
            view.relative_to(root).as_posix(): sorted(
                p.relative_to(root).as_posix()
                for p in files
                if p == view or p.is_relative_to(view.with_suffix(""))
            )
            for view in views
            if view.suffix == ".md"
        }
        snapshot.verify()
        return {
            "groups": groups,
            "originals": originals,
            "outputs": None,
            "stage": "PREPARED",
        }
    finally:
        snapshot.close()


def generated_manifests(root, plan):
    generated = plan.get("generated")
    if not isinstance(generated, dict):
        raise Blocked(
            "observed plan has no generated-file evidence; safe resume cannot be proven"
        )
    groups, originals, outputs = (
        generated[key] for key in ("groups", "originals", "outputs")
    )
    if (
        not isinstance(groups, dict)
        or not groups
        or not isinstance(originals, dict)
        or generated["stage"] not in {"PREPARED", "CANDIDATE", "PUBLISHED"}
        or set(originals) != {p for files in groups.values() for p in files}
        or outputs is not None
        and (not isinstance(outputs, dict) or outputs.keys() != originals.keys())
    ):
        raise Blocked("invalid observed generated-file evidence")
    task = task_snapshot(root).text
    declared, allowed = (
        paths_in(task, "## Modified files"),
        paths_in(task, "## Allowed paths"),
    )
    for view, files in groups.items():
        if (
            not view.startswith("docs/designs/")
            or not view.endswith(".md")
            or view not in files
            or len(files) != len(set(files))
        ):
            raise Blocked("invalid observed generated-file group")
        for relative in files:
            path = root / relative
            safe(root, path)
            if (
                relative not in declared
                or not any(matches(relative, p) for p in allowed)
                or relative != view
                and (
                    path.suffix != ".json"
                    or path.parent != (root / view).with_suffix("")
                )
            ):
                raise Blocked("observed generated output outside Task authority")
    before = manifest(
        {
            p: None if raw is None else base64.b64decode(raw, validate=True)
            for p, raw in originals.items()
        }
    )
    after = (
        before
        if outputs is None
        else manifest({p: text.encode("utf-8") for p, text in outputs.items()})
    )
    return before, after


def check_generated(root, plan, *, mixed=False):
    before, after = generated_manifests(root, plan)
    current = {}
    for relative in before:
        path = root / relative
        safe(root, path)
        current[relative] = path.read_bytes() if path.is_file() else None
    generated = plan["generated"]
    for view in generated["groups"]:
        # Generation scans this exact artifact selection, including unexpected JSONs.
        for path in (root / view).with_suffix("").rglob("*.json"):
            if path.relative_to(root).as_posix() not in before:
                raise Blocked(
                    "observed generated file set changed: "
                    + str(path.relative_to(root))
                )
    current = manifest(current)
    classify(current, before, after, mixed=True)
    if not mixed:
        # Each service is one existing journal transaction; completed services may differ.
        for files in generated["groups"].values():
            classify(
                {p: current[p] for p in files},
                {p: before[p] for p in files},
                {p: after[p] for p in files},
            )
    return current


def verify_generated_journal(root, plan, record):
    before, after = generated_manifests(root, plan)
    generated = plan["generated"]
    if (
        "importReceipt" in record
        or generated["outputs"] is None
        or not record["originals"]
        or any(
            p not in generated["originals"] or raw != generated["originals"][p]
            for p, raw in record["originals"].items()
        )
        or not any(
            set(record["originals"]) == {p for p in files if before[p] != after[p]}
            for files in generated["groups"].values()
        )
    ):
        raise Blocked(
            "publication journal is not owned by this observed generated plan"
        )
    current = check_generated(root, plan, mixed=True)
    restored = {**current, **{p: before[p] for p in record["originals"]}}
    for files in generated["groups"].values():
        classify(
            {p: restored[p] for p in files},
            {p: before[p] for p in files},
            {p: after[p] for p in files},
        )


@task_read_scope
def _identity(root, run_context, target, environment, directory):
    snapshot = task_snapshot(root)
    task, text = snapshot.path, snapshot.text
    validate_contract(root, task.relative_to(root).as_posix(), text)
    if (
        run_context["repository"] != str(root)
        or run_context["taskFile"] != task.relative_to(root).as_posix()
        or run_context["taskDigest"] != task_digest(text)
    ):
        raise Blocked("observed plan Task/repository changed")
    return {
        "repository": str(root),
        "taskFile": run_context["taskFile"],
        "taskDigest": task_digest(text),
        "taskBytes": snapshot.raw_digest,
        "environment": environment,
        "directory": directory,
        "target": target,
        "inputDigest": run_context["inputDigest"],
    }


def reauthorize(backend, task):
    """Adopt signed unfinished publication only under this invocation's own authority."""
    context, root = backend.run_context, backend.root
    previous = {
        key: context[key]
        for key in (
            "repository",
            "taskFile",
            "taskDigest",
            "environment",
            "directory",
            "target",
            "inputDigest",
        )
    }
    candidate = dict(
        context, repository=str(root), taskFile=task.name, taskDigest=task.task_digest
    )
    identity = _identity(
        root, candidate, backend.target, backend.environment, backend.directory
    )
    plans = [*context.get("pendingGeneration", {}).values()]
    if context.get("pendingObserved"):
        plans.append(context["pendingObserved"])
    for plan in plans:
        saved = plan["identity"]
        if (
            set(saved) != set(identity)
            or {k: v for k, v in saved.items() if k != "taskBytes"} != previous
        ):
            raise Blocked("signed publication ownership differs from operation")
    # A saved candidate remains exact; a fresh patch preserves independent current edits.
    plan = context.get("pendingObserved")
    if plan and plan["generated"]["outputs"] is None:
        rebase_inputs(root, context, plan)
    context.update(
        repository=str(root), taskFile=task.name, taskDigest=task.task_digest
    )
    for plan in plans:
        plan["identity"] = copy.deepcopy(identity)
        for producer in plan.get("producers", []):
            path = Path(producer["producerModel"])
            if not path.is_relative_to(previous["repository"]):
                raise Blocked("pending Producer belongs to an unrelated repository")
            producer["producerModel"] = str(
                root / path.relative_to(previous["repository"])
            )
    if (
        not context.get("pendingObserved")
        and not any(
            item["generated"]["outputs"] is not None
            for item in context.get("pendingGeneration", {}).values()
        )
        and not any(
            state.get("status") == "SUCCESS"
            and not state.get("observedSynced")
            or state.get("bootstrap")
            or state.get("cleanupStatus") == "DELETE_INTENT"
            for state in context["states"].values()
        )
    ):
        # Observed is already committed: a fresh generation may consume the current Model.
        context["modelInputs"] = {}


def rebase_inputs(root, context, plan):
    for relative, encoded in list(plan["originals"].items()):
        path = root / relative
        safe(root, path)
        current = path.read_bytes()
        if manifest({relative: current})[relative] in (
            plan["beforeManifest"][relative],
            plan["afterManifest"][relative],
        ):
            continue
        original = base64.b64decode(encoded, validate=True)
        verify_observed_outputs({path: original}, {path: plan["outputs"][relative]})
        old = parse(original.decode("utf-8"))
        after = parse(plan["outputs"][relative])
        live = parse(current.decode("utf-8"))
        updates = {
            key: after.values.get(key)
            for key in old.values.keys() | after.values.keys()
            if old.values.get(key) != after.values.get(key)
        }
        resources = {key.split(".")[2].rpartition("-")[0] for key in updates}
        for key in old.values.keys() | live.values.keys():
            if old.values.get(key) == live.values.get(key) and (key in old.values) == (
                key in live.values
            ):
                continue
            if key in updates and live.values.get(key) in (
                old.values.get(key),
                after.values.get(key),
            ):
                continue
            parts = key.split(".")
            if (
                len(parts) >= 4
                and parts[0] == "desired"
                and parts[1] in {"resource", "row"}
            ):
                resource = (
                    parts[2] if parts[1] == "resource" else parts[2].rpartition("-")[0]
                )
                if resource not in resources:
                    continue
            raise Blocked(
                "observed recovery cannot explain third-party Model values: "
                + relative
                + ": "
                + key
            )
        before_text = patch(live, {key: old.values.get(key) for key in updates})
        after_text = patch(live, updates)
        plan["originals"][relative] = base64.b64encode(
            before_text.encode("utf-8")
        ).decode("ascii")
        plan["outputs"][relative] = after_text
        plan["beforeManifest"][relative] = manifest(
            {relative: before_text.encode("utf-8")}
        )[relative]
        plan["afterManifest"][relative] = manifest(
            {relative: after_text.encode("utf-8")}
        )[relative]
        context["modelInputs"][relative] = plan["beforeManifest"][relative]


def prepare(backend, units, outputs, services, views):
    root, run_context = backend.root, backend.run_context
    with publication_lock(root, read_only=True):
        before = source_snapshot(root, outputs)
        verify_observed_outputs(before, outputs)
        relative = {
            path.relative_to(root).as_posix(): raw for path, raw in before.items()
        }
        before_manifest = manifest(relative)
        if any(
            run_context["modelInputs"].get(p) != digest
            for p, digest in before_manifest.items()
        ):
            raise Blocked("Model inputs changed before observed plan")
        after = {
            **relative,
            **{
                path.relative_to(root).as_posix(): text.encode("utf-8")
                for path, text in outputs.items()
            },
        }
        directories = {
            str(source_scope(root, path).path.with_suffix("").relative_to(root))
            for path in outputs
        }
        generated = generated_plan(root, views)
        if (
            manifest(
                {
                    p.relative_to(root).as_posix(): raw
                    for p, raw in source_snapshot(root, outputs).items()
                }
            )
            != before_manifest
        ):
            raise Blocked("Model inputs changed during observed generation planning")
        run_context["pendingObserved"] = {
            "identity": _identity(
                root,
                run_context,
                backend.target,
                backend.environment,
                backend.directory,
            ),
            "evidence": evidence(
                run_context["states"], [unit["name"] for unit in units]
            ),
            "beforeManifest": before_manifest,
            "afterManifest": manifest(after),
            "originals": {
                path.relative_to(root).as_posix(): base64.b64encode(
                    before[path]
                ).decode("ascii")
                for path in outputs
            },
            "outputs": {
                path.relative_to(root).as_posix(): text
                for path, text in outputs.items()
            },
            "directories": sorted(directories),
            "inventory": inventory(root, directories),
            "services": services,
            "stage": "PREPARED",
            "generated": generated,
        }
        backend.save()  # A failed intent save must never reach Model publication.


@task_read_scope
def validate_plan(root, run_context, target, environment, directory):
    plan = run_context["pendingObserved"]
    if not isinstance(plan, dict) or any(
        not isinstance(plan.get(key), dict)
        for key in (
            "identity",
            "evidence",
            "beforeManifest",
            "afterManifest",
            "originals",
            "outputs",
        )
    ):
        raise Blocked("invalid observed plan records")
    if (
        plan["originals"].keys() != plan["outputs"].keys()
        or plan["beforeManifest"].keys() != plan["afterManifest"].keys()
    ):
        raise Blocked("observed plan file sets differ")
    if plan["identity"] != _identity(root, run_context, target, environment, directory):
        raise Blocked("observed plan Task/target/run identity changed")
    if {p: run_context["modelInputs"].get(p) for p in plan["beforeManifest"]} not in (
        plan["beforeManifest"],
        plan["afterManifest"],
    ):
        raise Blocked("observed plan/run input manifest mismatch")
    if plan["stage"] not in {"PREPARED", "MODEL_PUBLISHED"}:
        raise Blocked("unknown observed plan stage")
    before = {}
    outputs = {}
    declared = paths_in(task_snapshot(root).text, "## Modified files")
    allowed = paths_in(task_snapshot(root).text, "## Allowed paths")
    for relative, text in plan["outputs"].items():
        path = root / relative
        safe(root, path)
        if (
            not relative.startswith("model/")
            or relative not in declared
            or not any(matches(relative, p) for p in allowed)
        ):
            raise Blocked("observed plan output outside Task authority")
        before[path] = base64.b64decode(plan["originals"][relative], validate=True)
        outputs[path] = text
    verify_observed_outputs(before, outputs)
    original_hashes = manifest(
        {p.relative_to(root).as_posix(): raw for p, raw in before.items()}
    )
    if (
        any(
            plan["beforeManifest"].get(p) != digest
            for p, digest in original_hashes.items()
        )
        or {
            **plan["beforeManifest"],
            **manifest({p: t.encode("utf-8") for p, t in plan["outputs"].items()}),
        }
        != plan["afterManifest"]
    ):
        raise Blocked("observed plan candidate/manifest mismatch")
    for relative in plan["beforeManifest"]:
        safe(root, root / relative)
    directories = {
        str(source_scope(root, root / path).path.with_suffix("").relative_to(root))
        for path in plan["outputs"]
    }
    if plan["directories"] != sorted(directories):
        raise Blocked("observed discovery scope changed")
    if inventory(root, plan["directories"]) != plan["inventory"]:
        raise Blocked("observed Model file set changed")
    return plan


def verify_journal(plan, record, current):
    if (
        "importReceipt" in record
        or not record["originals"]
        or any(
            path not in plan["originals"] or raw != plan["originals"][path]
            for path, raw in record["originals"].items()
        )
    ):
        raise Blocked("publication journal is not owned by this observed plan")
    classify(current, plan["beforeManifest"], plan["afterManifest"], mixed=True)
    restored = {
        **current,
        **{path: plan["beforeManifest"][path] for path in record["originals"]},
    }
    if restored != plan["beforeManifest"]:
        raise Blocked("journal cannot restore the complete observed input state")


# Never let an unrelated transaction or third-party bytes be rolled back.
def _callback_reconcile_recovery(
    directory, environment, root, run_context, target, /, record
):
    with task_reads(root, live=True):
        # Never let an unrelated transaction or third-party bytes be rolled back.
        plan = validate_plan(root, run_context, target, environment, directory)
        current = {
            relative: (root / relative).read_bytes()
            if (root / relative).is_file()
            else None
            for relative in plan["beforeManifest"]
        }
        if record["originals"] and all(
            p.startswith("docs/designs/") for p in record["originals"]
        ):
            classify(manifest(current), plan["beforeManifest"], plan["afterManifest"])
            verify_generated_journal(root, plan, record)
        else:
            check_generated(root, plan)
            verify_journal(plan, record, manifest(current))


@task_read_scope
def reconcile(root, run_context, target, environment, directory):
    """Validate recovery before any read-only Model load can encounter a journal."""
    recovery = _bind_framework_callback(
        _callback_reconcile_recovery, directory, environment, root, run_context, target
    )

    with publication_lock(root, recovery_check=recovery):
        plan = validate_plan(root, run_context, target, environment, directory)
        current = {
            path.relative_to(root).as_posix(): raw
            for path, raw in plan_snapshot(root, plan).items()
        }
        stage = classify(
            manifest(current), plan["beforeManifest"], plan["afterManifest"]
        )
        check_generated(root, plan)
        dependency_index.update(
            root, {root / p for p in plan["outputs"]}, observed=True
        )
        plan["stage"] = stage
        run_context["modelInputs"] = {
            **run_context["modelInputs"],
            **(
                plan["beforeManifest"] if stage == "PREPARED" else plan["afterManifest"]
            ),
        }
    return stage


def finish(backend, units):
    publish_observed = _imports_model_adapters_observed.publish_observed

    root, run_context = backend.root, backend.run_context
    plan = run_context["pendingObserved"]
    stage = reconcile(
        root, run_context, backend.target, backend.environment, backend.directory
    )
    outputs = {root / path: text for path, text in plan["outputs"].items()}
    previous = plan_snapshot(root, plan)
    backend.guard()
    if stage == "PREPARED":
        publish_observed(root, outputs, previous)
        # The journal may be gone while the operation journal still says PREPARED.
        if (
            reconcile(
                root,
                run_context,
                backend.target,
                backend.environment,
                backend.directory,
            )
            != "MODEL_PUBLISHED"
        ):
            raise Blocked("observed publication did not produce the exact candidate")
    if getattr(backend, "_observed_cache_plan", None) is not plan and hasattr(
        backend, "after_observed"
    ):
        backend.after_observed(outputs)
        backend._observed_cache_plan = plan
    backend.guard()
    generation_resume.enqueue(backend, plan)
    # The journal saves the Model barrier and generation ownership in one revision.
    for name in plan["evidence"]:
        run_context["states"][name]["observedSynced"] = True
    run_context.pop("pendingObserved")
    backend.save()
    return outputs
