#!/usr/bin/env python3
"""Scoped staging retains complete auxiliary properties and transitive producer inputs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from model.sources import model_paths as model_paths
from model.sources import source_inputs as source_inputs
from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import (
    Path,
    json,
    load_model,
    reference,
    resource,
    serialize,
    setup,
    tempfile,
    write_model,
)
from sync_runtime import stage_inputs

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def staged(root, model, values, expected):
    destination = root / 'docs/designs/preview/team' / (model.stem + '.md')
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory).resolve()
        stage_inputs(stage, root, {destination: values}, [model], [], [model.stem], False)
        copied = {p.relative_to(stage) for p in (stage / 'model').rglob('*') if p.is_file()}
        assert copied == expected, (copied, expected)
        for relative in copied:
            assert (stage / relative).read_bytes() == (root / relative).read_bytes()
        assert load_model(stage / model.relative_to(root)).authoritative == load_model(model).authoritative
        assert not (stage / 'framework').exists()


@it_case
def check(root):
    setup(root, ['iam', 's3', 'ec2', 'eventbridge'], ['IAM.Role', 'S3.Bucket', 'EC2.Instance', 'Events.Rule'])
    topology = json.loads((root / 'project.json').read_text())
    topology['targets'].append({**topology['targets'][0], 'alias': 'other'})
    (root / 'project.json').write_text(json.dumps(topology))
    entrance = root / 'model/preview/team/iam.properties'
    part = entrance.with_suffix('') / 'part-001.properties'
    part.parent.mkdir(parents=True)
    entrance.write_text('# model-format: 2\n# model-index: 2\n# part: iam/part-001.properties\n')
    part.write_text(serialize(resource('041', 'IAM.Role', 'iam-one', [('RoleName', '`fixture-role`')])))
    unrelated = root / 'model/preview/other/unrelated.properties'
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text('invalid unrelated model\n')
    bucket = entrance.with_name('s3.properties')
    values = resource('041', 'S3.Bucket', 's3-one', [('BucketName', '`fixture-role`'), ('Producer', '[fixture-role](iam.md#iam-one)')])
    values.update(reference('role-name', 'desired.row.041-001.value', 'fixture-role', 'iam', '041', 'IAM.Role', prop='IAM.Role.RoleName'))
    values.update(reference('role-link', 'desired.row.041-002.value', '[fixture-role](iam.md#iam-one)', 'iam', '041', 'IAM.Role', mode='link', label='display-name'))
    write_model(bucket, values)
    stack = entrance.with_name('cloudformation-stacks.properties')
    values = {'desired.stack.001.name': 'fixture-role', 'desired.stack.001.placementName': 'fixture',
              'desired.stack.001.template': 'fixture.yaml', 'desired.stack.001.parameters': 'fixture.json',
              'desired.stack.001.deployOrder': '1', 'desired.deployment.templateKeyPrefix': 'fixture/', 'desired.deployment.templateBucket': '[fixture-role](s3.md#s3-one)'}
    values.update(reference('bucket-name', 'desired.stack.001.name', 'fixture-role', 's3', '041', 'S3.Bucket', prop='S3.Bucket.BucketName'))
    write_model(stack, values)
    instance = entrance.with_name('ec2.properties')
    values = resource('017', 'EC2.Instance', 'ec2-fixture', [('ImageId', '`ami-fixture`')])
    values['desired.resource.017.cfn-logicalId'] = 'fixture-Instance'
    write_model(instance, values)
    transitive = {p.relative_to(root) for p in (instance, stack, bucket, entrance, part)}
    staged(root, instance, load_model(instance).authoritative, transitive)
    # Ownership checking reads this independent same-target Model when stacks are selected.
    event = entrance.with_name('eventbridge.properties')
    values = resource('001', 'Events.Rule', 'eventbridge-one', [('Name', '`rule`')])
    values['desired.resource.001.cfn-logicalId'] = 'fixture-Rule'
    write_model(event, values)
    staged(root, stack, load_model(stack).authoritative, transitive | {event.relative_to(root)})
    raw = part.read_bytes()
    part.unlink()
    with tempfile.TemporaryDirectory() as directory:
        try:
            stage_inputs(Path(directory).resolve(), root,
                {root / 'docs/designs/preview/team/ec2.md': load_model(instance).authoritative}, [instance], [], ['ec2'], False)
        except (ValueError, OSError) as error:
            assert 'missing' in str(error).lower() or 'part-001.properties' in str(error), error
        else:
            raise AssertionError('missing auxiliary producer part accepted')
    part.write_bytes(raw)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
    print('Auxiliary staging: PASS (typed/transitive properties dependencies; parts; exact bytes; alias separation; missing rejection)')
