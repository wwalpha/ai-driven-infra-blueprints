#!/usr/bin/env python3
"""Stack name edits keep fixed placements and their Resource mappings."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from support.it_case_receipt import it_case
import io
import json
import tempfile
from contextlib import redirect_stdout
import pytest
from support.model_sources import write_model
from support.it_workspace import copy_framework
from support.model_design_fixtures import model
from model.core import stack_model
from model.sources import load_model, design_source_digest
from model.format import serialize
from model.operations import CandidateReads
from model.sources import FileReads
from model.projection import bound_stack_names
from model.render import markdown_for
from model.adapters.observed import validate_mapping_targets, mappings, destroy_plan
import sync_runtime


@it_case
def check(root):
    copy_framework(root / 'framework')
    (root / 'project.json').write_text(json.dumps({'projectName': 'app', 'targets': [
        {'environment': 'preview', 'alias': alias, 'awsAccountId': account, 'awsRegion': 'ap-northeast-1',
         'iacEngine': 'cloudformation'} for alias, account in [('other', '210987654321'), ('team', '123456789012')]]}) + '\n')
    task = root / 'tasks/active.md'
    task.parent.mkdir()
    task.write_text('## Task contract\n- Task type: `migration`\n- Task status: `running`\n'
        '## Validation scope\n- `preview/team/vpc`\n- `preview/team/cloudformation-stacks`\n'
        '## Modified files\n- `tasks/active.md`\n## Allowed paths\n- `tasks/active.md`\n- `model/**`\n- `docs/designs/**`\n')
    path = root / 'model/preview/team/cloudformation-stacks.properties'
    values = {'display.service.title': '# CloudFormation Stacks 詳細設計', 'desired.deployment.maxConcurrentStacks': '2'}
    for rid, purpose in [('017', 'network'), ('083', 'empty')]:
        name = 'cfn-stack-app-preview-' + purpose + '-original'
        values.update({f'desired.stack.{rid}.name': name, f'desired.stack.{rid}.placementName': name,
            f'desired.stack.{rid}.template': purpose + '.yaml', f'desired.stack.{rid}.parameters': purpose + '.json',
            f'desired.stack.{rid}.deployOrder': '10', f'display.stack.{rid}.comment': '配置注記 ' + purpose})
    write_model(path, values)
    fixed = values['desired.stack.017.placementName']
    vpc = model('vpc', 'EC2.VPC', 'vpc-app-preview-main', [('Name', '`vpc-app-preview-main`', '名前'),
        ('VpcId', 'resource://preview/team/vpc/EC2_VPC_001', '識別子'), ('CidrBlock', '`10.10.0.0/24`', 'アドレス範囲')], 'PrimaryVpc')
    vpc = {key.replace('resource.001.', 'resource.027.').replace('row.001-', 'row.027-'): value for key, value in vpc.items()}
    vpc.update({'desired.resource.027.cfn-logicalId': fixed + '-PrimaryVpc', 'desired.resource.027.resourceMode': 'CREATE',
                'observed.row.027-002.value': '`vpc-' + '1' * 17 + '`'})
    vpc_path = path.with_name('vpc.properties')
    write_model(vpc_path, vpc)
    expected_vpc = load_model(vpc_path).authoritative
    document = {'Resources': {'PrimaryVpc': {'Type': 'AWS::EC2::VPC'}}, 'Outputs': {'VpcId': {'Value': {'Ref': 'PrimaryVpc'}}}}
    assert sync_runtime.sync(root, True, 'preview', 'team', services=['vpc', 'cloudformation-stacks']) == 0
    validate_mapping_targets(root, 'preview', 'team', load_model(path).values)
    unit = dict(dict(stack_model(values)[1])['017'])
    assert mappings(root, 'preview', 'team', {fixed: (document, {})}, [unit])[1][fixed]['PrimaryVpc'][1] == '027'
    assert destroy_plan(root, 'preview', 'team', [fixed], check_scope=False)['owners'][fixed][0]['resource'] == '027'
    vpc_bytes = {p: p.read_bytes() for p in load_model(vpc_path).files}
    for suffix in ('-changed', '', '-second', '-MiX--'):
        updated = dict(values)
        for rid, purpose in [('017', 'network'), ('083', 'empty')]:
            updated[f'desired.stack.{rid}.name'] = 'cfn-stack-app-preview-' + purpose + suffix
        write_model(path, updated)
        current = load_model(path)
        assert current.values['desired.stack.017.name'] == 'cfn-stack-app-preview-network' + suffix
        assert current.authoritative['desired.stack.017.placementName'] == fixed
        assert bound_stack_names(path)[fixed] == current.values['desired.stack.017.name']
        validate_mapping_targets(root, 'preview', 'team', current.values)
        assert sync_runtime.sync(root, True, 'preview', 'team', services=['vpc', 'cloudformation-stacks']) == 0
        assert load_model(vpc_path).authoritative == expected_vpc and all(p.read_bytes() == raw for p, raw in vpc_bytes.items())
        changed_unit = dict(dict(stack_model(current.values)[1])['017'])
        for analyze in (lambda: mappings(root, 'preview', 'team', {changed_unit['name']: (document, {})}, [changed_unit]),
                        lambda: destroy_plan(root, 'preview', 'team', [changed_unit['name']], False)):
            with pytest.raises(ValueError, match='explicit placement reconciliation'):
                analyze()
        assert destroy_plan(root, 'preview', 'team', [fixed], False)['owners'][fixed][0]['resource'] == '027'
        baseline = {p: p.read_bytes() for base in ('model', 'docs/designs') for p in (root / base).rglob('*') if p.is_file()}
        write_model(path, updated)
        assert sync_runtime.sync(root, True, 'preview', 'team', services=['vpc', 'cloudformation-stacks']) == 0
        assert all(p.read_bytes() == raw for p, raw in baseline.items())
    original = path.read_bytes()
    canonical, placements, digest = current.authoritative, bound_stack_names(path), design_source_digest(path)
    path.write_text(serialize(dict(reversed(list(canonical.items())))))
    assert load_model(path).authoritative == canonical and bound_stack_names(path) == placements
    assert path.read_bytes() != original and design_source_digest(path) == digest
    assert sync_runtime.sync(root, True, 'preview', 'team', services=['vpc', 'cloudformation-stacks']) == 0
    path.write_bytes(original)
    for rid, placement in [('017', 'bad_name'), ('083', fixed), ('017', None), ('017', current.values['desired.stack.083.name'])]:
        bad = dict(canonical)
        key = f'desired.stack.{rid}.placementName'
        bad.pop(key) if placement is None else bad.update({key: placement})
        with pytest.raises(ValueError, match='placementName'):
            load_model(path, CandidateReads(FileReads(), {path: serialize(bad)}))
    for placement in ('cfn-stack-app-preview-unknown', current.values['desired.stack.017.name']):
        invalid = {**load_model(vpc_path).values, 'desired.resource.027.cfn-logicalId': placement + '-PrimaryVpc'}
        with pytest.raises(ValueError, match='undeclared stack'):
            markdown_for(root / 'docs/designs/preview/team/vpc.md', invalid, root)
    path.unlink()
    with pytest.raises((OSError, ValueError)):
        bound_stack_names(path)
    path.write_bytes(original)
    legacy = root / 'model/parameters'
    legacy.mkdir()
    with pytest.raises(ValueError, match='explicit migration'):
        bound_stack_names(path)
    print('Bound Stacks: PASS (explicit names; fixed placement/IDs/observed; generation idempotence; raw/design digests; mapping/destroy safety; legacy rejection)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        with redirect_stdout(io.StringIO()) as output:
            check(Path(directory).resolve())
        print(output.getvalue().strip().splitlines()[-1])
