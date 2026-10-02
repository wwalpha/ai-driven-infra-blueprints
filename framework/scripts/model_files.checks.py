#!/usr/bin/env python3
"""Checks for bounded, indexed authoritative service models."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from model_files import INDEX_HEADER, model_parts, model_file_contents, read_model
from model_design import properties, markdown_for
from validation_scope import scoped_files
from issue_gate import unresolved_services

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


SYNC = module("index_sync", "sync-model.py")
VALIDATOR = module("index_validator", "validate-blueprint.py")
DEPLOY = module("index_deploy", "cloudformation-deploy.py")


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        source = root / "model/dev/123456789012/config.properties"
        source.parent.mkdir(parents=True)
        # 600-line files remain single; 601-line files split without changing any line.
        for count in (0, 600, 601, 1700):
            text = "".join(f"desired.note.{number:04d}.text=日本語の説明{number}\n" for number in range(count))
            old = set(model_parts(source)) if source.exists() else set()
            output = model_file_contents(source, text)
            SYNC.save_files(output)
            for path in old - output.keys() - {source}:
                path.unlink()
            assert read_model(source) == text
            assert list(properties(read_model(source)).items()) == list(properties(text).items())
            assert all(len(content.splitlines()) <= 600 for content in output.values())
            assert len(output) == (1 if count <= 600 else 1 + (count + 549) // 550)
        for part in model_parts(source):
            part.unlink()
        source.unlink()

        (root / "project.json").write_text('{"projectName":"test","targets":[{"environment":"dev","awsAccountId":"123456789012","awsRegion":"ap-northeast-1","iacEngine":"cloudformation"}]}\n')
        contract = root / "tasks/active.md"
        contract.parent.mkdir()
        contract.write_text("""# Split model

## Task contract
- Task type: `migration`

## Validation scope
- `dev/123456789012/config`

## Allowed paths
- `model/dev/123456789012/config.properties`
- `model/dev/123456789012/config/*.properties`
""")
        anchor = "config-configuration-recorder-default"
        values = {
            "desired.service.config.serviceId": "config",
            "desired.service.config.ownedCatalogResourceTypes": "Config.ConfigurationRecorder",
            "desired.resource.001.resourceType": "Config.ConfigurationRecorder",
            "desired.resource.001.logicalId": "Recorder",
            "desired.resource.001.anchor": anchor,
            "display.service.title": "# AWS Config 詳細設計",
            "display.resource.001.comment": "構成情報を記録するrecorder",
            "desired.row.001-001.property": "Config.ConfigurationRecorder.Name",
            "desired.row.001-001.value": "`default`",
            "desired.row.001-001.comment": "recorderの名前",
            "desired.row.001-002.property": "Config.ConfigurationRecorder.Id",
            "desired.row.001-002.value": f"[Recorder](#{anchor})",
            "desired.row.001-002.comment": "recorderを識別するID",
            "observed.row.001-002.property": "Config.ConfigurationRecorder.Id",
            "observed.row.001-002.value": "`default`",
            "observed.row.001-002.comment": "recorderを識別するID",
            "desired.row.001-003.property": "Config.ConfigurationRecorder.RoleARN",
            "desired.row.001-003.value": "`AWSServiceRoleForConfig`",
            "desired.row.001-003.comment": "記録に使用するrole",
            **{f"desired.note.{number:03d}.text": f"注記{number}: 設計の説明" for number in range(1, 651)},
        }
        text = "".join(f"{key}={value}\n" for key, value in values.items())
        source.write_text(text)
        docs = root / "docs/designs/dev/123456789012/config.md"
        docs.parent.mkdir(parents=True)
        expected = markdown_for(docs, values, root)
        docs.write_text(expected)
        validator = VALIDATOR.Validator(root)
        validator.check_model_files()
        assert any("exceeds 600 lines" in error for error in validator.errors)

        def cli(*args):
            return subprocess.run([sys.executable, "-B", str(ROOT / "framework/scripts/model_files.py"), str(source), *args], capture_output=True, text=True)

        result = cli("--split")
        assert result.returncode == 0, result.stderr
        assert read_model(source) == text
        result = cli("--find", "desired.note.600.text")
        assert result.returncode == 0, result
        found_path, line_number, key = result.stdout.strip().rsplit(":", 2)
        assert Path(found_path) == source.parent / "config/part-002.properties", result.stdout
        assert int(line_number) > 0 and key.strip() == "desired.note.600.text", result.stdout
        assert "desired.note.600.text" in result.stdout
        assert "注記600" not in result.stdout  # Lookup does not dump potentially large JSON values.
        assert "desired.note.599" not in result.stdout
        scope = {("dev", "123456789012", "config")}
        assert scoped_files(root, "model", ".properties", None) == [source]
        assert scoped_files(root, "model", ".properties", scope) == [source]
        snapshot = {path: path.read_bytes() for path in {source, *model_parts(source)}}
        for services in (None, ["config"]):
            with redirect_stdout(io.StringIO()):
                assert SYNC.sync(root, True, "dev", "123456789012", services=services) == 0
                assert SYNC.sync(root, False, "dev", "123456789012", services=services) == 0
        assert docs.read_text() == expected
        assert all(path.read_bytes() == content for path, content in snapshot.items())
        original_contract = contract.read_text()
        for invalid_contract in (original_contract.replace("`migration`", "`infrastructure`"),
                                 original_contract.replace("`dev/123456789012/config`", "`dev/123456789012/iam`"),
                                 original_contract.replace("config/*.properties", "iam/*.properties")):
            contract.write_text(invalid_contract)
            result = cli("--split")
            assert result.returncode == 1, result
            assert all(path.read_bytes() == content for path, content in snapshot.items())
        contract.write_text(original_contract)
        validator = VALIDATOR.Validator(root, scope)
        validator.check_project_topology()
        validator.check_model_files()
        validator.changed_paths = {"model/dev/123456789012/config/part-002.properties", "docs/designs/dev/123456789012/config.md"}
        validator.task_type = "design"
        validator.check_validation_scope()
        validator.check_task_type_requirements()
        assert not validator.errors, validator.errors
        issues = root / "issues/dev/123456789012/issues.md"
        issues.parent.mkdir(parents=True)
        issues.write_text("### AWS Config\n\n1. 検証不備。[根拠](../../../model/dev/123456789012/config/part-002.properties:10)。\n")
        assert unresolved_services(root, issues) == [("1", {"config"})]
        issues.unlink()

        first, second = model_parts(source)
        saved = {path: path.read_text() for path in (source, first, second)}

        def rejected():
            try:
                read_model(source)
            except (OSError, ValueError):
                pass
            else:
                raise AssertionError("invalid model index/part accepted")
            for path, content in saved.items():
                path.write_text(content)

        second.unlink()
        rejected()
        for invalid in ("../other.properties", "other/part-001.properties", "config/part-001.properties"):
            source.write_text(saved[source].replace("config/part-002.properties", invalid))
            rejected()
        second.write_text(saved[second] + "desired.service.config.serviceId=duplicate\n")
        rejected()
        second.write_text(INDEX_HEADER + "\n" + saved[second])
        rejected()
        first.write_text(saved[first].rstrip("\n"))
        rejected()
        second.write_text("# extra\n" * 601)
        rejected()
        extra = first.with_name("unlisted.properties")
        extra.write_text("desired.note.extra.text=説明\n")
        rejected()
        extra.unlink()
        second.unlink()
        second.symlink_to(first)
        try:
            read_model(source)
        except ValueError as error:
            assert "unsafe" in str(error)
        else:
            raise AssertionError("symlink model part accepted")
        second.unlink()
        second.write_text(saved[second])
        first.write_text(saved[first].replace("observed.row.001-002.value=`default`", "observed.row.001-002.value=arn:aws:config:generated"))
        validator = VALIDATOR.Validator(root)
        validator.check_observed_values([source])
        assert any("generated ARN" in error for error in validator.errors), validator.errors
        first.write_text(saved[first])

        # Stack consumers read the same indexed format.
        stack = source.with_name("cloudformation-stacks.properties")
        stack_values = {"desired.deployment.maxConcurrentStacks": "2"}
        for number in range(1, 111):
            key = f"{number:03d}"
            stack_values.update({f"desired.stack.{key}.name": f"cfn-stack-app-dev-core-{key}",
                                 f"desired.stack.{key}.deployOrder": "10", f"desired.stack.{key}.template": "app.yaml",
                                 f"desired.stack.{key}.parameters": f"app-{key}.json",
                                 f"display.stack.{key}.comment": "アプリケーションのstack"})
        SYNC.save_files(model_file_contents(stack, "".join(f"{key}={value}\n" for key, value in stack_values.items())))
        stack_docs = docs.with_name("cloudformation-stacks.md")
        stack_docs.write_text(markdown_for(stack_docs, stack_values, root))
        limit, units = DEPLOY.load_units(root, "dev", "123456789012", [stack_values["desired.stack.001.name"]])
        assert limit == 2 and len(units) == 1
    print("model-files: PASS (600-line limit, indexes, lookup, lossless values/order, service scope, generation, stacks and invalid parts)")


if __name__ == "__main__":
    main()
