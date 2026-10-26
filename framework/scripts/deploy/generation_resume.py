"""Durable service generation after the Stack's atomic Observed barrier."""

import base64
import copy
from functools import partial
from pathlib import Path

import sync_runtime
from generation_inputs import GenerationInputs
from model.core import ReferenceResolutionError
from model.identity import Resolver
from model.importing.scope import read_context
from model.sources import publication_lock, safe, scope_for, session_reads, source_scope
from task_contract_core import task_read_scope
from utils.cloudformation.inputs import Blocked
from utils.iac_values import cfn_resource_identity

import deploy.observed_resume as observed


def complete(run_context):
    return (
        not run_context.get("pendingObserved")
        and not run_context.get("pendingGeneration")
        and not run_context.get("generationError")
        and all(
            state["status"] == "SUCCESS" and state.get("observedSynced")
            for state in run_context["states"].values()
        )
    )


def describe(run_context):
    if run_context.get("generationError"):
        return run_context["generationError"]
    return "pending design generation: " + "; ".join(
        key + ": " + record["reason"] + " " + str(record["producers"])
        for key, record in run_context.get("pendingGeneration", {}).items()
    )


def enqueue(backend, plan):
    """Transfer exact publication candidates only after their existing exact-byte guard."""
    root, run_context = backend.root, backend.run_context
    observed.check_generated(root, plan)
    pending = run_context.setdefault("pendingGeneration", {})
    for view, files in plan["generated"]["groups"].items():
        prior = pending.get(view)
        if prior is not None:
            if prior["generated"]["stage"] != "PREPARED":
                raise Blocked(
                    "unfinished generation candidate overlaps Observed: " + view
                )
            observed.check_generated(root, prior)
            continue
        generated = plan["generated"]
        pending[view] = {
            "identity": copy.deepcopy(plan["identity"]),
            "environment": backend.environment,
            "directory": backend.directory,
            "service": Path(view).stem,
            "reason": "Observed committed; generation required",
            "producers": [],
            "waitingModelManifest": retry_manifest(root, run_context, view),
            "candidateSelections": []
            if generated["outputs"] is None
            else [
                [
                    directory,
                    "*.properties",
                    True,
                    None,
                    [
                        p
                        for p in plan["inventory"]
                        if (root / p).is_relative_to(root / directory)
                    ],
                ]
                for directory in plan["directories"]
            ],
            "candidateManifest": copy.deepcopy(run_context["modelInputs"])
            if generated["outputs"] is not None
            else None,
            "generated": {
                "groups": {view: files},
                "originals": {p: generated["originals"][p] for p in files},
                "outputs": None
                if generated["outputs"] is None
                else {p: generated["outputs"][p] for p in files},
                "stage": generated["stage"],
            },
        }


@task_read_scope
def validate(root, run_context, target, environment, directory, views=None):
    identity = observed._identity(root, run_context, target, environment, directory)
    for view, record in run_context.get("pendingGeneration", {}).items():
        if views is not None and view not in views:
            continue
        if (
            record["identity"] != identity
            or record["environment"] != environment
            or record["directory"] != directory
            or view != f"docs/designs/{environment}/{directory}/{record['service']}.md"
            or set(record["generated"]["groups"]) != {view}
        ):
            raise Blocked("pending generation Task/target/run identity changed")
        observed.generated_manifests(root, record)
        if record["generated"]["outputs"] is not None and any(
            run_context["modelInputs"].get(p) != digest
            for p, digest in record["candidateManifest"].items()
        ):
            raise Blocked("generation candidate Model manifest changed")
        if record["generated"]["outputs"] is not None:
            for relative in record["candidateManifest"]:
                safe(root, root / relative)
            for base, pattern, recursive, kinds, expected in record[
                "candidateSelections"
            ]:
                safe(root, root / base)
                current_files = GenerationInputs.live_select(
                    root / base, pattern, recursive, kinds
                )
                if [p.relative_to(root).as_posix() for p in current_files] != expected:
                    raise Blocked("generation candidate Model file set changed")
            current = {
                p: (root / p).read_bytes() if (root / p).is_file() else None
                for p in record["candidateManifest"]
            }
            if observed.manifest(current) != record["candidateManifest"]:
                raise Blocked("generation candidate Model bytes changed")


def recover_journal(root, run_context, target, environment, directory, record):
    validate(root, run_context, target, environment, directory)
    owners = [
        item
        for item in run_context["pendingGeneration"].values()
        if set(record["originals"]) <= set(item["generated"]["originals"])
    ]
    if len(owners) != 1:
        raise Blocked("publication journal is not owned by pending generation")
    observed.verify_generated_journal(root, owners[0], record)


def reconcile(root, run_context, target, environment, directory, views=None):
    recovery = partial(
        recover_journal, root, run_context, target, environment, directory
    )
    with publication_lock(root, recovery_check=recovery):
        validate(root, run_context, target, environment, directory, views)
        return {
            view: observed.check_generated(root, record)
            for view, record in run_context.get("pendingGeneration", {}).items()
            if views is None or view in views
        }


def producers(backend, view, info, stage, resolver):
    """Only exact, indexed CREATE owners in this run can unblock a service."""
    diagnostics = info.get("diagnostics")
    if not diagnostics or any(
        d.get("category") != "REFERENCE_PENDING_DEPLOY" for d in diagnostics
    ):
        raise Blocked(
            "generation unavailable is not a pending CREATE reference: " + str(info)
        )
    root, run_context = backend.root, backend.run_context
    scope = scope_for(
        root
        / "model"
        / backend.environment
        / backend.directory
        / (view.stem + ".properties")
    )
    result = {}
    names = {u["name"] for u in backend.units}
    for diagnostic in diagnostics:
        logical = diagnostic.get("targetLogicalId")
        model = diagnostic.get("producerModel")
        if not isinstance(logical, str) or not isinstance(model, str):
            raise Blocked("pending reference has no exact Producer identity")
        producer_path = Path(model)
        if producer_path.is_relative_to(stage):
            producer_path = root / producer_path.relative_to(stage)
        snapshot, _, resource = resolver.resolve_logical(logical, scope)
        if (
            snapshot.scope.path != producer_path
            or resource.get("resourceMode", "CREATE") != "CREATE"
        ):
            raise Blocked("pending Producer identity/mode differs from diagnostic")
        stack, template_logical = cfn_resource_identity(
            resource.get("cfn-logicalId", "")
        )
        if stack not in names or stack not in run_context["states"]:
            raise Blocked("pending Producer is outside Deploy session: " + stack)
        if producer_state(run_context, stack).get("observedSynced"):
            raise Blocked("pending Producer is already synchronized: " + stack)
        result[(str(producer_path), logical)] = {
            "producerModel": str(producer_path),
            "logicalId": logical,
            "stack": stack,
            "templateLogicalId": template_logical,
            "observedSynced": False,
        }
    return list(result.values())


def producer_state(run_context, stack):
    state = run_context["states"].get(stack)
    if (
        state is None
        or state["status"]
        not in {"NOT_STARTED", "CHANGESET_CREATING", "READY", "RUNNING", "SUCCESS"}
        or state.get("failureDetected")
        or state.get("schedulerError")
    ):
        raise Blocked("pending Producer cannot resolve: " + stack)
    return state


def ready(run_context, record):
    for producer in record["producers"]:
        producer["observedSynced"] = bool(
            producer_state(run_context, producer["stack"]).get("observedSynced")
        )
    return all(p["observedSynced"] for p in record["producers"])


def retry_manifest(root, run_context, view):
    """Reuse checked Model dependencies; unknown references wait for explicit Resume."""
    entrance = (root / "model" / Path(view).relative_to("docs/designs")).with_suffix(
        ".properties"
    )
    shared = session_reads(root)
    paths, visited, pending = {entrance}, set(), [entrance]
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        relative = path.relative_to(root).as_posix()
        paths.update(
            root / p
            for p in run_context["modelInputs"]
            if p == relative or p.startswith(relative.removesuffix(".properties") + "/")
        )
        if shared is None:
            continue
        model = shared.models.get((scope_for(path), read_context(root)))
        if model is None:
            continue
        paths.update(model.dependencies)
        pending.extend(
            source_scope(root, p).path
            for p in model.dependencies
            if p.is_relative_to(root / "model")
        )
    return {
        p.relative_to(root).as_posix(): run_context["modelInputs"].get(
            p.relative_to(root).as_posix()
        )
        for p in sorted(paths)
    }


def retry_producers(run_context, record):
    root = Path(run_context["repository"])
    shared = session_reads(root)
    if shared is None or shared.dependency_index is None:
        return {}
    stacks = set()
    for path in record["waitingModelManifest"]:
        if not path.startswith("model/"):
            continue
        entrance = source_scope(root, root / path).path.relative_to(root).as_posix()
        entry = shared.dependency_index["models"].get(entrance)
        if entry is None:
            continue
        for owner in entry["owners"]:
            try:
                stack, _ = cfn_resource_identity(owner)
            except ValueError:
                # Unknown ownership cannot supply retry evidence; Resume re-evaluates it.
                continue
            if stack in run_context["states"]:
                stacks.add(stack)
    return {
        stack: bool(run_context["states"][stack].get("observedSynced"))
        for stack in sorted(stacks)
    }


def revision(run_context, record):
    """In-process invalidation only; a fresh backend/session always recovers evidence."""
    return (
        record,
        {p: run_context["modelInputs"].get(p) for p in record["waitingModelManifest"]},
        retry_producers(run_context, record),
        [
            bool(producer_state(run_context, p["stack"]).get("observedSynced"))
            for p in record["producers"]
        ],
    )


def failed_services(generation, selected):
    failed, unclassified = sync_runtime.generation_failures(
        generation,
        [generation.root / view for view in selected],
    )
    return {
        path.relative_to(generation.root).as_posix(): reasons
        for path, reasons in failed.items()
    }, unclassified


def retry_published(record):
    """Start a retry only from candidate bytes already verified as published."""
    record["generated"].update(
        originals={
            p: base64.b64encode(text.encode("utf-8")).decode("ascii")
            for p, text in record["generated"]["outputs"].items()
        },
        outputs=None,
        stage="PREPARED",
    )
    record.update(candidateManifest=None, candidateSelections=[])


def settle(
    backend,
    views=(),
    *,
    current=None,
    saved=None,
    failed=None,
    unclassified=(),
    error=None,
    validated=False,
):
    """Commit Pending and Error together, retaining candidates on uncertain publication."""
    root, run_context = backend.root, backend.run_context
    previous = run_context["pendingGeneration"]
    pending = copy.deepcopy(previous)
    failed = failed or {}
    for view in views:
        record = pending[view]
        if record["generated"]["outputs"] is None:
            continue
        try:
            actual = (
                current[view]
                if current is not None
                else observed.check_generated(root, record)
            )
            before, after = observed.generated_manifests(root, record)
            published = actual == after and (saved is None or root / view in saved)
            reasons = [*failed.get(view, ()), *unclassified]
            if saved is None:
                if published and record["reason"].startswith("FAILED:"):
                    retry_published(record)
                elif published:
                    del pending[view]
                continue
            if published and not reasons:
                del pending[view]
                continue
            if published:
                retry_published(record)
            elif actual == before and root / view not in saved:
                record["generated"].update(outputs=None, stage="PREPARED")
                record.update(candidateManifest=None, candidateSelections=[])
            else:
                raise Blocked(
                    "publication result does not prove saved candidate or restored originals: "
                    + view
                )
            record["reason"] = "FAILED: " + "; ".join(
                reasons
                or [
                    str(error)
                    if error is not None
                    else "publication did not save candidate"
                ]
            )
        except (Blocked, OSError, ValueError) as failure:
            error = error or failure
            record["reason"] = "FAILED: " + str(failure)
    if error is not None and not any(view in pending for view in views):
        # An exception after all saves still needs a retry owner; bytes alone cannot dismiss it.
        for view in views or pending.keys():
            pending.setdefault(view, copy.deepcopy(previous[view]))
            record = pending[view]
            record["reason"] = (
                record["reason"] + "; "
                if record["reason"].startswith("FAILED:")
                else "FAILED: "
            ) + str(error)
    errors = [
        view + ": " + record["reason"]
        for view, record in pending.items()
        if record["reason"].startswith("FAILED:")
    ]
    errors.extend(unclassified)
    if error is not None:
        errors.append(str(error))
    prior_error = run_context.get("generationError")
    if prior_error and not previous and not views and not errors:
        raise Blocked(
            "generation error has no retained candidate evidence; safe recovery cannot be proven: "
            + prior_error
        )
    if prior_error and pending and not errors and not validated and saved is None:
        # Pending records without a current result cannot disprove an unclassified error.
        errors.append(prior_error)
    backend.guard()
    run_context["pendingGeneration"] = pending
    if errors:
        run_context["generationError"] = "pending design generation: " + "; ".join(
            errors
        )
    else:
        run_context.pop("generationError", None)
    try:
        backend.save()
    except Exception:
        run_context["pendingGeneration"] = previous
        if prior_error is None:
            run_context.pop("generationError", None)
        else:
            run_context["generationError"] = prior_error
        raise
    return error


def run(backend):
    root, run_context = backend.root, backend.run_context
    backend._generation_finalized = False
    backend.guard()
    pending = run_context["pendingGeneration"]
    if getattr(backend, "_generation_session", None) is not run_context:
        backend._generation_session = run_context
        backend._generation_checks = {}
    checked = backend._generation_checks
    changed = {
        view
        for view, record in pending.items()
        if checked.get(view) != revision(run_context, record)
    }
    if not changed:
        if run_context.get("generationError"):
            if not pending:
                settle(backend)
            raise Blocked(run_context["generationError"])
        return
    recovered = getattr(backend, "generation_recovery", {})
    current = {}
    for view in changed:
        evidence = recovered.pop(view, None)
        if evidence is not None and evidence[0] == revision(run_context, pending[view]):
            current[view] = evidence[1]
    if changed - current.keys():
        current.update(
            reconcile(
                root,
                run_context,
                backend.target,
                backend.environment,
                backend.directory,
                changed - current.keys(),
            )
        )
    recovery_error = settle(backend, sorted(changed), current=current)
    if recovery_error is not None:
        raise recovery_error
    pending = run_context["pendingGeneration"]
    selected = []
    for view in sorted(changed):
        if view not in pending:
            continue
        record = pending[view]
        if ready(run_context, record) or record["reason"].startswith("FAILED:"):
            selected.append(view)
        else:
            checked[view] = copy.deepcopy(revision(run_context, record))
    if not selected:
        if run_context.get("generationError"):
            raise Blocked(run_context["generationError"])
        return
    backend.guard()
    with publication_lock(root, read_only=True):
        with sync_runtime.generation_context(root, True) as snapshot:
            generation = sync_runtime.prepare_generation(
                root,
                {
                    (backend.environment, backend.directory, pending[v]["service"])
                    for v in selected
                },
                snapshot=snapshot,
                strict=True,
            )
            try:
                sync_runtime.validate_generation(generation)
                failed, unclassified = failed_services(generation, selected)
                resolver = Resolver(root)
                deferred = {
                    path.relative_to(root).as_posix(): producers(
                        backend, path, info, generation.stage, resolver
                    )
                    for path, info in sync_runtime.generation_unavailable(
                        generation
                    ).items()
                }
                if not set(deferred) <= set(selected):
                    raise Blocked("generation returned an unselected service")
                candidates = {
                    path.relative_to(root).as_posix(): {
                        p.relative_to(root).as_posix(): text
                        for p, text in files.items()
                    }
                    for path, files in generation.expected_outputs.items()
                }
                expected = set(selected) - set(deferred) - set(failed)
                if set(candidates) - expected or (
                    expected - set(candidates) and not unclassified
                ):
                    raise Blocked("generation candidate service set changed")
                for view, candidate in candidates.items():
                    generated = pending[view]["generated"]
                    if candidate.keys() != generated["originals"].keys():
                        raise Blocked("observed generated candidate file set changed")
                    if (
                        generated["outputs"] is not None
                        and candidate != generated["outputs"]
                    ):
                        raise Blocked(
                            "observed generated candidate differs from saved session"
                        )
                    observed.check_generated(root, pending[view])
                for view, dependencies in deferred.items():
                    record = pending[view]
                    if record["generated"]["outputs"] is not None:
                        raise Blocked("saved generation candidate became unavailable")
                    record.update(
                        producers=dependencies, reason="REFERENCE_PENDING_DEPLOY"
                    )
                for view, reasons in failed.items():
                    pending[view]["reason"] = "FAILED: " + "; ".join(reasons)
                if unclassified:
                    message = "unclassified generation errors: " + "; ".join(
                        unclassified
                    )
                    for view in selected:
                        pending[view]["reason"] = "FAILED: " + "; ".join(
                            [*failed.get(view, []), message]
                        )
                for view, candidate in candidates.items():
                    if not unclassified and view not in failed:
                        pending[view]["reason"] = (
                            "validated candidate; publication required"
                        )
                    pending[view]["generated"].update(
                        outputs=candidate, stage="CANDIDATE"
                    )
                    pending[view]["candidateSelections"] = [
                        [
                            base.relative_to(root).as_posix(),
                            pattern,
                            recursive,
                            kinds,
                            [p.relative_to(root).as_posix() for p in paths],
                        ]
                        for (
                            base,
                            pattern,
                            recursive,
                            kinds,
                        ), paths in snapshot.selections.items()
                        if base.is_relative_to(root / "model")
                    ]
                    pending[view]["candidateManifest"] = observed.manifest(
                        {
                            p.relative_to(root).as_posix(): raw
                            for p, raw in snapshot.contents.items()
                            if p.is_relative_to(root / "model")
                        }
                    )
                settle(backend, validated=True)
                pending = run_context["pendingGeneration"]
                backend.guard()
                reconcile(
                    root,
                    run_context,
                    backend.target,
                    backend.environment,
                    backend.directory,
                    set(candidates),
                )
                publication_error = None
                try:
                    sync_runtime.publish_generation(generation)
                except Exception as error:
                    publication_error = error
                failed, unclassified = failed_services(generation, selected)
                for view in selected:
                    pending[view]["waitingModelManifest"] = retry_manifest(
                        root, run_context, view
                    )
                publication_error = settle(
                    backend,
                    candidates,
                    saved=generation.saved,
                    failed=failed,
                    unclassified=unclassified,
                    error=publication_error,
                )
                pending = run_context["pendingGeneration"]
                if publication_error is not None:
                    raise publication_error
                for view in selected:
                    if view in pending:
                        checked[view] = copy.deepcopy(
                            revision(run_context, pending[view])
                        )
                backend._generation_finalized = True
                try:
                    sync_runtime.report_generation(generation)
                except Exception as error:
                    if (
                        isinstance(error, ReferenceResolutionError)
                        and error.diagnostic["category"] == "REFERENCE_PENDING_DEPLOY"
                        and not generation.failures
                        and deferred
                    ):
                        pass
                    elif run_context.get("generationError"):
                        raise Blocked(run_context["generationError"]) from error
                    else:
                        raise
                if run_context.get("generationError"):
                    raise Blocked(run_context["generationError"])
            finally:
                generation.close()
