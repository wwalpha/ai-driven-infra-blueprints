"""Execution-local reuse of parsed inputs without sharing mutable worker state."""

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import sync_runtime
from design import layout, policy_tables
from generation_inputs import GenerationInputs
from model.core import SnapshotValues
from model.format import serialize
from model.importing import scope as permissions
from support.model_sources import write_model
from support.pytest_cli import run
from utils import source_reads
from utils.input_cache import input_context, memo_table, recording_inputs

from model import change_scope, dependency_index, sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def model_input(root):
    (root / "project.json").write_text(
        '{"projectName":"fixture","targets":[{"environment":"dev",'
        '"alias":"team","awsAccountId":"123456789012",'
        '"awsRegion":"ap-northeast-1","iacEngine":"cloudformation"}]}\n',
        encoding="utf-8",
    )
    path = root / "model/dev/team/logs.properties"
    values = {
        "desired.service.logs.serviceId": "logs",
        "desired.service.logs.ownedCatalogResourceTypes": "Logs.LogGroup",
        "desired.service.identity.lastAllocated": '{"Logs.LogGroup":1}',
        "desired.resource.001.logicalId": "Logs_LogGroup_001",
        "desired.resource.001.anchor": "logs-group",
        "desired.resource.001.resourceType": "Logs.LogGroup",
        "desired.row.001-001.property": "Logs.LogGroup.LogGroupName",
        "desired.row.001-001.value": "`fixture-logs`",
        "desired.row.001-001.comment": "合成",
    }
    write_model(path, values)
    return path, values


def check_update_reads_are_live_inside_input_context(tmp_path):
    path, values = model_input(tmp_path)
    path.unlink()
    with input_context(fresh=True):
        assert not sources.model_exists(path)
        write_model(path, values)
        assert sources.model_exists(path)
        assert sources.model_parts(path) == [path]
        original = sources.load_model(path)
        assert sources.raw_model(path).authoritative == values
        replacement = dict(values, **{"desired.row.001-001.value": "`changed`"})
        write_model(path, replacement)
        assert sources.raw_model(path).authoritative == replacement
        assert sources.load_model(path).authoritative == replacement
        assert original.authoritative == values
        path.unlink()
        assert not sources.model_exists(path)
        with pytest.raises(FileNotFoundError):
            sources.model_parts(path)


def check_index_rebuild_is_live_inside_input_context(tmp_path):
    path, values = model_input(tmp_path)
    dependency_index.rebuild(tmp_path)
    relative = path.relative_to(tmp_path).as_posix()
    with input_context(fresh=True):
        original = dependency_index.load(tmp_path)
        write_model(
            path,
            dict(values, **{"desired.resource.001.logicalId": "Logs_LogGroup_002"}),
        )
        dependency_index.rebuild(tmp_path)
        rebuilt = dependency_index.load(tmp_path)
        assert rebuilt["files"][relative] != original["files"][relative]
        assert rebuilt["models"][relative]["logical"] == ["Logs_LogGroup_002"]
        assert dependency_index.load(tmp_path) == rebuilt


@pytest.mark.parametrize("candidate", [False, True])
def check_explicit_read_context_keeps_its_snapshot(tmp_path, candidate):
    path, values = model_input(tmp_path)
    reads = sources.FileReads()
    if candidate:
        reads = sources.CandidateReads(reads, {path: serialize(values)})
    with input_context(fresh=True):
        original = sources.raw_model(path, reads)
        write_model(path, dict(values, **{"desired.row.001-001.value": "`changed`"}))
        assert sources.raw_model(path, reads) is original
        assert sources.raw_model(path).authoritative != original.authoritative


@pytest.mark.parametrize("raw_first", [True, False])
def check_one_parse_for_raw_checked_and_layout(tmp_path, raw_first):
    path, values = model_input(tmp_path)
    with (
        input_context(fresh=True, read_only=True),
        patch.object(sources, "parse", wraps=sources.parse) as parse,
    ):
        readers = [sources.raw_model, sources.load_model]
        first, second = (
            reader(path) for reader in (readers if raw_first else reversed(readers))
        )
        checked = sources.load_model(path)
        assert (
            layout.design_model_values(
                tmp_path / "docs/designs/dev/team/logs.md", tmp_path
            )
            is checked.values
        )
        assert (
            sources.raw_model(path).authoritative
            == first.authoritative
            == second.authoritative
            == values
        )
        assert parse.call_count == 1


def check_reader_candidate_root_and_next_execution(tmp_path):
    first, values = model_input(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    second, _ = model_input(other)
    replacement = dict(values, **{"desired.row.001-001.value": "`changed`"})
    with (
        input_context(fresh=True, read_only=True),
        patch.object(sources, "parse", wraps=sources.parse) as parse,
    ):
        original = sources.raw_model(first)
        assert sources.raw_model(second) is not original
        for text in (serialize(replacement), serialize(values)):
            reads = sources.CandidateReads(sources.FileReads(), {first: text})
            candidate = sources.raw_model(first, reads)
            assert candidate.authoritative == (
                replacement if "`changed`" in text else values
            )
            assert sources.raw_model(first, reads) is candidate
        write_model(first, replacement)
        assert sources.raw_model(first) is original
        assert parse.call_count == 4
    with input_context(fresh=True, read_only=True):
        assert sources.raw_model(first).authoritative == replacement


def check_permission_checked_before_cached_source(tmp_path):
    path, _ = model_input(tmp_path)
    with (
        input_context(fresh=True, read_only=True),
        permissions.restrict(("dev", "team", "logs")),
    ):
        original = sources.raw_model(path)
        with permissions.read_consumers({("dev", "team", "other")}):
            with pytest.raises(ValueError, match="outside selected"):
                sources.raw_model(path)
            with permissions.reference_reader(path):
                reference = sources.raw_model(path)
                assert reference is not original
                assert sources.raw_model(path) is reference
        assert sources.raw_model(path) is original


def check_index_checked_once_per_root_permission_and_execution(tmp_path):
    path, _ = model_input(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    model_input(other)
    for root in (tmp_path, other):
        dependency_index.rebuild(root)
    with patch.object(dependency_index, "_load", wraps=dependency_index._load) as load:
        with input_context(fresh=True, read_only=True):
            assert dependency_index.load(tmp_path) is dependency_index.load(tmp_path)
            assert load.call_count == 1
            dependency_index.load(tmp_path)
            assert load.call_count == 1
            with (
                permissions.restrict(("dev", "team", "logs")),
                permissions.reference_reader(path),
            ):
                dependency_index.load(tmp_path)
            dependency_index.load(tmp_path / "other")
            assert load.call_count == 3
        with input_context(fresh=True, read_only=True):
            dependency_index.load(tmp_path)
        assert load.call_count == 4


class ColdWorker:
    def __init__(self, inputs, path, *, inventory=False, checked=False):
        self.inputs, self.path = inputs, path
        self.barrier = Barrier(4)
        self.inventory, self.diagnostics = inventory, []
        self.checked = checked

    def __call__(self, number):
        with input_context(
            fresh=True, read_only=True, inputs=sources.fork_model_inputs(self.inputs)
        ):
            self.barrier.wait(timeout=10)
            reads = sources._invocation_reads(self.path.parents[3])
            if self.inventory:
                metadata = {}
                with change_scope.change_reads(metadata=metadata):
                    index = dependency_index.check_change_inventory(
                        self.path.parents[3], set()
                    )
                self.diagnostics.append(metadata)
            else:
                index = dependency_index.load(self.path.parents[3])
            snapshot = (sources.load_model if self.checked else sources.raw_model)(
                self.path
            )
            reads.models[number] = None
            return snapshot, reads, index


@pytest.mark.parametrize("recorded", [False, True])
@pytest.mark.parametrize("checked", [False, True])
def check_cold_workers_share_one_read_parse_and_index(tmp_path, recorded, checked):
    path, values = model_input(tmp_path)
    dependency_index.rebuild(tmp_path)
    with ExitStack() as lifetime:
        lifetime.enter_context(input_context(fresh=True, read_only=True))
        if recorded:
            recorder = GenerationInputs(tmp_path, read_only=True)
            lifetime.callback(recorder.close)
            lifetime.enter_context(recording_inputs(recorder))
        reads = sources._invocation_reads(tmp_path)
        assert path not in reads.contents and not reads.documents
        inputs = dict(memo_table())
        worker = ColdWorker(inputs, path, checked=checked)
        with (
            patch.object(sources, "_read_model", wraps=sources._read_model) as model,
            patch.object(
                sources, "validate_blocks", wraps=sources.validate_blocks
            ) as blocks,
            patch.object(
                sources, "runtime_values", wraps=sources.runtime_values
            ) as runtime,
            patch.object(
                sources._imports_model_references,
                "diagnose",
                wraps=sources._imports_model_references.diagnose,
            ) as diagnose,
            patch.object(sources, "parse", wraps=sources.parse) as parse,
            patch.object(
                source_reads, "input_bytes", wraps=source_reads.input_bytes
            ) as read,
            patch.object(
                dependency_index, "_load", wraps=dependency_index._load
            ) as index,
            ThreadPoolExecutor(max_workers=4) as executor,
        ):
            first = list(executor.map(worker, range(4)))
            assert parse.call_count == 1
            write_model(
                path, dict(values, **{"desired.row.001-001.value": "`changed`"})
            )
            second = list(executor.map(worker, range(4)))
        assert parse.call_count == 1
        assert (
            model.call_count == blocks.call_count == runtime.call_count == int(checked)
        )
        assert diagnose.call_count == int(checked)
        assert sum(call.args == (path,) for call in read.call_args_list) == 1
        assert index.call_count == 1
        assert all(
            snapshot.authoritative == values for snapshot, _, _ in first + second
        )
        assert all(
            snapshot.documents[path] is first[0][0].documents[path]
            for snapshot, _, _ in first + second
        )
        assert len({id(fork.models) for _, fork, _ in first}) == 4
        assert not any(number in reads.models for number in range(4))
        assert all(loaded is first[0][2] for _, _, loaded in first + second)
        if checked:
            assert all(
                snapshot.authoritative is first[0][0].authoritative
                and snapshot.values is first[0][0].values
                for snapshot, _, _ in first + second
            )
    with input_context(fresh=True, read_only=True):
        assert sources.raw_model(path).authoritative != values


@pytest.mark.parametrize("warm", [False, True])
def check_diagnosis_keeps_worker_warnings_private(tmp_path, warm):
    path, values = model_input(tmp_path)
    values["desired.row.001-001.value"] = "[Absent](missing.md#absent)"
    write_model(path, values)
    with input_context(fresh=True, read_only=True):
        single = sources.load_model(path)
    assert single.warnings
    with (
        input_context(fresh=True, read_only=True),
        patch.object(
            sources._imports_model_references,
            "diagnose",
            wraps=sources._imports_model_references.diagnose,
        ) as diagnose,
    ):
        reads = sources._invocation_reads(tmp_path)
        original = sources.load_model(path) if warm else None
        if warm:
            direct = sources.load_model(path, reads.fork())
            direct.warnings[0]["message"] = "private direct fork"
            assert original.warnings == single.warnings
        inputs = dict(memo_table())
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(worker_read, [(inputs, path)] * 4))
        assert diagnose.call_count == 1
        snapshots = [snapshot for snapshot, _ in results]
        for snapshot in snapshots:
            assert snapshot == single
        assert len({id(s.warnings[0]) for s in snapshots}) == 4
        snapshots[0].warnings[0]["message"] = "private"
        assert all(s.warnings == single.warnings for s in snapshots[1:])
        if original is not None:
            assert original.warnings == single.warnings
        assert "private" not in reads.models


def check_diagnosis_respects_change_context_and_candidate_producers(tmp_path):
    path, values = model_input(tmp_path)
    producer = path.with_name("producer.properties")
    write_model(producer, values)
    values = dict(values)
    values["desired.row.001-001.value"] = "[Producer](producer.md#logs-group)"
    write_model(path, values)
    with (
        input_context(fresh=True, read_only=True),
        patch.object(
            sources._imports_model_references,
            "diagnose",
            wraps=sources._imports_model_references.diagnose,
        ) as diagnose,
    ):
        original = sources.load_model(path)
        assert not original.warnings
        reads = sources._invocation_reads(tmp_path)
        candidate_values = dict(sources.raw_model(producer).authoritative)
        candidate_values["desired.resource.001.anchor"] = "candidate-anchor"
        candidate = sources.raw_model(
            producer,
            sources.CandidateReads(reads, {producer: serialize(candidate_values)}),
        )
        metadata = {"snapshots": {producer: candidate}}
        with change_scope.change_reads(tmp_path, reads, metadata=metadata):
            changed = sources.load_model(path)
            assert changed.warnings
            assert any(
                "candidate-anchor" in raw.decode()
                for raw in changed.dependencies.values()
                if raw
            )
        with change_scope.change_reads(tmp_path, reads, metadata={}):
            unchanged = sources.load_model(path)
            assert not unchanged.warnings
        assert sources.load_model(path) is original
        assert diagnose.call_count == 3


def check_shared_sources_respect_permission_and_candidate_boundaries(tmp_path):
    path, values = model_input(tmp_path)
    with (
        input_context(fresh=True, read_only=True),
        patch.object(sources, "_read_model", wraps=sources._read_model) as read,
    ):
        original = sources.load_model(path)
        reads = sources._invocation_reads(tmp_path)
        with permissions.restrict(("dev", "team", "logs")):
            restricted = sources.load_model(path, reads.fork())
            assert restricted.authoritative == original.authoritative
            assert restricted.authoritative is not original.authoritative
            with permissions.read_consumers({("dev", "team", "other")}):
                with pytest.raises(ValueError, match="outside selected"):
                    sources.load_model(path, reads.fork())
                with permissions.reference_reader(path):
                    reference = sources.load_model(path, reads.fork())
                    assert reference.authoritative is not restricted.authoritative
        for value in ("`candidate-a`", "`candidate-b`"):
            candidate = sources.load_model(
                path,
                sources.CandidateReads(
                    reads,
                    {
                        path: serialize(
                            dict(values, **{"desired.row.001-001.value": value})
                        )
                    },
                ),
            )
            assert candidate.authoritative["desired.row.001-001.value"] == value
        assert sources.load_model(path) is original
        assert read.call_count == 5


class SourceBuildProbe:
    def __init__(self, original, *, barrier=None, release=None):
        self.original, self.barrier, self.release = original, barrier, release
        self.started = Event()

    def __call__(self, scope, reads):
        self.started.set()
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        if self.release is not None:
            assert self.release.wait(timeout=10)
            raise ValueError("fixture source build failed")
        return self.original(scope, reads)


def check_distinct_source_builds_do_not_hold_shared_lock(tmp_path):
    path, values = model_input(tmp_path)
    other = path.with_name("other.properties")
    write_model(other, values)
    probe = SourceBuildProbe(sources._read_model, barrier=Barrier(2))
    with (
        input_context(fresh=True, read_only=True),
        patch.object(sources, "_read_model", probe),
    ):
        sources._invocation_reads(tmp_path)
        inputs = dict(memo_table())
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(worker_read, [(inputs, p) for p in (path, other)])
            )
        assert {snapshot.scope.path for snapshot, _ in results} == {path, other}


def check_source_waiting_for_publication_does_not_hold_read_lock(tmp_path):
    path, _ = model_input(tmp_path)
    probe = SourceBuildProbe(sources._read_model)
    with (
        input_context(fresh=True, read_only=True),
        patch.object(sources, "_read_model", probe),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        reads = sources._invocation_reads(tmp_path)
        inputs = dict(memo_table())
        with sources.publication_lock(tmp_path, read_only=True):
            future = executor.submit(worker_read, (inputs, path))
            assert probe.started.wait(timeout=10)
            assert reads.lock.acquire(timeout=2)
            reads.lock.release()
        assert future.result(timeout=10)[0].scope.path == path


class WaitingFuture(source_reads.Future):
    barrier = None

    def result(self, timeout=None):
        self.barrier.wait(timeout=10)
        return super().result(timeout=timeout)


def check_failed_source_build_reaches_all_waiters_and_can_retry(tmp_path):
    path, _ = model_input(tmp_path)
    release = Event()
    probe = SourceBuildProbe(sources._read_model, release=release)
    with input_context(fresh=True, read_only=True):
        reads = sources._invocation_reads(tmp_path)
        inputs = dict(memo_table())
        with (
            patch.object(sources, "_read_model", probe),
            patch.object(source_reads, "Future", WaitingFuture),
            patch.object(WaitingFuture, "barrier", Barrier(4)),
            ThreadPoolExecutor(max_workers=4) as executor,
        ):
            futures = [executor.submit(worker_read, (inputs, path)) for _ in range(4)]
            try:
                WaitingFuture.barrier.wait(timeout=10)
            finally:
                release.set()
            for future in futures:
                with pytest.raises(ValueError, match="fixture source build failed"):
                    future.result(timeout=10)
        assert not reads.snapshots
        assert sources.load_model(path).scope.path == path


def check_workers_share_inventory_and_retain_diagnostics(tmp_path):
    path, values = model_input(tmp_path)
    values.update(
        {
            "desired.row.001-002.property": "Logs.LogGroup.KmsKeyId",
            "desired.row.001-002.value": '`{"$modelRef":{"attribute":"Arn"}}`',
        }
    )
    write_model(path, values)
    with input_context(fresh=True, read_only=True):
        sources._invocation_reads(tmp_path)
        worker = ColdWorker(dict(memo_table()), path, inventory=True)
        with (
            patch.object(
                dependency_index, "inventory", wraps=dependency_index.inventory
            ) as inventory,
            patch.object(sources, "parse", wraps=sources.parse) as parse,
            ThreadPoolExecutor(max_workers=4) as executor,
        ):
            results = list(executor.map(worker, range(4)))
        assert inventory.call_count == parse.call_count == 1
        assert all(index is results[0][2] for _, _, index in results)
        assert len({id(metadata) for metadata in worker.diagnostics}) == 4
        assert all(
            metadata["reference_errors"][path] for metadata in worker.diagnostics
        )


def check_inventory_distinguishes_changed_sets_and_candidates(tmp_path):
    path, values = model_input(tmp_path)
    metadata = {}
    changed = {("dev", "team", "logs")}
    candidate = sources.CandidateReads(
        sources.FileReads(),
        {
            path: serialize(
                dict(values, **{"desired.resource.001.logicalId": "Logs_LogGroup_002"})
            ),
        },
    )
    with (
        input_context(fresh=True, read_only=True),
        change_scope.change_reads(metadata=metadata),
    ):
        original = dependency_index.check_change_inventory(tmp_path, set())
        forced = dependency_index.check_change_inventory(tmp_path, changed)
        replacement = dependency_index.check_change_inventory(
            tmp_path, changed, reads=candidate
        )
        assert forced == original and forced is not original
        assert replacement["models"][path.relative_to(tmp_path).as_posix()][
            "logical"
        ] == ["Logs_LogGroup_002"]
        assert dependency_index.check_change_inventory(tmp_path, set()) is original


def check_worker_forks_share_snapshots_and_keep_private_tables(tmp_path):
    path, _ = model_input(tmp_path)
    with input_context(fresh=True, read_only=True):
        model = sources.load_model(path)
        inputs = dict(memo_table())
        with patch.object(
            sources, "parse", side_effect=AssertionError("worker reparsed")
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                parallel = list(executor.map(worker_read, [(inputs, path)] * 4))
            sequential = [worker_read((inputs, path)) for _ in range(4)]
        assert all(value is model for value, _ in [*parallel, *sequential])
        assert len({id(reads.models) for _, reads in parallel}) == 4
        assert "private" not in sources._invocation_reads(tmp_path).models


def worker_read(arguments):
    inputs, path = arguments
    with input_context(
        fresh=True, read_only=True, inputs=sources.fork_model_inputs(inputs)
    ):
        reads = sources._invocation_reads(path.parents[3])
        value = sources.load_model(path)
        reads.models["private"] = None
        return value, reads


def check_stage_and_original_snapshots_remain_separate(tmp_path):
    path, values = model_input(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    staged, _ = model_input(stage)
    changed = dict(values, **{"desired.row.001-001.value": "`stage`"})
    write_model(staged, changed)
    with (
        input_context(fresh=True, read_only=True),
        change_scope.change_reads(),
        change_scope.index_stage(tmp_path, stage),
    ):
        assert sources.load_model(path).authoritative == values
        assert sources.load_model(staged).authoritative == changed
        assert sources.raw_model(path).authoritative == values


def check_comparison_keeps_saved_bytes_and_still_reports_difference(tmp_path):
    path, _ = model_input(tmp_path)
    view = tmp_path / "docs/designs/dev/team/logs.md"
    view.parent.mkdir(parents=True)
    view.write_text("saved\n", encoding="utf-8")
    with ExitStack() as lifetime:
        snapshot = GenerationInputs(tmp_path, read_only=True)
        lifetime.callback(snapshot.close)
        snapshot.read(path)
        snapshot.read(view)
        view.write_text("expected\n", encoding="utf-8")
        path.write_text("external change\n", encoding="utf-8")
        plan = SimpleNamespace(
            root=tmp_path,
            snapshot=snapshot,
            expected_outputs={view: {view: "expected\n"}},
            failure_records=[],
            saved={},
        )
        sync_runtime._compare_generation(plan)
        assert [d.code for d in plan.failure_records] == ["generation.mismatch"]
        with pytest.raises(ValueError, match="inputs changed before publication"):
            snapshot.verify()


def check_policy_batch_evaluates_documents_once(tmp_path):
    path, _ = model_input(tmp_path)
    view = tmp_path / "docs/designs/dev/team/logs.md"
    view.parent.mkdir(parents=True)
    view.write_text("# fixture\n", encoding="utf-8")
    values = SnapshotValues(
        {
            "desired.row.001-001.property": "Logs.ResourcePolicy.PolicyDocument",
            "desired.row.001-001.value": "[Policy](logs/policy.json)",
            "desired.row.001-001.document": '{"Statement":[]}',
        }
    )
    with (
        patch.object(
            policy_tables._module_design_layout,
            "design_model_values",
            return_value=values,
        ),
        patch.object(
            policy_tables._model_render, "generate_markdown", return_value="# fixture\n"
        ) as generate,
        patch.object(policy_tables, "resources_in") as saved,
        patch.object(
            policy_tables._design_document, "require_saved_identity"
        ) as identity,
    ):
        assert policy_tables.rendered_design(view) == "# fixture\n"
    generate.assert_called_once()
    saved.assert_not_called()
    identity.assert_not_called()


class ComparisonProbe:
    def __init__(self, interrupt):
        self.interrupt, self.tables = interrupt, []

    def __call__(self, *args, **kwargs):
        table = memo_table()
        assert "outer" not in table
        self.tables.append(table)
        table["private"] = True
        if self.interrupt:
            raise KeyboardInterrupt
        return ()


@pytest.mark.parametrize("interrupt", [False, True])
def check_independent_comparison_scope_cleanup(tmp_path, interrupt):
    probe = ComparisonProbe(interrupt)
    with (
        input_context(fresh=True, read_only=True),
        patch.object(sync_runtime, "_comparison", probe),
    ):
        outer = memo_table()
        outer["outer"] = True
        for _ in range(2):
            if interrupt:
                with pytest.raises(KeyboardInterrupt):
                    sync_runtime.compare_generation(tmp_path, None)
            else:
                assert sync_runtime.compare_generation(tmp_path, None) == ()
            assert memo_table() is outer and "private" not in outer
        assert probe.tables[0] is not probe.tables[1]


if __name__ == "__main__":
    raise SystemExit(run(__file__))
