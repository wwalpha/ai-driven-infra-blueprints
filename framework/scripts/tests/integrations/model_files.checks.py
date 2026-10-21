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
import model.files as model_files

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
                "desired.row.001-002.comment": "識別子",
                "desired.row.001-002.value": "[Resource1](#kms-resource-001)",
                "observed.row.001-002.property": "KMS.Key.KeyId",
                "observed.row.001-002.value": "12345678-current-key-id",
                "desired.row.001-003.property": "KMS.Key.KeyPolicy",
                "desired.row.001-003.comment": "Policy",
                "desired.row.001-003.value": "[Policy](kms/key-policy.json)",
                "desired.row.001-003.document": '{"Statement": [{"Sid": "保持=値", "Resource": "[Recorder](config.md#config-recorder)"}]}',
            })
    from model.cli import main as cli_main
    from model.format import serialize, split
    from model import sources
    from model.importing.scope import restrict, reference_reader
    from validation_cache import input_context, memo_table

    def cli(command, selector, *extra):
        return subprocess.run([sys.executable, "-B", str(ROOT / "framework/scripts/model/cli.py"),
                               command, str(source), selector, *extra],
                              capture_output=True, text=True, encoding="utf-8")

    def invoke(path, command, selector):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sources, '_read_model', wraps=sources._read_model) as body, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli_main([command, str(path), selector])
        return (code, stdout.getvalue(), stderr.getvalue()), body.call_count

    write_model(source, values)
    authority = dict(load_model(source).authoritative)
    prefixes = ("desired.service.", "display.service.", "desired.note.") + tuple(
        prefix for identity in ("001", "002", "003") for prefix in (
            f"desired.resource.{identity}.", f"display.resource.{identity}.",
            f"desired.row.{identity}-", f"observed.row.{identity}-"))
    expected = {key: value for key, value in authority.items() if key.startswith(prefixes)}
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
        for command, selector in (('find', 'Resource60'), ('find', '見つからない'),
                                   ('resource', '001'), ('trace', 'desired.row.001-001.value'),
                                   ('trace', 'observed.row.001-002.value'),
                                   ('trace', 'observed.row.001-002.property')):
            result, count = invoke(source, command, selector)
            actual = cli(command, selector)
            assert result == (actual.returncode, actual.stdout, actual.stderr)
            assert result[0] == 0 and not result[2], result
            assert count == 1, (command, count)
            answer = json.loads(result[1])
            if command == 'trace':
                assert answer == model_files.trace_model(source, selector)
                if selector.endswith('.property') and selector.startswith('observed.'):
                    assert answer['derivedFrom'] == selector.replace('observed.', 'desired.')
            else:
                selected = model_files.read_resource(source, selector) if command == 'resource' else model_files.find_model(source, selector)
                assert answer == {key: [str(origin[0]), *origin[1:]] for key, origin in selected.items()}
        for selector in ("001", "Resource1", "kms-resource-001", "Resource2", "003"):
            result = cli('resource', selector)
            assert result.returncode == 0, result.stderr
            extracted = json.loads(result.stdout)
            assert {key: origin[2] for key, origin in extracted.items()} == expected
            assert len(extracted) < len(authority) // 5
            for key, (filename, number, value) in extracted.items():
                file = Path(filename)
                assert file.is_absolute() and file in loaded.parts and number > 0
                assert file.read_text(encoding='utf-8').splitlines()[number - 1] == key + '=' + value
            assert 'desired.resource.004.' not in result.stdout
            assert 'config.md#config-recorder' in result.stdout
        result = cli('resource', 'Resource60')
        assert result.returncode == 0 and json.loads(result.stdout)['desired.row.060-001.value'][2] == '設定60=値'
        assert 'desired.resource.006.' not in result.stdout and 'desired.resource.001.' not in result.stdout
        for selector in ('', 'Resource', '999', 'Resource61'):
            result = cli('resource', selector)
            assert result.returncode == 1 and not result.stdout
        assert cli('resource', '001', '--split').returncode == 2
        assert all(path.read_bytes() == raw for path, raw in snapshot.items())

    for command, selector in (('find', 'Resource1'), ('resource', '001'), ('trace', 'desired.row.001-001.value')):
        for invalid_path in (root / 'invalid.properties', source.with_name('missing.properties')):
            result, count = invoke(invalid_path, command, selector)
            assert result[0] == 1 and not result[1] and json.loads(result[2])['status'] == 'failed'
        with restrict(('stg', '123456789012', 'kms')):
            result, count = invoke(source, command, selector)
            assert result[0] == 1 and 'outside selected' in result[2] and count == 0
        first = load_model(source).parts[0]
        for file, bad in ((source, '# model-format: 99\n'), (first, '# model-format: 2\ninvalid\n'),
                          (root / 'project.json', '{')):
            saved = file.read_bytes()
            try:
                file.write_text(bad, encoding='utf-8')
                result, count = invoke(source, command, selector)
                assert result[0] == 1 and not result[1] and json.loads(result[2])['status'] == 'failed'
            finally:
                file.write_bytes(saved)
        result, count = invoke(source, command, 'missing-key-or-resource')
        assert result[0] == (0 if command == 'find' else 1) and count == 1
        if command == 'find':
            assert json.loads(result[1]) == {}
        else:
            assert not result[1]

    tasks = root / 'tasks'
    tasks.mkdir()
    try:
        for name in ('one', 'two'):
            (tasks / f'{name}.md').write_text(
                f'## Task contract\n- Task type: `governance`\n- Task status: `running`\n'
                f'## Modified files\n- `tasks/{name}.md`\n## Allowed paths\n- `tasks/{name}.md`\n', encoding='utf-8')
        for command, selector in (('find', 'Resource1'), ('resource', '001'), ('trace', 'desired.row.001-001.value')):
            with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': ''}):
                result, count = invoke(source, command, selector)
                assert result[0] == 1 and not result[1] and 'multiple running tasks' in result[2] and count == 0
            with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/one.md'}):
                result, count = invoke(source, command, selector)
                assert result[0] == 0 and count == 1
    finally:
        for file in tasks.iterdir():
            file.unlink()
        tasks.rmdir()

    text = serialize(authority)
    for invalid in (
        text.replace('desired.resource.002.logicalId=Resource2', 'desired.resource.002.logicalId=Resource1'),
        text.replace('[Resource1](#kms-resource-001)', '[Missing](#missing)'),
        text.replace('[Resource1](#kms-resource-001)', '[Other](other.md#kms-resource-001)'),
    ):
        try:
            resource_keys(invalid, 'Resource1')
        except ValueError:
            pass
        else:
            raise AssertionError('ambiguous selector or invalid grouped parent accepted')

    producer = source.with_name('iam.properties')
    write_model(producer, {
        'desired.resource.001.resourceType': 'IAM.Role',
        'desired.resource.001.anchor': 'role',
        'desired.resource.001.logicalId': 'Role',
        'desired.resource.001.resourceMode': 'CREATE',
        'desired.row.001-001.property': 'IAM.Role.RoleName',
        'desired.row.001-001.value': '`shared-role`',
        'desired.row.001-001.comment': 'Role name',
    })
    with input_context():
        memo = memo_table()
        with patch.object(sources, '_read_model', wraps=sources._read_model) as body:
            original = load_model(source)
            for _ in range(3):
                model_files.find_model(source, 'Resource1')
                model_files.read_resource(source, '001')
                model_files.trace_model(source, 'desired.row.001-001.value')
                assert load_model(source) is original
            assert body.call_count == 1 and memo_table() is memo
        with restrict(('dev', '123456789012', 'kms')):
            with reference_reader(producer):
                load_model(producer)
            try:
                load_model(producer)
            except ValueError as error:
                assert 'outside selected' in str(error)
            else:
                raise AssertionError('cached producer bypassed current IMPORT permission')
    assert memo_table() is None

    first = load_model(source).parts[0]
    for file, bad in ((source, '# model-format: 99\n'), (first, first.read_text() + 'invalid\n'),
                      (root / 'project.json', '{')):
        saved = file.read_bytes()
        try:
            file.write_text(bad, encoding='utf-8')
            result, _ = invoke(source, 'resource', '001')
            assert result[0] == 1 and not result[1]
        finally:
            file.write_bytes(saved)
        assert invoke(source, 'resource', '001')[0][0] == 0

    def assert_inputs(inputs):
        for file, raw in inputs.items():
            if (file.read_bytes() if file.is_file() else None) != raw:
                raise ValueError('input changed after validation')

    # Publication invalidates the invocation cache; stale raw-input snapshots still fail closed.
    with input_context():
        original = load_model(source)
        saved = first.read_text()
        inputs = dict(original.dependencies)
        try:
            with sources.publication_lock(root) as journal:
                sources._publish_transaction(root, {first: saved.replace('用途1', '公開後の用途1')}, (), journal,
                    start=lambda: assert_inputs(inputs))
            changed = load_model(source)
            assert changed is not original and changed.values['display.resource.001.comment'] == '公開後の用途1'
            inputs = dict(changed.dependencies)
            first.write_text(saved, encoding='utf-8')
            try:
                with sources.publication_lock(root) as journal:
                    sources._publish_transaction(root, {}, (), journal, start=lambda: assert_inputs(inputs))
            except ValueError as error:
                assert 'changed' in str(error)
            else:
                raise AssertionError('changed snapshot accepted')
        finally:
            with sources.publication_lock(root) as journal:
                sources._publish_transaction(root, {first: saved}, (), journal)
    assert memo_table() is None
    with patch.object(sources, '_read_model', side_effect=RuntimeError('injected')):
        try:
            invoke(source, 'find', 'Resource1')
        except RuntimeError as error:
            assert str(error) == 'injected'
        else:
            raise AssertionError('unexpected exception swallowed')
    assert memo_table() is None
    try:
        with redirect_stderr(io.StringIO()):
            cli_main([])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError('argparse error accepted')
    assert memo_table() is None


def main():
    subprocess.run([sys.executable, '-B', '-c',
                    "import sys, model.core, model.files; "
                    "assert not {'model.render', 'design_layout', 'sync_runtime', 'model_core', 'model_files'} & sys.modules.keys()"],
                   cwd=ROOT / 'framework/scripts', check=True)
    from model.format import FORMAT, split
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        copy_framework(root / 'framework')
        (root / 'project.json').write_text(json.dumps({'projectName': 'test', 'targets': [{
            'environment': 'dev', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
        source = root / 'model/dev/123456789012/config.properties'
        source.parent.mkdir(parents=True)
        check_resource_reading(root)
        # The header counts toward the approximate 600-line initial packing target.
        for count in (0, 600, 601, 1700):
            values = {f'desired.note.{number:04d}.text': f'日本語の説明{number}' for number in range(count)}
            old = set(model_parts(source)) if source.exists() else set()
            output = split(source, values)
            sync_files.save_files(output)
            for path in old - output.keys():
                path.unlink()
            assembled = {key: value for part in model_parts(source) for key, value in properties(part.read_text()).items()}
            assert list(assembled.items()) == list(values.items())
            assert all(content.startswith(FORMAT + '\n') and len(content.splitlines()) <= 600 for content in output.values())
            assert len(output) == (1 if count < 600 else 1 + (count + 598) // 599)
        for part in model_parts(source):
            part.unlink()
        source.unlink()

        values = {'desired.deployment.maxConcurrentStacks': '2'}
        for number in range(1, 111):
            key = f'{number:03d}'
            values.update({f'desired.stack.{key}.name': f'cfn-stack-app-dev-core-{key}',
                           f'desired.stack.{key}.deployOrder': '10', f'desired.stack.{key}.template': 'app.yaml',
                           f'desired.stack.{key}.parameters': f'app-{key}.json',
                           f'display.stack.{key}.comment': 'アプリケーションのstack'})
        stack = source.with_name('cloudformation-stacks.properties')
        write_model(stack, values)
        docs = root / 'docs/designs/dev/123456789012/cloudformation-stacks.md'
        docs.parent.mkdir(parents=True)
        docs.write_text(markdown_for(docs, values, root))
        limit, units = DEPLOY.load_units(root, 'dev', '123456789012', [values['desired.stack.001.name']])
        assert limit == 2 and len(units) == 1
        for part in load_model(stack).files:
            saved = part.read_bytes()
            part.unlink()
            try:
                load_model(stack)
            except (OSError, ValueError):
                pass
            else:
                raise AssertionError('missing authoritative part accepted')
            finally:
                part.write_bytes(saved)
        assert load_model(stack).values == values
    print('model-files: PASS (format-2 parts, CLI resource/find/trace, grouped context, read-only, value/order retention, scope/cache isolation, publication and stale inputs)')


if __name__ == '__main__':
    main()
