#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import threading
from types import SimpleNamespace as _CallbackState

import model.sources as model_sources
import pytest
import sync_runtime
import sync_views
import task_contract_core as tasks
import utils.aws_mappings as mapping_state
import utils.input_cache as input_cache
from model.files import read_model
from model.format import FORMAT, INDEX
from model.importing import scope as import_scope
from model.sources import load_model
from support.model_v2_fixtures import format_fixture
from support.producer_identifier_reference_fixtures import resource, setup
from support.pytest_cli import run
from support.validation_cache_fixtures import (
    PassCache,
    Path,
    design_material_files,
    entries,
    input_scope,
    os,
    sys,
    tempfile,
    write_model,
)
from support.validator import MODULE as validator_module
from utils.aws_mappings import mapping_alias, mappings_for
from utils.function_wrapper import BoundCallback
from utils.input_cache import input_context, memoized

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_cache_inputs_read_inputs(root, /, values):
    assert design_material_files(root) is design_material_files(root)
    extracted = entries(values, "desired.row.")
    extracted[0][1]["value"] = "caller mutation"
    return entries(values, "desired.row.")


def check_cache_inputs(tmp_path):
    root = tmp_path
    with tempfile.TemporaryDirectory() as directory:
        cache = PassCache(root, directory=directory)
        key = cache.key("catalog")
        assert cache.load(key) is None
        cache.save(key, 17)
        assert cache.load(key) == 17
        assert PassCache(root, fresh=True, directory=directory).load(key) is None
        bytecode = root / "__pycache__/fixture.cpython.pyc"
        bytecode.parent.mkdir(parents=True, exist_ok=True)
        bytecode.write_bytes(b"generated cache")
        assert PassCache(root, directory=directory).key("catalog") == key
        bytecode.write_bytes(b"regenerated cache")
        assert PassCache(root, directory=directory).key("catalog") == key
        cache.save(key, 0)
        assert cache.load(key) == 17
        for relative in (
            "README.md",
            "AGENTS.md",
            "project.json",
            ".agents/project/SKILL.md",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            before = PassCache(root, directory=directory).key("catalog")
            path.write_text("entry\n", encoding="utf-8")
            added = PassCache(root, directory=directory).key("catalog")
            assert added != before
            path.write_text("change\n", encoding="utf-8")
            assert PassCache(root, directory=directory).key("catalog") != added
            path.unlink()
            assert PassCache(root, directory=directory).key("catalog") == before
        read_inputs = (input_scope)(
            _bind_framework_callback(_callback_check_cache_inputs_read_inputs, root)
        )
        values = {"desired.row.001-001.value": "first"}
        assert read_inputs(values)[0][1]["value"] == "first"
        values["desired.row.001-001.value"] = "second"
        assert read_inputs(values)[0][1]["value"] == "second", (
            "later invocations must see edits"
        )


def check_cache_location(tmp_path):
    root = tmp_path
    try:
        PassCache(root, directory=root / "cache")
    except ValueError:
        pass
    else:
        raise AssertionError("cache directory inside repository accepted")


def _project_rglob(path, pattern):
    assert path.name == ".agents", f"unexpected Framework scan: {path}"
    return iter(())


def check_cache_lifetime(tmp_path):
    root, definitions, directory = (
        tmp_path / "repo",
        tmp_path / "definitions",
        tmp_path / "cache",
    )
    root.mkdir()
    source = root / "source.txt"
    source.write_bytes(b"fixed input")
    directory.mkdir()
    cache = PassCache(root, directory=directory, definitions_root=definitions)
    with patch.object(Path, "rglob", _project_rglob), input_context():
        key = cache.key("catalog")
        cache.save(key, 17)
        assert (
            PassCache(root, directory=directory, definitions_root=definitions).load(key)
            == 17
        )
        assert (
            PassCache(
                root, fresh=True, directory=directory, definitions_root=definitions
            ).load(key)
            is None
        )
    with patch.object(Path, "rglob", _project_rglob), input_context():
        assert cache.load(cache.key("catalog")) is None
        assert (
            PassCache(root, directory=directory, definitions_root=definitions).load(key)
            is None
        )
    with pytest.raises(ValueError, match="symlink inputs"):
        (root / "README.md").symlink_to(source)
        PassCache(root, directory=directory).common_key()


def _check_retained_common_key_contract(name, service):
    return f"## Task contract\n- Task type: `migration`\n- Task status: `running`\n- Workflow: `import`\n- IMPORT target: `dev/cde/{service}`\n## Modified files\n- `tasks/{name}.md`\n## Allowed paths\n- `tasks/{name}.md`\n## Validation scope\n- `dev/cde/{service}`\n"


def _callback_check_retained_common_key_read(project, read_cached, /, path):
    import_scope.require_readable(project, path)
    return read_cached(path, import_scope.read_context(project))


def _callback_check_retained_common_key_read_cached(path, context):
    return object()


def check_retained_common_key(tmp_path):
    # Contract reuse belongs only to a read-only invocation, never to authority saves.

    project = tmp_path / "contracts"
    (project / "tasks").mkdir(parents=True)
    contract = _check_retained_common_key_contract
    first = project / "tasks/first.md"
    second = project / "tasks/second.md"
    original = contract("first", "sqs")
    first.write_text(original)
    second.write_text(contract("second", "s3"))
    read_cached = (memoized)(_callback_check_retained_common_key_read_cached)
    read = _bind_framework_callback(
        _callback_check_retained_common_key_read, project, read_cached
    )
    with tasks.selected_task(project, "tasks/first.md"), input_context():
        with (
            patch.object(tasks, "_catalog", wraps=tasks._catalog) as scans,
            patch.object(tasks, "_read_task", wraps=tasks._read_task) as selections,
        ):
            with tasks.contract_reads(project):
                for _ in range(1000):
                    assert import_scope.selected(project) == ("dev", "cde", "sqs")
                assert scans.call_count == 1
                assert selections.call_count == 2
                with tasks.selected_task(project, "tasks/second.md"):
                    assert import_scope.selected(project) == ("dev", "cde", "s3")
                assert import_scope.selected(project) == ("dev", "cde", "sqs")
                with import_scope.read_consumers({("dev", "cde", "sqs")}):
                    path = project / "model/dev/cde/sqs.properties"
                    before = import_scope.read_context(project)
                    cached = read(path)
                    with import_scope.reference_reader(path):
                        assert import_scope.read_context(project)[2] == path.absolute()
                        assert read(path) is not cached
                    assert import_scope.read_context(project) == before
                    assert read(path) is cached
                with import_scope.read_consumers(
                    {("dev", "cde", "sqs"), ("dev", "cde", "iam")}
                ):
                    assert read(path) is not cached
                with tasks.selected_task(project, "tasks/second.md"):
                    try:
                        read(path)
                    except ValueError as error:
                        assert "outside selected" in str(error)
                    else:
                        raise AssertionError(
                            "cached result bypassed Task read permission"
                        )
                    with import_scope.reference_reader(path):
                        assert read(path) is not cached
                assert read(path) is cached
            assert scans.call_count == 2
        for change in ("content", "line-endings", "addition", "deletion", "selector"):
            try:
                with tasks.contract_reads(project):
                    assert import_scope.selected(project) == ("dev", "cde", "sqs")
                    if change == "content":
                        first.write_text(contract("first", "iam"))
                    elif change == "line-endings":
                        first.write_bytes(
                            original.replace("\n", "\r\n").encode("utf-8")
                        )
                    elif change == "addition":
                        (project / "tasks/third.md").write_text(
                            contract("third", "iam")
                        )
                    elif change == "deletion":
                        second.unlink()
                    else:
                        with patch.dict(
                            os.environ, {tasks.SELECTOR: "tasks/second.md"}
                        ):
                            tasks.verify_contract_reads(project)
            except ValueError as error:
                assert "changed during validation" in str(error)
            else:
                raise AssertionError(f"contract {change} was not detected")
            finally:
                first.write_text(original)
                second.write_text(contract("second", "s3"))
                (project / "tasks/third.md").unlink(missing_ok=True)
        first.write_text(contract("first", "iam"))
        with tasks.contract_reads(project):
            assert import_scope.selected(project) == ("dev", "cde", "iam")
        first.write_text(original)
        assert tasks.contracts(project)["tasks/first.md"] == original


@pytest.mark.parametrize(
    "relative",
    [
        "model/dev/team/iam.properties",
        "docs/designs/dev/team/iam.md",
        "docs/designs/dev/team/iam/policy.json",
        "docs/designs/dev/team/iam/extra.json",
        "model/dev/team/iam/extra.properties",
    ],
)
def check_service_cache_invalidation(tmp_path, relative):
    root, directory = tmp_path / "repo", tmp_path / "cache"
    design = root / "docs/designs/dev/team/iam.md"
    source = root / "model/dev/team/iam.properties"
    artifact = design.with_suffix("") / "policy.json"
    source.parent.mkdir(parents=True)
    artifact.parent.mkdir(parents=True)
    (root / "project.json").write_text(
        '{"targets":[{"environment":"dev","alias":"team",'
        '"awsAccountId":"123456789012","awsRegion":"ap-northeast-1","iacEngine":"cloudformation"}]}\n'
    )
    source.write_text(
        "# model-format: 2\ndesired.service.iam.serviceId=iam\n"
        "desired.service.iam.ownedCatalogResourceTypes=IAM.Role\ndesired.note.001.text=original\n"
    )
    design.write_text("# Policy\n[policy](iam/policy.json)\n")
    artifact.write_text("{}\n")
    cache = PassCache(root, directory=directory)
    entry = ("dev", "team", "iam")
    target = root / relative
    original = target.read_bytes() if target.exists() else None
    with input_context():
        key = cache.service_key(entry)
        cache.save(key, 17)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((original or b"") + b"\n")
        if relative.endswith("extra.properties"):
            with pytest.raises(ValueError, match="unregistered Model parts"):
                cache.service_key(entry)
            return
        changed = cache.service_key(entry)
        assert changed != key and cache.load(changed) is None
    if original is not None:
        target.unlink()
        with input_context(), pytest.raises(ValueError):
            cache.service_key(entry)


def check_link_and_part_inputs():
    with (
        tempfile.TemporaryDirectory() as temporary,
        tempfile.TemporaryDirectory() as directory,
    ):
        root = Path(temporary).resolve()
        setup(root, ("sqs", "kms"), ("SQS.Queue", "KMS.Key"), environments=("dev",))
        docs = root / "docs/designs/dev/team"
        docs.mkdir(parents=True)
        design, model = docs / "sqs.md", root / "model/dev/team/sqs.properties"
        design.write_text("[Reference](kms.md#key)\n", encoding="utf-8")
        (docs / "kms.md").write_text('<a id="key"></a>\n', encoding="utf-8")
        write_model(
            model, resource("001", "SQS.Queue", "sqs", [("QueueName", "`first`")])
        )
        entry = ("dev", "team", "sqs")
        before = PassCache(root, directory=directory).service_key(entry)
        (docs / "kms.md").write_text('<a id="changed"></a>\n', encoding="utf-8")
        assert PassCache(root, directory=directory).service_key(entry) != before
        body = model.read_text()
        part = model.with_suffix("") / "part-003.properties"
        part.parent.mkdir()
        part.write_text(body)
        model.write_text(FORMAT + "\n" + INDEX + "\n# part: sqs/part-003.properties\n")
        before = PassCache(root, directory=directory).service_key(entry)
        part.write_text(body.replace("`first`", "`changed`"))
        assert PassCache(root, directory=directory).service_key(entry) != before
    print("validation-cache: PASS (references, stable part names and raw bytes)")


def _callback_check_read_scope_lifetime_expand(original, scopes, /, *args):
    scopes.append(input_cache.memo_table())
    return original(*args)


def _callback_check_read_scope_lifetime_nested(model, scopes, /):
    scope = input_cache.memo_table()
    read_model(model)
    assert scopes[-1] is scope
    read_model(model)
    assert input_cache.memo_table() is scope


def check_read_scope_lifetime(tmp_path):
    scope, values = format_fixture(tmp_path)
    model = scope.path
    original = model_sources._read_model
    scopes = []
    expand = BoundCallback(_callback_check_read_scope_lifetime_expand, original, scopes)
    with patch.object(model_sources, "_read_model", side_effect=expand):
        first = read_model(model)
        assert scopes[-1] is not None
        assert input_cache.memo_table() is None
        values["desired.row.007-002.value"] = "`changed-name`"
        write_model(model, values)
        assert read_model(model) != first
        nested = (input_cache.input_scope)(
            BoundCallback(_callback_check_read_scope_lifetime_nested, model, scopes)
        )
        nested()
    assert input_cache.memo_table() is None
    with patch.object(model_sources, "_read_model", side_effect=ValueError("injected")):
        with pytest.raises(ValueError, match="injected"):
            read_model(model)
    assert input_cache.memo_table() is None


def _callback_check_single_and_parallel_threads_validate(
    barrier, provider, stage, threads, /, *args, **kwargs
):
    assert mappings_for(stage) is provider
    assert mappings_for(stage).get("iam") is provider.get("iam")
    threads.append((threading.get_ident(), input_cache.memo_table()))
    if barrier:
        barrier.wait(timeout=10)


def _callback_check_single_and_parallel_threads_run_candidates(
    _state_check_single_and_parallel_threads_259, main, paths, root, stage, /
):
    scope = input_cache.memo_table()
    scope["candidate-local"] = object()
    failures = []
    with patch.object(
        sync_views,
        "validate_views",
        side_effect=_state_check_single_and_parallel_threads_259.validate,
    ):
        sync_runtime.validate_candidates(
            stage,
            root,
            {
                p: []
                for p in paths[: _state_check_single_and_parallel_threads_259.count]
            },
            {
                p: {}
                for p in paths[: _state_check_single_and_parallel_threads_259.count]
            },
            failures,
            4,
            False,
        )
    assert not failures
    assert all(
        inputs is not scope and "candidate-local" not in inputs
        for _, inputs in _state_check_single_and_parallel_threads_259.threads
    )
    if _state_check_single_and_parallel_threads_259.count == 1:
        assert [
            thread for thread, _ in _state_check_single_and_parallel_threads_259.threads
        ] == [main]
    else:
        assert (
            len(
                {
                    thread
                    for thread, _ in _state_check_single_and_parallel_threads_259.threads
                }
            )
            == 2
        )
        assert all(
            thread != main
            for thread, _ in _state_check_single_and_parallel_threads_259.threads
        )


def check_single_and_parallel_threads(tmp_path):
    _state_check_single_and_parallel_threads_259 = _CallbackState()
    root, stage = tmp_path / "root", tmp_path / "stage"
    provider = mappings_for(root)
    paths = [root / "docs/designs/dev/team" / (s + ".md") for s in ("iam", "s3")]
    main = threading.get_ident()
    for _state_check_single_and_parallel_threads_259.count in (1, 2):
        _state_check_single_and_parallel_threads_259.threads = []
        barrier = (
            threading.Barrier(2)
            if _state_check_single_and_parallel_threads_259.count == 2
            else None
        )
        _state_check_single_and_parallel_threads_259.validate = BoundCallback(
            _callback_check_single_and_parallel_threads_validate,
            barrier,
            provider,
            stage,
            _state_check_single_and_parallel_threads_259.threads,
        )
        run_candidates = (input_cache.input_scope)(
            BoundCallback(
                _callback_check_single_and_parallel_threads_run_candidates,
                _state_check_single_and_parallel_threads_259,
                main,
                paths,
                root,
                stage,
            )
        )
        with mapping_alias(root, stage):
            run_candidates()
        assert (
            stage not in mapping_state._aliases
            and stage not in mapping_state._instances
        )


def _callback_check_scoped_validation_threads_and_failures_designs(
    barrier, seen, /, validator
):
    seen.append((threading.get_ident(), input_cache.memo_table()))
    if barrier:
        barrier.wait(timeout=10)
    validator.check(False, "synthetic service failure")


def _callback_check_scoped_validation_threads_and_failures_validate(
    _state_check_scoped_validation_threads_and_failures_322, main, tmp_path, /
):
    scope = input_cache.memo_table()
    validator = validator_module.Validator(
        tmp_path, _state_check_scoped_validation_threads_and_failures_322.entries
    )
    validator.schema_catalog = object()
    with (
        patch.object(validator_module.Validator, "design_files", return_value=[]),
        patch.object(validator_module.Validator, "check_design_service_ownership"),
        patch.object(validator_module.Validator, "check_stack_designs"),
        patch.object(validator_module.Validator, "check_generated_service_models"),
        patch.object(
            validator_module.Validator,
            "check_designs",
            _state_check_scoped_validation_threads_and_failures_322.designs,
        ),
        patch.object(validator_module.Validator, "check_observed_values"),
    ):
        validator.check_scoped_designs()
    assert (
        validator.errors
        == ["synthetic service failure"]
        * _state_check_scoped_validation_threads_and_failures_322.count
    )
    if _state_check_scoped_validation_threads_and_failures_322.count == 1:
        assert _state_check_scoped_validation_threads_and_failures_322.seen == [
            (main, scope)
        ]
    else:
        assert (
            len(
                {
                    thread
                    for thread, _ in _state_check_scoped_validation_threads_and_failures_322.seen
                }
            )
            == 2
        )
        assert all(
            thread != main and memo is not scope
            for thread, memo in _state_check_scoped_validation_threads_and_failures_322.seen
        )


def check_scoped_validation_threads_and_failures(tmp_path):
    _state_check_scoped_validation_threads_and_failures_322 = _CallbackState()
    main = threading.get_ident()
    for _state_check_scoped_validation_threads_and_failures_322.count in (1, 2):
        _state_check_scoped_validation_threads_and_failures_322.entries = {
            ("dev", "team", s)
            for s in ("iam", "s3")[
                : _state_check_scoped_validation_threads_and_failures_322.count
            ]
        }
        _state_check_scoped_validation_threads_and_failures_322.seen = []
        barrier = (
            threading.Barrier(2)
            if _state_check_scoped_validation_threads_and_failures_322.count == 2
            else None
        )
        _state_check_scoped_validation_threads_and_failures_322.designs = BoundCallback(
            _callback_check_scoped_validation_threads_and_failures_designs,
            barrier,
            _state_check_scoped_validation_threads_and_failures_322.seen,
        )
        validate = (input_cache.input_scope)(
            BoundCallback(
                _callback_check_scoped_validation_threads_and_failures_validate,
                _state_check_scoped_validation_threads_and_failures_322,
                main,
                tmp_path,
            )
        )
        validate()


def _callback_check_preparation_cache_snapshot(original, path, /):
    with patch.object(
        model_sources, "_read_model", wraps=model_sources._read_model
    ) as parsed:
        first = load_model(path)
        assert first.authoritative["desired.row.001-001.value"] == "`first`"
        path.write_bytes(original.replace(b"`second`", b"`changed`"))
        second = load_model(path)
        assert second.authoritative["desired.row.002-001.value"] == "`second`"
        assert parsed.call_count == 1 and second.dependencies[path] == original


def check_preparation_cache(tmp_path):
    root = tmp_path
    setup(root, ["iam"], ["IAM.Role"])

    path = root / "model/preview/team/iam.properties"
    values = {}
    for identity, rid in [("first", "001"), ("second", "002")]:
        values.update(
            resource(
                rid, "IAM.Role", "iam-" + rid, [("RoleName", "`" + identity + "`")]
            )
        )
    write_model(path, values)
    original = path.read_bytes()
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    snapshot = (input_scope)(
        BoundCallback(_callback_check_preparation_cache_snapshot, original, path)
    )
    try:
        with input_context(read_only=True):
            snapshot()
        assert (
            load_model(path).authoritative["desired.row.002-001.value"] == "`changed`"
        )
        path.unlink()
        with pytest.raises((ValueError, OSError), match="iam.properties"):
            load_model(path)
    finally:
        path.write_bytes(original)
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _callback_check_template_snapshot_reuse(original, path, root, /):
    with patch.object(
        model_sources, "_read_model", wraps=model_sources._read_model
    ) as parsed:
        first, second = load_model(path), load_model(path)
        assert first is second and parsed.call_count == 1
        with pytest.raises(TypeError):
            first.files[root / "foreign"] = "unrelated"
        with pytest.raises(TypeError):
            first.authoritative["desired.row.007-001.value"] = "changed"
    path.write_text("invalid")
    assert load_model(path) is first
    path.write_bytes(original)
    assert load_model(path) is first


def check_template_snapshot(tmp_path):
    root = tmp_path
    scope, _ = format_fixture(root)
    path = scope.path
    original = path.read_bytes()
    reuse = (input_scope)(
        BoundCallback(_callback_check_template_snapshot_reuse, original, path, root)
    )
    with input_context(read_only=True):
        reuse()
    path.write_text("invalid")
    with pytest.raises(ValueError, match="unsupported Model format"):
        load_model(path)
    path.write_bytes(original)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
