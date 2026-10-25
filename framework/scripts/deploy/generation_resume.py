"""Durable service generation after the Stack's atomic Observed barrier."""

import copy
from functools import partial
from pathlib import Path

import sync_runtime
from generation_inputs import GenerationInputs
from model.identity import Resolver
from model.sources import publication_lock, safe, scope_for
from task_contract_core import task_read_scope
from utils.cloudformation.inputs import Blocked
from utils.iac_values import cfn_resource_identity

import deploy.observed_resume as observed


def complete(session):
    return (
        not session.get("pendingObserved")
        and not session.get("pendingGeneration")
        and all(
            state["status"] == "SUCCESS" and state.get("observedSynced")
            for state in session["states"].values()
        )
    )


def describe(session):
    return "pending design generation: " + "; ".join(
        key + ": " + record["reason"] + " " + str(record["producers"])
        for key, record in session.get("pendingGeneration", {}).items()
    )


def enqueue(backend, plan):
    """Transfer even v16 candidates only after their existing exact-byte guard."""
    root, session = backend.root, backend.session
    observed.check_generated(root, plan)
    pending = session.setdefault("pendingGeneration", {})
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
            "waitingModelManifest": copy.deepcopy(session["modelInputManifest"]),
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
            "candidateManifest": copy.deepcopy(session["modelInputManifest"])
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
def validate(root, session, target, environment, directory, views=None):
    identity = observed._identity(root, session, target, environment, directory)
    for view, record in session.get("pendingGeneration", {}).items():
        if views is not None and view not in views:
            continue
        if (
            {k: v for k, v in record["identity"].items() if k != "infraManifest"}
            != {k: v for k, v in identity.items() if k != "infraManifest"}
            or record["environment"] != environment
            or record["directory"] != directory
            or view != f"docs/designs/{environment}/{directory}/{record['service']}.md"
            or set(record["generated"]["groups"]) != {view}
        ):
            raise Blocked("pending generation Task/target/session identity changed")
        observed.generated_manifests(root, record)
        if record["generated"]["outputs"] is not None and any(
            session["modelInputManifest"].get(p) != digest
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


def recover_journal(root, session, target, environment, directory, record):
    validate(root, session, target, environment, directory)
    owners = [
        item
        for item in session["pendingGeneration"].values()
        if set(record["originals"]) <= set(item["generated"]["originals"])
    ]
    if len(owners) != 1:
        raise Blocked("publication journal is not owned by pending generation")
    observed.verify_generated_journal(root, owners[0], record)


def reconcile(root, session, target, environment, directory, views=None):
    recovery = partial(recover_journal, root, session, target, environment, directory)
    with publication_lock(root, recovery_check=recovery):
        validate(root, session, target, environment, directory, views)
        return {
            view: observed.check_generated(root, record)
            for view, record in session.get("pendingGeneration", {}).items()
            if views is None or view in views
        }


def producers(backend, view, info, stage, resolver):
    """Only exact, indexed CREATE owners in this session can unblock a service."""
    diagnostics = info.get("diagnostics")
    if not diagnostics or any(
        d.get("category") != "REFERENCE_PENDING_DEPLOY" for d in diagnostics
    ):
        raise Blocked(
            "generation unavailable is not a pending CREATE reference: " + str(info)
        )
    root, session = backend.root, backend.session
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
        if stack not in names or stack not in session["states"]:
            raise Blocked("pending Producer is outside Deploy session: " + stack)
        if producer_state(session, stack).get("observedSynced"):
            raise Blocked("pending Producer is already synchronized: " + stack)
        result[(str(producer_path), logical)] = {
            "producerModel": str(producer_path),
            "logicalId": logical,
            "stack": stack,
            "templateLogicalId": template_logical,
            "observedSynced": False,
        }
    return list(result.values())


def producer_state(session, stack):
    state = session["states"].get(stack)
    if (
        state is None
        or state["status"]
        not in {"NOT_STARTED", "CHANGESET_CREATING", "READY", "RUNNING", "SUCCESS"}
        or state.get("failureDetected")
        or state.get("schedulerError")
    ):
        raise Blocked("pending Producer cannot resolve: " + stack)
    return state


def ready(session, record):
    for producer in record["producers"]:
        producer["observedSynced"] = bool(
            producer_state(session, producer["stack"]).get("observedSynced")
        )
    return all(p["observedSynced"] for p in record["producers"])


def revision(session, record):
    """In-process invalidation only; a fresh backend/session always recovers evidence."""
    return (
        record,
        {
            p: session["modelInputManifest"].get(p)
            for p in record["waitingModelManifest"]
        },
        session["taskDigest"],
        session["inputDigest"],
        session.get("inputRevision", 0),
        [
            bool(producer_state(session, p["stack"]).get("observedSynced"))
            for p in record["producers"]
        ],
    )


def failed_services(generation, selected):
    failed = {}
    if generation.failures and not generation.failure_records:
        raise Blocked("generation failure has no structured service ownership")
    for diagnostic in generation.failure_records:
        affected = set(diagnostic.affected_services)
        if diagnostic.service is not None:
            affected.add(diagnostic.service)
        for view in selected:
            identity = (*Path(view).parts[2:4], Path(view).stem)
            if not affected or identity in affected:
                failed.setdefault(view, []).append(diagnostic.message)
    return failed


def run(backend):
    root, session = backend.root, backend.session
    backend.guard()
    pending = session["pendingGeneration"]
    if getattr(backend, "_generation_session", None) is not session:
        backend._generation_session = session
        backend._generation_checks = {}
    checked = backend._generation_checks
    changed = {
        view
        for view, record in pending.items()
        if checked.get(view) != revision(session, record)
    }
    if not changed:
        return
    recovered = getattr(backend, "generation_recovery", {})
    current = {}
    for view in changed:
        evidence = recovered.pop(view, None)
        if evidence is not None and evidence[0] == revision(session, pending[view]):
            current[view] = evidence[1]
    if changed - current.keys():
        current.update(
            reconcile(
                root,
                session,
                backend.target,
                backend.environment,
                backend.directory,
                changed - current.keys(),
            )
        )
    selected = []
    for view in sorted(changed):
        record = pending[view]
        outputs = record["generated"]["outputs"]
        if outputs is not None and current[view] == observed.manifest(
            {p: text.encode("utf-8") for p, text in outputs.items()}
        ):
            # Exact saved candidates already committed before interruption need no rendering.
            del pending[view]
        elif ready(session, record):
            selected.append(view)
        else:
            checked[view] = copy.deepcopy(revision(session, record))
    if not pending:
        session.pop("generationError", None)
    backend.save()
    if not selected:
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
            )
            try:
                sync_runtime.validate_generation(generation)
                failed = failed_services(generation, selected)
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
                if set(candidates) != set(selected) - set(deferred) - set(failed):
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
                for view, candidate in candidates.items():
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
                backend.save()
                backend.guard()
                reconcile(
                    root,
                    session,
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
                failed = failed_services(generation, selected)
                for view in candidates:
                    if root / view not in generation.saved:
                        continue
                    candidate = candidates[view]
                    try:
                        if observed.check_generated(
                            root, pending[view]
                        ) != observed.manifest(
                            {p: t.encode("utf-8") for p, t in candidate.items()}
                        ):
                            raise Blocked(
                                "observed generated publication did not produce the saved candidate"
                            )
                    except (Blocked, OSError, ValueError) as error:
                        publication_error = publication_error or error
                        continue
                    del pending[view]
                backend.save()
                if publication_error is not None:
                    raise publication_error
                for view in candidates.keys() & pending.keys():
                    record = pending[view]
                    current = observed.check_generated(root, record)
                    before, _ = observed.generated_manifests(root, record)
                    if current != before:
                        raise Blocked(
                            "failed publication did not restore originals: " + view
                        )
                    record["generated"].update(outputs=None, stage="PREPARED")
                    record.update(candidateManifest=None, candidateSelections=[])
                    record["reason"] = "FAILED: " + "; ".join(
                        failed.get(view, ["publication did not save candidate"])
                    )
                for view in selected:
                    if view in pending:
                        pending[view]["waitingModelManifest"] = copy.deepcopy(
                            session["modelInputManifest"]
                        )
                        checked[view] = copy.deepcopy(revision(session, pending[view]))
                if any(r["reason"].startswith("FAILED:") for r in pending.values()):
                    session["generationError"] = describe(session)
                else:
                    session.pop("generationError", None)
                backend.guard()
                backend.save()
                try:
                    sync_runtime.report_generation(generation)
                except ValueError:
                    if not generation.failures and not deferred:
                        raise
            finally:
                generation.close()
