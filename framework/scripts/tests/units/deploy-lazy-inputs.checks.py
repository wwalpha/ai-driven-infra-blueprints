"""Synthetic Deploy read counts and incremental Model/publication safety."""

import json
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
from deploy import controller, handoff, inputs, model_cache, scheduler, session
from deploy.model_cache import SessionModels
from model.adapters.observed import mapped_resource, resource_index
from model.format import FORMAT, INDEX, parse, serialize
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


def guard_model_io(root, function, path, *args, **kwargs):
    assert not path.is_relative_to(root / "model"), "repeated Model I/O"
    return function(path, *args, **kwargs)


def interrupt_journal_unlink(journal, unlink, path, *args, **kwargs):
    if path == journal:
        raise OSError("interrupted unlink")
    return unlink(path, *args, **kwargs)


def check_model_load_once_parallel_and_observed(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    scope.path.write_text(
        patch_properties(
            parse(scope.path.read_text()),
            {
                "desired.row.007-002.property": "EC2.VPC.CidrBlock",
                "desired.row.007-002.value": "`10.0.0.0/16`",
                "desired.row.007-002.comment": "合成 CIDR",
            },
        )
    )
    dependency_index.rebuild(tmp_path)
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
        dependency_index.load(tmp_path)
        assert all(value is first for value in results)
        assert (
            sum(call.args[0].path == scope.path for call in loads.call_args_list) == 1
        )
        assert (
            sum(call.args[0].scope.path == scope.path for call in checks.call_args_list)
            == 1
        )
        with (
            patch.object(
                model_cache, "revision", side_effect=AssertionError("repeated revision")
            ),
            patch.object(
                Path,
                "read_bytes",
                autospec=True,
                side_effect=partial(guard_model_io, tmp_path, Path.read_bytes),
            ),
            patch.object(
                Path,
                "stat",
                autospec=True,
                side_effect=partial(guard_model_io, tmp_path, Path.stat),
            ),
        ):
            for _ in range(100):
                assert sources.load_model(scope.path) is first
        load_count, check_count = loads.call_count, checks.call_count
        accumulated = {}
        for row, value in [
            ("007-001", "vpc-first"),
            ("007-002", "10.0.0.0/16"),
            ("007-001", "vpc-second"),
        ]:
            text = patch_properties(
                parse(scope.path.read_text()),
                {f"observed.row.{row}.value": f"`{value}`"},
            )
            scope.path.write_text(text)
            with (
                patch.object(
                    dependency_index,
                    "inventory",
                    side_effect=AssertionError("inventory"),
                ),
                patch.object(
                    dependency_index,
                    "read_sealed",
                    side_effect=AssertionError("index reload"),
                ),
                patch.object(
                    dependency_index, "record", side_effect=AssertionError("reanalysis")
                ),
                patch.object(
                    model_cache,
                    "verify_snapshot",
                    side_effect=AssertionError("index recheck"),
                ),
            ):
                dependency_index.update(tmp_path, {scope.path}, observed=True)
                cache.apply_observed({scope.path: text})
                cache.source(scope, cache)
                assert dependency_index.owners(
                    tmp_path, scope.environment, scope.target, ["fixture-OriginalVpc"]
                ) == [scope.path]
            accumulated[f"observed.row.{row}.value"] = f"`{value}`"
            current = sources.load_model(scope.path).authoritative
            assert all(current[key] == value for key, value in accumulated.items())
        assert loads.call_count == load_count and checks.call_count == check_count
    print(
        "100 shared Model requests: load=1, check=1; subsequent/Observed reload=0, recheck=0"
    )


def check_unrelated_invalid_model_and_shared_index(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    existing = scope.path.with_name("existing.properties")
    existing.write_text(serialize({}))
    dependency_index.rebuild(tmp_path)
    existing.write_text("unrelated invalid change")
    unconnected = scope.path.with_name("unrelated.properties")
    unconnected.write_text("this is invalid properties")
    with (
        sources.model_session(SessionModels(tmp_path, {})),
        patch.object(
            dependency_index, "inventory", side_effect=AssertionError("inventory")
        ),
        patch.object(
            dependency_index, "read_sealed", wraps=dependency_index.read_sealed
        ) as index_reads,
    ):
        assert sources.load_model(scope.path).scope == scope
        for _ in range(100):
            assert dependency_index.owners(
                tmp_path, scope.environment, scope.target, ["fixture-OriginalVpc"]
            ) == [scope.path]
            dependency_index.logical_models(
                tmp_path, scope.environment, scope.target, "EC2_VPC_001"
            )
            dependency_index.consumers(tmp_path, set(), set())
        assert index_reads.call_count == 1
        unconnected.write_text("another unrelated change")
        assert (
            dependency_index.owners(
                tmp_path, scope.environment, scope.target, ["unused"]
            )
            == []
        )
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
    with (
        patch.object(
            dependency_index, "record", wraps=dependency_index.record
        ) as reindex,
        patch.object(
            dependency_index, "inventory", side_effect=AssertionError("inventory")
        ),
    ):
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
        first = sources.load_model(scope.path)
        assert sources.load_model(scope.path) is first
        context.return_value = ("second",)
        sources.load_model(scope.path)
        assert (
            sum(call.args[0].path == scope.path for call in loaded.call_args_list) == 2
        )
        scope.path.write_bytes(scope.path.read_bytes() + b"# changed input revision\n")
        assert sources.load_model(scope.path).files == first.files
        with pytest.raises(ValueError, match="differs from consumed inputs"):
            sources.load_model(scope.path, sources.FileReads())
        with patch.object(
            permission, "require_readable", side_effect=ValueError("denied")
        ):
            with pytest.raises(ValueError, match="denied"):
                sources.load_model(scope.path)
    with sources.model_session(SessionModels(tmp_path, cache.session)):
        for _ in range(2):
            with pytest.raises(ValueError, match="differs from saved session"):
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
            assert sources.load_model(candidate_path) is candidate
        with sources.model_stage(tmp_path, stage):
            with pytest.raises(ValueError, match="staged Model differs"):
                sources.load_model(candidate_path)
        assert not cache.stages
        with pytest.raises(ValueError, match="unsupported Model format"):
            sources.load_model(
                scope.path,
                sources.CandidateReads(cache, {scope.path: "invalid candidate"}),
            )


def check_first_read_revision_race(tmp_path):
    path = tmp_path / "model.properties"
    path.write_text("input")
    cache = SessionModels(tmp_path, {})
    with patch.object(model_cache, "revision", side_effect=[[1] * 5, [2] * 5]):
        with pytest.raises(ValueError, match="changed during first read"):
            cache.read(path)
    assert path not in cache.contents


@pytest.mark.parametrize(
    "problem", ["signature", "shape", "membership", "owners", "missing"]
)
@pytest.mark.parametrize("loaded_first", [False, True])
def check_index_corruption_and_related_model(
    tmp_path, monkeypatch, problem, loaded_first
):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    dependency_index.rebuild(tmp_path)
    path = dependency_index.location(tmp_path)
    index = dependency_index.load(tmp_path)
    relative = scope.path.relative_to(tmp_path).as_posix()
    if problem == "signature":
        envelope = json.loads(path.read_text())
        envelope["signature"] = "0" * 64
        path.write_text(json.dumps(envelope))
    else:
        if problem == "shape":
            index = []
        elif problem == "membership":
            index["models"][relative]["files"] = []
        elif problem == "owners":
            index["models"][relative]["owners"] = ["wrong-owner"]
        else:
            del index["models"][relative]
            del index["files"][relative]
        dependency_index.write_sealed(tmp_path, path, index)
    cache = SessionModels(tmp_path, {})
    with sources.model_session(cache):
        if loaded_first:
            sources.load_model(scope.path)
        with pytest.raises(ValueError, match="evidence|dependency index"):
            dependency_index.load(tmp_path)
            sources.load_model(scope.path)


def check_index_service_part_add_retarget_delete(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    dependency_index.rebuild(tmp_path)
    added = scope.path.with_name("added.properties")
    part = added.with_suffix("") / "part-001.properties"
    part.parent.mkdir()
    part.write_text(scope.path.read_text())
    added.write_text(FORMAT + "\n" + INDEX + "\n# part: added/part-001.properties\n")
    untouched = dependency_index.load(tmp_path)["models"][
        scope.path.relative_to(tmp_path).as_posix()
    ]
    with patch.object(
        dependency_index, "inventory", side_effect=AssertionError("inventory")
    ):
        dependency_index.update(tmp_path, {added, part})
        text = patch_properties(
            parse(part.read_text()),
            {
                "desired.resource.007.cfn-logicalId": "fixture-AddedVpc",
                "desired.row.007-002.property": "EC2.VPC.Name",
                "desired.row.007-002.value": "[link](network.md#resource-EC2_VPC_001)",
            },
        )
        part.write_text(text)
        dependency_index.update(tmp_path, {part})
        assert dependency_index.owners(
            tmp_path, scope.environment, scope.target, ["fixture-AddedVpc"]
        ) == [added]
        assert added in dependency_index.consumers(
            tmp_path, {f"{scope.environment}/{scope.target}/network"}, set()
        )
        assert (
            dependency_index.load(tmp_path)["models"][
                scope.path.relative_to(tmp_path).as_posix()
            ]
            == untouched
        )
        part.unlink()
        added.unlink()
        dependency_index.update(tmp_path, {added, part})
        assert (
            dependency_index.owners(
                tmp_path, scope.environment, scope.target, ["fixture-AddedVpc"]
            )
            == []
        )


@pytest.mark.parametrize("interrupted", [False, True])
def check_index_transaction_rollback_and_recovery(tmp_path, monkeypatch, interrupted):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, _ = deploy_properties_fixture(tmp_path)
    dependency_index.rebuild(tmp_path)
    original = scope.path.read_bytes()
    output = patch_properties(
        parse(original.decode()),
        {"desired.resource.007.cfn-logicalId": "fixture-NewVpc"},
    )
    with sources.publication_lock(tmp_path) as journal:
        if interrupted:
            with patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=partial(interrupt_journal_unlink, journal, Path.unlink),
            ):
                with pytest.raises(OSError, match="interrupted unlink"):
                    sources._publish_transaction(
                        tmp_path, {scope.path: output}, (), journal
                    )
            assert dependency_index.owners(
                tmp_path, scope.environment, scope.target, ["fixture-NewVpc"]
            ) == [scope.path]
        else:
            with patch.object(
                dependency_index, "record", side_effect=ValueError("index failure")
            ):
                with pytest.raises(ValueError, match="index failure"):
                    sources._publish_transaction(
                        tmp_path, {scope.path: output}, (), journal
                    )
            assert not journal.exists()
    with patch.object(
        dependency_index, "inventory", side_effect=AssertionError("inventory")
    ):
        with sources.publication_lock(tmp_path):
            pass
        assert scope.path.read_bytes() == original
        with sources.model_session(SessionModels(tmp_path, {})):
            sources.load_model(scope.path)
            assert dependency_index.owners(
                tmp_path, scope.environment, scope.target, ["fixture-OriginalVpc"]
            ) == [scope.path]


if __name__ == "__main__":
    raise SystemExit(run(__file__))
