#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import io
import json
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from functools import partial as _bind_framework_callback

import model.files as model_files
import pytest
from model.cli import main as cli_main
from model.files import load_model, resource_keys
from model.format import FORMAT, INDEX, owner, serialize, split
from model.importing.scope import reference_reader, restrict
from model.projection import bound_resource_anchors
from model.sources import list_models, source_scope
from support.model_files_fixtures import (
    Path,
    model_parts,
    properties,
    resource_reading_fixture,
    sync_files,
    sys,
    write_model,
)
from support.model_v2_fixtures import format_fixture
from support.pytest_cli import run
from utils.input_cache import input_context, memo_table

from model import sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_cfn_selector():
    text = 'desired.resource.007.resourceType=EC2.VPC\ndesired.resource.007.logicalId=EC2_VPC_001\ndesired.service.identity.lastAllocated={"EC2.VPC":1}\ndesired.resource.007.cfn-logicalId=cfn-stack-app-dev-network-Vpc\n'
    assert resource_keys(text, "007") == resource_keys(text, "EC2_VPC_001")
    for selector in ("ec2-network", "cfn-stack-app-dev-network-Vpc"):
        with pytest.raises(ValueError):
            resource_keys(text, selector)


def check_cli_entrypoints():
    scripts = Path(__file__).resolve().parents[2]
    direct = subprocess.run(
        [sys.executable, "-B", str(scripts / "model/cli.py"), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    imported = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import sys; sys.argv[0] = 'cli.py'; from model.cli import main; main(['--help'])",
        ],
        cwd=scripts,
        capture_output=True,
        text=True,
        check=True,
    )
    assert direct.stdout == imported.stdout
    module = subprocess.run(
        [sys.executable, "-B", "-m", "model.cli", "--help"],
        cwd=scripts,
        capture_output=True,
        text=True,
        check=True,
    )
    assert module.stdout == ""  # Preserve the existing module execution contract.


def check_journal_precedes_publication(tmp_path: Path) -> None:
    destination = tmp_path / "model.properties"
    destination.write_bytes(b"old\r\n")
    record = {
        "root": str(tmp_path.resolve()),
        "originals": {"model.properties": "b2xkDQo="},
    }
    calls = Mock()
    with sources.publication_lock(tmp_path) as journal:
        with (
            patch.object(
                sources, "atomic_replace_file", wraps=sources.atomic_replace_file
            ) as save,
            patch.object(
                sources.sync_files, "save_files", wraps=sources.sync_files.save_files
            ) as publish,
        ):
            calls.attach_mock(save, "journal")
            calls.attach_mock(publish, "model")
            sources._publish_transaction(tmp_path, {destination: "new\n"}, (), journal)
        save.assert_called_once_with(
            journal, sources.json_text(record), fsync=True, mode=0o666
        )
        assert [call[0] for call in calls.mock_calls] == ["journal", "model"]
        assert not journal.exists()
    with sources.publication_lock(tmp_path) as journal:
        with (
            patch.object(
                sources, "atomic_replace_file", side_effect=OSError("journal save")
            ),
            patch.object(sources.sync_files, "save_files") as publish,
            pytest.raises(OSError, match="journal save"),
        ):
            sources._publish_transaction(
                tmp_path, {destination: "unpublished"}, (), journal
            )
        publish.assert_not_called()
        assert not journal.exists()


def check_loader_rejects_corrupt_and_unreadable_sources(tmp_path):
    scope, _ = format_fixture(tmp_path)
    path = scope.path
    for text, phrase in [
        ("# model-format: 99\n", "unsupported Model format"),
        ("# model-format: 2\ndesired.extra=unknown\n", "invalid Model key"),
        (
            "# model-format: 2\ndesired.note.a.text=one\ndesired.note.a.text=two\n",
            "duplicate",
        ),
    ]:
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=phrase):
            sources.load_model(path)
    with patch.object(Path, "read_bytes", side_effect=PermissionError("denied")):
        with pytest.raises(PermissionError, match="denied"):
            sources.load_model(path)


@pytest.mark.parametrize(
    "anchor", ['bad"anchor', "bad<anchor", "bad/anchor", "", "s3-../unsafe"]
)
def check_saved_anchor_inputs(tmp_path, anchor):
    scope, values = format_fixture(tmp_path)
    values["desired.resource.007.anchor"] = anchor
    scope.path.write_text(serialize(values), encoding="utf-8")
    with pytest.raises(ValueError, match="anchor"):
        bound_resource_anchors(scope.path)


def _callback_check_resource_reading_invoke(path, command, selector):
    stdout, stderr = io.StringIO(), io.StringIO()
    with (
        patch.object(sources, "_read_model", wraps=sources._read_model) as body,
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        code = cli_main([command, str(path), selector])
    return (code, stdout.getvalue(), stderr.getvalue()), body.call_count


def _callback_resource_inputs_cli(source, /, command, selector, *extra):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = cli_main([command, str(source), selector, *extra])
        except SystemExit as error:
            code = error.code
    return subprocess.CompletedProcess([], code, stdout.getvalue(), stderr.getvalue())


def check_resource_reading_inputs(tmp_path):
    root = tmp_path
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": "dev",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        )
    )
    source, values = resource_reading_fixture(root)
    cli = _bind_framework_callback(_callback_resource_inputs_cli, source)

    invoke = _callback_check_resource_reading_invoke

    write_model(source, values)
    authority = dict(load_model(source).authoritative)
    prefixes = ("desired.service.", "display.service.", "desired.note.") + tuple(
        prefix
        for identity in ("001", "002", "003")
        for prefix in (
            f"desired.resource.{identity}.",
            f"display.resource.{identity}.",
            f"desired.row.{identity}-",
            f"observed.row.{identity}-",
        )
    )
    expected = {
        key: value for key, value in authority.items() if key.startswith(prefixes)
    }
    # Exercise both a single source and Resource-aligned parts with identical values.
    for limit in (600, 100):
        old = set(model_parts(source))
        output = split(source, authority, limit=limit)
        sync_files.save_files(output)
        for obsolete in old - output.keys():
            obsolete.unlink()
        loaded = load_model(source)
        snapshot = {path: path.read_bytes() for path in loaded.files}
        assert len(loaded.parts) == 1 if limit == 600 else len(loaded.parts) > 1
        for command, selector in (
            ("find", "KMS_Key_060"),
            ("find", "見つからない"),
            ("resource", "001"),
            ("trace", "desired.row.001-001.value"),
            ("trace", "observed.row.001-002.value"),
            ("trace", "observed.row.001-002.property"),
        ):
            result, count = invoke(source, command, selector)
            assert result[0] == 0 and not result[2], result
            assert count == 1, (command, count)
            answer = json.loads(result[1])
            if command == "trace":
                assert answer == model_files.trace_model(source, selector)
                if selector.endswith(".property") and selector.startswith("observed."):
                    assert answer["derivedFrom"] == selector.replace(
                        "observed.", "desired."
                    )
            else:
                selected = (
                    model_files.read_resource(source, selector)
                    if command == "resource"
                    else model_files.find_model(source, selector)
                )
                assert answer == {
                    key: [str(origin[0]), *origin[1:]]
                    for key, origin in selected.items()
                }
        for selector in ("001", "KMS_Key_001", "KMS_Alias_002", "003"):
            result = cli("resource", selector)
            assert result.returncode == 0, result.stderr
            extracted = json.loads(result.stdout)
            assert {key: origin[2] for key, origin in extracted.items()} == expected
            assert len(extracted) < len(authority) // 5
            for key, (filename, number, value) in extracted.items():
                file = Path(filename)
                assert file.is_absolute() and file in loaded.parts and number > 0
                assert (
                    file.read_text(encoding="utf-8").splitlines()[number - 1]
                    == key + "=" + value
                )
            assert "desired.resource.004." not in result.stdout
            assert "config.md#config-recorder" in result.stdout
        result = cli("resource", "KMS_Key_060")
        assert (
            result.returncode == 0
            and json.loads(result.stdout)["desired.row.060-001.value"][2] == "設定60=値"
        )
        assert (
            "desired.resource.006." not in result.stdout
            and "desired.resource.001." not in result.stdout
        )
        for selector in ("", "Resource", "kms-resource-001", "999", "KMS_Key_061"):
            result = cli("resource", selector)
            assert result.returncode == 1 and not result.stdout
        assert cli("resource", "001", "--split").returncode == 2
        assert all(path.read_bytes() == raw for path, raw in snapshot.items())

    for command, selector in (
        ("find", "KMS_Key_001"),
        ("resource", "001"),
        ("trace", "desired.row.001-001.value"),
    ):
        for invalid_path in (
            root / "invalid.properties",
            source.with_name("missing.properties"),
        ):
            result, count = invoke(invalid_path, command, selector)
            assert (
                result[0] == 1
                and not result[1]
                and json.loads(result[2])["status"] == "failed"
            )
        with restrict(("stg", "123456789012", "kms")):
            result, count = invoke(source, command, selector)
            assert result[0] == 1 and "outside selected" in result[2] and count == 0
        first = load_model(source).parts[0]
        for file, bad in (
            (source, "# model-format: 99\n"),
            (first, "# model-format: 2\ninvalid\n"),
            (root / "project.json", "{"),
        ):
            saved = file.read_bytes()
            try:
                file.write_text(bad, encoding="utf-8")
                result, count = invoke(source, command, selector)
                assert (
                    result[0] == 1
                    and not result[1]
                    and json.loads(result[2])["status"] == "failed"
                )
            finally:
                file.write_bytes(saved)
        result, count = invoke(source, command, "missing-key-or-resource")
        assert result[0] == (0 if command == "find" else 1) and count == 1
        if command == "find":
            assert json.loads(result[1]) == {}
        else:
            assert not result[1]

    text = serialize(authority)
    for invalid in (
        text.replace(
            "desired.resource.002.logicalId=KMS_Alias_002",
            "desired.resource.002.logicalId=KMS_Key_001",
        ),
        text.replace(
            "[KMS_Key_001](kms.md#resource-KMS_Key_001)",
            "[KMS_Key_999](kms.md#resource-KMS_Key_999)",
        ),
        text.replace(
            "[KMS_Key_001](kms.md#resource-KMS_Key_001)",
            "[KMS_Key_001](other.md#resource-KMS_Key_001)",
        ),
    ):
        try:
            resource_keys(invalid, "KMS_Key_001", scope=load_model(source).scope)
        except ValueError:
            pass
        else:
            raise AssertionError(
                "ambiguous selector or invalid grouped parent accepted"
            )

    producer = source.with_name("iam.properties")
    write_model(
        producer,
        {
            "desired.resource.001.resourceType": "IAM.Role",
            "desired.service.identity.lastAllocated": '{"IAM.Role":1}',
            "desired.resource.001.logicalId": "IAM_Role_001",
            "desired.resource.001.anchor": "resource-IAM_Role_001",
            "desired.resource.001.resourceMode": "CREATE",
            "desired.row.001-001.property": "IAM.Role.RoleName",
            "desired.row.001-001.value": "`shared-role`",
            "desired.row.001-001.comment": "Role name",
        },
    )
    with input_context(read_only=True):
        memo = memo_table()
        with patch.object(sources, "_read_model", wraps=sources._read_model) as body:
            original = load_model(source)
            for _ in range(3):
                model_files.find_model(source, "KMS_Key_001")
                model_files.read_resource(source, "001")
                model_files.trace_model(source, "desired.row.001-001.value")
                assert load_model(source) is original
            assert body.call_count == 1 and memo_table() is memo
        with restrict(("dev", "123456789012", "kms")):
            with reference_reader(producer):
                load_model(producer)
            try:
                load_model(producer)
            except ValueError as error:
                assert "outside selected" in str(error)
            else:
                raise AssertionError(
                    "cached producer bypassed current IMPORT permission"
                )
    assert memo_table() is None

    first = load_model(source).parts[0]
    for file, bad in (
        (source, "# model-format: 99\n"),
        (first, first.read_text() + "invalid\n"),
        (root / "project.json", "{"),
    ):
        saved = file.read_bytes()
        try:
            file.write_text(bad, encoding="utf-8")
            result, _ = invoke(source, "resource", "001")
            assert result[0] == 1 and not result[1]
        finally:
            file.write_bytes(saved)
        assert invoke(source, "resource", "001")[0][0] == 0

    with patch.object(sources, "_read_model", side_effect=RuntimeError("injected")):
        try:
            invoke(source, "find", "KMS_Key_001")
        except RuntimeError as error:
            assert str(error) == "injected"
        else:
            raise AssertionError("unexpected exception swallowed")
    assert memo_table() is None
    try:
        with redirect_stderr(io.StringIO()):
            cli_main([])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("argparse error accepted")
    assert memo_table() is None


def check_part_boundaries(tmp_path):
    root = tmp_path
    scope, _ = format_fixture(root)
    source = scope.path.with_name("config.properties")
    # The header counts toward the approximate 600-line initial packing target.
    for count in (0, 600, 601, 1700):
        values = {
            f"desired.note.{number:04d}.text": f"日本語の説明{number}"
            for number in range(count)
        }
        old = set(model_parts(source)) if source.exists() else set()
        output = split(source, values)
        sync_files.save_files(output)
        for path in old - output.keys():
            path.unlink()
        assembled = {
            key: value
            for part in model_parts(source)
            for key, value in properties(part.read_text()).items()
        }
        assert list(assembled.items()) == list(values.items())
        assert all(
            content.startswith(FORMAT + "\n") and len(content.splitlines()) <= 600
            for content in output.values()
        )
        assert len(output) == (1 if count < 600 else 1 + (count + 598) // 599)
    for part in model_parts(source):
        part.unlink()
    source.unlink()


def check_discovery_alias_and_account():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first, _ = format_fixture(root)
        assert [scope.target for scope in list_models(root)] == ["one"]
        second, _ = format_fixture(root, target="two")
        third, _ = format_fixture(root, target="222222222222")
        assert {scope.target for scope in list_models(root)} == {
            "one",
            "two",
            "222222222222",
        }
        assert {scope.environment for scope in list_models(root)} == {
            "qa-custom",
            "qa-custom-single",
        }
        assert load_model(first).scope.path != load_model(second).scope.path
        assert all("999999999999" not in str(scope.path) for scope in list_models(root))
        assert load_model(third).scope.target == "222222222222"
        for scope in (first, second, third):
            scope.path.unlink()
        assert list_models(root) == []
    for environment in ("templates", "parameters"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, values = format_fixture(
                root, environment=environment, service="network.v1"
            )
            part = scope.path.with_suffix("") / "part-001.properties"
            part.parent.mkdir()
            part.write_text(serialize(values), encoding="utf-8")
            scope.path.write_text(
                FORMAT + "\n" + INDEX + "\n# part: network.v1/part-001.properties\n",
                encoding="utf-8",
            )
            assert source_scope(root, part) == scope
            assert load_model(scope).authoritative == values
            assert [item.environment for item in list_models(root)] == [environment]
            project = root / "project.json"
            retained = root / "project-original.json"
            project.rename(retained)
            project.symlink_to(retained)
            with patch.object(
                Path, "read_bytes", side_effect=AssertionError("symlink input was read")
            ):
                with pytest.raises(ValueError, match="unsafe"):
                    load_model(scope)


def check_parts_and_large_resource():
    assert owner("desired.service.network.serviceId", {}) == owner(
        "display.service.title", {}
    )
    assert owner("desired.deployment.templateBucket", {}) == owner(
        "desired.deployment.templateKeyPrefix", {}
    )
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        for index in range(3, 220):
            values.update(
                {
                    f"desired.row.007-{index:03d}.{field}": value
                    for field, value in (
                        ("property", "EC2.VPC.Name"),
                        ("value", "example"),
                        ("comment", "合成行"),
                    )
                }
            )
        values.update(
            {
                "desired.resource.008.resourceType": "EC2.VPC",
                "desired.resource.008.logicalId": "EC2_VPC_002",
                "desired.resource.008.anchor": "resource-EC2_VPC_002",
                "desired.service.identity.lastAllocated": '{"EC2.VPC":2}',
            }
        )
        output = split(scope.path, values)
        assert output[scope.path].splitlines()[1] == INDEX
        assert (
            len(
                next(
                    text for path, text in output.items() if path != scope.path
                ).splitlines()
            )
            > 600
        )
        for path, text in output.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        assert load_model(scope).authoritative == values
        part = scope.path.with_suffix("") / "part-002.properties"
        renamed = part.with_name("part-003.properties")
        part.rename(renamed)
        scope.path.write_text(
            output[scope.path].replace("part-002", "part-003"), encoding="utf-8"
        )
        assert load_model(scope).authoritative == values


if __name__ == "__main__":
    raise SystemExit(run(__file__))
