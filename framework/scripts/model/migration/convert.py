"""Convert a complete export into a new, separately staged properties candidate."""
import hashlib
import os
from pathlib import Path
import tempfile
from model.format import owner, split
from utils.json_format import strict_json
from model.sources import Scope


def checked_export(value):
    if (not isinstance(value, dict) or value.get('exportFormat') != 2 or value.get('modelFormat') != 2
            or value.get('snapshotVersion') != 2 or value.get('complete') is not True):
        raise ValueError('unsupported or incomplete legacy export')
    if not isinstance(value.get('models'), list) or any(model.get('complete') is not True for model in value['models']):
        raise ValueError('legacy export contains incomplete Models')
    project = value.get('project')
    if not isinstance(project, str) or hashlib.sha256(project.encode('utf-8')).hexdigest() != value['inputs'].get('project.json'):
        raise ValueError('legacy export project hash differs')
    strict_json(project)
    for model in value['models']:
        try:
            legacy_declarations(model['authoritative'])
        except ValueError as error:
            raise ValueError('invalid legacy export references; regenerate export and evidence: ' + str(error)) from error
    return value


def legacy_declarations(values):
    """Validate historical export metadata without enabling ordinary legacy resolution."""
    from model.core import entries
    from model.references import declarations
    candidate = dict(values)
    for identity, spec in entries(values, 'desired.reference.'):
        if spec.get('producerKind') == 'resource' and 'producerId' in spec:
            prefix = f'desired.reference.{identity}.'
            candidate[prefix + 'producerLogicalId'] = candidate.pop(prefix + 'producerId')
    declarations(candidate)
    return dict(entries(values, 'desired.reference.'))


def block_order(values, resource_order, row_order):
    from model.core import entries
    resources = {identity for identity, _ in entries(values, 'desired.resource.')}
    rows = {identity for identity, _ in entries(values, 'desired.row.')}
    if len(resource_order) != len(set(resource_order)) or set(resource_order) != resources or len(row_order) != len(set(row_order)) or set(row_order) != rows:
        raise ValueError('exported Resource/Row display order is incomplete or duplicated')
    blocks = {}
    for key, value in values.items():
        blocks.setdefault(owner(key, values), {})[key] = value
    resource_blocks = iter(blocks[('resource', identity)] for identity in resource_order)
    ordered = [next(resource_blocks) if block[0] == 'resource' and block[1] in resources else fields for block, fields in blocks.items()]
    result = {}
    for block in ordered:
        def emit(key):
            result[key] = block[key]
            observed = key.replace('desired.', 'observed.', 1)
            if key.startswith('desired.row.') and observed in block:
                result[observed] = block[observed]
            for ref_key, consumer in block.items():
                if ref_key.startswith('desired.reference.') and ref_key.endswith('.consumerKey') and consumer == key:
                    prefix = ref_key.removesuffix('consumerKey')
                    result.update((name, content) for name, content in block.items() if name.startswith(prefix))
        for prefix in ('desired.resource.', 'display.resource.', 'desired.stack.', 'display.stack.'):
            for key in block:
                if key.startswith(prefix):
                    emit(key)
        row_rank = {identity: index for index, identity in enumerate(row_order)}
        for key in sorted((key for key in block if key.startswith('desired.row.')),
                          key=lambda key: row_rank[key.split('.')[2]]):
            emit(key)
        for key in block:
            if key not in result and not key.startswith(('observed.', 'desired.reference.')):
                emit(key)
        result.update((key, value) for key, value in block.items() if key not in result)
    return result


def convert_export(value, destination):
    value = checked_export(value)
    destination = Path(destination).absolute()
    if destination.exists() or any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError('migration candidate destination must not exist')
    with tempfile.TemporaryDirectory(prefix='model-v2-convert-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'candidate'
        stage.mkdir()
        (stage / 'project.json').write_text(value['project'], encoding='utf-8', newline='')
        scopes = set()
        for model in value['models']:
            identity = tuple(model['scope'])
            if len(identity) != 3 or identity in scopes:
                raise ValueError('invalid or duplicate exported Model scope')
            if any(not isinstance(name, str) or not name or name in {'.', '..'} or '/' in name or '\\' in name for name in identity):
                raise ValueError('unsafe exported Model scope')
            scopes.add(identity)
            path = Scope(stage, *identity).path
            for output, text in split(path, block_order(model['authoritative'], model['resourceOrder'], model['rowOrder'])).items():
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(text, encoding='utf-8', newline='')
        # Compare the historical format exactly; identity rewriting is a separate guarded Task.
        from model.migration.compare import compare_export
        compare_export(value, stage)
        os.replace(stage, destination)
    return destination
