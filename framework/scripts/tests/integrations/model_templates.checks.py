#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import support.model_sources as _imports_support_model_sources
import support.model_templates_fixtures as _exports_support_model_templates_fixtures
from generation_inputs import GenerationInputs
from model.files import service_model_path
from model.importing.scope import read_consumers, restrict
from model.operations import _verify_published_inputs
from model.sources import list_models
from support.model_templates_fixtures import (
    ROOT,
    Path,
    _publish_transaction,
    affected,
    config_model,
    dependencies,
    entries,
    fixture,
    install_candidate,
    io,
    json,
    load_model,
    patch,
    publication_lock,
    pytest,
    redirect_stdout,
    rejected,
    role_model,
    run,
    shutil,
    source_scope,
    split,
    subprocess,
    sync_runtime,
    sys,
    trace_model,
    write_fixture,
    write_model,
)
from support.producer_identifier_reference_fixtures import reference, resource
from support.validator import MODULE
from sync_files import changed_files
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from validation.project import check_validation_scope as validate_scope

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

_CALLBACK_DEFAULT = object()


# Preserve shared fixtures and compatibility exports under their historical names.
root = _exports_support_model_templates_fixtures.root
save_files = _exports_support_model_templates_fixtures.save_files


def _callback_check_transactions_verify(new, original, /):
    assert original.read_text() == "a=new\n" and new.is_file()


def _callback_check_transactions_concurrent(dependency, /):
    dependency.write_text('{"changed":true}\n')


def _callback_check_transactions_file_rollback_fail_restore(restores, /, path, content):
    restores.append(path)
    raise OSError("injected restoration failure")


def _callback_check_transactions_fail(new, write, /, path, *args, **kwargs):
    if path == new:
        raise OSError("injected partial-write failure")
    return write(path, *args, **kwargs)


def _callback_check_transactions_callback_finish_import(called, path, /):
    called.append(path.read_bytes())
    raise ValueError("injected completion callback failure")


def _callback_check_transactions_recovery_interrupted(
    created, write, /, path, *args, **kwargs
):
    result = write(path, *args, **kwargs)
    if path == created:
        raise KeyboardInterrupt()
    return result


def _callback_check_transactions_file_rollback_fail_write(
    _state_file_rollback_196, write_text, /, path, *args, **kwargs
):
    _state_file_rollback_196.calls.append(path)
    if path == _state_file_rollback_196.failed:
        write_text(path, "partially written", encoding="utf-8")
        raise OSError("injected publication failure")
    return write_text(path, *args, **kwargs)


def _callback_check_transactions_callback(root, transaction, /):
    path = root / "view.md"
    path.write_bytes(b"original\r\n")
    called = []
    finish_import = _bind_framework_callback(
        _callback_check_transactions_callback_finish_import, called, path
    )
    with pytest.raises(ValueError, match="completion callback"):
        transaction(root, {path: "changed\n"}, verify=finish_import)
    assert called == [b"changed\r\n"]
    assert path.read_bytes() == b"original\r\n"
    with publication_lock(root) as journal:
        assert not journal.exists()


def _callback_check_transactions_recovery(root, /):
    first, created = root / "view.md", root / "artifact.json"
    first.write_bytes(b"original\r\n")
    originals = {first: first.read_bytes(), created: None}
    write = Path.write_text
    interrupted = _bind_framework_callback(
        _callback_check_transactions_recovery_interrupted, created, write
    )
    with publication_lock(root) as journal:
        with (
            patch.object(Path, "write_text", interrupted),
            pytest.raises(KeyboardInterrupt),
        ):
            _publish_transaction(
                root,
                {first: "changed\n", created: "{}\n"},
                (),
                journal,
                originals=originals,
            )
        assert journal.is_file()
    # Recovery precedes the next generation snapshot and its originals/output differences.
    with publication_lock(root) as journal:
        assert first.read_bytes() == originals[first] and not created.exists()
        assert not journal.exists()
    with publication_lock(root) as journal:
        with (
            patch.object(Path, "write_text", side_effect=OSError("injected I/O")),
            pytest.raises(OSError),
        ):
            _publish_transaction(
                root,
                {first: "changed\n"},
                (),
                journal,
                originals={first: originals[first]},
            )
        assert first.read_bytes() == originals[first] and not journal.exists()


def _callback_check_transactions_file_rollback(root, /):
    _state_file_rollback_196 = _CallbackState()
    save_files = _imports_support_model_sources.write_fixture_files
    first, created, last = [root / name for name in ("first.md", "new.json", "last.md")]
    originals = {first: b"first\r\n", last: b"last\r\n"}
    write_text, write_bytes = Path.write_text, Path.write_bytes
    for _state_file_rollback_196.failed in (first, created, last):
        for path, content in originals.items():
            path.write_bytes(content)
        _state_file_rollback_196.calls = []
        fail_write = _bind_framework_callback(
            _callback_check_transactions_file_rollback_fail_write,
            _state_file_rollback_196,
            write_text,
        )
        with patch.object(Path, "write_text", fail_write):
            with pytest.raises(OSError) as error:
                save_files({first: "changed\n", created: "{}\n", last: "changed\n"})
            assert str(error.value) == "injected publication failure"
        assert _state_file_rollback_196.failed in _state_file_rollback_196.calls
        assert {path: path.read_bytes() for path in originals} == originals
    restores = []
    fail_restore = _bind_framework_callback(
        _callback_check_transactions_file_rollback_fail_restore, restores
    )
    with (
        patch.object(Path, "write_text", fail_write),
        patch.object(Path, "write_bytes", fail_restore),
    ):
        with pytest.raises(OSError) as error:
            save_files({first: "changed\n", created: "{}\n", last: "changed\n"})
        assert "generated-file rollback failed:" in str(error.value)
        assert all(
            f"{path}: injected restoration failure" in str(error.value)
            for path in (last, first)
        )
    assert last in _state_file_rollback_196.calls and restores == [last, first]
    for path, content in originals.items():
        write_bytes(path, content)
    with patch.object(
        Path, "write_text", side_effect=AssertionError("unchanged file rewritten")
    ):
        save_files(
            {path: content.decode("utf-8") for path, content in originals.items()}
        )
    print(
        "File rollback: PASS (first/middle/last partial write, restoration error, no-op)"
    )


def _callback_check_transactions_transaction_finish(changes, root, snapshot, verify, /):
    if verify is not None:
        verify()
    _verify_published_inputs(SimpleNamespace(root=root, snapshot=snapshot), changes)


def _callback_check_transactions_transaction_185(
    _default_obsolete,
    _default_read_paths,
    _default_verify,
    /,
    root,
    output,
    obsolete=_CALLBACK_DEFAULT,
    *,
    read_paths=_CALLBACK_DEFAULT,
    verify=_CALLBACK_DEFAULT,
):
    if obsolete is _CALLBACK_DEFAULT:
        obsolete = _default_obsolete
    if read_paths is _CALLBACK_DEFAULT:
        read_paths = _default_read_paths
    if verify is _CALLBACK_DEFAULT:
        verify = _default_verify
    snapshot = GenerationInputs(root)
    for path in set(output) | set(obsolete) | set(read_paths):
        snapshot.read(path)
    changes = {**changed_files(output), **{path: None for path in obsolete}}
    finish = _bind_framework_callback(
        _callback_check_transactions_transaction_finish, changes, root, snapshot, verify
    )
    try:
        with publication_lock(root) as journal:
            snapshot.verify()
            _publish_transaction(root, output, obsolete, journal, finish=finish)
    finally:
        snapshot.close()


def check_transactions(root):
    task = root / "tasks/example.md"
    task.parent.mkdir()
    task.write_text(
        "## Task contract\n- Task type: `migration`\n- Task status: `running`\n## Validation scope\n- `framework`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `**`\n"
    )
    transaction = _bind_framework_callback(
        _callback_check_transactions_transaction_185, (), (), None
    )
    original = root / "original.properties"
    original.write_text("a=old\n")
    new = root / "new.json"
    output = {original: "a=new\n", new: "{}\n"}
    write = Path.write_text
    fail = _bind_framework_callback(_callback_check_transactions_fail, new, write)
    with patch.object(Path, "write_text", fail):
        rejected(lambda: transaction(root, output), "injected")
    assert original.read_text() == "a=old\n"
    stale = GenerationInputs(root)
    stale.read(original)
    original.write_text("a=other\n")
    rejected(stale.verify, "inputs changed")
    assert original.read_text() == "a=other\n"
    original.write_text("a=old\n")
    # Written inputs are checked against published bytes; untouched inputs retain their snapshot.
    dependency = root / "dependency.json"
    dependency.write_text("{}\n", encoding="utf-8")
    obsolete = root / "obsolete.json"
    obsolete.write_text('{"old":true}\n', encoding="utf-8")
    snapshots = {
        original: original.read_bytes(),
        dependency: dependency.read_bytes(),
        obsolete: obsolete.read_bytes(),
    }
    verify = _bind_framework_callback(
        _callback_check_transactions_verify, new, original
    )
    transaction(root, output, [obsolete], read_paths=snapshots, verify=verify)
    assert original.read_text() == "a=new\n"
    original.write_text("a=old\n")
    new.unlink()
    obsolete.write_bytes(snapshots[obsolete])
    concurrent = _bind_framework_callback(
        _callback_check_transactions_concurrent, dependency
    )
    rejected(
        lambda: transaction(
            root, output, [obsolete], read_paths=snapshots, verify=concurrent
        ),
        "inputs changed during publication",
    )
    assert (
        original.read_text() == "a=old\n"
        and obsolete.read_bytes() == snapshots[obsolete]
    )
    dependency.write_bytes(snapshots[dependency])
    # A terminated process leaves a durable journal; the next reader restores prior inputs.
    program = """import sys,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from model.sources import publication_lock, _publish_transaction
import sync_files
root=Path(sys.argv[2]); original=root/'original.properties'
def crash(output):
    original.write_text('a=crash\\n');os._exit(17)
sync_files.save_files=crash
with publication_lock(root) as journal:
    _publish_transaction(root,{original:'a=crash\\n',root/'new.json':'{}\\n'},(),journal)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(ROOT / "framework/scripts"), str(root)]
    )
    assert result.returncode == 17 and original.read_text() == "a=crash\n"
    with publication_lock(root):
        pass
    assert original.read_text() == "a=old\n"

    callback = _bind_framework_callback(
        _callback_check_transactions_callback, root, transaction
    )

    callback()

    recovery = _bind_framework_callback(_callback_check_transactions_recovery, root)

    recovery()

    file_rollback = _bind_framework_callback(
        _callback_check_transactions_file_rollback, root
    )

    file_rollback()


def check_expansion(root):
    fixture(root)
    models = {"dev": role_model("dev", 2), "prod": role_model("prod", 5)}
    install_candidate(root, models)
    original = {}
    for env, expected in models.items():
        path = root / "model" / env / "team/iam.properties"
        assert load_model(path).authoritative == expected
        original[env] = path.read_bytes()
    # Each explicit environment is edited deliberately; no shared source expands to the other.
    for env in models:
        path = root / "model" / env / "team/iam.properties"
        edited = {
            key: value.replace("lambda.amazonaws.com", "ec2.amazonaws.com")
            if key.endswith(".document")
            else value
            for key, value in models[env].items()
        }
        write_model(path, edited)
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, env, "team", services=["iam"]) == 0
        outputs = {
            p: p.read_bytes()
            for p in (root / "docs/designs" / env / "team").rglob("*")
            if p.is_file()
        }
        policies = [p for p in outputs if p.suffix == ".json"]
        assert len(policies) == len(entries(models[env], "desired.resource."))
        assert all(
            json.loads(outputs[p])["Statement"][0]["Principal"]["Service"]
            == "ec2.amazonaws.com"
            for p in policies
        )
        with redirect_stdout(io.StringIO()) as diagnostics:
            assert sync_runtime.sync(root, True, env, "team", services=["iam"]) == 0
        assert (
            all(p.read_bytes() == data for p, data in outputs.items())
            and "FAIL" not in diagnostics.getvalue()
        )
        path.write_bytes(original[env])
    path = root / "model/dev/team/iam.properties"
    current = dict(models["dev"])
    current["desired.row.011-004.value"] = "`changed`"
    write_model(path, current)
    assert load_model(path).authoritative["desired.row.011-004.value"] == "`changed`"
    assert (
        load_model(root / "model/prod/team/iam.properties").authoritative
        == models["prod"]
    )
    assert affected(root, {path.relative_to(root)}) == {("dev", "team", "iam")}
    trace = trace_model(path, "desired.row.011-004.value")
    assert trace["file"] == str(path) and trace["value"] == "`changed`"


def check_layout(root):
    fixture(root, ("dev", "stg"))
    install_candidate(root, {env: role_model(env, 2) for env in ("dev", "stg")})
    logical = root / "model/dev/team/iam.properties"
    scope = source_scope(root, logical)
    assert (scope.environment, scope.target, scope.service) == ("dev", "team", "iam")
    for relative in (
        "model/templates/team/iam.properties",
        "model/parameters/team/iam.properties",
        "model/parameters/dev/team/iam/parameters.yaml",
        "model/dev/team/iam.json",
        "model/dev/team/iam.properties/part-001.properties",
    ):
        rejected(
            lambda *, relative=relative: load_model(source_scope(root, root / relative))
        )
    values = dict(load_model(logical).authoritative)
    output = split(logical, values, limit=20)
    assert len(output) > 1
    for path, text in output.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    part = next(path for path in output if path != logical)
    assert service_model_path(part, root / "model") == logical
    assert affected(root, {part.relative_to(root)}) == {("dev", "team", "iam")}
    assert load_model(logical).authoritative == values
    assert load_model(
        root / "model/stg/team/iam.properties"
    ).authoritative == role_model("stg", 2)
    for env in ("dev", "stg"):
        view = root / "docs/designs" / env / "team/iam.md"
        view.parent.mkdir(parents=True, exist_ok=True)
        view.write_text("fixture\n", encoding="utf-8")
    before = root / "empty-baseline"
    before.mkdir()
    dependency_index.rebuild(root)
    for changed, rejected_scope in (
        ({part.relative_to(root).as_posix()}, False),
        ({"model/stg/team/iam.properties"}, True),
        ({"model/dev/team/iam.properties"}, False),
    ):
        validator = MODULE.Validator(root, {("dev", "team", "iam")})
        validator.accounts = {("dev", "team"): {}, ("stg", "team"): {}}
        validator.changed_paths = changed
        validate_scope(
            validator.accounts,
            changed,
            None,
            validator.findings,
            root,
            validator.scope,
            None,
            before=before,
        )
        assert bool(validator.errors) == rejected_scope, validator.errors
    assert affected(root, {"docs/unrelated.md"}) == set()


def check_reference_impact(root):
    fixture(root)
    paths = {}
    for service, kind, producer, producer_kind in [
        ("codebuild", "CodeBuild.Project", None, None),
        ("codepipeline", "CodePipeline.Pipeline", "codebuild", "CodeBuild.Project"),
        ("lambda", "Lambda.Function", "codepipeline", "CodePipeline.Pipeline"),
    ]:
        path = root / "model/dev/team" / (service + ".properties")
        prop = "FunctionName" if service == "lambda" else "Name"
        values = resource(
            "005", kind, service + "-fixture", [(prop, "`app-dev-build`")]
        )
        if producer:
            values.update(
                reference(
                    "producer",
                    "desired.row.005-001.value",
                    "app-dev-build",
                    producer,
                    "005",
                    producer_kind,
                    prop=producer_kind + ".Name",
                    environment="dev",
                )
            )
        write_model(path, values)
        paths[service] = path
    own = {("dev", "team", "codebuild")}
    chain = own | {("dev", "team", service) for service in ("codepipeline", "lambda")}
    source = paths["codebuild"]
    relative = source.relative_to(root)
    assert affected(root, {relative}) == chain
    previous = root / "previous"
    shutil.copytree(root / "model", previous / "model")
    shutil.copyfile(root / "project.json", previous / "project.json")
    original = source.read_bytes()
    for raw in (
        original + b"# annotation\n",
        original.replace(b"app-dev-build", b"renamed"),
    ):
        source.write_bytes(raw)
        assert affected(root, {relative}) == chain
        assert (
            load_model(paths["codepipeline"]).authoritative["desired.row.005-001.value"]
            == "`app-dev-build`"
        )
    source.write_bytes(original)
    graph = dependencies(root)
    graph[("dev", "team", "codepipeline")].add(("dev", "team", "unrelated"))
    assert ("dev", "team", "unrelated") not in dependencies(root)[
        ("dev", "team", "codepipeline")
    ]
    with restrict(("dev", "team", "codebuild")):
        with read_consumers(own):
            assert set(dependencies(root)) == own
        with read_consumers(chain):
            assert set(dependencies(root)) == chain
    values = dict(load_model(paths["codepipeline"]).authoritative)
    values = {
        key: value
        for key, value in values.items()
        if not key.startswith("desired.reference.")
    }
    write_model(paths["codepipeline"], values)
    assert not dependencies(root)[("dev", "team", "codepipeline")]
    assert affected(root, {relative}, before=previous) == own
    raw = paths["codepipeline"].read_bytes()
    paths["codepipeline"].write_text("invalid")
    rejected(lambda: dependencies(root), "unsupported Model format")
    paths["codepipeline"].write_bytes(raw)
    paths["lambda"].unlink()
    assert ("dev", "team", "lambda") not in dependencies(root)


def check_creation(root):
    fixture(root)
    path = root / "model/dev/team/config.properties"
    assert list_models(root) == [] and not path.exists()
    write_model(path, config_model())
    expected = load_model(path).authoritative
    assert not [scope for scope in list_models(root) if scope.environment == "prod"]
    original = path.read_bytes()
    for _ in range(2):
        assert (
            load_model(path).authoritative == expected and path.read_bytes() == original
        )


def _callback_check_sync_drift(path, real, saved, /, *args, **kwargs):
    real(*args, **kwargs)
    path.write_bytes(saved + b"# changed\n")


def check_sync(root):
    with patch.object(sync_runtime, "sync", wraps=sync_runtime.sync) as calls:
        fixture(root, ("dev",))
        path = write_fixture(root, "dev", "config", config_model())
        view = root / "docs/designs/dev/team/config.md"
        before = {
            p: p.read_bytes()
            for p in root.rglob("*")
            if p.is_file() and p.suffix != ".pyc"
        }
        with redirect_stdout(io.StringIO()):
            assert (
                sync_runtime.sync(root, True, "dev", "team", services=["config"]) == 0
            )
            assert (
                sync_runtime.sync(root, False, "dev", "team", services=["config"]) == 0
            )
        assert all(p.read_bytes() == value for p, value in before.items())
        # Observation publication rights/IMPORT protection are exercised by the managed observation IT.
        values = dict(load_model(path).authoritative)
        values["observed.row.007-009.value"] = "`new-id`"
        write_model(path, values)
        with redirect_stdout(io.StringIO()):
            assert (
                sync_runtime.sync(root, True, "dev", "team", services=["config"]) == 0
            )
        assert (
            load_model(path).authoritative["observed.row.007-009.value"] == "`new-id`"
        )
        for newline, final in (
            ("\n", True),
            ("\n", False),
            ("\r\n", True),
            ("\r\n", False),
        ):
            original = view.read_text()
            content = original.rstrip("\n").replace("\n", newline) + (
                newline if final else ""
            )
            view.write_bytes(content.encode())
            with redirect_stdout(io.StringIO()):
                assert (
                    sync_runtime.sync(root, True, "dev", "team", services=["config"])
                    == 0
                )
            assert view.read_bytes() == content.encode()
        saved = path.read_bytes()
        real = sync_runtime.validate_candidates
        drift = _bind_framework_callback(_callback_check_sync_drift, path, real, saved)
        with (
            patch.object(sync_runtime, "validate_candidates", drift),
            redirect_stdout(io.StringIO()),
        ):
            rejected(
                lambda: sync_runtime.sync(
                    root, True, "dev", "team", services=["config"]
                ),
                "inputs changed",
            )
        assert path.read_bytes() == saved + b"# changed\n"
        path.write_bytes(saved)
    assert calls.call_count == 9


def main():
    return run(__file__, message="model_templates: PASS")


if __name__ == "__main__":
    raise SystemExit(main())
