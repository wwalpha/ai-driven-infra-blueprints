"""Build explicit YAML service fixtures from each test's Model values."""
import re
from contextlib import contextmanager

from model_core import properties
from model_files import model_file_contents, model_parts
from model_templates import json_text, source_paths
from sync_files import save_files


def write_model(path, values):
    """Keep fixture identities explicit; production readers consume YAML only."""
    root, template, directory = source_paths(path)
    comments = [line for line in values.splitlines() if line.startswith('#') and not line.startswith(('# Generated', '# Authoritative', '# model-index:', '# part:'))] if isinstance(values, str) else []
    if isinstance(values, str):
        try:
            values = properties(values)
        except ValueError:
            # Negative fixtures corrupt the actual template, never a discarded projection.
            save_files({template: '# model-template: 1\n# definition: Invalid\n'+values+'# end-definition\n',
                        directory/'parameters.yaml': 'instances: {}\n',
                        directory/'bindings.json': json_text({'instances': {'fixture': {'definition': 'Invalid', 'resources': {}, 'rows': {}, 'parameters': {}}}}),
                        directory/'observed.json': json_text({'version': 1, 'values': {}})})
            return path
    from model_projection import document_sha256
    values = dict(values)
    for key, value in list(values.items()):
        if key.startswith('desired.row.') and key.endswith('.document'):
            from model_templates import json_read
            try:
                document = json_read(value)
            except ValueError:
                continue  # Invalid-input fixtures must reach the production reader.
            values[key] = json_text(document)
            values[key.removesuffix('.document')+'.artifactSha256'] = document_sha256(document)
    desired = {key: value for key, value in values.items() if not key.startswith('observed.')}
    resources = {key.split('.')[2] for key in desired if key.startswith('desired.resource.')}
    rows = {key.split('.')[2] for key in desired if key.startswith('desired.row.')}
    resource_map = {'resource_'+identity: identity for identity in resources}
    row_map = {'row_'+identity: identity for identity in rows}
    name = 'Fixture_'+path.parent.parent.name.replace('-', '_')
    lines = ['# definition: '+name, *comments]
    for local in sorted(resource_map):
        lines.append('# resource: '+local)
    for local, identity in sorted(row_map.items()):
        lines.append('# row: '+local+' resource_'+identity.rpartition('-')[0])
    retained = {key.split('.')[2] for key in desired if key.startswith('display.resource.')} - resources
    lines += ['# retained-display: '+identity for identity in sorted(retained)]
    for key, value in desired.items():
        parts = key.split('.')
        if len(parts) >= 4 and parts[1] == 'resource' and parts[2] in resources:
            parts[2] = 'resource_'+parts[2]
        elif len(parts) >= 4 and parts[1] == 'row' and parts[2] in rows:
            parts[2] = 'row_'+parts[2]
        lines.append('.'.join(parts)+'='+value)
    lines += ['# end-definition', '']
    previous = ''.join(p.read_text(encoding='utf-8') for p in model_parts(template)) if template.exists() else '# model-template: 1\n'
    pattern = r'^# definition: '+re.escape(name)+r'\n.*?^# end-definition\n?'
    block = '\n'.join(lines)
    previous = re.sub(pattern, lambda _: block, previous, flags=re.M | re.S) if re.search(pattern, previous, flags=re.M | re.S) else previous+block
    previous_parts = set(model_parts(template)) if template.exists() else set()
    output = model_file_contents(template, previous, validate=False)
    obsolete = previous_parts - output.keys() - {template}
    bindings = {'instances': {'fixture': {'definition': name, 'resources': resource_map,
        'rows': row_map, 'parameters': {}}}}
    output.update({directory/'parameters.yaml': 'instances: {}\n',
        directory/'bindings.json': json_text(bindings)+'\n'})
    observed = {k:v for k,v in values.items() if k.startswith('observed.')
                and not (k.endswith(('.property', '.comment')) and desired.get('desired.'+k.removeprefix('observed.')) == v)}
    if observed:
        output[directory/'observed.json'] = json_text({'version':1, 'values':observed})+'\n'
    else:
        (directory/'observed.json').unlink(missing_ok=True)
    save_files(output)
    for part in obsolete:
        part.unlink()
    return path


def write_fixture_files(output):
    """Create YAML authorities for explicitly supplied service fixture values."""
    output = dict(output)
    for path, text in list(output.items()):
        paths = source_paths(path)
        if paths is None:
            continue
        if paths[2]/'parameters.yaml' in output:
            for existing in list(output):
                if existing == path or existing.parent == path.with_suffix(''):
                    del output[existing]
            continue
        if text.startswith('# model-index: 1'):
            parts = [path.parent/line.removeprefix('# part: ') for line in text.splitlines() if line.startswith('# part: ')]
            text = ''.join(output[part] for part in parts)
        write_model(path, text)
        for existing in list(output):
            if existing == path or existing.parent == path.with_suffix(''):
                del output[existing]
    save_files(output)


def snapshot_model(path):
    from model_files import load_model
    return {file: file.read_bytes() for file in load_model(path).files}


@contextmanager
def catalog_display():
    """Legacy catalog fixtures select all fields, independent of consumer display sets."""
    from dataclasses import replace
    from unittest.mock import patch
    import array_display
    import aws_mapping_display
    from design_layout import HIDDEN_PROPERTIES
    from validation_cache import memoized
    original = aws_mapping_display.rules
    validate = aws_mapping_display.validate_mappings
    catalog = array_display.display_catalog

    @memoized
    def selectable(root, kind):
        if not (root / 'framework/mappings/aws').is_dir():
            root = aws_mapping_display.ROOT
        return {key: replace(prop, include=True, show=key not in HIDDEN_PROPERTIES)
                for key, prop in original(root, kind).items()}

    with patch.object(aws_mapping_display, 'rules', selectable), \
         patch.object(aws_mapping_display, 'validate_mappings', lambda source, root: validate(
             source, root if (root / 'framework/mappings/aws').is_dir() else aws_mapping_display.ROOT)), \
         patch.object(array_display, 'display_catalog', lambda root: catalog(
             root if (root / 'framework/rules/resource-layout.json').is_file() else aws_mapping_display.ROOT)):
        yield
