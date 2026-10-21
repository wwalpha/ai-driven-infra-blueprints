#!/usr/bin/env python3
"""Explicit saved references: fixed identity, dependencies and semantic warnings."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from support.it_case_receipt import it_case, module_complete
from support.producer_identifier_reference_fixtures import *

def check(root, service, kind, name_property):
    setup(root, [service, 'ec2'], [kind, 'EC2.Instance', 'IAM.Role'])
    producer = root / 'model/preview/team' / (service + '.properties')
    original = resource('052', kind, service + '-app-preview-one', [
        ((name_property or 'KMS.Key.Description').removeprefix(kind + '.'), '`app-preview-one`')])
    if name_property:
        original.update(resource('075', 'IAM.Role', 'iam-app-role', [('RoleName', '`app-role`')]))
        original.update({'desired.row.052-002.property': 'IAM.InstanceProfile.Roles',
                         'desired.row.052-002.value': '[app-role](#iam-app-role)', 'desired.row.052-002.comment': 'ロール'})
    write_model(producer, original)
    path = producer.with_name('ec2.properties')
    values = {}
    for rid, label, policy in [('021', 'app-preview-one' if name_property else '052', 'display-name' if name_property else 'resource-id'),
                               ('083', 'original-label', 'fixed')]:
        key = f'desired.row.{rid}-001.value'
        link = '[' + label + '](' + service + '.md#' + service + '-app-preview-one)'
        values.update(resource(rid, 'EC2.Instance', 'ec2-' + rid, [
            ('IamInstanceProfile' if name_property else 'BlockDeviceMappings[].Ebs.KmsKeyId', link)]))
        values.update(reference('producer-' + rid, key, link, service, '052', kind, mode='link', label=policy))
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert producer in source_inputs(path)
    assert affected(root, [producer.relative_to(root)]) == {('preview', 'team', service), ('preview', 'team', 'ec2')}
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    producer.write_text(producer.read_text() + '# producer annotation\n')
    assert design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    assert load_model(path).authoritative == snapshot.authoritative
    write_model(producer, {key: value.replace('preview-one', 'preview-two') for key, value in original.items()})
    assert warning(path, 'differs from the saved link').authoritative == snapshot.authoritative
    changed_label = dict(values)
    changed_label['desired.row.083-001.value'] = changed_label['desired.row.083-001.value'].replace('[original-label]', '[changed-label]')
    changed_label['desired.reference.producer-083.text'] = changed_label['desired.row.083-001.value']
    write_model(producer, original)
    write_model(path, changed_label)
    assert not load_model(path).warnings and design_source_digest(path) != digest
    write_model(path, values)
    for bad, phrase in [({**original, 'desired.resource.052.resourceType': 'S3.Bucket'}, 'Type differs'),
                        ({key.replace('.052', '.053', 1): value for key, value in original.items()}, 'absent or ambiguous')]:
        write_model(producer, bad)
        assert warning(path, phrase).authoritative == snapshot.authoritative
    write_model(producer, original)
    if name_property:
        for bad in [{**original, 'desired.row.052-001.property': 'IAM.InstanceProfile.Path'},
                    {**original, 'desired.row.052-001.value': '``'},
                    {**original, 'desired.row.052-003.property': name_property, 'desired.row.052-003.value': '`duplicate`', 'desired.row.052-003.comment': '重複'}]:
            write_model(producer, bad)
            assert load_model(path).warnings
        write_model(producer, original)
    else:
        # Description and grouped display never become a raw KMS Key name.
        bad = dict(values)
        bad['desired.row.021-001.value'] = '`app-preview-one`'
        for key in list(bad):
            if key.startswith('desired.reference.producer-021.'):
                del bad[key]
        bad.update(reference('producer-021', 'desired.row.021-001.value', 'app-preview-one', service, '052', kind,
                             prop='KMS.Key.Description'))
        write_model(path, bad)
        warning(path, 'not a raw name Property')
        write_model(path, values)
        for selected in ('missing', 'app-preview-one'):
            write_model(path, {**values, 'desired.reference.producer-021.producerId': selected})
            warning(path, 'absent or ambiguous')
        write_model(path, values)
    rejected(lambda: declarations({**values, 'desired.reference.producer-083.selector': 'first'}), 'fields')
    producer.unlink()
    assert warning(path, 'Model is absent').authoritative == snapshot.authoritative


if __name__ == '__main__':
    for service, kind, name in [('iam', 'IAM.InstanceProfile', 'IAM.InstanceProfile.InstanceProfileName'), ('kms', 'KMS.Key', None)]:
        with tempfile.TemporaryDirectory() as directory:
            check(Path(directory).resolve(), service, kind, name)
    print('Group 03 references: PASS (InstanceProfileName; unnamed Key; labels; explicit candidates; dependency snapshots; warnings)')

module_complete(__file__)
