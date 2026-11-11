#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import support.model_templates_fixtures as _exports_support_model_templates_fixtures
from generation_inputs import GenerationInputs
from model.files import service_model_path
from model.importing.scope import read_consumers, restrict
from model.operations import _verify_published_inputs
from model.sources import list_models
from support.model_templates_fixtures import (
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
    redirect_stdout,
    role_model,
    run,
    shutil,
    source_scope,
    split,
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
        policies = re.findall(rb"```json\n(.*?)\n```", outputs[root / "docs/designs" / env / "team/iam.md"], re.DOTALL)
        assert len(policies) == len(entries(models[env], "desired.resource."))
        assert all(
            json.loads(p)["Statement"][0]["Principal"]["Service"]
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
    TestCase().assertEqual(calls.call_count, 8)


def main():
    return run(__file__, message="model_templates: PASS")


if __name__ == "__main__":
    raise SystemExit(main())
