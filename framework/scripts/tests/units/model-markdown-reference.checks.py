"""Offline saved-anchor and scoped Markdown reference regression."""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from model.core import entries, validate_model_keys, validate_runtime_keys, ReferenceResolutionError
from model.format import serialize, parse
from model.identity import Resolver, parse_reference, COUNTERS, preserve_allocation, allocate
from model.sources import Scope, load_model
from model.references import usages, incoming, symbolic, diagnose
from model.projection import execution_document, reference_display


def main():
    assert __debug__, 'run without -O'
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'project.json').write_text(json.dumps({'projectName': 'synthetic', 'targets': [
            {'environment': 'dev', 'alias': 'cde', 'awsAccountId': '123456789012',
             'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}), encoding='utf-8')
        scope = Scope(root, 'dev', 'cde', 'lambda')
        scope.path.parent.mkdir(parents=True)
        anchor = 'lambda-lmda-venusinf-dev-inbound-detect'
        original = f'[lmda-venusinf-dev-inbound-detect](lambda.md#{anchor})'
        values = {COUNTERS: '{"Lambda.Function":2}',
            'desired.service.lambda.serviceId': 'lambda',
            'desired.resource.017.resourceType': 'Lambda.Function',
            'desired.resource.017.logicalId': 'Lambda_Function_002',
            'desired.resource.017.anchor': anchor,
            'desired.resource.017.resourceMode': 'IMPORT',
            'desired.row.017-008.property': 'Lambda.Function.FunctionName',
            'desired.row.017-008.value': original,
            'desired.row.017-008.comment': '合成参照',
            'observed.row.017-008.value': '`physical-function`'}
        scope.path.write_text(serialize(values), encoding='utf-8')
        before = scope.path.read_bytes()
        validate_model_keys(values)
        validate_runtime_keys(values)
        assert parse(serialize(values)).values == values
        snapshot = load_model(scope)
        assert snapshot.authoritative == values and not snapshot.warnings
        resolver = Resolver(root)
        import model.sources as sources
        with patch.object(sources, '_read_model', wraps=sources._read_model) as read:
            for text in [original, f'[other](#{anchor})', f'[other](./lambda.md#{anchor})']:
                producer, number, resource = resolver.resolve(text, scope)
                assert number == '017' and resource['logicalId'] == 'Lambda_Function_002'
            assert read.call_count == 1, read.call_count
        assert usages(snapshot)[0].producer_id == '017'
        assert incoming(snapshot, '017')[0][1].text == original
        for filename in ['', './lambda.md', 'lambda.md']:
            alternative = snapshot._replace(authoritative={**values, 'desired.row.017-008.value': f'[lmda-venusinf-dev-inbound-detect]({filename}#{anchor})'})
            assert symbolic(alternative) == symbolic(snapshot)
        assert reference_display(values, root / 'docs/designs/dev/cde/lambda.md', root) == values
        assert execution_document({'$resource': original, '$attribute': 'FunctionName'}, root, scope=scope) == 'physical-function'
        ordinary = {'Description': '[guide](guide.md#section)', 'artifact': '[file](lambda/file.json)'}
        assert execution_document(ordinary, root, scope=scope) == ordinary
        try:
            execution_document('resource://dev/cde/lambda/Lambda_Function_002', root, scope=scope)
        except ReferenceResolutionError:
            pass
        else:
            raise AssertionError('retired internal syntax emitted as an AWS value')
        from model.identity import display_anchor
        try:
            display_anchor({'logicalId': 'Lambda_Function_002'})
        except ReferenceResolutionError:
            pass
        else:
            raise AssertionError('missing saved anchor was guessed')
        # A distinct consumer resolves the producer through its saved anchor.

        other = Scope(root, 'dev', 'cde', 'consumer')
        other_values = {COUNTERS: '{"CloudTrail.Trail":1}',
            'desired.service.consumer.serviceId': 'consumer',
            'desired.resource.003.resourceType': 'CloudTrail.Trail',
            'desired.resource.003.logicalId': 'CloudTrail_Trail_001',
            'desired.resource.003.anchor': 'cloudtrail-ctrail-venusinf-dev-p4x8r2',
            'desired.resource.003.resourceMode': 'IMPORT',
            'desired.row.003-001.property': 'CloudTrail.Trail.Name',
            'desired.row.003-001.value': original, 'desired.row.003-001.comment': '合成'}
        other.path.write_text(serialize(other_values), encoding='utf-8')
        assert resolver.resolve(original, other)[1] == '017'
        from model.adapters.observed import propagate_references
        changes = {}
        key = ('dev', 'cde', 'lambda', 'Lambda_Function_002')
        propagate_references(root, {scope.path: values, other.path: other_values}, changes, {key: 'new-function'})
        assert changes[other.path]['observed.row.003-001.value'] == 'new-function'
        assert scope.path.read_bytes() == before
        from model.importing.references import Resolver as ImportResolver
        matching = ImportResolver(root, 'dev', 'cde')
        matching.consumer_scope = other
        candidate = {'scope': scope, 'anchor': anchor}
        assert matching.candidate_matches(candidate, original)
        matching.consumer_scope = scope
        assert matching.candidate_matches(candidate, f'[different label](#{anchor})')
        missing = snapshot._replace(authoritative={**values, 'desired.row.017-008.value': '[missing](lambda.md#missing)'})
        assert usages(missing)[0].producer_id is None
        assert diagnose(missing)[0]
        duplicate = {**values, 'desired.resource.019.resourceType': 'Lambda.Function',
            'desired.resource.019.logicalId': 'Lambda_Function_003', 'desired.resource.019.anchor': anchor,
            COUNTERS: '{"Lambda.Function":3}'}
        scope.path.write_text(serialize(duplicate), encoding='utf-8')
        try:
            Resolver(root).resolve(original, scope)
        except ReferenceResolutionError:
            pass
        else:
            raise AssertionError('ambiguous anchor accepted')
        scope.path.write_bytes(before)
        for text in ['[web](https://example.com/page.md#x)', '[artifact](lambda/file.json)', '[plain](readme.md)']:
            ordinary = snapshot._replace(authoritative={**values, 'desired.row.017-008.value': text})
            assert usages(ordinary) == (), text
        for filename in ['../../../escape.md', '/absolute.md']:
            try:
                parse_reference(f'[unsafe]({filename}#anchor)', scope)
            except ValueError:
                pass
            else:
                raise AssertionError('unsafe scope accepted')
        preserve_allocation(values, values)
        new = allocate({**values, 'desired.resource.021.resourceType': 'Lambda.Function'}, ['021'])
        assert new['desired.resource.021.logicalId'] == 'Lambda_Function_003'
        preserve_allocation(values, new)
        # Render actual Resource anchors, with catalog presentation isolated from naming fixtures.
        from model.render import resource_details, render_markdown
        for service, model_values in [('lambda', values), ('consumer', other_values)]:
            resources = entries(model_values, 'desired.resource.')
            kind = resources[0][1]['resourceType']
            with patch('model.render.resource_presentation', return_value=('confirmed', 'confirmed', [])), patch('model.render.naming_errors', return_value=[]):
                details, by_anchor = resource_details(model_values, root, service, [kind], resources, {})
            assert details[0][1]['anchor'] == resources[0][1]['anchor']
            displayed = {**model_values, 'display.service.title': '# Synthetic',
                         'display.resource.' + resources[0][0] + '.comment': '合成'}
            with patch('model.render.resource_table_lines', return_value=[]), patch('model.render.model_policy_views', return_value=[]):
                markdown = render_markdown(root / 'docs/designs/dev/cde' / (service + '.md'), displayed, root, [kind], details, {})
            assert '<a id="' + resources[0][1]['anchor'] + '"></a>' in markdown
        # Generate the standalone engine and resolve under isolated Python without Framework imports.
        from model.audit import generate
        program, metadata, unsupported = generate(root, 'dev', 'cde', 'lambda')
        audit = root / 'audit.py'
        audit.write_text(program, encoding='utf-8')
        import subprocess
        code = ('import runpy; n=runpy.run_path(' + repr(str(audit)) + '); '
            'm=n["engine"](n["SNAPSHOT"]); '
            'ctx=m.Context(m.ROOT, n["SNAPSHOT"]["target"], None); '
            'model=m.Model(ctx,m.ROOT/"model/dev/cde/lambda.properties"); '
            'ctx.models[model.path]=model; '
            'assert model.resources[0].reference(' + repr(original) + ').number == "017"')
        code += '\ntry:\n model.resources[0].reference("[missing](lambda.md#missing)")\nexcept m.Unresolved:\n pass\nelse:\n raise AssertionError("missing audit anchor accepted")\n'
        result = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

        print('saved Markdown references, anchors, scope, incoming, observed, JSON and allocation: PASS')


if __name__ == '__main__':
    main()
