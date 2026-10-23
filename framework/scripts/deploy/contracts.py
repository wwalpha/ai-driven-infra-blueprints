"""Task identity and exact verified-child evidence shared by execution and validation."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import cloudformation_inputs as _imports_cloudformation_inputs
import model.core as _imports_model_core
import task_contract_core as _imports_task_contract
import utils.json_format as _imports_utils_json_format
from task_contract_core import task_digest as task_digest
from utils.file_operations import sha as sha
from utils.sealed_evidence import read_sealed
from worktree_state import output, paths, task_start_commit
from worktree_state import subprocess_bytes as subprocess_bytes

import deploy.delivery as _imports_deploy_delivery
import deploy.handoff as _imports_deploy_handoff


def accepted_changes(root, contract, changed):
    """Attribute exact child commit transitions; never grant the parent IaC write scope."""
    task_path = _imports_task_contract.task_path
    fingerprint = _imports_utils_json_format.fingerprint
    if not any(path.startswith('infra/') for path in changed):
        return set()
    entries = re.findall(r"^- Deploy repair session: `([^`]+)`$", contract, re.M)
    if len(entries) != 1:
        return set()
    path = Path(entries[0])
    if not path.is_absolute() or path.is_symlink() or path.resolve().is_relative_to(root.resolve()):
        raise ValueError('deploy repair session must be outside repository')
    session = json.loads(path.read_text(encoding='utf-8'))
    selected = task_path(root)
    if (session.get('repository') != str(root.resolve()) or session.get('taskFile') != selected.relative_to(root).as_posix()
            or session.get('taskDigest') != task_digest(contract)):
        raise ValueError('deploy repair session task identity changed')

    binding_path = _imports_deploy_handoff.binding_path
    protected = _imports_deploy_handoff.protected
    proof = binding_path(root, session['taskFile'])
    ledger = read_sealed(root, proof)
    if (proof.with_name(proof.name + '.intent').exists() or ledger['session'] != str(path) or
            ledger['taskFile'] != session['taskFile'] or fingerprint(ledger['state']) != fingerprint(protected(session))):
        raise ValueError('child attribution needs the current verified workflow ledger')
    records = session.get('workflow', {}).get('accepted', [])
    expected = {}
    for receipt_path in records:
        result = read_sealed(root, Path(receipt_path))
        if (result['workflowId'] != session['workflow']['workflowId'] or result['repository'] != str(root) or
                result['taskFile'] != session['taskFile'] or result['taskDigest'] != session['taskDigest']):
            raise ValueError('child attribution workflow mismatch')
        commit, parent = result['commit'], result['parentTip']
        if output(root, 'rev-parse', commit + '^') != parent or paths(root, 'diff', '--name-only', '--no-renames', '-z', parent, commit) != set(result['changes']):
            raise ValueError('child integration commit or path set changed')
        for relative, record in result['changes'].items():
            for revision, side in ((parent, 'before'), (commit, 'after')):
                raw = subprocess_bytes(root, revision, relative)
                if hashlib.sha256(raw).hexdigest() != record[side]:
                    raise ValueError('child commit bytes differ from receipt')
            expected.setdefault(relative, []).append((record['before'], record['after']))
    delegated = set(expected) & set(changed)
    if not delegated:
        return set()
    baseline = task_start_commit(root, selected.relative_to(root).as_posix())
    if not baseline:
        raise ValueError('child attribution requires managed parent lifecycle')
    actual = {relative: [] for relative in delegated}
    for commit in output(root, 'rev-list', '--reverse', baseline + '..HEAD').splitlines():
        parent = output(root, 'rev-parse', commit + '^')
        for relative in delegated & paths(root, 'diff', '--name-only', '--no-renames', '-z', parent, commit):
            actual[relative].append(tuple(hashlib.sha256(subprocess_bytes(root, rev, relative)).hexdigest() for rev in (parent, commit)))
    for relative in delegated:
        if actual[relative] != expected[relative] or sha(root / relative) != expected[relative][-1][1]:
            raise ValueError('unrecorded parent IaC edits or commit sequence: ' + relative)
    return delegated




def migrate_delivery(root, target, unit, state, template_data, file_digest):
    """Explicit migration of old delivery arguments; preserve execution identity/evidence."""
    Blocked = _imports_cloudformation_inputs.Blocked
    condition_active = _imports_cloudformation_inputs.condition_active
    ARTIFACT_PROPERTIES = _imports_model_core.ARTIFACT_PROPERTIES

    source_path = _imports_deploy_delivery.source_path


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
    for artifact, obj in zip(active, pending, strict=False):
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


def validation_snapshot(root):
    """Hash ordinary Git inputs used by a validated repair candidate."""
    safe_path = _imports_task_contract.safe_path
    result = {}
    for relative in sorted(paths(root, 'ls-files', '-z') | paths(root, 'ls-files', '--others', '--exclude-standard', '-z')):
        path = safe_path(root, relative)
        result[relative] = sha(path) if path.is_file() else None
    return result
