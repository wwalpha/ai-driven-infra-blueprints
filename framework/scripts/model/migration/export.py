"""Export through a pinned legacy checkout and its interpreter in an isolated child."""
import hashlib
import json
from pathlib import Path
import subprocess
from model.format import strict_json
from model.sources import json_text

# This adapter invokes the old public reader. It contains no copy of that reader.
CHILD = r'''
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import importlib.metadata
old, root, revision = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]
actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=old, text=True).strip()
if actual != revision:
    raise ValueError('legacy checkout revision differs from the pinned baseline')
def verify_legacy():
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=old, text=True).strip()
    if current != revision:
        raise ValueError('legacy checkout changed during export')
    subprocess.run(['git', 'diff', '--no-ext-diff', '--exit-code', revision, '--', 'framework', '.agents', 'AGENTS.md'], cwd=old, check=True, stdout=sys.stderr)
    untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', 'framework/scripts'], cwd=old, text=True)
    if untracked.strip():
        raise ValueError('legacy runtime has unversioned script files')
verify_legacy()
for line in (old / 'framework/scripts/requirements.txt').read_text(encoding='utf-8').splitlines():
    if not line.strip() or line.startswith('#'):
        continue
    package, separator, version = line.partition('==')
    if not separator or importlib.metadata.version(package) != version:
        raise ValueError('legacy interpreter does not match pinned requirements: ' + line)
sys.path.insert(0, str(old / 'framework/scripts'))
import model_templates as legacy
from model_parameter_inputs import human_instances, parameter_value, select_reference_target, schema
from model_core import entries
from utils.aws_mappings import mapping_alias
from validation_cache import input_context

def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def inputs():
    if (root / 'model').is_symlink() or (root / 'project.json').is_symlink():
        raise ValueError('legacy export rejects redirected source entrances')
    result = {}
    for path in (root / 'model').rglob('*'):
        if path.is_symlink():
            raise ValueError('legacy export rejects symlink inputs: ' + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = checksum(path)
    for binding in (root / 'model/parameters').glob('*/*/*/bindings.json'):
        optional = binding.parent / 'observed.json'
        result.setdefault(optional.relative_to(root).as_posix(), None)
    result['project.json'] = checksum(root / 'project.json')
    return result

def leaves(value, pointer=''):
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, pointer + '/' + str(index))

def semantic_values(expansion):
    return {key: value for key, value in expansion.values.items()
            if not (key.startswith('observed.') and not key.endswith('.value'))
            and not key.endswith('.artifactSha256')}

def export_model(path):
    expansion = legacy.load_for_analysis(path)
    if expansion is None:
        raise ValueError('missing legacy service: ' + str(path))
    root_, template, directory = legacy.service_source(path)
    definitions, template_files = legacy.parse_template(template)
    parameters = __import__('model_parameter_inputs').yaml_read((directory / 'parameters.yaml').read_text(encoding='utf-8'))
    bindings = legacy.json_read((directory / 'bindings.json').read_text(encoding='utf-8'))
    observed = legacy.read_observed(directory)[0]
    markers = {}
    environment, target, service = path.parent.parent.name, path.parent.name, path.stem

    def bind(template, parameters, bindings, definitions, environment):
        normalized, files = human_instances(template, parameters, bindings, definitions, environment, resolve_references=False)
        result = copy.deepcopy(normalized)
        for item in result['instances']:
            original = next(value for value in normalized['instances'] if value['id'] == item['id'])
            definition = definitions[item['definition']]
            for name in item['parameters']:
                spec = schema(definition.parameters[name])
                dependency = spec.get('source', '')
                try:
                    value = parameter_value(template, original, name, normalized['instances'], bindings, definitions, environment, files)
                except legacy.ReferenceResolutionError as error:
                    raise ValueError('cannot prove legacy reference equivalence: ' + item['id'] + '/' + name + ': ' + str(error)) from error
                item['parameters'][name] = value
                reference = None
                if spec['type'] == 'reference':
                    rid, kind = select_reference_target(template, original, name, normalized['instances'], definitions, environment, files)
                    producer_service = spec.get('service', service)
                    mode = spec.get('format', 'link')
                    producer_scope = '/'.join((environment, target, producer_service))
                    producer_kind = 'stack' if kind == 'stack' else 'resource'
                    reference = {'producerKind': producer_kind, 'producerScope': producer_scope,
                                 'producerId': rid, 'format': mode,
                                 'labelPolicy': ('fixed' if name in bindings['instances'][item['id']].get('labels', {}) else
                                                 'display-name' if 'service' in spec else 'resource-id') if mode == 'link' else 'none'}
                    if producer_kind == 'stack':
                        reference['property'] = 'name'
                    else:
                        reference['resourceType'] = spec['resourceType']
                        if mode in {'name', 'identifier'}:
                            prop = spec.get('property')
                            if prop is None:
                                producer = path.with_name(producer_service + '.properties')
                                resolved = legacy.reference_values(producer, rid, spec['resourceType'], mode)
                                candidates = [row['property'] for row_id, row in entries(resolved.values, 'desired.row.')
                                              if row_id.rpartition('-')[0] == rid and row['property'].endswith(legacy.REFERENCE_NAME_SUFFIXES)]
                                if len(candidates) != 1:
                                    raise ValueError('cannot identify the legacy raw name Property: ' + producer_scope + '/' + rid)
                                prop = candidates[0]
                            reference['property'] = prop
                elif dependency in {'consumer.environment', 'consumer.executionAccountId'}:
                    reference = {'producerKind': 'context', 'producerScope': environment + '/' + target,
                                 'format': 'literal', 'labelPolicy': 'none',
                                 'contextProperty': 'environment' if dependency.endswith('.environment') else 'executionAccountId'}
                if reference is not None:
                    if not isinstance(value, str) or not value:
                        raise ValueError('legacy reference must have representable nonempty string text: ' + name)
                    marker = 'MIGRATIONREFERENCE' + str(len(markers)).zfill(8) + 'END'
                    if any(marker in raw for raw in expansion.values.values()):
                        raise ValueError('reserved migration marker in legacy input')
                    markers[marker] = value, reference
                    item['parameters'][name] = marker
        return result, files

    marked, _, _ = legacy.expand_inputs(template, parameters, observed, bindings, environment, bind, _parsed=(definitions, template_files))
    expected = semantic_values(expansion)
    metadata = {}
    number = 1
    for key, raw in list(expected.items()):
        if key.startswith('observed.'):
            continue
        source = marked.get(key)
        if source is None:
            raise ValueError('legacy export lost an active key: ' + key)
        # The pinned reader rejects unknown expressions; reconstruction below proves literal token data.
        if key.endswith('.document'):
            symbolic = legacy.json_read(source)
            actual = legacy.json_read(raw)
            structured = True
        elif (key.endswith('.value') and source.startswith('`') and source[1:].lstrip().startswith(('{', '['))
              and not re.fullmatch(r'\{\{resolve:[^{}\r\n]+\}\}', source[1:-1].strip())
              and not re.fullmatch(r'\[[^\]\r\n]+\]\([^()\r\n]+\)', source[1:-1].strip())):
            symbolic = legacy.json_read(source[1:-1])
            actual = legacy.json_read(raw[1:-1])
            structured = True
        else:
            symbolic, actual, structured = source, raw, False
        replaced = source
        for marker, (text, _) in markers.items():
            # JSON string escaping is applied by the old serializer, not guessed here.
            replaced = replaced.replace(marker, json.dumps(text, ensure_ascii=False)[1:-1] if structured else text)
        if structured:
            restored = legacy.json_read(replaced if key.endswith('.document') else replaced[1:-1])
            if json.dumps(restored, sort_keys=True) != json.dumps(actual, sort_keys=True):
                raise ValueError('legacy JSON reference reconstruction differs: ' + key)
        elif replaced != raw:
            raise ValueError('legacy reference reconstruction differs: ' + key)
        actual_leaves = dict(leaves(actual))
        for pointer, leaf in leaves(symbolic):
            matches = list(re.finditer(r'MIGRATIONREFERENCE[0-9]{8}END', leaf))
            offset, last = 0, 0
            for match in matches:
                text, spec = markers[match[0]]
                offset += len(leaf[last:match.start()])
                actual_leaf = actual_leaves[pointer]
                if actual_leaf[offset:offset + len(text)] != text:
                    raise ValueError('legacy reference position cannot be proven: ' + key)
                positions, occurrence_start = [], -1
                while (occurrence_start := actual_leaf.find(text, occurrence_start + 1)) >= 0:
                    positions.append(occurrence_start)
                occurrence = str(positions.index(offset) + 1)
                identity = f'migration-{number:06d}'
                number += 1
                record = {'consumerKey': key, **({'pointer': pointer} if structured else {}),
                          'text': text, 'occurrence': occurrence, **spec}
                metadata.update({f'desired.reference.{identity}.{field}': value for field, value in record.items()})
                offset += len(text)
                last = match.end()
    expected.update(metadata)
    for identity, name in bindings.get('stacks', {}).items():
        expected[f'desired.stack.{identity}.placementName'] = name
    if any(key.startswith('desired.stack.') for key in expected) and not bindings.get('stacks'):
        raise ValueError('legacy Stack has no provable fixed placement binding: ' + str(path))
    return {'scope': [environment, target, service], 'authoritative': expected,
            'resourceOrder': [identity for identity, _ in entries(expansion.values, 'desired.resource.')],
            'rowOrder': [identity for identity, _ in entries(expansion.values, 'desired.row.')],
            'warnings': list(expansion.warnings), 'legacyProvenance': expansion.provenance,
            'complete': True}

# The read-only outer lock is acquired before any reader that could recover a journal.
with legacy.publication_lock(root, read_only=True), mapping_alias(old, root), input_context():
    start = inputs()
    models = [export_model(path) for path in legacy.model_paths(root)]
    finish = inputs()
    verify_legacy()
    if start != finish:
        raise ValueError('legacy inputs changed during export')
    result = {'exportFormat': 2, 'modelFormat': 2, 'snapshotVersion': 2,
              'legacyRevision': revision, 'legacyInterpreter': sys.executable,
              'inputs': start, 'project': (root / 'project.json').read_bytes().decode('utf-8'),
              'models': models, 'complete': True}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
'''


def export_legacy(old_checkout, old_python, source_root, revision, destination):
    old_checkout, source_root = Path(old_checkout).resolve(), Path(source_root).resolve()
    old_python, destination = Path(old_python), Path(destination).absolute()
    if not old_python.is_absolute() or not old_python.is_file():
        raise ValueError('legacy interpreter must be an explicit existing absolute path')
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError('export destination must not use symlinks')
    if destination.is_relative_to(source_root) or destination.is_relative_to(old_checkout):
        raise ValueError('export destination must be outside the source and legacy checkout')
    if destination.exists():
        raise ValueError('export destination already exists')
    result = subprocess.run([str(old_python), '-I', '-B', '-c', CHILD, str(old_checkout), str(source_root), revision],
                            capture_output=True, text=True, encoding='utf-8', cwd=old_checkout)
    if result.returncode:
        raise ValueError('legacy export not completed: ' + result.stderr.strip())
    value = strict_json(result.stdout)
    if not value.get('complete') or value.get('legacyRevision') != revision:
        raise ValueError('legacy export is incomplete or has another baseline')
    payload = json_text(value) + '\n'
    from sync_files import atomic_files
    atomic_files({destination: payload}, staging_directory=destination.parent)
    return value
