"""Synthetic Deploy read counts and incremental Model/publication safety."""

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import model.observed as model_observed
import model.sources as sources
import model.validation as model_validation
import pytest
from deploy import controller, handoff, inputs, scheduler, session
from deploy.model_cache import SessionModels
from model.adapters.observed import mapped_resource, resource_index
from model.format import parse, serialize
from model.format import patch as patch_properties
from model.render import stack_markdown
from support.model_v2_fixtures import deploy_properties_fixture
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked
from validation.findings import Findings

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


class Queue:
    def __init__(self, fail, limit):
        self.loads, self.deliveries, self.executed = [], [], []
        self.fail, self.limit = fail, limit

    def load_inputs(self, unit):
        self.loads.append(unit["name"])
        assert len(self.loads) <= self.limit or not self.fail

    def prepare_delivery_group(self, units, states):
        self.deliveries.extend(u["name"] for u in units)

    def prepare(self, unit, state):
        return "READY"

    def execute(self, unit, state):
        self.executed.append(unit["name"])

    def poll(self, unit, state):
        return "ROLLBACK_COMPLETE" if self.fail else "CREATE_COMPLETE"


@pytest.mark.parametrize("limit", [1, 3])
def check_100_stacks_bounded(limit):
    units = [{"name": str(i), "deployOrder": 10} for i in range(100)]
    states = {u["name"]: {"status": "NOT_STARTED"} for u in units}
    backend = Queue(True, limit)
    assert (
        scheduler.run_group(units, limit, states, backend, sleep=lambda _: None)
        == "STOPPED"
    )
    assert (
        backend.loads
        == backend.deliveries
        == backend.executed
        == [str(i) for i in range(limit)]
    )
    assert all(states[str(i)]["status"] == "NOT_STARTED" for i in range(limit, 100))
    print(
        f"100 Stacks, concurrency {limit}: loaded={len(backend.loads)}, untouched decode=0"
    )


def load_shared(cache, path, ignored):
    return cache.load(sources.scope_for(path), cache)


def diagnose_cached(cache, diagnose, snapshot, reads):
    assert sources.session_reads(snapshot.scope.root) is cache
    return diagnose(snapshot, reads)


def check_model_load_once_parallel_and_observed(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    cache = SessionModels(tmp_path, {})
    loader = sources._read_model
    diagnose = sources._imports_model_references.diagnose
    with (
        sources.model_session(cache),
        patch.object(sources, "_read_model", wraps=loader) as loads,
        patch.object(
            sources._imports_model_references,
            "diagnose",
            side_effect=partial(diagnose_cached, cache, diagnose),
        ) as checks,
    ):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(partial(load_shared, cache, scope.path), range(100))
            )
        first = sources.load_model(scope.path)
        assert all(value is first for value in results)
        assert (
            sum(call.args[0].path == scope.path for call in loads.call_args_list) == 1
        )
        assert (
            sum(call.args[0].scope.path == scope.path for call in checks.call_args_list)
            == 1
        )
        load_count, check_count = loads.call_count, checks.call_count
        for row, value in [("007-001", "vpc-first"), ("007-001", "vpc-second")]:
            text = patch_properties(
                parse(scope.path.read_text()),
                {f"observed.row.{row}.value": f"`{value}`"},
            )
            scope.path.write_text(text)
            cache.apply_observed({scope.path: text})
            assert (
                sources.load_model(scope.path).authoritative[
                    f"observed.row.{row}.value"
                ]
                == f"`{value}`"
            )
        assert loads.call_count == load_count and checks.call_count == check_count
    print(
        "100 shared Model requests: load=1, check=1; subsequent/Observed reload=0, recheck=0"
    )


def check_unrelated_invalid_model_and_missing_stale_index(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    dependency_index.rebuild(tmp_path)
    unconnected = scope.path.with_name("unrelated.properties")
    unconnected.write_text("this is invalid properties")
    with sources.model_session(SessionModels(tmp_path, {})):
        assert sources.load_model(scope.path).scope == scope
    with pytest.raises(ValueError, match="stale"):
        dependency_index.owners(tmp_path, scope.environment, scope.target, ["unused"])
    dependency_index.location(tmp_path).unlink()
    with pytest.raises(ValueError, match="missing"):
        dependency_index.owners(tmp_path, scope.environment, scope.target, ["unused"])


def check_index_owners_duplicate_and_unknown(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    before = dependency_index.rebuild(tmp_path)
    expected = next(iter(before[scope.path.relative_to(tmp_path).as_posix()]["owners"]))
    assert dependency_index.owners(
        tmp_path, scope.environment, scope.target, [expected]
    ) == [scope.path]
    assert (
        dependency_index.owners(tmp_path, scope.environment, scope.target, ["unknown"])
        == []
    )
    duplicate = scope.path.with_name("duplicate.properties")
    duplicate.write_text(scope.path.read_text())
    dependency_index.rebuild(tmp_path)
    assert set(
        dependency_index.owners(tmp_path, scope.environment, scope.target, [expected])
    ) == {scope.path, duplicate}


def check_claim_immutable_inputs_and_no_eager_decode(tmp_path):
    template, parameters = tmp_path / "first.json", tmp_path / "parameters.json"
    template.write_text('{"Resources": {}}')
    parameters.write_text("[]")
    runtime = SimpleNamespace(
        root=tmp_path,
        session={
            "infraManifest": {},
            "unitDigests": {},
            "inputIdentities": {
                p.name: dependency_index.revision(p) for p in (template, parameters)
            },
        },
        hashes={},
    )
    runtime.deployment_input_paths = lambda _: [template, parameters]
    runtime.file_digest = partial(controller.file_digest, runtime)
    runtime.input_digest = partial(controller.input_digest, runtime)
    unit = {"name": "first"}
    session._callback_claim_inputs(
        tmp_path, runtime.session, runtime, lambda: None, unit
    )
    assert set(runtime.session["unitDigests"]) == {"first"}
    template.write_text('{"Resources": {}, "Description": "changed"}')
    with pytest.raises(Blocked, match="changed before first use"):
        session._callback_claim_inputs(
            tmp_path, runtime.session, runtime, lambda: None, unit
        )


@pytest.mark.parametrize("change", ["desired", "display", "raw"])
def check_observed_patch_rejects_authority_changes(tmp_path, monkeypatch, change):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    snapshot = sources.load_model(scope.path)
    updates = {"observed.row.007-001.value": "`vpc-new`"}
    if change == "desired":
        updates["desired.row.007-001.comment"] = "unexpected"
    if change == "display":
        updates["display.resource.007.label"] = "unexpected"
    text = patch_properties(snapshot.documents[scope.path], updates) + (
        "# unrelated\n" if change == "raw" else ""
    )
    with pytest.raises(ValueError, match="non-observed|unrelated"):
        sources.observed_snapshot(snapshot, {scope.path: text})


def check_resume_skips_success_and_dependency_unknown(tmp_path):
    units = [{"name": str(i), "deployOrder": 10} for i in range(3)]
    states = {u["name"]: {"status": "SUCCESS", "observedSynced": True} for u in units}
    states["2"] = {"status": "NOT_STARTED"}
    backend = Queue(False, 1)
    assert (
        scheduler.run_group(units, 1, states, backend, sleep=lambda _: None)
        == "GROUP_COMPLETE"
    )
    assert backend.loads == backend.executed == ["2"]
    backend.templates, backend.target = (
        {},
        {"awsRegion": "region", "awsAccountId": "account"},
    )
    assert handoff.dependencies(backend, units) == {
        "__unloaded__": [u["name"] for u in units]
    }


def check_desired_validation_reused_after_observed(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    cache = SessionModels(tmp_path, {})
    with (
        sources.model_session(cache),
        patch.object(
            model_validation, "_check_model_inputs", return_value=Findings(tmp_path)
        ) as validate,
    ):
        for value in ("vpc-one", "vpc-two"):
            snapshot = sources.load_model(scope.path)
            model_validation.check_model_inputs(
                scope.path, snapshot.authoritative, tmp_path
            )
            text = patch_properties(
                snapshot.documents[scope.path],
                {"observed.row.007-001.value": f"`{value}`"},
            )
            scope.path.write_text(text)
            cache.apply_observed({scope.path: text})
        model_validation.check_model_inputs(
            scope.path, sources.load_model(scope.path).authoritative, tmp_path
        )
        assert validate.call_count == 1


def check_observed_publication_rejects_conflict(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    snapshot = sources.load_model(scope.path)
    before = scope.path.read_bytes()
    output = patch_properties(
        snapshot.documents[scope.path], {"observed.row.007-001.value": "`vpc-new`"}
    )
    context = SimpleNamespace(snapshot=sources.FileReads())
    scope.path.write_bytes(before + b"# concurrent edit\n")
    with (
        patch.object(
            model_observed._imports_model_adapters_task,
            "observed_write_context",
            return_value=nullcontext(context),
        ),
        patch.object(
            model_observed._imports_model_operations, "_publish_plans"
        ) as publish,
    ):
        with pytest.raises(
            ValueError, match="input snapshot changed|unrelated original bytes"
        ):
            model_observed.publish_observed_candidates(
                tmp_path, {scope.path: output}, {scope.path: before}
            )
        publish.assert_not_called()
    assert scope.path.read_bytes() == before + b"# concurrent edit\n"


def check_stack_metadata_defers_delivery_model(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, stack = deploy_properties_fixture(tmp_path)
    values = dict(sources.stack_snapshot(stack).authoritative)
    reference = "[assets](missing.md#resource-S3_Bucket_001)"
    values["display.stack.009.comment"] = "synthetic Stack"
    values.update(
        {
            "desired.deployment.templateBucket": reference,
            "desired.deployment.templateKeyPrefix": "templates/",
        }
    )
    stack.write_text(serialize(values))
    design = (
        tmp_path
        / "docs/designs"
        / scope.environment
        / scope.target
        / "cloudformation-stacks.md"
    )
    design.parent.mkdir(parents=True)
    design.write_text(stack_markdown(design, values, tmp_path, validate_delivery=False))
    with (
        sources.model_session(SessionModels(tmp_path, {})),
        patch.object(sources, "_read_model", wraps=sources._read_model) as loaded,
    ):
        _, units = inputs.load_units(
            tmp_path, scope.environment, scope.target, ["CurrentName"]
        )
        assert units[0]["templateBucket"] == reference
        assert all(call.args[0].path == stack for call in loaded.call_args_list)
    with pytest.raises(ValueError):
        stack_markdown(design, values, tmp_path)


def check_index_delta_retarget_delete_and_invalid_unrelated(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    unrelated = scope.path.with_name("invalid.properties")
    unrelated.write_text(serialize({"desired.resource.001.resourceType": "invalid"}))
    with pytest.raises(ValueError):
        sources.load_model(unrelated)
    dependency_index.rebuild(tmp_path)
    values = parse(scope.path.read_text()).values
    old_owner = values["desired.resource.007.cfn-logicalId"]
    scope.path.write_text(
        patch_properties(
            parse(scope.path.read_text()),
            {"observed.row.007-001.value": "`vpc-updated`"},
        )
    )
    with patch.object(
        dependency_index, "record", wraps=dependency_index.record
    ) as reindex:
        dependency_index.update(tmp_path, {scope.path}, observed=True)
        reindex.assert_not_called()
    assert dependency_index.owners(
        tmp_path, scope.environment, scope.target, [old_owner]
    ) == [scope.path]
    scope.path.write_text(
        patch_properties(
            parse(scope.path.read_text()),
            {"desired.resource.007.cfn-logicalId": "fixture-NewVpc"},
        )
    )
    dependency_index.update(tmp_path, {scope.path})
    assert (
        dependency_index.owners(tmp_path, scope.environment, scope.target, [old_owner])
        == []
    )
    assert dependency_index.owners(
        tmp_path, scope.environment, scope.target, ["fixture-NewVpc"]
    ) == [scope.path]
    scope.path.unlink()
    dependency_index.update(tmp_path, {scope.path})
    assert (
        dependency_index.owners(
            tmp_path, scope.environment, scope.target, ["fixture-NewVpc"]
        )
        == []
    )


def check_owner_ambiguity_blocks_mapping(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    duplicate = scope.path.with_name("duplicate.properties")
    duplicate.write_bytes(scope.path.read_bytes())
    dependency_index.rebuild(tmp_path)
    paths = dependency_index.owners(
        tmp_path, scope.environment, scope.target, ["fixture-OriginalVpc"]
    )
    loaded = {p: sources.load_model(p).values for p in paths}
    index = resource_index(
        loaded, SimpleNamespace(cloudformation_type=lambda _: "AWS::EC2::VPC")
    )
    with pytest.raises(ValueError, match="matches=2"):
        mapped_resource(index, "fixture", "OriginalVpc", "AWS::EC2::VPC")
    with pytest.raises(ValueError, match="matches=0"):
        mapped_resource(index, "fixture", "Unknown", "AWS::EC2::VPC")


def check_cache_permission_and_input_revision(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    cache = SessionModels(tmp_path, {})
    permission = sources._imports_model_importing_scope
    with (
        sources.model_session(cache),
        patch.object(permission, "read_context", return_value=("first",)) as context,
        patch.object(sources, "_read_model", wraps=sources._read_model) as loaded,
    ):
        sources.load_model(scope.path)
        sources.load_model(scope.path)
        context.return_value = ("second",)
        sources.load_model(scope.path)
        assert (
            sum(call.args[0].path == scope.path for call in loaded.call_args_list) == 2
        )
        scope.path.write_bytes(scope.path.read_bytes() + b"# changed input revision\n")
        with pytest.raises(ValueError, match="consumed Model input changed"):
            sources.load_model(scope.path)


def check_generation_stage_reuses_checked_model(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    cache = SessionModels(tmp_path, {})
    stage = tmp_path / "candidate-stage"
    with (
        sources.model_session(cache),
        patch.object(sources, "_read_model", wraps=sources._read_model) as loaded,
    ):
        before = sources.load_model(scope.path)
        for path, raw in before.dependencies.items():
            if raw is not None:
                destination = stage / path.relative_to(tmp_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
        candidate_path = stage / scope.path.relative_to(tmp_path)
        with sources.model_stage(tmp_path, stage):
            candidate = sources.load_model(candidate_path)
            assert candidate.authoritative is before.authoritative
            assert candidate.scope.root == stage
            assert (
                sum(
                    call.args[0].service == scope.service
                    for call in loaded.call_args_list
                )
                == 1
            )
            candidate_path.write_bytes(
                candidate_path.read_bytes() + b"# changed candidate\n"
            )
            with pytest.raises(ValueError, match="staged Model differs"):
                sources.load_model(candidate_path)
        assert not cache.stages


if __name__ == "__main__":
    raise SystemExit(run(__file__))
