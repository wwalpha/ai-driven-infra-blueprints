#!/usr/bin/env python3
"""Attribute dependency regressions; isolated registered sources, no AWS."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import tempfile

import model_templates as t
from model_files import load_model
from model_parameter_inputs import parameter_text
from support.model_sources import write_fixture_files as save_files
from validation_cache import input_scope


KINDS = {'s3': ('S3.Bucket', 'BucketName'), 'cloudtrail': ('CloudTrail.Trail', 'TrailName'),
         'lambda': ('Lambda.Function', 'FunctionName'), 'eventbridge': ('Events.Rule', 'Name')}


def fixture(root, service, other=None, *, derived=False):
    kind, property_name = KINDS[service]
    path = root/'model/preview/team'/(service+'.properties')
    template = root/'model/templates/team'/(service+'.properties.tpl')
    directory = root/'model/parameters/preview/team'/service
    declaration = {'type': 'string', 'description': '独立した名前', 'required': True, 'format': 'literal'}
    lines = ['# model-template: 1', '# definition: Main',
             '# parameter: Name '+(t.json_text(declaration))]
    if other:
        reference = {'service': other, 'resource': '001', 'resourceType': KINDS[other][0]}
        lines += ['# reference: Other '+t.json_text(reference),
                  '# reference: OtherName '+t.json_text({**reference, 'format': 'name'})]
    lines += ['# resource: main', '# row: name main',
              'desired.resource.main.resourceType='+kind,
              'desired.resource.main.anchor='+service+'-original',
              'desired.row.name.property='+kind+'.'+property_name,
              'desired.row.name.value='+('`<<OtherName>>`' if derived else '<<Name>>'),
              'desired.note.input.text=<<Name>>']
    if other:
        lines += ['desired.note.link.text=<<Other>>',
                  'desired.note.config.document={"name":"<<OtherName>>","count":2,"enabled":false,"items":["a","b"]}']
    lines += ['# end-definition', '']
    instance = {'id': 'main', 'definition': 'Main', 'resources': {'main': '001'},
                'rows': {'name': '001-001'}, 'parameters': {'Name': '`'+service+'-original`'}}
    binding = {'instances': {'main': {**{k: v for k, v in instance.items() if k != 'id'},
                                     'parameters': {}, 'labels': {}}}}
    human = {'instances': {'main': {'parameters': {'Name': service+'-original'}}}}
    values = {'desired.resource.001.resourceType': kind, 'desired.resource.001.anchor': service+'-original',
              'desired.row.001-001.property': kind+'.'+property_name,
              'desired.row.001-001.value': '`'+service+'-original`'}
    save_files({template: '\n'.join(lines), path: ''.join(k+'='+v+'\n' for k, v in values.items()),
        directory/'observed.json': t.json_text({'version': 1, 'values': {}})})
    save_files({directory/'bindings.json': t.json_text(binding),
                directory/'parameters.yaml': parameter_text(human, t.parse_template(template)[0], binding)})
    return path, directory, template


def rejected(root, action, phrase):
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    try:
        action()
    except (ValueError, OSError) as error:
        assert phrase in str(error), (phrase, str(error))
    else:
        raise AssertionError('invalid reference accepted: '+phrase)
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}


def check_pair(root, first, second):
    consumer, _, _ = fixture(root, first, second)
    producer, directory, template = fixture(root, second, first)
    loaded = load_model(consumer)
    assert loaded.values['desired.note.link.text'] == f'[{second}-original]({second}.md#{second}-original)'
    config = t.json_read(loaded.values['desired.note.config.document'])
    assert config == {'name': second+'-original', 'count': 2, 'enabled': False, 'items': ['a', 'b']}
    assert type(config['count']) is int and type(config['enabled']) is bool
    assert load_model(producer).values['desired.row.001-001.value'] == '`'+second+'-original`'
    assert directory/'parameters.yaml' in loaded.files and template in loaded.files
    digest = t.design_source_digest(consumer)
    source = directory/'parameters.yaml'; original = source.read_bytes()
    source.write_bytes(original.replace((second+'-original').encode(), (second+'-changed').encode()))
    assert t.design_source_digest(consumer) != digest
    assert t.json_read(load_model(consumer).values['desired.note.config.document'])['name'] == second+'-changed'
    assert ('preview', 'team', first) in t.affected(root, [source.relative_to(root)])
    trace = t.load_expansion(consumer).provenance
    assert trace['desired.note.config.document']['references']['OtherName']['service'] == second
    source.write_bytes(original)
    assert t.design_source_digest(consumer) == digest and load_model(consumer).values == loaded.values
    @input_scope
    def snapshot():
        pinned = load_model(consumer)
        source.write_bytes(original.replace((second+'-original').encode(), (second+'-changed').encode()))
        assert load_model(consumer) == pinned and pinned.files[source].encode() == original
    snapshot(); source.write_bytes(original)
    binding_path = directory/'bindings.json'; binding_original = binding_path.read_bytes()
    binding = t.json_read(binding_original.decode())
    binding['instances']['duplicate'] = copy.deepcopy(binding['instances']['main'])
    binding_path.write_text(t.json_text(binding), encoding='utf-8')
    source.write_text(original.decode()+'  duplicate:\n    parameters:\n      Name: duplicate\n', encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'duplicate fixed Model identity')
    binding_path.write_bytes(binding_original); source.write_bytes(original)
    source.write_text('instances:\n  main:\n    parameters:\n      Name: 17\n', encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'parameter type mismatch')
    source.write_bytes(original)
    (directory/'parameters.json').write_text('{}', encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'unsupported JSON')
    (directory/'parameters.json').unlink()
    original_template = template.read_bytes()
    template.write_bytes(original_template.replace(b'desired.row.name.value=<<Name>>', b'desired.row.name.value=`<<OtherName>>`'))
    _, _, first_template = fixture(root, first, second, derived=True)
    rejected(root, lambda: load_model(consumer), 'cyclic attribute reference:')
    try:
        load_model(consumer)
    except ValueError as error:
        assert str(consumer) in str(error) and str(producer) in str(error) and '.value' in str(error)
    template.write_bytes(original_template)


def check_fixed_label(root):
    consumer, directory, template = fixture(root, 's3', 'cloudtrail')
    producer, producer_directory, producer_template = fixture(root, 'cloudtrail', 's3')
    content = template.read_text(encoding='utf-8')
    template.write_text('\n'.join(line for line in content.splitlines()
        if not line.startswith(('# reference: OtherName ', 'desired.note.config.'))) + '\n', encoding='utf-8')
    content = producer_template.read_text(encoding='utf-8')
    producer_template.write_text(content.replace('CloudTrail.Trail.TrailName', 'CloudTrail.Trail.Tags[].Value')
        .replace('desired.row.name.value=<<Name>>', 'desired.row.name.value=<<Other>>'), encoding='utf-8')
    binding_path = directory/'bindings.json'
    binding = t.json_read(binding_path.read_text(encoding='utf-8'))
    binding['instances']['main']['labels'] = {'Other': 'fixed-label'}
    binding_path.write_text(t.json_text(binding), encoding='utf-8')
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    loaded = load_model(consumer)
    assert loaded.values['desired.note.link.text'] == '[fixed-label](cloudtrail.md#cloudtrail-original)'
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    digest = t.design_source_digest(consumer)
    inputs = producer_directory/'parameters.yaml'; original = inputs.read_bytes()
    inputs.write_bytes(original.replace(b'cloudtrail-original', b'cloudtrail-changed'))
    assert load_model(consumer).values == loaded.values
    assert t.design_source_digest(consumer) != digest
    assert ('preview', 'team', 's3') in t.affected(root, [inputs.relative_to(root)])
    trace = t.load_expansion(consumer).provenance
    assert trace['desired.note.link.text']['references']['Other']['service'] == 'cloudtrail'
    inputs.write_bytes(original)
    binding['instances']['main']['labels'] = {}
    binding_path.write_text(t.json_text(binding), encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'reference producer requires exactly one name')
    binding['instances']['main']['labels'] = {'Other': '[invalid]'}
    binding_path.write_text(t.json_text(binding), encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'invalid reference label')
    binding['instances']['main']['labels'] = {'Other': 'fixed-label'}
    binding_path.write_text(t.json_text(binding), encoding='utf-8')
    content = template.read_bytes()
    template.write_bytes(content.replace(b'"resource":"001"', b'"resource":"999"'))
    rejected(root, lambda: load_model(consumer), 'ambiguous/type-mismatched')
    template.write_bytes(content.replace(b'"resourceType":"CloudTrail.Trail"', b'"resourceType":"IAM.Role"'))
    rejected(root, lambda: load_model(consumer), 'ambiguous/type-mismatched')
    template.write_bytes(content)


def fixture_stack(root):
    template = root/'model/templates/team/cloudformation-stacks.properties.tpl'
    path = root/'model/preview/team/cloudformation-stacks.properties'
    directory = root/'model/parameters/preview/team/cloudformation-stacks'
    declaration = t.json_text({'type': 'string', 'description': 'Stack名の独立suffix', 'required': True})
    values = {'desired.stack.001.name': 'cfn-stack-app-preview-original', 'desired.stack.001.template': 'network.yaml',
              'desired.stack.001.parameters': 'network.json', 'desired.stack.001.deployOrder': '10',
              'display.stack.001.comment': '-original'}
    text = '# model-template: 1\n# definition: Stack\n# parameter: Suffix '+declaration+'\n'
    text += ''.join(key+'='+('cfn-stack-app-preview<<Suffix>>' if key.endswith('.name') else '<<Suffix>>' if key.endswith('.comment') else value)+'\n' for key, value in values.items())
    text += '# end-definition\n'
    instance = {'id': 'stack', 'definition': 'Stack', 'resources': {}, 'rows': {}, 'parameters': {'Suffix': '-original'}}
    output = {template: text, path: ''.join(k+'='+v+'\n' for k, v in values.items()),

              directory/'observed.json': t.json_text({'version': 1, 'values': {}})}
    output[directory/'bindings.json'] = t.json_text({'instances': {'stack': {**{k: v for k, v in instance.items() if k != 'id'}, 'parameters': {}, 'labels': {}}}, 'stacks': {'001': values['desired.stack.001.name']}})
    output[directory/'parameters.yaml'] = 'instances:\n  stack:\n    parameters:\n      Suffix: -original\n'
    save_files(output)
    return path, directory, template


def check_stack(root):
    consumer, _, template = fixture(root, 's3')
    producer, directory, producer_template = fixture_stack(root)
    content = template.read_text(encoding='utf-8').replace('# definition: Main', '# definition: Main\n# reference: StackName '+t.json_text({'service': 'cloudformation-stacks', 'resource': '001', 'resourceType': 'CloudFormation.Stack', 'format': 'name'}))
    content = content.replace('# end-definition', 'desired.note.permission.document={"Resource":"arn:aws:cloudformation:ap-northeast-1:123456789012:stack/<<StackName>>/*"}\n# end-definition')
    template.write_text(content, encoding='utf-8')
    loaded = load_model(consumer)
    assert t.json_read(loaded.values['desired.note.permission.document'])['Resource'].endswith('/cfn-stack-app-preview-original/*')
    digest = t.design_source_digest(consumer)
    inputs = directory/'parameters.yaml'; original = inputs.read_bytes()
    inputs.write_bytes(original.replace(b'-original', b'-changed'))
    assert t.json_read(load_model(consumer).values['desired.note.permission.document'])['Resource'].endswith('/cfn-stack-app-preview-changed/*')
    assert t.design_source_digest(consumer) != digest
    assert ('preview', 'team', 's3') in t.affected(root, [inputs.relative_to(root)])
    trace = t.load_expansion(consumer).provenance['desired.note.permission.document']
    assert trace['references']['StackName']['service'] == 'cloudformation-stacks'
    inputs.write_bytes(original)
    @input_scope
    def snapshot():
        pinned = load_model(consumer)
        inputs.write_bytes(original.replace(b'-original', b'-changed'))
        assert load_model(consumer) == pinned and pinned.files[inputs].encode() == original
    snapshot(); inputs.write_bytes(original)
    template.write_text(content.replace('"resource":"001"', '"resource":"999"'), encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'ambiguous/type-mismatched')
    template.write_text(content.replace('"resourceType":"CloudFormation.Stack"', '"resourceType":"IAM.Role"'), encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'ambiguous/type-mismatched')
    template.write_text(content.replace(',"format":"name"', ''), encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'stack reference requires format:name')
    template.write_text(content, encoding='utf-8')
    producer_content = producer_template.read_text(encoding='utf-8')
    producer_template.write_text(producer_content.replace('desired.stack.001.template=network.yaml\n', ''), encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'stack reference target')
    producer_template.write_text(producer_content, encoding='utf-8')
    bindings = directory/'bindings.json'; raw = bindings.read_bytes()
    bindings = directory/'bindings.json'; raw = bindings.read_bytes()
    binding = t.json_read(raw.decode()); binding['stacks']['999'] = 'cfn-other'
    binding = t.json_read(raw.decode()); binding['stacks']['999'] = 'cfn-other'
    bindings.write_text(t.json_text(binding), encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'fixed stack bindings')
    bindings.write_bytes(raw)
    producer_template.write_text(producer_content.replace('# definition: Stack', '# definition: Stack\n# reference: BucketName '+t.json_text({'service': 's3', 'resource': '001', 'resourceType': 'S3.Bucket', 'format': 'name'})).replace('cfn-stack-app-preview<<Suffix>>', '<<BucketName>>'), encoding='utf-8')
    template.write_text(content.replace('desired.row.name.value=<<Name>>', 'desired.row.name.value=`<<StackName>>`'), encoding='utf-8')
    rejected(root, lambda: load_model(consumer), 'cyclic attribute reference:')
    producer_template.write_text(producer_content, encoding='utf-8'); template.write_text(content, encoding='utf-8')
    producer_template.write_text(producer_content, encoding='utf-8'); template.write_text(content, encoding='utf-8')
    inputs.unlink()
    rejected(root, lambda: load_model(consumer), 'parameters.yaml')
    inputs.write_bytes(original)


def check_preparation_cache(root):
    template = root / 'model/templates/team/iam.properties.tpl'
    source = root / 'model/parameters/preview/team/iam'
    path = root / 'model/preview/team/iam.properties'
    text = ('# model-template: 1\n# definition: Role\n'
            '# parameter: RoleName {"type":"string","description":"独立したRole名","required":true,"format":"literal"}\n'
            '# resource: role\n# row: name role\n'
            'desired.resource.role.resourceType=IAM.Role\n'
            'desired.resource.role.anchor=iam-<<Id_role>>\n'
            'desired.row.name.property=IAM.Role.RoleName\n'
            'desired.row.name.value=<<RoleName>>\n# end-definition\n')
    values, binding = {}, {'instances': {}}
    for identity, rid in [('first', '001'), ('second', '002')]:
        values.update({f'desired.resource.{rid}.resourceType': 'IAM.Role',
                       f'desired.resource.{rid}.anchor': 'iam-' + rid,
                       f'desired.row.{rid}-001.property': 'IAM.Role.RoleName',
                       f'desired.row.{rid}-001.value': '`' + identity + '`'})
        binding['instances'][identity] = {'definition': 'Role', 'resources': {'role': rid},
            'rows': {'name': rid + '-001'}, 'parameters': {}, 'labels': {}}
    save_files({template: text, path: ''.join(k + '=' + v + '\n' for k, v in values.items()),

        source / 'parameters.yaml': 'instances:\n  first:\n    parameters:\n      RoleName: first\n  second:\n    parameters:\n      RoleName: second\n',
        source / 'bindings.json': t.json_text(binding), source / 'observed.json': t.json_text({'version': 1, 'values': {}})})
    from unittest.mock import patch
    inputs = root / 'model/parameters/preview/team/iam/parameters.yaml'
    original = inputs.read_bytes()
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    @input_scope
    def snapshot():
        with patch.object(t, 'parse_template', wraps=t.parse_template) as parsed:
            first = t.reference_values(path, '001', 'IAM.Role', 'name')
            assert first.values['desired.row.001-001.value'] == '`first`'
            inputs.write_bytes(original.replace(b'RoleName: second', b'RoleName: changed'))
            second = t.reference_values(path, '002', 'IAM.Role', 'name')
            assert second.values['desired.row.002-001.value'] == '`second`'
            assert parsed.call_count == 1
            assert second.files[inputs].encode() == original
    try:
        snapshot()
        changed = t.reference_values(path, '002', 'IAM.Role', 'name')
        assert changed.values['desired.row.002-001.value'] == '`changed`'
        inputs.unlink()
        rejected(root, lambda: t.reference_values(path, '001', 'IAM.Role', 'name'), 'parameters.yaml')
    finally:
        inputs.write_bytes(original)
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}


def check():
    with tempfile.TemporaryDirectory() as directory:
        check_preparation_cache(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        check_stack(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        check_fixed_label(Path(directory))
    for pair in [('s3', 'cloudtrail'), ('lambda', 'eventbridge')]:
        with tempfile.TemporaryDirectory() as directory:
            check_pair(Path(directory), *pair)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        consumer, _, template = fixture(root, 's3', 'cloudtrail')
        producer, _, _ = fixture(root, 'cloudtrail')
        assert t.json_read(load_model(consumer).values['desired.note.config.document'])['name'] == 'cloudtrail-original'
        before = template.read_bytes()
        template.write_bytes(before.replace(b'"resource":"001"', b'"resource":"999"'))
        rejected(root, lambda: load_model(consumer), 'ambiguous/type-mismatched')
        template.write_bytes(before.replace(b'"resourceType":"CloudTrail.Trail"', b'"resourceType":"IAM.Role"'))
        rejected(root, lambda: load_model(consumer), 'ambiguous/type-mismatched')
    print('Attribute references: PASS (one-way, reciprocal services, true attribute cycle with route, strict rejection/write=0, YAML inputs, producer change/hash/trace/impact, immutable snapshot)')


if __name__ == '__main__':
    check()
