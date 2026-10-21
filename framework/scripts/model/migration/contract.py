"""An exact, one-time format transition; never an ordinary Model update exemption."""
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
import tempfile

from model.format import strict_json
from model.migration.compare import compare_export, semantic
from model.migration.convert import checked_export
from model.migration.export import export_legacy


@dataclass(frozen=True)
class FormatMigration:
    baseline: str
    legacy_revision: str
    old_checkout: Path
    old_python: Path
    export_path: Path
    export_sha256: str
    services: frozenset
    paths: frozenset


def migration_contract(text):
    from task_contract import section, paths_in
    heading = '## Model format migration'
    lines = section(text, '## Task contract')
    reserved = [line for line in lines if re.match(r'-\s*Model format migration\b', line)]
    headings = [line for line in text.splitlines() if re.match(r'##\s+Model format migration\b', line)]
    if not reserved and not headings:
        return None
    if reserved != ['- Model format migration: `properties-v2`'] or headings != [heading]:
        raise ValueError('invalid Model format migration declaration')
    for name, value in (('Task type', 'migration'), ('Workflow', 'model-format-migration'),
                        ('AWS API execution', 'forbidden'), ('deploy/apply', 'forbidden')):
        if [line for line in lines if re.match(r'-\s*' + re.escape(name) + r'\b', line)] != [f'- {name}: `{value}`']:
            raise ValueError('Model format migration requires ' + name + ': ' + value)
    body = section(text, heading)
    if len(body) != 1 or not body[0].startswith('- {'):
        raise ValueError('Model format migration requires exactly one JSON contract')
    value = strict_json(body[0][2:])
    expected = {'baseline', 'legacyRevision', 'oldCheckout', 'oldPython', 'exportPath', 'exportSha256',
                'fromVersion', 'toVersion', 'services', 'paths'}
    if not isinstance(value, dict) or value.keys() != expected or type(value['fromVersion']) is not int or value['fromVersion'] != 1 or type(value['toVersion']) is not int or value['toVersion'] != 2:
        raise ValueError('Model format migration requires the exact 1-to-2 contract schema')
    for field, length in (('baseline', 40), ('legacyRevision', 40), ('exportSha256', 64)):
        if not isinstance(value[field], str) or re.fullmatch('[0-9a-f]{' + str(length) + '}', value[field]) is None:
            raise ValueError('Model format migration requires a fixed hash: ' + field)
    external = []
    for field in ('oldCheckout', 'oldPython', 'exportPath'):
        raw = value[field]
        if not isinstance(raw, str) or not Path(raw).is_absolute() or '..' in Path(raw).parts:
            raise ValueError('Model migration requires an explicit absolute external path: ' + field)
        external.append(Path(raw))
    collections = {}
    for field in ('services', 'paths'):
        raw = value[field]
        if not isinstance(raw, list) or not raw or any(not isinstance(item, str) for item in raw) or len(raw) != len(set(raw)):
            raise ValueError('Model migration requires an enumerated nonempty set: ' + field)
        for item in raw:
            path = PurePosixPath(item)
            if path.is_absolute() or '..' in path.parts or str(path) != item or '\\' in item:
                raise ValueError('unsafe Model migration ' + field)
            if field == 'services' and len(path.parts) != 3 or field == 'paths' and (not item.startswith('model/') or any(char in item for char in '*?[]')):
                raise ValueError('Model migration requires exact service/source paths')
        collections[field] = frozenset(raw)
    if paths_in(text, '## Validation scope') != collections['services']:
        raise ValueError('Model migration Validation scope must equal its complete service set')
    declared, allowed = paths_in(text, '## Modified files'), paths_in(text, '## Allowed paths')
    if not collections['paths'] <= declared or not collections['paths'] <= allowed:
        raise ValueError('Model migration paths must be explicitly listed in Modified files and Allowed paths')
    if '- Model refactor: `value-preserving`' in lines or any(line.startswith('- Model operation:') for line in lines):
        raise ValueError('format migration cannot be combined with a Model operation/dependency detach')
    return FormatMigration(value['baseline'], value['legacyRevision'], *external, value['exportSha256'],
                           collections['services'], collections['paths'])


def require_preserved_inputs(root, contract):
    from worktree_task import git
    for args in (('diff', '--no-renames', '--name-only', '-z', contract.baseline, '--', 'project.json', 'infra', 'issues'),
                 ('ls-files', '--others', '--exclude-standard', '-z', '--', 'project.json', 'infra', 'issues')):
        changed = git(root, *args).stdout
        if changed:
            raise ValueError('format migration must preserve project/IaC/issues bytes and file sets: ' + changed.replace('\0', ', '))


def verify_migration(root, before, after, contract, base, sources):
    if base != contract.baseline:
        raise ValueError('format migration baseline changed; export and register a new exact contract')
    require_preserved_inputs(root, contract)
    if set(sources) != contract.paths:
        raise ValueError('format migration source changes differ from the enumerated paths')
    for path in (contract.old_checkout, contract.old_python, contract.export_path):
        if path.resolve().is_relative_to(root.resolve()):
            raise ValueError('format migration runtime/export must be external')
    raw = contract.export_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != contract.export_sha256:
        raise ValueError('format migration export hash changed')
    pinned = checked_export(strict_json(raw.decode('utf-8')))
    if pinned['legacyRevision'] != contract.legacy_revision or {'/'.join(model['scope']) for model in pinned['models']} != contract.services:
        raise ValueError('format migration legacy revision/service set differs')
    with tempfile.TemporaryDirectory(prefix='model-format-migration-') as temporary:
        baseline = export_legacy(contract.old_checkout, contract.old_python, before,
                                 contract.legacy_revision, Path(temporary).resolve() / 'baseline.json')
    if baseline['inputs'] != pinned['inputs']:
        raise ValueError('format migration export does not describe the fixed Git baseline inputs')
    expected = {tuple(model['scope']): model for model in pinned['models']}
    actual = {tuple(model['scope']): model for model in baseline['models']}
    if expected.keys() != actual.keys() or any(semantic(model['authoritative']) != semantic(actual[scope]['authoritative']) or
            model['resourceOrder'] != actual[scope]['resourceOrder'] or model['rowOrder'] != actual[scope]['rowOrder']
            for scope, model in expected.items()):
        raise ValueError('format migration export differs from the isolated old baseline reader')
    compare_export(baseline, after)
    if contract.export_path.read_bytes() != raw:
        raise ValueError("format migration export changed during comparison")
    require_preserved_inputs(root, contract)
    return ()
