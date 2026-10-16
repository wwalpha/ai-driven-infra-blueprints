#!/usr/bin/env python3
"""Typed Lambda links track producer authority with attribute-level resolution."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import tempfile

import model_templates as t
from model_files import load_model, read_model
from support.model_sources import write_fixture_files as save_files
from validation_cache import PassCache


def registered(root, environment, service, body, labels=None):
    path = root/'model'/environment/'team'/(service+'.properties')
    template = root/'model/templates/team'/(service+'.properties.tpl')
    directory = root/'model/parameters'/environment/'team'/service
    save_files({template: body})
    binding = {'definition': 'One', 'resources': {'resource': '041'},
               'rows': {name: f'041-{number:03d}' for number, name in
                        enumerate(t.parse_template(template)[0]['One'].rows, 1)}, 'parameters': {}}
    observed = {'version': 1, 'values': {}}
    bindings = {'instances': {'one': {**binding, 'labels': labels or {}}}}
    parameters = {'instances': {}}
    values = t.expand(template, parameters, observed, bindings, environment)[0]
    files = {path: ''.join(k+'='+v+'\n' for k, v in values.items()),

             directory/'observed.json': t.json_text(observed),
             root/'docs/designs'/environment/'team'/(service+'.md'): 'fixture\n'}
    files.update({directory/'parameters.yaml': 'instances: {}\n', directory/'bindings.json': t.json_text(bindings)})
    save_files(files)
    return path


def check(root, human):
    save_files({root/'framework/fixture.txt': 'fixture\n'})
    body = ('# model-template: 1\n# definition: One\n# resource: resource\n# row: name resource\n'
            'desired.resource.resource.resourceType=Lambda.Function\n'
            'desired.resource.resource.anchor=lambda-fixture\n'
            'desired.row.name.property=Lambda.Function.FunctionName\n'
            'desired.row.name.value=`fixture`\n# end-definition\n')
    producers = {env: registered(root, env, 'lambda', body) for env in ('preview', 'release')}
    if human:
        template = root/'model/templates/team/lambda.properties.tpl'
        save_files({template: '# model-index: 1\n# part: lambda.properties/part-001.properties\n',
                    template.parent/'lambda.properties/part-001.properties': body})
        assert template.parent/'lambda.properties/part-001.properties' in t.parse_template(template)[1]
    targets = []
    for env in producers:
        for service, kind in [('cloudtrail', 'CloudTrail.Trail'), ('eventbridge', 'Events.Rule')]:
            link = '[PENDING_DEPLOY](lambda.md#lambda-fixture)'
            consumer = ('# model-template: 1\n# definition: One\n# reference: Function {"service":"lambda","resource":"041","resourceType":"Lambda.Function"}\n# resource: resource\n# row: name resource\n# row: target resource\n'
                        f'desired.resource.resource.resourceType={kind}\n'
                        f'desired.resource.resource.anchor={service}-fixture\n'
                        f'desired.row.name.property={kind}.Name\n'
                        'desired.row.name.value=`fixture-consumer`\n'
                        f'desired.row.target.property={kind}.Target\n'
                        'desired.row.target.value=<<Function>>\n'
                        'desired.row.target.document='+t.json_text({'Target': '<<Function>>', 'Enabled': False,
                                                                  'Count': 1, 'Order': ['b', 'a']})+'\n# end-definition\n')
            targets.append(registered(root, env, service, consumer, {'Function': 'PENDING_DEPLOY'}))
    originals = {p: load_model(p).values for p in targets}
    before = {p: t.design_source_digest(p) for p in targets}
    cache = PassCache(root)
    cache_before = {p: cache.service_key((p.parent.parent.name, 'team', p.stem)) for p in targets}
    producer = producers['preview']
    directory = root/'model/parameters/preview/team/lambda'
    inputs = t.source_inputs(targets[0])
    producer_inputs = t.source_inputs(producer)
    assert producer_inputs <= inputs
    for file in sorted(producer_inputs):
            original = file.read_bytes()
            # Whitespace-only input changes retain exactly the same consumer values.
            file.write_bytes(original+b'\n')
            for path in targets:
                changed = file.is_relative_to(root/'model/templates') or path.parent.parent.name == 'preview'
                assert (t.design_source_digest(path) != before[path]) == changed
                assert (cache.service_key((path.parent.parent.name, 'team', path.stem)) != cache_before[path]) == changed
                assert load_model(path).values == originals[path]
            impact = t.affected(root, [file.relative_to(root)])
            expected = {(env, 'team', service) for env in
                        (('preview', 'release') if file.is_relative_to(root/'model/templates') else ('preview',))
                        for service in ('lambda', 'cloudtrail', 'eventbridge')}
            assert impact == expected, (file, impact, expected)
            file.write_bytes(original)
    assert all(load_model(p).values == originals[p] for p in targets)
    # A producer may link back to its consumer without value recursion.
    if human:
        template = root/'model/templates/team/lambda.properties/part-001.properties'
        text = template.read_text()
        template.write_text(text.replace('# row: name resource\n', '# row: name resource\n'
            '# reference: Rule {"service":"eventbridge","resource":"041","resourceType":"Events.Rule"}\n')
            .replace('# end-definition', 'display.resource.resource.comment=<<Rule>>\n# end-definition'))
        assert set(load_model(root/'model/preview/team/eventbridge.properties').files) <= set(t.source_inputs(producer))
        assert load_model(targets[0]).values == originals[targets[0]]
        template.write_text(text)
    source = directory/'parameters.yaml'
    original = source.read_bytes()
    source.unlink()
    try:
        load_model(targets[0])
    except ValueError as error:
        assert 'orphan' in str(error) or 'missing' in str(error) or 'missing' in str(error)
    else:
        raise AssertionError('missing producer service_source accepted')
    source.write_bytes(original)
    part = next(p for p in load_model(producer).files if p.is_relative_to(root/'model/templates') and 'anchor=lambda-fixture' in p.read_text())
    original = part.read_bytes()
    part.write_bytes(original.replace(b'Lambda.Function', b'EC2.Instance'))
    try:
        load_model(targets[0])
    except ValueError as error:
        assert 'type-mismatched' in str(error)
    else:
        raise AssertionError('broken producer anchor accepted')
    part.write_bytes(original)
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    try:
        load_model(targets[0])
    except (OSError,ValueError) as error:
        assert "missing" in str(error)
    else:
        raise AssertionError('missing producer accepted')


if __name__ == '__main__':
    for human in (False, True):
        with tempfile.TemporaryDirectory() as directory:
            check(Path(directory).resolve(), human)
    print('Lambda dependencies: PASS (YAML inputs, hash/cache/impact, scope, exact values, reciprocal links, missing rejection)')
