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

    from collections import Counter
    from contextlib import ExitStack
    from import_scope import scoped_read, read_consumers
    from validation_cache import input_scope, memoized, memo_table

    consumer = root / 'reuse/model/dev/team/kms.properties'
    producer = consumer.with_name('iam.properties')
    write_model(producer, {
        'desired.resource.001.resourceType': 'IAM.Role',
        'desired.resource.001.anchor': 'role',
        'desired.row.001-001.property': 'IAM.Role.RoleName',
        'desired.row.001-001.value': '`shared-role`',
    })
    write_model(consumer, {
        'desired.resource.001.resourceType': 'KMS.Key',
        'desired.resource.001.anchor': 'key',
        'desired.note.first.text': '<<First>>',
        'desired.note.second.text': '<<Second>>',
        'desired.note.anchor.text': '<<Anchor>>',
        'desired.note.account.text': '<<Account>>',
    })
    _, template, parameters = model_templates.source_paths(consumer)
    text = template.read_text(encoding='utf-8')
    references = ''.join('# reference: ' + name + ' ' + json.dumps({
        'service': 'iam', 'resource': '001', 'resourceType': 'IAM.Role', **mode}) + '\n'
        for name, mode in (('First', {'format': 'name'}), ('Second', {'format': 'name'}), ('Anchor', {})))
    text = text.replace('# model-template: 1\n', '# model-template: 1\n# input: Account ' + json.dumps({
        'type': 'string', 'description': 'account', 'required': True, 'source': 'consumer.executionAccountId'}) + '\n')
    template.write_text(text.replace('# resource:', references + '# resource:', 1), encoding='utf-8')
    (consumer.parents[3] / 'project.json').write_text(json.dumps({'targets': [{
        'environment': 'dev', 'alias': 'team', 'awsAccountId': '123456789012',
        'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}), encoding='utf-8')

    def invoke_references(entry, flag='--find', selector='desired.note.'):
        stdout, stderr = io.StringIO(), io.StringIO()
        lookups, bodies = {}, {}
        with ExitStack() as patches:
            if entry is model_files.main.__wrapped__:
                # Simulate the pre-scope APIs too; unwrapping only main still reuses their scopes.
                for name in ('find_model', 'read_resource', 'trace_model'):
                    patches.enter_context(patch.object(model_files, name, getattr(model_files, name).__wrapped__))
            for module, name in ((model_files, 'load_model'), (model_templates, '_reference_inputs'),
                                 (model_templates, 'reference_values'), (model_templates, '_parse_template')):
                original = getattr(module, name)
                body = original.__wrapped__ if name == '_parse_template' else original.__wrapped__.__wrapped__
                calls = Counter()
                def counted(*args, _body=body, _calls=calls):
                    _calls[args] += 1
                    return _body(*args)
                cached = memoized(counted)
                if name != '_parse_template':
                    cached = scoped_read(cached)
                lookups[name] = patches.enter_context(patch.object(module, name, wraps=cached))
                bodies[name] = calls
            patches.enter_context(patch.object(sys, 'argv', ['model_files.py', str(consumer), flag, selector]))
            patches.enter_context(redirect_stdout(stdout))
            patches.enter_context(redirect_stderr(stderr))
            code = entry()
        return (code, stdout.getvalue(), stderr.getvalue()), {name: spy.call_count for name, spy in lookups.items()}, bodies

    for flag, selector in (('--find', 'desired.note.'), ('--resource', '001'),
                           ('--trace', 'desired.note.first.text'), ('--resource', 'missing'),
                           ('--trace', 'missing')):
        before, hits_before, bodies_before = invoke_references(model_files.main.__wrapped__, flag, selector)
        after, hits_after, bodies_after = invoke_references(model_files.main, flag, selector)
        assert after == before, (flag, before, after)
        assert memo_table() is None
        assert all(max(counts.values(), default=0) <= 1 for counts in bodies_after.values()), bodies_after
        assert sum(bodies_after['reference_values'].values()) == 3
        assert sum(bodies_after['_reference_inputs'].values()) == 1
        assert sum(bodies_before['reference_values'].values()) == 9
        assert sum(bodies_before['_reference_inputs'].values()) == 12
        assert (hits_before['reference_values'], hits_after['reference_values']) == (9, 8)
        assert hits_before['_parse_template'] == 13 and hits_after['_parse_template'] == 2
        assert sum(bodies_before['_parse_template'].values()) == 13
        assert sum(bodies_after['_parse_template'].values()) == 2
    print('CLI synthetic reuse: reference lookups=9->8, reference bodies=9->3 (type/name/link), '
          'producer preparation bodies=12->1, parser bodies=13->2; output/exit unchanged')

    @input_scope
    def inherited():
        memo = memo_table()
        loaded = model_files.load_model(consumer)
        result, _, bodies = invoke_references(model_files.main)
        assert result[0] == 0 and memo_table() is memo
        # The counter uses its own function identity; the production reader still shares its entry.
        assert model_files.load_model(consumer) is loaded
        assert all(max(counts.values(), default=0) <= 1 for counts in bodies.values())
        with restrict(('dev', 'team', 'kms')):
            with read_consumers({('dev', 'team', 'kms'), ('dev', 'team', 'iam')}):
                model_files.load_model(producer)
                model_templates._reference_inputs(producer)
                model_templates.reference_values(producer, '001', 'IAM.Role', 'name')
            for read in (lambda: model_files.load_model(producer),
                         lambda: model_templates._reference_inputs(producer),
                         lambda: model_templates.reference_values(producer, '001', 'IAM.Role', 'name')):
                try:
                    read()
                except ValueError as error:
                    assert 'outside selected' in str(error)
                else:
                    raise AssertionError('cached producer bypassed current IMPORT permission')
    inherited()
    assert memo_table() is None

    # Each CLI call owns a fresh snapshot, including dependency, optional and topology inputs.
    original, _, _ = invoke_references(model_files.main, '--resource', '001')
    _, producer_template, producer_parameters = model_templates.source_paths(producer)
    for file, changed in (
        (template, template.read_text(encoding='utf-8') + 'invalid\n'),
        (parameters / 'parameters.yaml', 'instances: [\n'),
        (parameters / 'bindings.json', '{'),
        (parameters / 'observed.json', '{'),
        (producer_template, producer_template.read_text(encoding='utf-8').replace('shared-role', 'changed-role')),
        (producer_parameters / 'parameters.yaml', 'instances: [\n'),
        (consumer.parents[3] / 'project.json', '{'),
    ):
        saved = file.read_bytes() if file.exists() else None
        try:
            file.write_text(changed, encoding='utf-8')
            result, _, bodies = invoke_references(model_files.main, '--resource', '001')
            assert result != original and (result[0] == 1 or 'changed-role' in result[1]), (file, result)
            assert sum(bodies['load_model'].values()) == 1, file
        finally:
            file.unlink() if saved is None else file.write_bytes(saved)
        assert invoke_references(model_files.main, '--resource', '001')[0] == original

    @input_scope
    def publication():
        original = model_files.load_model(consumer)
        saved = producer_template.read_text(encoding='utf-8')
        snapshot = model_templates.input_snapshot(consumer)
        try:
            model_templates.publish(consumer.parents[3], {
                producer_template: saved.replace('shared-role', 'published-role')}, inputs=snapshot)
            changed = model_files.load_model(consumer)
            assert changed is not original and changed.values['desired.note.first.text'] == 'published-role'
            # An external edit cannot be accepted by a publication using the pinned input snapshot.
            inputs = model_templates.input_snapshot(consumer)
            producer_template.write_text(saved, encoding='utf-8')
            try:
                model_templates.publish(consumer.parents[3], {}, inputs=inputs)
            except ValueError as error:
                assert 'changed after validation' in str(error)
            else:
                raise AssertionError('changed snapshot accepted')
        finally:
            model_templates.publish(consumer.parents[3], {producer_template: saved})
    publication()
    assert memo_table() is None

    with patch.object(sys, 'argv', ['model_files.py', str(consumer), '--find', 'desired.note.']), \
         patch.object(model_templates, 'load_expansion', side_effect=RuntimeError('injected')):
        try:
            model_files.main()
        except RuntimeError as error:
            assert str(error) == 'injected'
        else:
            raise AssertionError('unexpected exception swallowed')
    assert memo_table() is None
    try:
        with patch.object(sys, 'argv', ['model_files.py']):
            with redirect_stderr(io.StringIO()):
                model_files.main()
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError('argparse error accepted')
    assert memo_table() is None


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

