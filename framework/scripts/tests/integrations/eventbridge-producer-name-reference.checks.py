#!/usr/bin/env python3
"""Explicit saved references: fixed identity, dependencies and semantic warnings."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from support.it_case_receipt import it_case, module_complete
from support.producer_identifier_reference_fixtures import *

def check(root, service, kind, property_name):
    setup(root, [service, 'eventbridge'], [kind, 'Events.Rule', 'Lambda.Permission'])
    producer = root / 'model/preview/team' / (service + '.properties')
    original = resource('052', kind, service + '-original', [(property_name, '`Original-Case_01`'), ('Nested.Name', '`unrelated-nested-name`')])
    if service == 'lambda':
        original.update(resource('053', 'Lambda.Permission', 'lambda-invoke-permission', [
            ('FunctionName', '[052](#lambda-original)'), ('Principal', '`events.amazonaws.com`'),
            ('SourceArn', '[rule](eventbridge.md#eventbridge-rule)')]))
        original.update({'desired.resource.053.parentProperty': 'Lambda.Permission.FunctionName',
                         'desired.resource.053.parentReference': '[052](#lambda-original)'})
    write_model(producer, original)
    path = producer.with_name('eventbridge.properties')
    values = resource('021', 'Events.Rule', 'eventbridge-rule', [('Name', '`rule`'), ('EventPattern', '[config](eventbridge/raw.json)')])
    key = 'desired.row.021-002.document'
    values[key] = json.dumps({'name': 'Original-Case_01', 'count': 2, 'enabled': True})
    link = '[PENDING_DEPLOY](' + service + '.md#' + service + '-original)'
    values['desired.note.link.text'] = link
    values.update(reference('link', 'desired.note.link.text', link, service, '052', kind, mode='link', label='fixed'))
    values.update(reference('raw', key, 'Original-Case_01', service, '052', kind, prop=kind + '.' + property_name, pointer='/name'))
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert json.loads(snapshot.authoritative[key]) == {'name': 'Original-Case_01', 'count': 2, 'enabled': True}
    assert trace_model(path, key)['references']['raw']['format'] == 'name'
    assert producer in source_inputs(path)
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    write_model(producer, {**original, 'desired.row.052-001.value': '`Renamed`'})
    assert warning(path, 'differs from saved text').authoritative == snapshot.authoritative
    assert design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    assert affected(root, [producer.relative_to(root)]) == {('preview', 'team', service), ('preview', 'team', 'eventbridge')}
    for bad, phrase in [
        ({**original, 'desired.resource.052.resourceType': 'EC2.VPC'}, 'Type differs'),
        ({key.replace('.052', '.054', 1): value for key, value in original.items()}, 'absent or ambiguous'),
        ({**original, 'desired.row.052-001.property': kind + '.Description'}, 'Property is absent'),
        ({**original, 'desired.row.052-001.value': '``'}, 'differs from saved text'),
        ({**original, 'desired.row.052-003.property': kind + '.' + property_name, 'desired.row.052-003.value': '`duplicate`', 'desired.row.052-003.comment': '重複'}, 'Property is absent or ambiguous')]:
        write_model(producer, bad)
        assert warning(path, phrase).authoritative == snapshot.authoritative
    write_model(producer, original)
    rejected(lambda: declarations({**values, 'desired.reference.raw.labelPolicy': 'fixed'}), 'non-link')
    producer.unlink()
    assert warning(path, 'Model is absent').authoritative == snapshot.authoritative


if __name__ == '__main__':
    for service, kind, name in [('lambda', 'Lambda.Function', 'FunctionName'), ('sqs', 'SQS.Queue', 'QueueName'), ('iam', 'IAM.User', 'UserName')]:
        with tempfile.TemporaryDirectory() as directory:
            check(Path(directory).resolve(), service, kind, name)
    print('EventBridge producer names: PASS (FunctionName/QueueName/UserName; typed JSON; labels; trace; dependency snapshots; warnings)')

module_complete(__file__)
