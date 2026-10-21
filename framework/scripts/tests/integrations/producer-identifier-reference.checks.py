#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.producer_identifier_reference_fixtures import *

@it_case
def check(root):
    setup(root, ['vpc', 'vpc-endpoint'], ['EC2.VPC', 'EC2.VPCEndpoint'])
    producer = root / 'model/preview/team/vpc.properties'
    original = resource('001', 'EC2.VPC', 'vpc-one', [('Name', '`vpc-one`'), ('VpcId', '[vpc-one](#vpc-one)')])
    original['observed.row.001-002.value'] = '`vpc-fixture-one`'
    write_model(producer, original)
    path = producer.with_name('vpc-endpoint.properties')
    key = 'desired.row.008-001.document'
    values = resource('008', 'EC2.VPCEndpoint', 'endpoint-008', [('PolicyDocument', '[policy](vpc-endpoint/policy.json)')])
    values[key] = json.dumps({'Condition': {'StringEquals': {'aws:SourceVpc': 'vpc-fixture-one'}}, 'Enabled': True})
    values.update(reference('vpc-id', key, 'vpc-fixture-one', 'vpc', '001', 'EC2.VPC', mode='identifier', prop='EC2.VPC.VpcId', pointer='/Condition/StringEquals/aws:SourceVpc'))
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert json.loads(snapshot.authoritative[key]) == {'Condition': {'StringEquals': {'aws:SourceVpc': 'vpc-fixture-one'}}, 'Enabled': True}
    assert producer in source_inputs(path)
    trace = trace_model(path, key)
    assert trace['references']['vpc-id']['format'] == 'identifier'
    assert affected(root, [producer.relative_to(root)]) == {('preview', 'team', 'vpc'), ('preview', 'team', 'vpc-endpoint')}
    digest = design_source_digest(path)
    dependencies = dependency_hashes(path)
    for raw in ('`vpc-fixture-two`', '`PENDING_DEPLOY`'):
        write_model(producer, {**original, 'observed.row.001-002.value': raw})
        changed = load_model(path)
        assert changed.warnings and changed.authoritative == snapshot.authoritative
        assert design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    import shutil
    from utils.aws_mappings import mapping_alias
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        shutil.copytree(root / 'model', stage / 'model')
        shutil.copyfile(root / 'project.json', stage / 'project.json')
        staged_producer = stage / producer.relative_to(root)
        write_model(staged_producer, {**original, 'observed.row.001-002.value': '`vpc-stage-only`'})
        with mapping_alias(root, stage):
            assert not (stage / 'framework').exists()
            staged = load_model(stage / path.relative_to(root))
            assert staged.authoritative == snapshot.authoritative and staged.warnings
            assert staged_producer in staged.dependencies and producer not in staged.dependencies
    assert load_model(path).authoritative == snapshot.authoritative
    for changed, phrase in [
        ({**original, 'desired.row.001-002.property': 'EC2.Subnet.SubnetId'}, 'Property is absent'),
        ({**original, 'desired.row.001-001.property': 'EC2.VPC.VpcId'}, 'Property is absent or ambiguous'),
        ({key: value for key, value in original.items() if not key.startswith('observed.')}, 'unobserved'),
        ({**original, 'observed.row.001-002.value': '``'}, 'nonempty non-ARN'),
        ({**original, 'observed.row.001-002.value': 'arn:aws:fixture'}, 'nonempty non-ARN')]:
        write_model(producer, changed)
        assert warning(path, phrase).authoritative == snapshot.authoritative
    for suffix, raw, phrase in [('property', 'EC2.Subnet.SubnetId', 'derived'), ('value', False, 'str')]:
        if suffix == 'property':
            bad = {**original, 'observed.row.001-002.property': raw}
            write_model(producer, bad)
            rejected(lambda: load_model(producer), 'unknown Model field')
        else:
            rejected(lambda: serialize({**original, 'observed.row.001-002.value': raw}), 'str')
    write_model(producer, original)
    for change, phrase in [({'producerLogicalId': 'EC2_VPC_002'}, 'absent or ambiguous'),
        ({'resourceType': 'EC2.Subnet', 'property': 'EC2.Subnet.SubnetId'}, 'Type differs'),
        ({'property': 'EC2.VPC.Name'}, 'unobserved')]:
        bad = {**values, **{'desired.reference.vpc-id.' + field: value for field, value in change.items()}}
        write_model(path, bad)
        warning(path, phrase)
    bad = {**values, 'desired.reference.vpc-id.labelPolicy': 'fixed'}
    rejected(lambda: declarations(bad), 'non-link')
    write_model(path, values)
    producer.unlink()
    warning(path, 'Model is absent')
    print('Producer identifiers: PASS (saved observed authority, pending/empty/absent distinctions, exact JSON, stage dependencies, warnings, schema rejection)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())

