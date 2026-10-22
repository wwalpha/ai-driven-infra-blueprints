"""Task identity and exact controlled-repair evidence shared by execution and validation."""
import re
import json
import hashlib
from pathlib import Path

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def task_digest(text):
    # Human approval updates the existing contract, not deployment inputs/scope.
    text = '\n'.join(line for line in text.splitlines() if not line.startswith(('- Authorized delete/replacement:', '- Task status:')))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def repair_changes(root, contract, changed):
    """Shared validator/resume evidence: only exact session-authorized file bytes."""
    from task_contract import task_path, paths_in
    entries = re.findall(r"^- Deploy repair session: `([^`]+)`$", contract, re.M)
    if '- Controlled repair: `allowed`' not in contract.splitlines() or len(entries) != 1:
        raise ValueError('deploy phase IaC changes need controlled repair session authorization')
    path = Path(entries[0])
    if not path.is_absolute() or path.resolve().is_relative_to(root.resolve()):
        raise ValueError('deploy repair session must be outside repository')
    session = json.loads(path.read_text(encoding='utf-8'))
    selected = task_path(root)
    if (session.get('repository') != str(root.resolve()) or session.get('taskFile') != selected.relative_to(root).as_posix()
            or session.get('taskDigest') != task_digest(contract)):
        raise ValueError('deploy repair session task identity changed')
    authorized = {}
    for state in session['states'].values():
        for record in state.get('repairs', []):
            if record.get('classification') != 'AUTO_REPAIRABLE' or record.get('stage') == 'REPAIR_INTENT':
                continue
            relative = record['path']
            if relative in authorized and authorized[relative]['newFileDigest'] != record['oldFileDigest']:
                raise ValueError('deploy repair digest chain broken')
            authorized[relative] = record
    allowed = paths_in(contract, '## Allowed paths')
    for relative in changed:
        if relative not in allowed or relative not in authorized:
            raise ValueError('unauthorized deploy IaC change: ' + relative)
        if sha(root / relative) != authorized[relative]['newFileDigest']:
            raise ValueError('deploy repair file digest changed: ' + relative)
    return session




def migrate_delivery(root, target, unit, state, template_data, file_digest):
    """Explicit migration of old delivery arguments; preserve execution identity/evidence."""
    from cloudformation_inputs import Blocked, condition_active
    from model.core import ARTIFACT_PROPERTIES
    from deploy.delivery import source_path
    from urllib.parse import urlparse, parse_qs, unquote
    record = state.get('delivery')
    if not record or not isinstance(record.get('arguments'), list):
        return False
    arguments = record['arguments']
    if len(arguments) != 2:
        raise Blocked('legacy delivery arguments cannot be safely migrated')
    flag, value = arguments
    if flag == '--template-body' and value == 'file://' + record['path']:
        migrated = {'inline': True}
        template_object = None
    elif flag == '--template-url' and isinstance(value, str):
        parsed = urlparse(value)
        if parsed.scheme != 'https':
            raise Blocked('legacy template URL is not HTTPS')
        components = unquote(parsed.path).lstrip('/').split('/', 1)
        versions = parse_qs(parsed.query).get('versionId', [])
        candidates = [obj for obj in record['objects'] if components == [obj['bucket'], obj['key']]
                      and (versions == [obj['version']] if obj.get('version') else not versions)]
        if len(candidates) != 1:
            raise Blocked('legacy template URL/object version evidence is ambiguous')
        template_object = candidates[0]
        migrated = {'TemplateURL': value}
    else:
        raise Blocked('legacy delivery arguments/path identity cannot be migrated')
    document, parameters = template_data
    pseudo = {'AWS::StackName': unit['name'], 'AWS::Region': target['awsRegion'],
              'AWS::AccountId': target.get('awsExecutionAccountId', target['awsAccountId'])}
    pending = [obj for obj in record['objects'] if obj is not template_object]
    active = [artifact for artifact in unit.get('artifacts', [])
              if condition_active(document, parameters, pseudo, document['Resources'][artifact['resource']])]
    if len(pending) != len(active):
        raise Blocked('legacy artifact object/consumer identity is incomplete')
    updates = []
    for artifact, obj in zip(active, pending):
        path = source_path(root, artifact)
        expected_key = artifact['keyPrefix'] + file_digest(path) + path.suffix
        if obj['bucket'] != artifact['bucket'] or obj['key'] != expected_key:
            raise Blocked('legacy artifact key/source identity changed')
        kind = document['Resources'][artifact['resource']]['Type']
        updates.append((obj, bool(ARTIFACT_PROPERTIES[kind, artifact['property']]) and bool(obj.get('version'))))
    if template_object is not None:
        updates.append((template_object, bool(template_object.get('version'))))
    for obj, pinned in updates:
        obj['consumeVersion'] = pinned
    state['legacyDeliveryArguments'] = arguments
    record['arguments'] = migrated
    return True
