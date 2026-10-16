#!/usr/bin/env python3
"""Fixed YAML S3 anchors retain strict IDs, names, links and legacy validation."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from support.model_sources import write_model
from model_files import read_model
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
import copy
from contextlib import redirect_stdout
import io
import shutil
import tempfile
import model_templates as t
from model_files import load_model
from model_design import markdown_for
from model_references import bound_resource_anchors
from model_parameter_inputs import parameter_text
from support.model_sources import write_fixture_files as save_files
import sync_runtime

ROOT = Path(__file__).resolve().parents[4]


def rejected(call, phrase):
    try:
        call()
    except (ValueError, OSError) as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid input accepted: ' + phrase)


def check(root):
    shutil.copytree(ROOT / 'framework', root / 'framework')
    save_files({root / 'project.json': t.json_text({'projectName': 'anchor-fixture', 'targets': [{
        'environment': 'preview', 'alias': 'other', 'awsAccountId': '210987654321',
        'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}, {
        'environment': 'preview', 'alias': 'team', 'awsAccountId': '123456789012',
        'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n',
        root / 'tasks/active.md': '## Task contract\n- Task type: `migration`\n## Validation scope\n- `preview/team/s3`\n## Allowed paths\n- `model/**`\n- `model/parameters/**`\n- `model/templates/**`\n- `docs/designs/**`\n'})
    template = root / 'model/templates/team/s3.properties.tpl'
    text = '\n'.join(['# model-template: 1', '# definition: Bucket',
        '# parameter: BucketName ' + t.json_text({'type': 'string', 'description': 'bucketの名前', 'required': True, 'format': 'literal'}),
        '# internal: Anchor string', '# resource: bucket', '# row: name bucket', '# row: region bucket',
        'desired.resource.bucket.resourceType=S3.Bucket', 'desired.resource.bucket.resourceMode=IMPORT',
        'desired.resource.bucket.anchor=<<Anchor>>', 'desired.resource.bucket.logicalId=stable-archive',
        'desired.row.name.property=S3.Bucket.BucketName', 'desired.row.name.value=<<BucketName>>', 'desired.row.name.comment=bucketの名前',
        'desired.row.region.property=S3.Bucket.Region', 'desired.row.region.value=`ap-northeast-1`', 'desired.row.region.comment=配置region',
        'display.resource.bucket.comment=既存bucket', '# end-definition',
        '# definition: Service', 'desired.service.s3.serviceId=s3',
        'desired.service.s3.ownedCatalogResourceTypes=S3.Bucket', 'display.service.title=# Amazon S3 詳細設計', '# end-definition', ''])
    bindings = {'instances': {'archive': {'definition': 'Bucket', 'resources': {'bucket': '003'},
        'rows': {'name': '003-001', 'region': '003-002'}, 'parameters': {'Anchor': 's3-archive-original'}, 'labels': {}},
        'service': {'definition': 'Service', 'resources': {}, 'rows': {}, 'parameters': {}, 'labels': {}}}}
    human = {'instances': {'archive': {'parameters': {'BucketName': 'archive-original'}}}}
    observed = {'version': 1, 'values': {}}
    save_files({template: text})
    values = t.expand(template, human, observed, bindings, 'preview')[0]
    path = root / 'model/preview/team/s3.properties'
    directory = root / 'model/parameters/preview/team/s3'
    save_files({path: ''.join(k + '=' + v + '\n' for k, v in values.items()),

        directory / 'parameters.yaml': parameter_text(human, t.parse_template(template)[0], bindings),
        directory / 'bindings.json': t.json_text(bindings), directory / 'observed.json': t.json_text(observed)})
    view = root / 'docs/designs/preview/team/s3.md'
    with redirect_stdout(io.StringIO()):
        sync_runtime.sync(root, True, 'preview', 'team', services=['s3'])
    assert bound_resource_anchors(path) == {('S3.Bucket', 'stable-archive'): 's3-archive-original'}
    # A real external typed consumer resolves this unchanged anchor after the rename.
    reference = root / 'model/templates/team/cloudtrail.properties.tpl'
    save_files({reference: '# model-template: 1\n# definition: Link\n# reference: Bucket ' + t.json_text({
        'service': 's3', 'resource': '003', 'resourceType': 'S3.Bucket'}) + '\n# resource: job\n# row: link job\n'
        'desired.resource.job.resourceType=CloudTrail.Trail\ndesired.resource.job.anchor=cloudtrail-job\n'
        'desired.row.link.property=CloudTrail.Trail.S3BucketName\ndesired.row.link.value=<<Bucket>>\n# end-definition\n'})
    consumer = {'instances': {'job': {'definition': 'Link', 'resources': {'job': '087'},
        'rows': {'link': '087-001'}, 'parameters': {}, 'labels': {}}}}
    human['instances']['archive']['parameters']['BucketName'] = 'archive-renamed'
    t.save_parameters(path, human)
    updated = load_model(path).values
    assert updated['desired.resource.003.anchor'] == values['desired.resource.003.anchor']
    assert updated['desired.resource.003.logicalId'] == 'stable-archive'
    assert {k for k in updated if k.startswith('desired.row.')} == {k for k in values if k.startswith('desired.row.')}
    linked = t.expand(reference, {'instances': {}}, observed, consumer, 'preview')[0]['desired.row.087-001.value']
    assert linked == '[archive-renamed](s3.md#s3-archive-original)'
    with redirect_stdout(io.StringIO()):
        sync_runtime.sync(root, True, 'preview', 'team', services=['s3'])
        sync_runtime.sync(root, False, 'preview', 'team', services=['s3'])
    assert '### S3.Bucket: archive-renamed' in view.read_text(encoding='utf-8')
    assert '<a id="s3-archive-original"></a>' in view.read_text(encoding='utf-8')
    wrong = dict(updated, **{'desired.resource.003.anchor': 's3-other'})
    rejected(lambda: markdown_for(view, wrong, root), 'anchor must be unique')
    collision = copy.deepcopy(bindings)
    collision['instances']['archive']['rows']['region'] = '003-001'
    rejected(lambda: t.expand(template, human, observed, collision, 'preview'), 'duplicate')
    yaml_path = directory/'parameters.yaml'; original_yaml = yaml_path.read_bytes()
    yaml_path.write_text('instances: [')
    rejected(lambda: bound_resource_anchors(path), 'invalid')
    yaml_path.write_bytes(original_yaml)
    invalid = copy.deepcopy(bindings)
    invalid['instances']['archive']['parameters']['Anchor'] = 's3-../unsafe'
    (directory / 'bindings.json').write_text(t.json_text(invalid), encoding='utf-8')
    rejected(lambda: markdown_for(view, load_model(path).values, root), 'invalid bound resource anchor')
    (directory / 'bindings.json').write_text(t.json_text(bindings), encoding='utf-8')
    (directory / 'parameters.yaml').write_text('instances: {}\n', encoding='utf-8')
    rejected(lambda: bound_resource_anchors(path), 'input-bearing instances require YAML')
    (directory / 'parameters.yaml').write_text(parameter_text(human, t.parse_template(template)[0], bindings), encoding='utf-8')
    (directory/'parameters.yaml').unlink()
    rejected(lambda: markdown_for(view, updated, root), 'missing')
    print('Fixed S3 bindings: PASS (rename/sync; names/links/IDs; strict authority; legacy anchors)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
