#!/usr/bin/env python3
"""Scoped staging retains authoritative auxiliary Model producer dependencies."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model_files import read_model
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.model_sources import write_model
import tempfile

import model_templates as t
from model_files import load_model
from support.model_sources import write_fixture_files as save_files
from sync_runtime import stage_inputs


def registered(root, service, kind, property_name, producer=None):
    model = root / 'model/preview/team' / (service + '.properties')
    template = root / 'model/templates/team' / (service + '.properties.tpl')
    directory = root / 'model/parameters/preview/team' / service
    body = ['# model-template: 1', '# definition: One', '# resource: resource',
            '# row: name resource', 'desired.resource.resource.resourceType=' + kind,
            'desired.resource.resource.anchor=' + service + '-one',
            'desired.row.name.property=' + property_name, 'desired.row.name.value=`fixture-one`']
    if producer:
        body += ['# reference: ProducerName ' + t.json_text({**producer, 'format': 'name'}),
                 '# reference: Producer ' + t.json_text(producer), '# row: target resource',
                 'desired.row.target.property=' + kind + '.Producer', 'desired.row.target.value=<<Producer>>']
        body[body.index('desired.row.name.value=`fixture-one`')] = 'desired.row.name.value=`<<ProducerName>>`'
    body += ['# end-definition']
    save_files({template: '\n'.join(body) + '\n'})
    binding = {'definition': 'One', 'resources': {'resource': '041'}, 'rows': {'name': '041-001'},
               'parameters': {}}
    if producer:
        binding['rows']['target'] = '041-002'
    bindings = {'instances': {'one': {**binding, 'labels': {}}}}
    observed = {'version': 1, 'values': {}}
    parameters = {'instances': {}}
    values = t.expand(template, parameters, observed, bindings, 'preview')[0]
    files = {model: ''.join(k + '=' + v + '\n' for k, v in values.items()),

             directory / 'observed.json': t.json_text(observed)}
    files.update({directory / 'parameters.yaml': 'instances: {}\n', directory / 'bindings.json': t.json_text(bindings)})
    save_files(files)
    return model


def staged(root, model, values):
    destination = root / 'docs/designs/preview/team' / (model.stem + '.md')
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory).resolve()
        stage_inputs(stage, root, {destination: values}, [model], [], [model.stem], False)
        copied = {p.relative_to(stage) for p in (stage / 'model/parameters').rglob('*') if p.is_file()}
        expected = {p.relative_to(root) for p in t.source_inputs(model) if p.is_relative_to(root / 'model/parameters')}
        auxiliary = root / 'model/preview/team/cloudformation-stacks.properties'
        if any(k.endswith('.cfn-logicalId') for k in values):
            expected.update(p.relative_to(root) for p in t.source_inputs(auxiliary) if p.is_relative_to(root / 'model/parameters'))
        if any(k.startswith('desired.artifact.') for k in values):
            expected.update(p.relative_to(root) for p in t.source_inputs(root / 'model/preview/team/s3.properties') if p.is_relative_to(root / 'model/parameters'))
        if model.stem == 'cloudformation-stacks':
            expected.update(p.relative_to(root) for model in t.model_paths(root, 'preview', 'team')
                            for p in t.source_inputs(model) if p.is_relative_to(root / 'model/parameters'))
            producer = root / 'model/preview/team/eventbridge.properties'
            assert load_model(stage / producer.relative_to(root)).values == load_model(producer).values
        assert copied == expected, (copied, expected)
        for path in copied:
            assert (stage / path).read_bytes() == (root / path).read_bytes()
        assert load_model(stage / auxiliary.relative_to(root)).values == load_model(auxiliary).values


@it_case
def check(root):
    save_files({root / 'framework/fixture.txt': 'fixture\n',
                root / 'model/preview/team/iam.properties': '# model-index: 1\n# part: iam/part-001.properties\n',
                root / 'model/preview/team/iam/part-001.properties':
                    'desired.resource.041.resourceType=IAM.Role\n'
                    'desired.resource.041.anchor=iam-one\n'
                    'desired.row.041-001.property=IAM.Role.RoleName\n'
                    'desired.row.041-001.value=`fixture-role`\n',
                root / 'model/preview/other/unrelated.properties': 'invalid unrelated model\n'})
    write_model(root / 'model/preview/team/iam.properties', read_model(root / 'model/preview/team/iam.properties'))
    entrance = root / 'model/preview/team/iam.properties'
    content = read_model(entrance)
    save_files({entrance: '# model-index: 1\n# part: iam/part-001.properties\n', entrance.parent/'iam/part-001.properties': content})
    bucket = registered(root, 's3', 'S3.Bucket', 'S3.Bucket.BucketName',
                        {'service': 'iam', 'resource': '041', 'resourceType': 'IAM.Role'})
    stack = registered(root, 'cloudformation-stacks', 'CloudFormation.Stack', 'CloudFormation.Stack.StackName',
                       {'service': 's3', 'resource': '041', 'resourceType': 'S3.Bucket'})
    instance = root / 'model/preview/team/ec2.properties'
    write_model(instance, 'desired.resource.017.resourceType=EC2.Instance\ndesired.resource.017.anchor=ec2-fixture\ndesired.resource.017.cfn-logicalId=fixture-Instance\n')
    staged(root, instance, load_model(instance).values)
    # This service has no Markdown link from stacks but is read by ownership validation.
    write_model(root / 'model/preview/team/eventbridge.properties',
                'desired.resource.001.resourceType=Events.Rule\n'
                'desired.resource.001.anchor=eventbridge-one\n'
                'desired.resource.001.cfn-logicalId=fixture-Rule\n')
    # Selecting stacks exercises both its direct dependency and the supplemental bucket path.
    staged(root, stack, {**load_model(stack).values, 'desired.artifact.template.path': 'fixture.yaml'})
    (root / 'model/parameters/preview/team/iam/parameters.yaml').unlink()
    with tempfile.TemporaryDirectory() as directory:
        try:
            stage_inputs(Path(directory).resolve(), root,
                {root / 'docs/designs/preview/team/ec2.md': load_model(instance).values},
                [instance], [], ['ec2'], False)
        except (ValueError, OSError) as error:
            assert 'missing' in str(error).lower() or 'missing' in str(error), error
        else:
            raise AssertionError('missing auxiliary producer accepted')



if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
    print('Auxiliary Model producer staging: PASS (typed and transitive dependencies, parts, YAML, exact bytes, scoped selection, missing rejection)')
