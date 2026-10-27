"""Pending service generation, exact ownership, interruption and scheduler gates."""

import base64
import copy
import json
import sys
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import generation_resume as M
from deploy import observed_resume
from deploy import run_context as controller
from deploy.model_cache import RunModels
from model.format import parse as parse_properties
from model.format import patch as patch_properties
from model.identity import Resolver
from model.reference_nodes import parse as parse_reference
from model.reference_values import reference_value
from support.cloudformation_deploy_fixtures import Fake, starts
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
)
from support.model_reference_fixtures import (
    save as save_model,
)
from support.pytest_cli import run
from task_contract_core import selected_task
from utils.aws_mappings import mapping_alias
from utils.cloudformation.inputs import Blocked
from validation.diagnostics import Diagnostic
from validation.findings import Findings

from model import dependency_index, sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def save_copy(saved, session):
    saved.append(copy.deepcopy(session))


@pytest.fixture
def owned(tmp_path):
    root = tmp_path / "repo"
    units = [
        {"name": n, "deployOrder": o, "template": "app.yaml", "parameters": n + ".json"}
        for n, o in [("early", 10), ("build", 60), ("release", 70)]
    ]
    session = {
        "repository": str(root),
        "taskFile": "tasks/deploy.md",
        "inputDigest": "inputs",
        "consumedInputs": {},
        "modelInputs": {},
        "states": {u["name"]: {"status": "NOT_STARTED"} for u in units},
        "metrics": {"observedSyncSeconds": 0},
    }
    session["states"]["early"].update(status="SUCCESS", observedSynced=True)
    views = {
        s: root / "docs/designs/dev/team" / (s + ".md")
        for s in ("iam", "kms", "athena")
    }
    generated = {"groups": {}, "originals": {}, "outputs": None, "stage": "PREPARED"}
    for service, view in views.items():
        paths = [view, view.with_suffix("") / "policy.json"]
        files = [p.relative_to(root).as_posix() for p in paths]
        generated["groups"][files[0]] = files
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = f"old {service} {path.suffix}\n".encode()
            path.write_bytes(raw)
            generated["originals"][path.relative_to(root).as_posix()] = (
                base64.b64encode(raw).decode()
            )
    task = root / session["taskFile"]
    task.parent.mkdir()
    listed = "".join(
        f"- `{p}`\n" for p in [session["taskFile"], *generated["originals"]]
    )
    text = (
        "## Task contract\n- Task status: `running`\n## Modified files\n"
        + listed
        + "## Allowed paths\n"
        + listed
    )
    task.write_text(text, encoding="utf-8")
    session["taskDigest"] = observed_resume.task_digest(text)
    saved = []
    backend = SimpleNamespace(
        root=root,
        environment="dev",
        directory="team",
        target={},
        run_context=session,
        units=units,
        guard=Mock(),
        save=partial(save_copy, saved, session),
    )
    with selected_task(root, session["taskFile"]):
        plan = {
            "identity": observed_resume._identity(root, session, {}, "dev", "team"),
            "generated": generated,
        }
        M.enqueue(backend, plan)
        yield backend, views, saved


def generation_for(backend, views, deferred=(), failures=()):
    return SimpleNamespace(
        stage=backend.root.parent / "stage",
        root=backend.root,
        model_paths=[],
        markdown_paths=list(views.values()),
        reference_warnings=[],
        warnings={},
        baseline_links={},
        saved={},
        failure_records=[],
        generated_scope={
            (backend.environment, backend.directory, s)
            for s in views
            if s not in deferred
        },
        expected_outputs={
            view: {
                backend.root / p: f"new {p}\n"
                for p in backend.run_context["pendingGeneration"][
                    view.relative_to(backend.root).as_posix()
                ]["generated"]["originals"]
            }
            for service, view in views.items()
            if service not in deferred
        },
        unavailable={
            views[s]: {
                "reason": "reference",
                "status": "NOT_RUN",
                "diagnostics": [
                    {
                        "category": "REFERENCE_PENDING_DEPLOY",
                        "targetLogicalId": "CodeBuild_Project_001",
                        "producerModel": str(
                            backend.root / "model/dev/team/codebuild.properties"
                        ),
                    }
                ],
            }
            for s in deferred
        },
        failures=list(failures),
        close=Mock(),
    )


def publish_candidate(generation):
    for view, files in generation.expected_outputs.items():
        for path, text in files.items():
            path.write_text(text, encoding="utf-8")
        generation.saved[view] = {}


def resolved_producer(backend, logical, scope):
    assert scope.environment == "dev" and scope.target == "team"
    return (
        SimpleNamespace(
            scope=SimpleNamespace(
                path=backend.root / "model/dev/team/codebuild.properties"
            )
        ),
        "001",
        {
            "resourceMode": "CREATE",
            "cfn-logicalId": "build-Project",
            "logicalId": logical,
        },
    )


def invoke(backend, generation, publish=publish_candidate, operation=M.run):
    with (
        patch.object(
            M.sync_runtime,
            "generation_context",
            return_value=nullcontext(SimpleNamespace(contents={}, selections={})),
        ),
        patch.object(
            M.sync_runtime, "prepare_generation", return_value=generation
        ) as prepare,
        patch.object(M.sync_runtime, "validate_generation"),
        patch.object(
            M.sync_runtime, "report_generation", wraps=M.sync_runtime.report_generation
        ),
        patch.object(M.sync_runtime, "publish_generation", side_effect=publish),
        patch.object(
            M.Resolver,
            "resolve_logical",
            side_effect=partial(resolved_producer, backend),
        ),
    ):
        operation(backend)
    assert all(call.kwargs["strict"] is True for call in prepare.call_args_list)
    return prepare


def fail_service(generation, view=None, *, affected=(), message="fixture failure"):
    M.sync_runtime.generation_failure(
        generation.root,
        generation.failure_records,
        "generation.render",
        view,
        message,
        affected=affected,
    )
    generation.failures = [d.message for d in generation.failure_records]


@pytest.mark.parametrize("revision", ["model", "repair"])
def check_failed_service_does_not_reject_successes(owned, revision):
    backend, views, saved = owned
    backend.run_context["modelInputs"]["model/dev/team/kms.properties"] = "old-input"
    generation = generation_for(backend, views)
    failed = views["kms"]
    old = {p: p.read_bytes() for p in generation.expected_outputs.pop(failed)}
    fail_service(
        generation, failed, message="iam appears here but kms owns the failure"
    )
    with pytest.raises(Blocked, match="kms owns"):
        invoke(backend, generation)
    key = failed.relative_to(backend.root).as_posix()
    assert set(backend.run_context["pendingGeneration"]) == {key}
    assert set(generation.saved) == {views["iam"], views["athena"]}
    assert all(p.read_bytes() == raw for p, raw in old.items())
    assert backend.run_context["pendingGeneration"][key]["reason"].startswith("FAILED:")
    assert "kms owns" in backend.run_context["generationError"]
    assert saved[-1]["pendingGeneration"] == backend.run_context["pendingGeneration"]
    assert backend.run_context["states"]["early"] == {
        "status": "SUCCESS",
        "observedSynced": True,
    }
    assert not M.complete(backend.run_context)
    with (
        patch.object(M.observed, "check_generated") as check,
        patch.object(M.sync_runtime, "prepare_generation") as prepare,
    ):
        for _ in range(10):
            with pytest.raises(Blocked, match="kms owns"):
                M.run(backend)
        check.assert_not_called()
        prepare.assert_not_called()
    if revision == "repair":
        backend.run_context["inputRevision"] = 1
        with (
            patch.object(M.sync_runtime, "prepare_generation") as prepare,
            pytest.raises(Blocked, match="kms owns"),
        ):
            M.run(backend)
        prepare.assert_not_called()
    backend.run_context["modelInputs"]["model/dev/team/kms.properties"] = (
        "authorized-repair-revision"
    )
    retry = generation_for(backend, {"kms": failed})
    prepare = invoke(backend, retry)
    assert prepare.call_args.args[1] == {("dev", "team", "kms")}
    assert not backend.run_context["pendingGeneration"]
    assert "generationError" not in backend.run_context


def publish_with_rollback(views, rollback, plan):
    for view, files in plan.expected_outputs.items():
        if view == views["kms"] or rollback and view == views["iam"]:
            fail_service(plan, view, message="publication rolled back")
        else:
            for path, text in files.items():
                path.write_text(text, encoding="utf-8")
            plan.saved[view] = {}


@pytest.mark.parametrize("rollback", [False, True])
def check_publication_results_and_rollback_are_service_scoped(owned, rollback):
    backend, views, _ = owned
    generation = generation_for(backend, views)
    original = {p: p.read_bytes() for p in generation.expected_outputs[views["kms"]]}
    with pytest.raises(Blocked, match="publication rolled back"):
        invoke(backend, generation, partial(publish_with_rollback, views, rollback))
    expected = {views["kms"], *([views["iam"]] if rollback else [])}
    assert set(backend.run_context["pendingGeneration"]) == {
        p.relative_to(backend.root).as_posix() for p in expected
    }
    assert all(p.read_bytes() == raw for p, raw in original.items())
    assert all(
        r["generated"]["outputs"] is None
        for r in backend.run_context["pendingGeneration"].values()
    )


def publish_then_fail(views, plan):
    for view in (views["iam"], views["athena"]):
        for path, text in plan.expected_outputs[view].items():
            path.write_text(text, encoding="utf-8")
        plan.saved[view] = {}
    raise OSError("journal retained for kms")


def check_fatal_publication_preserves_already_saved_successes(owned):
    backend, views, saved = owned
    generation = generation_for(backend, views)
    with pytest.raises(OSError, match="journal retained"):
        invoke(backend, generation, partial(publish_then_fail, views))
    assert set(saved[-1]["pendingGeneration"]) == {
        views["kms"].relative_to(backend.root).as_posix()
    }
    assert backend.run_context["states"]["early"]["observedSynced"]


def publish_with_evidence(views, evidence, plan):
    if evidence != "saved-only":
        publish_candidate(plan)
    if evidence == "bytes-only":
        plan.saved.clear()
    elif evidence == "saved-only":
        plan.saved.update({v: {} for v in views.values()})
    else:
        views["iam"].write_bytes(b"foreign edit")


@pytest.mark.parametrize("evidence", ["saved-only", "bytes-only", "corrupt"])
def check_publication_requires_saved_result_and_exact_bytes(owned, evidence):
    backend, views, _ = owned
    generation = generation_for(backend, views)
    with pytest.raises(Blocked):
        invoke(backend, generation, partial(publish_with_evidence, views, evidence))
    assert backend.run_context["pendingGeneration"]


def check_waiting_services_do_no_repeated_file_work(owned):
    backend, views, _ = owned
    invoke(backend, generation_for(backend, views, deferred=views))
    assert all(
        record["reason"] == "REFERENCE_PENDING_DEPLOY"
        for record in backend.run_context["pendingGeneration"].values()
    )
    assert not any(
        key in backend.run_context
        for key in (
            "generationError",
            "observedError",
            "observedRecoveryError",
            "observedFailures",
        )
    )
    with (
        patch.object(M.observed, "check_generated") as check,
        patch.object(M.observed, "generated_manifests") as manifests,
        patch.object(M.sync_runtime, "prepare_generation") as prepare,
        patch.object(M, "producers") as producers,
        patch.object(M, "ready") as ready,
    ):
        for _ in range(10):
            M.run(backend)
        backend.run_context["states"]["build"]["status"] = "RUNNING"
        M.run(backend)
        for mocked in (check, manifests, prepare, producers, ready):
            mocked.assert_not_called()
    backend.run_context["states"]["build"].update(status="SUCCESS", observedSynced=True)
    invoke(backend, generation_for(backend, views))
    assert not backend.run_context["pendingGeneration"]


@pytest.mark.parametrize("failed", [False, True])
def check_fresh_resume_rechecks_and_retries_once(owned, failed):
    backend, views, saved = owned
    generation = generation_for(backend, views, deferred=() if failed else views)
    if failed:
        generation.expected_outputs.clear()
        fail_service(generation, affected={("dev", "team", s) for s in views})
    with pytest.raises(Blocked) if failed else nullcontext():
        invoke(backend, generation)
    backend.run_context = json.loads(json.dumps(saved[-1]))
    backend.save = partial(save_copy, saved, backend.run_context)
    with patch.object(
        M.observed, "check_generated", wraps=M.observed.check_generated
    ) as check:
        invoke(
            backend, generation_for(backend, views, deferred=() if failed else views)
        )
        assert check.call_count >= 3
        count = check.call_count
        M.run(backend)
        assert check.call_count == count


def check_startup_recovery_is_reused_by_first_run(owned):
    backend, views, _ = owned
    invoke(backend, generation_for(backend, views, deferred=views))
    backend.run_context = copy.deepcopy(backend.run_context)
    recovered = M.reconcile(
        backend.root,
        backend.run_context,
        backend.target,
        backend.environment,
        backend.directory,
    )
    backend.generation_recovery = {
        view: (
            copy.deepcopy(
                M.revision(
                    backend.run_context, backend.run_context["pendingGeneration"][view]
                )
            ),
            current,
        )
        for view, current in recovered.items()
    }
    with (
        patch.object(M.observed, "check_generated") as check,
        patch.object(M.observed, "generated_manifests") as manifests,
        patch.object(M, "reconcile") as reconcile,
    ):
        M.run(backend)
        M.run(backend)
        check.assert_not_called()
        manifests.assert_not_called()
        reconcile.assert_not_called()


@pytest.mark.parametrize("identified", [False, True])
def check_common_validation_uses_structured_ownership(owned, identified):
    backend, views, _ = owned
    stage = backend.root.parent / "stage"
    generated = {v: [] for v in views.values()}
    failures, validation = [], {}
    findings = Findings(backend.root)
    if identified:
        findings.add_diagnostic(
            Diagnostic.create(
                backend.root,
                code="fixture.common",
                check_id="design.ownership",
                service=("dev", "team", "kms"),
                source_path=None,
                message=str(views["iam"]) + " is text, not ownership",
            )
        )
    else:
        findings.errors.append(str(views["kms"]) + " unknown scope")
    contexts = [SimpleNamespace(findings=findings, errors=findings.errors)]
    if identified:
        contexts.append(SimpleNamespace(findings=Findings(backend.root), errors=[]))
    with (
        patch.object(
            M.sync_runtime.sync_views, "validation_context", side_effect=contexts
        ),
        patch.object(
            M.sync_runtime.sync_views,
            "validate_views",
            return_value=Findings(backend.root),
        ),
        patch.object(M.sync_runtime, "restore_view"),
        patch.object(M.sync_runtime, "DesignIndex"),
    ):
        M.sync_runtime.validate_candidates(
            stage, backend.root, generated, {}, failures, 1, True, validation
        )
    assert set(generated) == ({views["iam"], views["athena"]} if identified else set())
    assert failures


def check_partial_generation_then_dependency_completion(owned):
    backend, views, saved = owned
    iam = views["iam"].relative_to(backend.root).as_posix()
    before = {
        p: (backend.root / p).read_bytes()
        for p in backend.run_context["pendingGeneration"][iam]["generated"]["originals"]
    }
    first = generation_for(backend, views, ["iam"])
    invoke(backend, first)
    assert set(backend.run_context["pendingGeneration"]) == {iam}
    assert all((backend.root / p).read_bytes() == raw for p, raw in before.items())
    assert all(
        path.read_text().startswith("new ") for path in (views["kms"], views["athena"])
    )
    record = backend.run_context["pendingGeneration"][iam]
    assert (
        record["producers"][0]["stack"] == "build"
        and record["reason"] == "REFERENCE_PENDING_DEPLOY"
    )
    assert saved[-1]["pendingGeneration"] == backend.run_context["pendingGeneration"]
    with patch.object(M.sync_runtime, "prepare_generation") as prepare:
        M.run(backend)
    prepare.assert_not_called()
    backend.run_context["states"]["build"].update(status="SUCCESS", observedSynced=True)
    second = generation_for(backend, {"iam": views["iam"]})
    invoke(backend, second)
    assert not backend.run_context["pendingGeneration"] and views[
        "iam"
    ].read_text().startswith("new ")
    assert not M.complete(backend.run_context)
    backend.run_context["states"]["release"].update(
        status="SUCCESS", observedSynced=True
    )
    assert M.complete(backend.run_context)


@pytest.mark.parametrize(
    "problem",
    [
        "category",
        "missing-id",
        "missing-model",
        "wrong-model",
        "import",
        "bad-cfn",
        "outside",
        "synced",
        "failed",
        "ambiguous",
        "empty",
    ],
)
def check_invalid_references_stop(owned, problem):
    backend, views, _ = owned
    generation = generation_for(backend, views, ["iam"])
    diagnostic = generation.unavailable[views["iam"]]["diagnostics"][0]
    resource = {"resourceMode": "CREATE", "cfn-logicalId": "build-Project"}
    producer_path = backend.root / "model/dev/team/codebuild.properties"
    if problem == "category":
        diagnostic["category"] = "MODEL_NEEDS_FIX"
    if problem == "missing-id":
        diagnostic.pop("targetLogicalId")
    if problem == "missing-model":
        diagnostic.pop("producerModel")
    if problem == "wrong-model":
        diagnostic["producerModel"] = "different"
    if problem == "import":
        resource["resourceMode"] = "IMPORT"
    if problem == "bad-cfn":
        resource["cfn-logicalId"] = "invalid"
    if problem == "outside":
        resource["cfn-logicalId"] = "outside-Project"
    if problem == "synced":
        backend.run_context["states"]["build"].update(
            status="SUCCESS", observedSynced=True
        )
    if problem == "failed":
        backend.run_context["states"]["build"]["status"] = "FAILED"
    if problem == "empty":
        generation.unavailable[views["iam"]]["diagnostics"] = []
    before = {p: p.read_bytes() for p in views.values()}
    with (
        patch.object(
            M.sync_runtime,
            "generation_context",
            return_value=nullcontext(SimpleNamespace(contents={}, selections={})),
        ),
        patch.object(M.sync_runtime, "prepare_generation", return_value=generation),
        patch.object(M.sync_runtime, "validate_generation"),
        patch.object(M.sync_runtime, "publish_generation") as publish,
        patch.object(
            M.Resolver,
            "resolve_logical",
            return_value=(
                SimpleNamespace(scope=SimpleNamespace(path=producer_path)),
                "001",
                resource,
            ),
            side_effect=ValueError("ambiguous owner")
            if problem == "ambiguous"
            else None,
        ),
        pytest.raises((Blocked, ValueError)),
    ):
        M.run(backend)
    publish.assert_not_called()
    assert all(p.read_bytes() == raw for p, raw in before.items())


def check_multiple_producers_wait_once(owned):
    backend, views, _ = owned
    record = backend.run_context["pendingGeneration"][
        views["iam"].relative_to(backend.root).as_posix()
    ]
    record["producers"] = [
        {"stack": name, "observedSynced": False} for name in ("build", "release")
    ]
    assert not M.ready(backend.run_context, record)
    backend.run_context["states"]["build"].update(status="SUCCESS", observedSynced=True)
    assert not M.ready(backend.run_context, record)
    backend.run_context["states"]["release"].update(
        status="SUCCESS", observedSynced=True
    )
    assert M.ready(backend.run_context, record)


@pytest.mark.parametrize(
    "problem", ["candidate", "file-set", "tamper", "task", "manifest", "publish"]
)
def check_candidate_boundaries(owned, problem):
    backend, views, _ = owned
    generation = generation_for(backend, views)
    key = views["iam"].relative_to(backend.root).as_posix()
    record = backend.run_context["pendingGeneration"][key]
    if problem in {"candidate", "manifest"}:
        record["generated"].update(
            outputs={p: "saved\n" for p in record["generated"]["originals"]},
            stage="CANDIDATE",
        )
        record["candidateManifest"] = (
            {} if problem == "candidate" else {"model/changed.properties": "different"}
        )
    if problem == "file-set":
        generation.expected_outputs[views["iam"]].pop(views["iam"])
    if problem == "tamper":
        views["iam"].write_text("foreign edit")
    if problem == "task":
        (backend.root / backend.run_context["taskFile"]).write_text("changed task")
    with (
        patch.object(
            M.sync_runtime,
            "generation_context",
            return_value=nullcontext(SimpleNamespace(contents={}, selections={})),
        ),
        patch.object(M.sync_runtime, "prepare_generation", return_value=generation),
        patch.object(M.sync_runtime, "validate_generation"),
        patch.object(M.sync_runtime, "report_generation"),
        patch.object(
            M.sync_runtime,
            "publish_generation",
            side_effect=OSError("write failed") if problem == "publish" else None,
        ) as publish,
        pytest.raises((Blocked, ValueError, OSError)),
    ):
        M.run(backend)
    assert backend.run_context["pendingGeneration"]
    assert backend.run_context["states"]["early"]["observedSynced"]
    assert publish.call_count == int(problem == "publish")


@pytest.mark.parametrize(
    "interruption", ["queued", "candidate", "published", "journal", "foreign-journal"]
)
def check_durable_resume(owned, interruption):
    backend, views, saved = owned
    generation = generation_for(backend, views)
    pending = backend.run_context["pendingGeneration"]
    if interruption != "queued":
        for view, files in generation.expected_outputs.items():
            record = pending[view.relative_to(backend.root).as_posix()]
            record["generated"].update(
                outputs={
                    p.relative_to(backend.root).as_posix(): t for p, t in files.items()
                },
                stage="CANDIDATE",
            )
            record["candidateManifest"] = {}
    if interruption == "published":
        publish_candidate(generation)
    journal = None
    if interruption in {"journal", "foreign-journal"}:
        record = pending[views["iam"].relative_to(backend.root).as_posix()]
        views["iam"].write_text(
            record["generated"]["outputs"][
                views["iam"].relative_to(backend.root).as_posix()
            ]
        )
        with sources.publication_lock(backend.root) as journal:
            pass
        originals = copy.deepcopy(record["generated"]["originals"])
        if interruption == "foreign-journal":
            originals["docs/designs/dev/team/foreign.md"] = None
        journal.write_text(
            json.dumps({"root": str(backend.root), "originals": originals})
        )
    backend.save()
    backend.run_context = json.loads(json.dumps(saved[-1]))
    backend.save = partial(save_copy, saved, backend.run_context)
    if interruption == "foreign-journal":
        before = journal.read_bytes()
        with patch.object(controller, "sync_successful") as sync:
            assert not controller._callback_run_deploy_sync_once(
                backend, backend.save, backend.run_context, backend.units
            )
        sync.assert_not_called()
        assert journal.read_bytes() == before
        assert backend.sync_failed and backend.run_context["pendingGeneration"]
        assert "journal" in backend.run_context["generationError"]
        assert not any(
            key in backend.run_context
            for key in ("observedError", "observedRecoveryError", "observedFailures")
        )
        return
    prepared = invoke(backend, generation)
    assert prepared.call_count == int(interruption != "published")
    assert not backend.run_context["pendingGeneration"]
    assert journal is None or not journal.exists()
    assert all(p.read_text().startswith("new ") for p in views.values())


def mark_observed(backend, units, states):
    for u in units:
        states[u["name"]]["observedSynced"] = True
    return None


def run_deploy(backend):
    with patch.object(controller, "sync_successful", side_effect=mark_observed):
        backend.result = controller.run_deploy(
            backend.units,
            1,
            backend.run_context,
            backend,
            backend.save,
            sleep=lambda _: None,
        )


def check_service_failure_keeps_observed_barriers_and_final_pending(owned):
    backend, views, _ = owned
    runtime = Fake()
    runtime.__dict__.update(backend.__dict__)
    runtime.run_context["states"]["early"].pop("observedSynced")
    generation = generation_for(runtime, views)
    generation.expected_outputs.pop(views["kms"])
    fail_service(generation, views["kms"])
    prepare = invoke(runtime, generation, operation=run_deploy)
    assert runtime.result == "STOPPED" and runtime.sync_failed
    prepare.assert_called_once()
    assert starts(runtime) == []
    assert runtime.run_context["states"]["early"]["observedSynced"]
    assert all(
        runtime.run_context["states"][name]["status"] == "NOT_STARTED"
        for name in ("build", "release")
    )
    assert "kms" in runtime.run_context["generationError"]
    assert not any(
        name in runtime.run_context
        for name in ("observedError", "observedRecoveryError", "observedFailures")
    )
    runtime.run_context = json.loads(json.dumps(runtime.run_context))
    runtime.save = partial(save_copy, [], runtime.run_context)
    retry = generation_for(runtime, {"kms": views["kms"]})
    invoke(runtime, retry, operation=run_deploy)
    assert runtime.result == "COMPLETE" and not runtime.sync_failed
    assert starts(runtime) == ["build", "release"]
    assert not runtime.run_context["pendingGeneration"]
    assert "generationError" not in runtime.run_context


def add_unclassified(generation, ownership):
    if ownership == "unstructured":
        generation.failures.append("orphan generation failure")
    else:
        fail_service(
            generation,
            generation.root / "docs/designs/other/target/kms.md"
            if ownership == "foreign"
            else None,
            message="orphan generation failure",
        )


def publish_with_unclassified(ownership, generation):
    publish_candidate(generation)
    add_unclassified(generation, ownership)


@pytest.mark.parametrize("ownership", ["foreign", "none", "unstructured"])
@pytest.mark.parametrize("phase", ["validation", "publication", "no-candidates"])
def check_unclassified_failure_stops_and_revalidates_saved_services(
    owned, ownership, phase
):
    backend, views, saved = owned
    runtime = Fake()
    runtime.__dict__.update(backend.__dict__)
    generation = generation_for(runtime, views)
    if phase != "publication":
        add_unclassified(generation, ownership)
    if phase == "no-candidates":
        generation.expected_outputs.clear()
    publish = (
        partial(publish_with_unclassified, ownership)
        if phase == "publication"
        else publish_candidate
    )
    invoke(runtime, generation, publish, operation=run_deploy)
    assert runtime.result == "STOPPED" and runtime.sync_failed
    assert starts(runtime) == []
    assert runtime.run_context["states"]["early"]["observedSynced"]
    assert "orphan generation failure" in runtime.run_context["generationError"]
    assert set(runtime.run_context["pendingGeneration"]) == {
        v.relative_to(runtime.root).as_posix() for v in views.values()
    }
    assert set(generation.saved) == (
        set() if phase == "no-candidates" else set(views.values())
    )
    assert "orphan generation failure" in saved[-1]["generationError"]
    assert not M.complete(runtime.run_context)
    assert not any(
        key in runtime.run_context
        for key in ("observedError", "observedRecoveryError", "observedFailures")
    )
    runtime.run_context = json.loads(json.dumps(saved[-1]))
    runtime.save = partial(save_copy, saved, runtime.run_context)
    retry = generation_for(runtime, views)
    prepare = invoke(runtime, retry, operation=run_deploy)
    prepare.assert_called_once()
    assert runtime.result == "COMPLETE"
    assert starts(runtime) == ["build", "release"]
    assert not runtime.run_context["pendingGeneration"]
    assert "generationError" not in runtime.run_context


def check_unstructured_failure_cannot_hide_behind_mapped_failure(owned):
    backend, views, _ = owned
    generation = generation_for(backend, views)
    generation.expected_outputs.pop(views["kms"])
    fail_service(generation, views["kms"], message="owned failure")
    add_unclassified(generation, "unstructured")
    selected = [v.relative_to(backend.root).as_posix() for v in views.values()]
    failed, unclassified = M.failed_services(generation, selected)
    assert failed == {
        views["kms"].relative_to(backend.root).as_posix(): ["owned failure"]
    }
    assert unclassified == ["orphan generation failure"]
    with pytest.raises(Blocked, match="orphan generation failure"):
        invoke(backend, generation)
    assert "orphan generation failure" in backend.run_context["generationError"]


@pytest.mark.parametrize("deferred", [False, True])
def check_unclassified_retry_rechecks_errors_before_returning_to_pending(
    owned, deferred
):
    backend, views, saved = owned
    generation = generation_for(backend, views, ["iam"] if deferred else [])
    add_unclassified(generation, "foreign")
    with pytest.raises(Blocked, match="orphan"):
        invoke(backend, generation)
    assert all(
        record["generated"]["outputs"] is None
        for record in saved[-1]["pendingGeneration"].values()
    )
    backend.run_context = copy.deepcopy(saved[-1])
    backend.save = partial(save_copy, saved, backend.run_context)
    retry = generation_for(backend, views, ["iam"] if deferred else [])
    add_unclassified(retry, "foreign")
    with pytest.raises(Blocked, match="orphan"):
        invoke(backend, retry)
    assert "orphan" in saved[-1]["generationError"]
    backend.run_context = copy.deepcopy(saved[-1])
    backend.save = partial(save_copy, saved, backend.run_context)
    resolved = generation_for(backend, views, ["iam"] if deferred else [])
    for files in resolved.expected_outputs.values():
        for path in files:
            files[path] = "corrected generation\n"
    invoke(backend, resolved)
    assert "generationError" not in backend.run_context
    assert len(backend.run_context["pendingGeneration"]) == int(deferred)
    if deferred:
        assert next(iter(backend.run_context["pendingGeneration"].values()))[
            "reason"
        ] == ("REFERENCE_PENDING_DEPLOY")


@pytest.mark.parametrize("pause", [False, True])
@pytest.mark.parametrize("pending", [False, True])
def check_all_successful_stacks_cannot_complete_with_generation_error(
    owned, pause, pending
):
    backend, _, _ = owned
    for state in backend.run_context["states"].values():
        state.update(status="SUCCESS", observedSynced=True)
    if not pending:
        backend.run_context["pendingGeneration"].clear()
    backend.run_context["generationError"] = "unclassified generation failure"
    assert not M.complete(backend.run_context)
    with patch.object(M, "run") as generate:
        # The final completion gate must also reject an ineffective recovery callback.
        assert (
            controller.run_deploy(
                backend.units,
                1,
                backend.run_context,
                backend,
                backend.save,
                pause_after_group=pause,
                sleep=lambda _: None,
            )
            == "STOPPED"
        )
    generate.assert_called_once()
    assert "unclassified generation failure" in backend.run_context["generationError"]
    backend.run_context["result"] = "COMPLETE"


def check_unexpected_report_error_is_not_suppressed_for_deferred_generation(owned):
    backend, views, _ = owned
    generation = generation_for(backend, views, ["iam"])
    with (
        patch.object(
            M.sync_runtime, "report_generation", side_effect=ValueError("report failed")
        ),
        pytest.raises(ValueError, match="report failed"),
    ):
        invoke(backend, generation)


def check_success_has_no_pending_or_errors(owned):
    backend, views, _ = owned
    runtime = Fake()
    runtime.__dict__.update(backend.__dict__)
    invoke(runtime, generation_for(runtime, views), operation=run_deploy)
    assert runtime.result == "COMPLETE" and not runtime.sync_failed
    assert starts(runtime) == ["build", "release"]
    assert not runtime.run_context["pendingGeneration"]
    assert "generationError" not in runtime.run_context


@pytest.mark.parametrize("pause", [False, True])
def check_order_10_to_60_and_complete(owned, pause):
    backend, views, _ = owned
    units = backend.units[:2]
    backend.units = units
    backend.run_context["states"].pop("release")
    first = generation_for(backend, views, ["iam"])
    invoke(backend, first)
    runtime = Fake()
    runtime.__dict__.update(backend.__dict__)
    generation = generation_for(runtime, {"iam": views["iam"]})
    with (
        patch.object(controller, "sync_successful", side_effect=mark_observed),
        patch.object(
            M.sync_runtime,
            "generation_context",
            return_value=nullcontext(SimpleNamespace(contents={}, selections={})),
        ),
        patch.object(
            M.sync_runtime, "prepare_generation", return_value=generation
        ) as prepare,
        patch.object(M.sync_runtime, "validate_generation"),
        patch.object(M.sync_runtime, "report_generation"),
        patch.object(
            M.sync_runtime, "publish_generation", side_effect=publish_candidate
        ),
    ):
        assert (
            controller.run_deploy(
                units,
                1,
                runtime.run_context,
                runtime,
                runtime.save,
                pause_after_group=pause,
                sleep=lambda _: None,
            )
            == "COMPLETE"
        )
    assert starts(runtime) == ["build"] and prepare.call_count == 1
    assert M.complete(runtime.run_context)


@pytest.mark.parametrize("pause", [False, True])
def check_final_gate_and_workflow(owned, pause):
    backend, views, _ = owned
    for state in backend.run_context["states"].values():
        state.update(status="SUCCESS", observedSynced=True)
    with patch.object(M, "run"):
        assert (
            controller.run_deploy(
                backend.units,
                1,
                backend.run_context,
                backend,
                backend.save,
                pause_after_group=pause,
                sleep=lambda _: None,
            )
            == "STOPPED"
        )
    assert (
        "iam" in backend.run_context["generationError"]
        and "pending design" in backend.run_context["generationError"]
    )


@pytest.mark.parametrize(
    "kind,attribute,value",
    [
        ("CodeBuild.Project", "Name", "synthetic-project"),
        ("S3.Bucket", "BucketName", "synthetic-bucket"),
        ("KMS.Key", "KeyId", "12345678-1234-1234-1234-123456789012"),
    ],
)
@pytest.mark.parametrize("staged", [False, True])
def check_real_indexed_producer_and_observed_cache(
    tmp_path, kind, attribute, value, staged
):
    with (
        mapping_alias(FRAMEWORK, tmp_path),
        patch("socket.socket", side_effect=AssertionError("network forbidden")),
    ):
        _, _, consumer, _ = project(tmp_path)
        producer, values = resource(
            tmp_path,
            "kms" if kind == "KMS.Key" else "producer",
            kind,
            attribute=attribute,
            observed="PENDING_DEPLOY",
        )
        if attribute != "KeyId":
            values["desired.row.001-001.value"] = "`" + value + "`"
        values["desired.resource.001.cfn-logicalId"] = "build-Resource"
        save_model(producer, values)
        dependency_index.rebuild(tmp_path)
        session = {
            "states": {"build": {"status": "NOT_STARTED"}},
            "modelInputs": {},
        }
        cache = RunModels(tmp_path, session)
        backend = SimpleNamespace(
            root=tmp_path,
            environment="qa",
            directory="team",
            run_context=session,
            units=[{"name": "build"}],
        )
        node = parse_reference(reference(kind.replace(".", "_") + "_001"))
        with (
            sources.model_session(cache),
            patch.object(sources, "_read_model", wraps=sources._read_model) as loaded,
        ):
            result = reference_value(Resolver(tmp_path), consumer, node)
            if kind != "KMS.Key":
                assert result.status == "resolved"
            else:
                assert result.category == "REFERENCE_PENDING_DEPLOY"
                stage = tmp_path / "stage"
                diagnostic = dict(result.diagnostic)
                if staged:
                    diagnostic["producerModel"] = str(
                        stage / producer.path.relative_to(tmp_path)
                    )
                waiting = M.producers(
                    backend,
                    tmp_path / "docs/designs/qa/team/iam.md",
                    {"diagnostics": [diagnostic, diagnostic]},
                    stage,
                    Resolver(tmp_path),
                )
                assert len(waiting) == 1 and waiting[0]["stack"] == "build"
                assert waiting[0]["producerModel"] == str(producer.path)
            text = patch_properties(
                parse_properties(producer.path.read_text()),
                {"observed.row.001-001.value": "`" + value + "`"},
            )
            producer.path.write_text(text)
            dependency_index.update(tmp_path, {producer.path}, observed=True)
            cache.apply_observed({producer.path: text})
            assert (
                reference_value(Resolver(tmp_path), consumer, node).status == "resolved"
            )
            assert (
                sum(
                    call.args[0].path == producer.path for call in loaded.call_args_list
                )
                == 1
            )


@pytest.mark.parametrize("phase", ["after-observed", "only", "candidate"])
@pytest.mark.parametrize("guard", [False, True])
def check_generation_error_retains_confirmed_observed(owned, phase, guard):
    backend, _, _ = owned
    session = backend.run_context
    if phase != "only":
        session["states"]["early"].pop("observedSynced")
    if phase == "candidate":
        next(iter(session["pendingGeneration"].values()))["generated"]["outputs"] = {}
        session["pendingObserved"] = {"stage": "PREPARED"}
    pending = copy.deepcopy(session["pendingGeneration"])
    if guard:
        # After-observed Guard failure occurs inside generation.run, after Model commit.
        backend.guard.side_effect = (
            [None, Blocked("publication failed")]
            if phase == "after-observed"
            else Blocked("publication failed")
        )
    with (
        patch.object(controller, "sync_successful", side_effect=mark_observed) as sync,
        patch.object(
            M,
            "run",
            wraps=M.run,
            side_effect=None if guard else OSError("publication failed"),
        ),
    ):
        assert not controller._callback_run_deploy_sync_once(
            backend, backend.save, session, backend.units
        )
    assert sync.call_count == int(phase == "after-observed")
    assert bool(session["states"]["early"].get("observedSynced")) == (
        phase != "candidate"
    )
    assert backend.sync_failed and session["generationError"] == "publication failed"
    assert session["pendingGeneration"] == pending
    assert not any(
        key in session
        for key in ("observedError", "observedRecoveryError", "observedFailures")
    )
    if phase == "candidate":
        assert session["pendingObserved"] == {"stage": "PREPARED"}


def check_generation_retry_does_not_repeat_observed(owned):
    backend, views, _ = owned
    backend.run_context["states"]["early"].pop("observedSynced")
    with (
        patch.object(controller, "sync_successful", side_effect=mark_observed) as sync,
        patch.object(M, "run", side_effect=OSError("publication failed")),
    ):
        assert not controller._callback_run_deploy_sync_once(
            backend, backend.save, backend.run_context, backend.units
        )
    sync.assert_called_once()
    backend.sync_failed = False
    generation = generation_for(backend, views)
    with (
        patch.object(controller, "sync_successful") as sync,
        patch.object(
            M.sync_runtime,
            "generation_context",
            return_value=nullcontext(SimpleNamespace(contents={}, selections={})),
        ),
        patch.object(M.sync_runtime, "prepare_generation", return_value=generation),
        patch.object(M.sync_runtime, "validate_generation"),
        patch.object(
            M.sync_runtime, "publish_generation", side_effect=publish_candidate
        ),
    ):
        assert controller._callback_run_deploy_sync_once(
            backend, backend.save, backend.run_context, backend.units
        )
    sync.assert_not_called()
    assert backend.run_context["states"]["early"]["observedSynced"]
    assert not backend.run_context["pendingGeneration"]
    assert "generationError" not in backend.run_context


@pytest.mark.parametrize("failed", [False, True])
def check_generation_only_preserves_observed_history(owned, failed):
    backend, _, _ = owned
    history = {
        "observedError": "first Observed failure",
        "observedRecoveryError": "latest Observed failure",
        "observedFailures": [
            {"stage": "MODEL_PUBLISHED", "cause": "first Observed failure"}
        ],
    }
    backend.run_context.update(copy.deepcopy(history))
    with patch.object(
        M, "run", side_effect=OSError("generation failed") if failed else None
    ):
        assert controller._callback_run_deploy_sync_once(
            backend, backend.save, backend.run_context, backend.units
        ) == (not failed)
    assert {k: backend.run_context[k] for k in history} == history


def check_waiting_identity_survives_later_stack_input_claim(owned):
    backend, views, _ = owned
    invoke(backend, generation_for(backend, views, ["iam"]))
    backend.run_context["consumedInputs"]["infra/build.yaml"] = (
        "claimed-for-later-stack"
    )
    backend.run_context["modelInputs"]["model/dev/team/unrelated.properties"] = (
        "first-consumption"
    )
    with (
        patch.object(M.sync_runtime, "prepare_generation") as prepare,
        patch.object(M.observed, "check_generated") as check,
    ):
        M.run(backend)
    prepare.assert_not_called()
    check.assert_not_called()


def check_pending_generation_deduplicates_new_observations(owned):
    backend, views, _ = owned
    invoke(backend, generation_for(backend, views, ["iam"]))
    before = copy.deepcopy(backend.run_context["pendingGeneration"])
    record = next(iter(before.values()))
    M.enqueue(
        backend, {"identity": record["identity"], "generated": record["generated"]}
    )
    assert backend.run_context["pendingGeneration"] == before


@pytest.mark.parametrize("change", ["bytes", "symlink", "file-set"])
@pytest.mark.parametrize("failed", [False, True])
def check_published_candidate_preserves_model_input_guards(owned, change, failed):
    backend, views, _ = owned
    source = backend.root / "model/dev/team/iam.properties"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"confirmed authority")
    relative = source.relative_to(backend.root).as_posix()
    manifest = observed_resume.manifest({relative: source.read_bytes()})
    backend.run_context["modelInputs"].update(manifest)
    generation = generation_for(backend, views)
    for view, files in generation.expected_outputs.items():
        record = backend.run_context["pendingGeneration"][
            view.relative_to(backend.root).as_posix()
        ]
        record["candidateManifest"] = manifest
        record["candidateSelections"] = [
            [
                source.parent.relative_to(backend.root).as_posix(),
                "*.properties",
                False,
                None,
                [relative],
            ]
        ]
        record["generated"].update(
            outputs={
                p.relative_to(backend.root).as_posix(): t for p, t in files.items()
            },
            stage="CANDIDATE",
        )
    publish_candidate(generation)
    if failed:
        backend.run_context["generationError"] = "unclassified generation failure"
    if change == "bytes":
        source.write_bytes(b"external change")
    elif change == "symlink":
        other = source.with_suffix(".txt")
        other.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(other)
    else:
        source.with_name("extra.properties").write_bytes(b"unregistered authority")
    with (
        patch.object(M.sync_runtime, "prepare_generation") as prepare,
        pytest.raises((Blocked, ValueError)),
    ):
        M.run(backend)
    prepare.assert_not_called()
    assert len(backend.run_context["pendingGeneration"]) == 3


def check_same_failure_is_not_retried_while_draining(owned):
    backend, _, _ = owned
    with patch.object(M, "run", side_effect=OSError("publication failed")) as generate:
        assert not controller._callback_run_deploy_sync_once(
            backend, backend.save, backend.run_context, backend.units
        )
        assert not controller._callback_run_deploy_sync_once(
            backend, backend.save, backend.run_context, backend.units
        )
    generate.assert_called_once()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
