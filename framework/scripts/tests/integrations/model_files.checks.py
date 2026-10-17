#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.model_files_fixtures import *

from support.it_workspace import copy_framework
from contextlib import redirect_stderr
import json
import model_files
import model_templates
from import_scope import restrict

@it_case
def check_resource_reading(root):
    source = root / "model/dev/123456789012/kms.properties"
    values = {
        "desired.service.kms.serviceId": "kms",
        "desired.service.kms.ownedCatalogResourceTypes": "KMS.Key,KMS.Alias",
        "display.service.title": "# KMS 詳細設計",
        "desired.note.001.text": "共通注記はresource番号と同じでもservice全体に適用する",
    }
    for number in range(1, 61):
        identity = f"{number:03d}"
        kind = "KMS.Alias" if number in (2, 3) else "KMS.Key"
        values.update({
            f"desired.resource.{identity}.resourceType": kind,
            f"desired.resource.{identity}.logicalId": f"Resource{number}",
            f"desired.resource.{identity}.anchor": f"kms-resource-{identity}",
            f"desired.resource.{identity}.resourceMode": "CREATE",
            f"display.resource.{identity}.comment": f"用途{number}",
            f"desired.row.{identity}-001.property": f"{kind}.Description",
            f"desired.row.{identity}-001.value": f"設定{number}=値",
            f"desired.row.{identity}-001.comment": f"説明{number}",
        })
        if number in (2, 3):
            values[f"desired.resource.{identity}.parentReference"] = "[Resource1](#kms-resource-001)"
            values[f"desired.resource.{identity}.parentProperty"] = "KMS.Alias.TargetKeyId"
        if number == 1:
            values.update({
                "desired.row.001-002.property": "KMS.Key.KeyId",
                "desired.row.001-002.value": "[Resource1](#kms-resource-001)",
                "observed.row.001-002.property": "KMS.Key.KeyId",
                "observed.row.001-002.value": "12345678-current-key-id",
                "desired.row.001-003.property": "KMS.Key.KeyPolicy",
                "desired.row.001-003.value": "[Policy](kms/key-policy.json)",
                "desired.row.001-003.document": '{"Statement": [{"Sid": "保持=値", "Resource": "[Recorder](config.md#config-recorder)"}]}',
            })
    text = "".join(f"{key}={value}\n" for key, value in values.items())

    def cli(*args):
        return subprocess.run([sys.executable, "-B", str(ROOT / "framework/scripts/model_files.py"), str(source), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def invoke(path, flag, selector):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['model_files.py', str(path), flag, selector]), \
             patch.object(model_files, 'load_model', wraps=model_files.load_model) as loaded, \
             patch.object(model_templates, 'load_expansion', wraps=model_templates.load_expansion) as expansion, \
             patch.object(model_templates, 'expand', wraps=model_templates.expand) as body, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            code = model_files.main()
        return (code, stdout.getvalue(), stderr.getvalue()), (loaded.call_count, expansion.call_count, body.call_count)

    group_prefixes = ("desired.service.", "display.service.", "desired.note.") + tuple(
        prefix for identity in ("001", "002", "003") for prefix in (
            f"desired.resource.{identity}.", f"display.resource.{identity}.",
            f"desired.row.{identity}-", f"observed.row.{identity}-",
        )
    )
    expected = [f"{key}={value}" for key, value in sorted(values.items()) if key.startswith(group_prefixes)]
    # The single model fits in 600 lines; padding moves the selected rows across a part boundary.
    write_model(source, values)
    for content in (text, "# padding\n" * 540 + text):
        write_model(source, content)
        loaded = load_model(source)
        expected = [f"{key}={value}" for key, value in loaded.values.items() if key.startswith(group_prefixes)]
        snapshot = {path: path.read_bytes() for path in loaded.files}
        for flag, selector in (('--find', 'Resource60'), ('--find', '見つからない'),
                               ('--resource', '001'), ('--trace', 'desired.row.001-001.value'),
                               ('--trace', 'observed.row.001-002.value')):
            result, counts = invoke(source, flag, selector)
            assert counts == (0 if flag == '--trace' else 1, 1, 1), (flag, counts)
            actual = cli(flag, selector)
            assert result == (actual.returncode, actual.stdout, actual.stderr)
            assert result[0] == 0 and not result[2], result
            if flag == '--trace':
                assert json.loads(result[1]) == model_templates.load_expansion(source).provenance[selector]
            else:
                keys = resource_keys(loaded.text, selector) if flag == '--resource' else {
                    key for key, value in loaded.values.items() if selector in key + '=' + value}
                assert result[1] == ''.join(
                    f'{loaded.locations[key][0]}:{loaded.locations[key][1]}: {key}'
                    + ('=' + value if flag == '--resource' else '') + '\n'
                    for key, value in loaded.values.items() if key in keys)
        for selector in ("001", "Resource1", "kms-resource-001", "Resource2", "003"):
            result = cli("--resource", selector)
            assert result.returncode == 0, result.stderr
            extracted = []
            locations = set()
            for line in result.stdout.splitlines():
                # Values may themselves contain colons, including JSON; split only the location prefix.
                location, value = line.split(": ", 1)
                filename, number = location.rsplit(":", 1)
                path = Path(filename)
                assert path.is_absolute() and path.is_file()
                assert int(number) > 0
                key = value.partition("=")[0]
                trace = __import__("model_templates").load_expansion(source).provenance[key]
                if "template" in trace:
                    assert path.read_text(encoding="utf-8").splitlines()[int(number) - 1].partition("=")[0] == trace["key"]
                else:
                    assert path.name == "observed.json"
                extracted.append(value)
                locations.add(path)
            assert extracted == expected, result.stdout
            assert len(extracted) < len(values) // 5
            assert locations <= {location[0] for location in loaded.locations.values()}
            assert "desired.resource.004." not in result.stdout
            assert "config.md#config-recorder" in result.stdout  # Preserve links without reading other services.
        result = cli("--resource", "Resource60")
        assert result.returncode == 0 and "desired.row.060-001.value=設定60=値" in result.stdout
        assert "desired.resource.006." not in result.stdout and "desired.resource.001." not in result.stdout
        for selector in ("", "Resource", "999", "Resource61"):
            result = cli("--resource", selector)
            assert result.returncode == 1 and not result.stdout, result
        assert cli("--resource", "001", "--split").returncode == 2
        assert all(path.read_bytes() == data for path, data in snapshot.items())

    for flag, selector in (('--find', 'Resource1'), ('--resource', '001'),
                           ('--trace', 'desired.row.001-001.value')):
        for invalid_path, message in ((root / 'invalid.properties', 'Model requires a YAML service source'),
                                      (source.with_name('missing.properties'), 'YAML Model inputs missing')):
            result, counts = invoke(invalid_path, flag, selector)
            assert result[0] == 1 and not result[1] and message in result[2], result
            assert counts[2] == 0, counts
        with restrict(('stg', '123456789012', 'kms')):
            result, counts = invoke(source, flag, selector)
            assert result == (1, '', 'Service model files: FAIL: IMPORT reference is outside selected environment/target/service\n')
            assert counts[1:] == (0, 0), counts
        _, template, directory = model_templates.source_paths(source)
        for file, bad in ((directory / 'parameters.yaml', 'instances: [\n'),
                          (directory / 'bindings.json', '{'), (template, '# invalid template\n')):
            saved = file.read_bytes()
            try:
                file.write_text(bad, encoding='utf-8')
                result, counts = invoke(source, flag, selector)
                assert result[0] == 1 and not result[1] and result[2].startswith('Service model files: FAIL:'), result
                assert counts[2] == 0, counts
            finally:
                file.write_bytes(saved)
        result, counts = invoke(source, flag, 'missing-key-or-resource')
        assert result[0] == (0 if flag == '--find' else 1) and not result[1], result
        assert counts[2] == 1, counts

    tasks = root / 'tasks'
    tasks.mkdir()
    try:
        for name in ('one', 'two'):
            (tasks / f'{name}.md').write_text(
                f'## Task contract\n- Task type: `governance`\n- Task status: `running`\n'
                f'## Modified files\n- `tasks/{name}.md`\n## Allowed paths\n- `tasks/{name}.md`\n', encoding='utf-8')
        for flag, selector in (('--find', 'Resource1'), ('--resource', '001'),
                               ('--trace', 'desired.row.001-001.value')):
            with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': ''}):
                result, counts = invoke(source, flag, selector)
                assert result[0] == 1 and not result[1] and 'multiple running tasks' in result[2], result
                assert counts[1:] == (0, 0), counts
            with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/one.md'}):
                result, counts = invoke(source, flag, selector)
                assert result[0] == 0 and counts[2] == 1, (result, counts)
    finally:
        for file in tasks.iterdir():
            file.unlink()
        tasks.rmdir()

    for invalid in (
        text.replace("desired.resource.002.logicalId=Resource2", "desired.resource.002.logicalId=Resource1"),
        text.replace("[Resource1](#kms-resource-001)", "[Missing](#missing)"),
        text.replace("[Resource1](#kms-resource-001)", "[Other](other.md#kms-resource-001)"),
    ):
        try:
            resource_keys(invalid, "Resource1")
        except ValueError:
            pass
        else:
            raise AssertionError("ambiguous selector or invalid grouped parent accepted")


def main():
    subprocess.run([sys.executable, "-B", "-c",
                    "import sys, model_core, model_files; "
                    "assert not {'model_design', 'design_layout', 'sync_runtime'} & sys.modules.keys()"],
                   cwd=ROOT / "framework/scripts", check=True)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        copy_framework(root / 'framework')
        source = root / "model/dev/123456789012/config.properties"
        source.parent.mkdir(parents=True)
        check_resource_reading(root)
        # 600-line files remain single; 601-line files split without changing any line.
        for count in (0, 600, 601, 1700):
            text = "".join(f"desired.note.{number:04d}.text=日本語の説明{number}\n" for number in range(count))
            old = set(model_parts(source)) if source.exists() else set()
            output = model_file_contents(source, text)
            sync_files.save_files(output)
            for path in old - output.keys() - {source}:
                path.unlink()
            combined = "".join(part.read_text(encoding="utf-8") for part in model_parts(source))
            assert combined == text
            assert list(properties(combined).items()) == list(properties(text).items())
            assert all(len(content.splitlines()) <= 600 for content in output.values())
            assert len(output) == (1 if count <= 600 else 1 + (count + 549) // 550)
        for part in model_parts(source):
            part.unlink()
        source.unlink()

        (root / "project.json").write_text('{"projectName":"test","targets":[{"environment":"dev","awsAccountId":"123456789012","awsRegion":"ap-northeast-1","iacEngine":"cloudformation"}]}\n')
        values = {"desired.deployment.maxConcurrentStacks": "2"}
        for number in range(1, 111):
            key = f"{number:03d}"
            values.update({f"desired.stack.{key}.name": f"cfn-stack-app-dev-core-{key}",
                           f"desired.stack.{key}.deployOrder": "10", f"desired.stack.{key}.template": "app.yaml",
                           f"desired.stack.{key}.parameters": f"app-{key}.json",
                           f"display.stack.{key}.comment": "アプリケーションのstack"})
        stack = source.with_name("cloudformation-stacks.properties")
        write_model(stack, values)
        docs = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
        docs.parent.mkdir(parents=True)
        docs.write_text(markdown_for(docs, values, root))
        limit, units = DEPLOY.load_units(root, "dev", "123456789012", [values["desired.stack.001.name"]])
        assert limit == 2 and len(units) == 1
        for part in __import__("model_templates").source_inputs(stack) - {root/"project.json"}:
            saved = part.read_bytes()
            part.unlink()
            try:
                load_model(stack)
            except (OSError, ValueError):
                pass
            else:
                raise AssertionError("missing projection part accepted")
            part.write_bytes(saved)
        assert load_model(stack).values == values

    print("model-files: PASS (600-line limit, indexes, lookup, resource extraction across 60 resources/parts, grouped context, read-only, lossless values/order, YAML sources, stacks and invalid parts)")


if __name__ == "__main__":
    main()

