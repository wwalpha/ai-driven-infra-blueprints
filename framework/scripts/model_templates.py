"""Explicit service sources, restricted Pystache expansion and runtime Model expansion."""
from __future__ import annotations
from validation_cache import input_bytes, input_exists, input_is_dir, input_is_file, input_is_symlink, input_select

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import NamedTuple

from model_core import properties, entries, LINK
from policy_tables import unique_object, invalid_constant
from validation_cache import input_scope, memoized, memo_table
import sync_files
from sync_progress import phase, thread_lock, advance

NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
IDENTITY = re.compile(r"[A-Za-z0-9_-]+")
TOKEN = re.compile(r"<<([A-Za-z][A-Za-z0-9_-]*)>>")
REFERENCE_NAME_SUFFIXES = ('.Name', '.RoleName', '.LogGroupName', '.BucketName', '.AliasName',
                         '.GroupName', '.InstanceProfileName', '.FunctionName', '.TrailName',
                         '.QueueName', '.UserName', '.RepositoryName')
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
         "object": dict, "array": list, "null": type(None)}
_local = threading.local()


from import_scope import scoped_read
from model_sources import (json_text, json_read, exact, source_paths, safe, publication_lock,
                           _publish_transaction, parameter_files, consumers)

def digest(values):
    # Include JSON types and array order; Properties keys themselves are unordered.
    return hashlib.sha256(json_text(sorted(values.items())).encode("utf-8")).hexdigest()


def publish(root, output, obsolete=(), inputs=None, *, verify=None, expected_task=None):
    """One transaction; readers cannot see a partial authority switch."""
    obsolete = set(obsolete) | {path for path, text in output.items() if text is None}
    output = {path: text for path, text in output.items() if text is not None}
    from task_contract import task_revision, status
    expected_task = expected_task if expected_task is not None else task_revision(root)
    name, text = expected_task
    if text is not None and status(text, name == 'tasks/active.md') != 'running':
        raise ValueError('completed task cannot write')
    from import_guard import managed_source_write, source_write_context
    raw_paths = set(output) | obsolete
    if text is not None and raw_paths and all(p.relative_to(root).as_posix().startswith(('model/templates/', 'model/parameters/')) for p in raw_paths) and managed_source_write(root, name):
        from model_sources import write_sources
        with source_write_context(root, name) as context:
            if context.snapshot.expected_task != expected_task:
                raise ValueError('task scope changed after planning; rerun publication')
            if inputs is not None and any((p.read_bytes() if p.is_file() else None) != data for p, data in inputs.items()):
                raise ValueError('Model sources changed after planning')
            write_sources(context, {**output, **{p: None for p in obsolete}})
        return
    with publication_lock(root) as journal:
        paths = set(output) | set(obsolete)
        for path in paths:
            safe(root, path)
        if any(p.relative_to(root).as_posix().startswith(('model/templates/', 'model/parameters/')) for p in paths):
            from import_guard import require_import_changes
            require_import_changes(root, output={**output, **{p: None for p in obsolete}})
        if task_revision(root, selected=name if text is not None else None) != expected_task:
            raise ValueError("task scope changed after planning; rerun generation")
        from validation_cache import input_recorder
        snapshot = input_recorder(root)
        if snapshot is not None:
            snapshot.verify()
        elif inputs is not None and any((p.read_bytes() if p.is_file() else None) != data for p, data in inputs.items()):
            raise ValueError('Model sources changed after validation; rerun generation/migration')
        def finish():
            if verify is not None:
                verify()
                expected_inputs = {p: data for p, data in (inputs or {}).items() if p not in paths}
                expected_inputs.update({p: text.encode('utf-8') for p, text in output.items()})
                expected_inputs.update({p: None for p in obsolete})
                if any((p.read_bytes() if p.is_file() else None) != data for p, data in expected_inputs.items()):
                    raise ValueError('generation inputs changed during publication')
            if task_revision(root, selected=name if text is not None else None) != expected_task:
                raise ValueError('task scope changed during publication; rerun generation')
        _publish_transaction(root, output, obsolete, journal, finish=finish)


def service_source(path):
    """Resolve a logical Model handle to its actual authoritative inputs."""
    paths = source_paths(path)
    if paths is None:
        return None
    root, template, directory = paths
    from import_scope import require_readable
    require_readable(root, path)
    with publication_lock(root):
        safe(root, directory)
        if not input_exists(directory):
            return None
        if not input_is_dir(directory):
            raise ValueError(f'Model source must be a service directory: {directory}')
        for file in (template, *parameter_files(directory)):
            safe(root, file)
            if not input_is_file(file):
                raise ValueError(f'required YAML Model input missing: {file}')
        safe(root, directory/'observed.json')
        return paths


def read_observed(directory):
    """Only an absent file means unobserved; malformed data and read errors propagate."""
    path = directory/'observed.json'
    try:
        text = input_bytes(path).decode('utf-8')
    except FileNotFoundError:
        return {'version':1, 'values':{}}, {}
    return json_read(text), {path:text}


def validate_observed(desired, observed):
    if not isinstance(observed, dict):
        raise ValueError('observed.values must be an object')
    for key, value in observed.items():
        if not isinstance(key, str) or not re.fullmatch(r'observed\.row\.[A-Za-z0-9_-]+\.value', key) or not isinstance(value, str):
            raise ValueError(f'invalid observed key/value: {key}')
        if 'desired.'+key.removeprefix('observed.') not in desired:
            raise ValueError(f'orphan observed key: {key}')
        properties(f'{key}={value}\n')
        if any(c in value for c in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029'):
            raise ValueError(f'observed value must be one line: {key}')


def restore_observed(desired, observed):
    validate_observed(desired, observed)
    restored = dict(observed)
    for key in observed:
        prefix = key.removesuffix('value')
        for field in ('property', 'comment'):
            desired_key = 'desired.'+prefix.removeprefix('observed.')+field
            if desired_key in desired:
                restored[prefix+field] = desired[desired_key]
    return restored


def input_snapshot(path):
    """Guard missing optional observed files too, including producer dependencies."""
    from model_files import load_model
    files = load_model(path).files
    result = {p:text.encode('utf-8') for p,text in files.items()}
    for file in files:
        if file.name == 'parameters.yaml' and file.is_relative_to(source_paths(path)[0]/'model/parameters'):
            result.setdefault(file.parent/'observed.json', None)
    return result


def model_paths(root, environment=None, alias=None):
    """Enumerate service directories, including incomplete sources, without projections."""
    from import_scope import selected, model_path, readable
    identity = selected(root)
    if identity is not None:
        return sorted(model_path(root, item) for item in readable(root)
                      if environment in (None, item[0]) and alias in (None, item[1]) and
                      input_is_dir(root / 'model/parameters' / Path(*item)))
    result = []
    for directory in sorted(input_select(root/'model/parameters', '*/*/*')):
        env, target, service = directory.relative_to(root/'model/parameters').parts
        if environment is not None and env != environment or alias is not None and target != alias:
            continue
        if any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', item) for item in (env,target,service)):
            raise ValueError(f'invalid Model source identity: {directory}')
        if not input_is_dir(directory) or input_is_symlink(directory):
            raise ValueError(f'Model source must be a real service directory: {directory}')
        result.append(root/'model'/env/target/(service+'.properties'))
    return result


def save_parameters(path, parameters):
    """Preserve registered human format on every authorized input update."""
    registered = service_source(path)
    if registered is None:
        raise ValueError('parameters require a registered template consumer')
    root = registered[0]
    from task_contract import task_revision
    expected_task = task_revision(root)
    from import_guard import managed_source_write, source_write_context
    if managed_source_write(root, expected_task[0]):
        from model_sources import write_sources
        from import_sources import parameter_edit
        with source_write_context(root, expected_task[0]) as context:
            target = registered[2] / 'parameters.yaml'
            write_sources(context, {target: parameter_edit(context.snapshot.read(target).decode('utf-8'), parameters)})
        return
    with publication_lock(root):
        _, template, directory = service_source(path)
        from model_files import load_model
        inputs = input_snapshot(path)
        target = parameter_files(directory)[0]
        observed = read_observed(directory)[0]
        from model_parameter_inputs import parameter_text
        definitions, _ = parse_template(template)
        bindings = json_read(inputs[directory/'bindings.json'].decode('utf-8'))
        expand(template, parameters, observed, bindings, path.parent.parent.name)
        text = parameter_text(parameters, definitions, bindings)
        publish(root, {target:text}, inputs=inputs, expected_task=expected_task)


def create_service(path):
    """Validate explicit new YAML service inputs; no registration sidecar is needed."""
    from model_files import load_model
    paths = service_source(path)
    if paths is None:
        raise ValueError(f'new service requires explicit YAML inputs: {path}')
    with publication_lock(paths[0]):
        return load_model(path)


@input_scope
def publish_edit(root, directory):
    """Publish ordinary agent-edited sources for the exact Model-only update contract."""
    from import_sources import candidate_sources
    from task_contract import model_operation, task_path, paths_in
    from issue_gate import require_no_issues
    from sync_runtime import GenerationInputs
    from validation_cache import input_context, recording_inputs
    root = root.resolve()
    text = task_path(root).read_text(encoding='utf-8')
    operation = model_operation(text)
    if operation is None:
        raise ValueError('source publication requires an explicit Model-only /update operation')
    identity = operation.scope
    from import_guard import managed_source_write, source_write_context
    name = task_path(root).relative_to(root).as_posix()
    if managed_source_write(root, name):
        from model_sources import write_sources
        directory = Path(directory).absolute()
        if directory.is_relative_to(root) or directory.is_symlink() or not directory.is_dir():
            raise ValueError('IMPORT candidates must be a temporary directory outside the repository')
        with source_write_context(root, name) as context:
            output = {}
            for file in sorted(directory.rglob('*')):
                safe(directory, file)
                if file.is_file():
                    output[root / file.relative_to(directory)] = file.read_bytes().decode('utf-8')
            return [p.relative_to(root).as_posix() for p in write_sources(context, output)]
    with input_context(), publication_lock(root):
        snapshot = GenerationInputs(root)
        try:
            with recording_inputs(snapshot):
                direct = consumers(root, identity[1], identity[2])
                output = candidate_sources(root, directory, identity, preservation_consumers=direct)
                declared = paths_in(text, '## Modified files')
                if {file.relative_to(root).as_posix() for file in output} - declared:
                    raise ValueError('Model-only candidate is absent from Modified files')
                from validation_scope import active_scope
                if active_scope(root) is None or not direct <= active_scope(root):
                    raise ValueError('include every shared consumer in Model-only Validation scope')
                require_no_issues(root, direct)
                for file, content in list(output.items()):
                    if file.name == 'observed.json' and json_read(content) == {'version': 1, 'values': {}}:
                        output[file] = None
                publish(root, output, inputs=snapshot.contents, expected_task=snapshot.expected_task)
                return sorted(file.relative_to(root).as_posix() for file in output)
        finally:
            snapshot.close()


class Definition(NamedTuple):
    parameters: dict
    resources: set
    rows: dict
    values: dict
    locations: dict
    retained_displays: set
    optional: dict
    optional_json: dict
    choices: dict


def parse_template(path, source_files=None):
    from model_files import model_parts
    path = Path(path).absolute()
    source_files = source_files or {}
    text = source_files[path] if path in source_files else input_bytes(path).decode('utf-8')
    if source_files:
        from model_files import INDEX_HEADER, PART_PREFIX
        lines = text.splitlines()
        parts = [path.parent / line.removeprefix(PART_PREFIX) for line in lines if line.startswith(PART_PREFIX)] if lines and lines[0] == INDEX_HEADER else [path]
        for number, part in enumerate(parts, 1):
            if part != path and part != path.parent / path.stem / f'part-{number:03d}.properties':
                raise ValueError('unsafe planned template part')
    else:
        parts = model_parts(path)
    files = tuple((p, source_files[p] if p in source_files else input_bytes(p).decode('utf-8')) for p in dict.fromkeys([path, *parts]))
    definitions = _parse_template(path, tuple(parts), files)
    # Definitions are read-only; expansion adds dependencies only to its own file map.
    return definitions, dict(files)


@memoized
def _parse_template(path, parts, contents):
    files = dict(contents)
    if any(len(text.splitlines()) > 600 for text in files.values()):
        raise ValueError('template entry/parts must be at most 600 lines; use the existing index/part format')
    lines = [(p, n, line) for p in parts
             for n, line in enumerate(files[p].splitlines(), 1)]
    if not lines or lines[0][2] != '# model-template: 1':
        raise ValueError(f'template header required: {path}')
    definitions, current, shared = {}, None, {}
    for file, number, line in lines[1:]:
        if line.startswith('# definition: '):
            name = line.removeprefix('# definition: ')
            if current is not None or not NAME.fullmatch(name) or name in definitions:
                raise ValueError(f'invalid/duplicate definition: {file}:{number}: {name}')
            current = Definition({}, set(), {}, {}, {}, set(), {}, {}, {})
            definitions[name] = current
        elif line == '# end-definition':
            if current is None:
                raise ValueError('end-definition without definition')
            current = None
        elif line.startswith(('# optional: ', '# optional-json: ')):
            declaration, payload = line[2:].split(': ', 1)
            words = payload.split()
            expected = 2 if declaration == 'optional' else 3
            if current is None or len(words) != expected or not NAME.fullmatch(words[-1]):
                raise ValueError(f'invalid optional declaration: {file}:{number}')
            target = current.optional if declaration == 'optional' else current.optional_json
            key = words[0] if declaration == 'optional' else tuple(words[:2])
            if key in target:
                raise ValueError(f'duplicate optional declaration: {file}:{number}')
            target[key] = words[-1]
        elif line.startswith('# choice: '):
            key, payload = line.removeprefix('# choice: ').split(' ', 1)
            choice = json_read(payload)
            if current is None or not isinstance(choice, dict) or set(choice) not in ({'parameter', 'value'}, {'parameter', 'value', 'pointer'}) or not isinstance(choice['parameter'], str) or not NAME.fullmatch(choice['parameter']):
                raise ValueError(f'invalid field choice: {file}:{number}')
            if 'pointer' in choice and not isinstance(choice['pointer'], str):
                raise ValueError('field choice pointer must be a string')
            identity = key, choice.get('pointer'), choice['parameter']
            if identity in current.choices:
                raise ValueError('duplicate field choice')
            current.choices[identity] = choice['value']
            current.locations[('choice', *identity)] = (file, number)
        elif line.startswith('# retained-display:'):
            identity = line.removeprefix('# retained-display:').strip()
            if current is None or not re.fullmatch(r'[0-9]{3,}', identity) or identity in current.retained_displays:
                raise ValueError(f'invalid/duplicate retained display: {file}:{number}')
            current.retained_displays.add(identity)
        elif line.startswith('# input: '):
            from model_parameter_inputs import schema
            name, payload = line.removeprefix('# input: ').split(' ', 1)
            spec = schema(json_read(payload))
            if definitions or not NAME.fullmatch(name) or name in shared or name.startswith(('Id_', 'Anchor_')):
                raise ValueError('invalid/duplicate service input')
            if spec.get('source', 'service') not in {'service', 'consumer.environment', 'consumer.executionAccountId'} or spec.get('internal') or spec.get('format'):
                raise ValueError('shared inputs require raw service/consumer values')
            shared[name] = {**spec, 'source': spec.get('source', 'service')}
        elif line.startswith('# reference: '):
            from model_parameter_inputs import reference_schema
            name, payload = line.removeprefix('# reference: ').split(' ', 1)
            if current is None or not NAME.fullmatch(name) or name in current.parameters or name in shared or name.startswith(('Id_', 'Anchor_')):
                raise ValueError('invalid/duplicate template reference')
            current.parameters[name] = reference_schema(json_read(payload))
        elif line.startswith(('# parameter: ', '# internal: ', '# resource: ', '# row: ')):
            if current is None:
                raise ValueError('declaration outside definition')
            declaration, payload = line[2:].split(': ', 1)
            words = payload.split(maxsplit=1) if declaration in {'parameter', 'internal'} else payload.split()
            target = getattr(current, {'parameter':'parameters','internal':'parameters','resource':'resources','row':'rows'}[declaration])
            count = 1 if declaration == 'resource' else 2
            if len(words) != count or not NAME.fullmatch(words[0]) or words[0] in target or words[0] in shared:
                raise ValueError(f'invalid/duplicate {declaration}: {file}:{number}')
            if declaration in {'parameter', 'internal'}:
                from model_parameter_inputs import schema
                spec = schema(json_read(words[1])) if words[1].startswith('{') else words[1]
                if isinstance(spec, dict) and 'source' in spec:
                    raise ValueError('explicit input sources belong to # input or # reference declarations')
                if declaration == 'internal':
                    if not isinstance(spec, str) or spec not in TYPES:
                        raise ValueError('internal declaration requires a primitive type')
                    spec = {'type':spec, 'description':'内部対応', 'required':True, 'internal':True}
                if isinstance(spec, str) and spec not in TYPES or words[0].startswith(('Id_', 'Anchor_')):
                    raise ValueError(f'invalid parameter type/name: {words}')
                target[words[0]] = spec
            elif declaration == 'resource':
                target.add(words[0])
            else:
                target[words[0]] = words[1]
        elif not line.strip() or line.startswith('#'):
            if line.startswith('# model-template:'):
                raise ValueError('duplicate template header')
        else:
            if current is None:
                raise ValueError('property outside definition')
            parsed = properties(line)
            key, value = next(iter(parsed.items()))
            if key.startswith('observed.') or key in current.values:
                raise ValueError(f'observed/duplicate template property: {key}')
            current.values[key] = value
            current.locations[key] = (file, number)
    if current is not None or not definitions:
        raise ValueError('unterminated/empty template')
    shared_used = set()
    for name, definition in definitions.items():
        if set(definition.rows.values()) - definition.resources:
            raise ValueError(f'unknown local row owner: {name}')
        used = set()
        for (key, pointer, selector), value in definition.choices.items():
            if key not in definition.values:
                raise ValueError('field choice requires a declared property')
            if any(other_key == key and other_pointer != pointer and
                   (pointer is None or other_pointer is None or
                    pointer.startswith(other_pointer + '/') or other_pointer.startswith(pointer + '/'))
                   for other_key, other_pointer, _ in definition.choices):
                raise ValueError('field choice pointers must not overlap')
            if pointer is not None:
                json_pointer(template_document(key, definition.values[key]), pointer)
            elif not isinstance(value, str):
                raise ValueError('Properties field choice requires a string expression')
            elif any(c in value for c in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029'):
                raise ValueError('Properties field choice must be one line')
            used.update(variables(json_text(value)))
            used.add(selector)
        for key, selector in definition.optional.items():
            if key not in definition.values:
                raise ValueError(f'optional property is undeclared: {name}/{key}')
            used.add(selector)
        for (key, pointer), selector in definition.optional_json.items():
            if key not in definition.values:
                raise ValueError('optional JSON requires a declared document property')
            json_pointer(template_document(key, definition.values[key]), pointer)
            if any(other_key == key and other_pointer != pointer and
                   (pointer.startswith(other_pointer + '/') or other_pointer.startswith(pointer + '/'))
                   for other_key, other_pointer in definition.optional_json):
                raise ValueError('optional JSON pointers must not overlap')
            used.add(selector)
        selectors = set(definition.optional.values()) | set(definition.optional_json.values()) | {selector for _, _, selector in definition.choices}
        for selector in selectors:
            spec = definition.parameters.get(selector)
            if not isinstance(spec, dict) or spec.get('type') != 'boolean':
                raise ValueError(f'optional selector requires a boolean parameter: {name}/{selector}')
        for key, value in definition.values.items():
            remap_key(key, definition, {r:r for r in definition.resources}, {r:r for r in definition.rows})
            used.update(variables(value))
            if key.endswith('.document'):
                try:
                    json_read(value)
                except ValueError as error:
                    file, line = definition.locations[key]
                    raise ValueError(f'invalid JSON template document: {file}:{line}: {key}: {error}') from error
        for parameter in used & shared.keys():
            definition.parameters[parameter] = shared[parameter]
            shared_used.add(parameter)
        declared = set(definition.parameters) | {prefix + r for r in definition.resources for prefix in ('Id_', 'Anchor_')}
        if used - declared:
            raise ValueError(f'undeclared template variables: {name}: {sorted(used-declared)}')
        if set(definition.parameters) - used:
            raise ValueError(f'unused parameter declarations: {name}: {sorted(set(definition.parameters)-used)}')
        for parameter, spec in definition.parameters.items():
            if isinstance(spec, dict) and spec.get('format') == 'literal' and any(
                    parameter in variables(value) and (key.endswith('.document') or not TOKEN.fullmatch(value))
                    for key, value in definition.values.items()):
                raise ValueError('literal format requires an entire scalar value, not a string fragment/JSON document')
            if isinstance(spec, dict) and spec.get('format') == 'literal' and any(
                    parameter in variables(json_text(value)) and
                    (pointer is not None or key.endswith('.document') or not isinstance(value, str) or not TOKEN.fullmatch(value))
                    for (key, pointer, _), value in definition.choices.items()):
                raise ValueError('literal format requires an entire scalar field choice')
        for local in definition.resources:
            if f'desired.resource.{local}.resourceType' not in definition.values or f'desired.resource.{local}.anchor' not in definition.values:
                raise ValueError(f'local resource requires resourceType and anchor: {name}/{local}')
    if shared.keys() - shared_used:
        raise ValueError(f'unused service inputs: {sorted(shared.keys()-shared_used)}')
    return definitions


def json_pointer(document, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/') or re.search(r'~(?![01])', pointer):
        raise ValueError('optional JSON requires a non-root JSON pointer')
    parts = [part.replace('~1', '/').replace('~0', '~') for part in pointer[1:].split('/')]
    parent = document
    try:
        for part in parts[:-1]:
            if isinstance(parent, list) and not re.fullmatch(r'0|[1-9][0-9]*', part):
                raise ValueError('invalid list index')
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        if isinstance(parent, list) and not re.fullmatch(r'0|[1-9][0-9]*', parts[-1]):
            raise ValueError('invalid list index')
        key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
        parent[key]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError(f'invalid optional JSON pointer: {pointer}') from error
    return parent, key


def template_document(key, value):
    if key.endswith('.document'):
        return json_read(value)
    if key.endswith('.value') and value.startswith('`') and value.endswith('`'):
        document = json_read(value[1:-1])
        if isinstance(document, (dict, list)):
            return document
    raise ValueError('JSON field selection requires a document or literal JSON object/array')


def template_document_text(key, document):
    text = json_text(document)
    return text if key.endswith('.document') else '`'+text+'`'


def bound_definition(definition, supplied):
    """Select explicitly configured fields, without interpreting an environment name."""
    from model_parameter_inputs import check_type
    selectors = set(definition.optional.values()) | set(definition.optional_json.values()) | {selector for _, _, selector in definition.choices}
    for selector in selectors:
        if selector not in supplied:
            raise ValueError(f'missing required parameter: {selector}; optional selector requires an explicit boolean')
        check_type(definition.parameters[selector], supplied[selector], f'optional selector requires an explicit boolean: {selector}')
    values = {key: value for key, value in definition.values.items()
              if key not in definition.optional or supplied[definition.optional[key]]}
    selected = set()
    documents, origins = {}, {}
    locations = dict(definition.locations)

    def origin_tree(value, location):
        if isinstance(value, dict):
            return {key: origin_tree(item, location) for key, item in value.items()}
        if isinstance(value, list):
            return [origin_tree(item, location) for item in value]
        return location

    def record_origins(key, value, pointer=''):
        if isinstance(value, dict):
            for name, item in value.items():
                record_origins(key, item, pointer + '/' + name.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                record_origins(key, item, pointer + '/' + str(index))
        elif value is not None:
            locations[key, pointer] = value

    for (key, pointer, selector), value in definition.choices.items():
        if key not in values or not supplied[selector]:
            continue
        if (key, pointer) in selected:
            raise ValueError(f'ambiguous field choices: {key}/{pointer}')
        selected.add((key, pointer))
        location = locations.get(('choice', key, pointer, selector), locations.get(key))
        if pointer is None:
            values[key] = value
            if location is not None:
                locations[key] = location
        else:
            document = documents.setdefault(key, template_document(key, values[key]))
            origin = origins.setdefault(key, origin_tree(template_document(key, values[key]), locations.get(key)))
            parent, item = json_pointer(document, pointer)
            parent[item] = value
            parent, item = json_pointer(origin, pointer)
            parent[item] = origin_tree(value, location)
    values.update({key: template_document_text(key, document) for key, document in documents.items()})
    removals, origin_removals = {}, {}
    for (key, pointer), selector in definition.optional_json.items():
        if key in values and not supplied[selector]:
            if key not in removals:
                removals[key] = template_document(key, values[key]), []
            document, operations = removals[key]
            operations.append(json_pointer(document, pointer))
            if key in origins:
                origin_removals.setdefault(key, []).append(json_pointer(origins[key], pointer))
    # Resolve all pointers before removing list elements; reverse indexes retain identity.
    for key, (document, operations) in removals.items():
        for parent, item in sorted(operations, key=lambda operation: str(operation[1]).zfill(20), reverse=True):
            del parent[item]
        values[key] = template_document_text(key, document)
        for parent, item in sorted(origin_removals.get(key, ()), key=lambda operation: str(operation[1]).zfill(20), reverse=True):
            del parent[item]
    for key, origin in origins.items():
        record_origins(key, origin)
    resources = {key.split('.')[2] for key in values if key.startswith('desired.resource.')}
    rows = {key.split('.')[2] for key in values if key.startswith('desired.row.')}
    used = selectors | set().union(*(variables(value) for value in values.values()))
    parameters = {name: spec for name, spec in definition.parameters.items() if name in used}
    return definition._replace(parameters=parameters, resources=resources, locations=locations,
                               rows={row: owner for row, owner in definition.rows.items() if row in rows}, values=values)


def variables(value):
    if '{{' in re.sub(r'\{\{resolve:[^{}\r\n]+\}\}', '', value):
        raise ValueError('Mustache curly syntax is forbidden except AWS dynamic references')
    names = set(TOKEN.findall(value))
    remainder = TOKEN.sub('', value)
    if '<<' in remainder or '>>' in remainder:
        raise ValueError('only <<ParameterName>> variables are permitted; forbidden template syntax')
    return names


def remap_key(key, definition, resources, rows):
    parts = key.split('.')
    if len(parts) >= 3 and parts[:2] == ['display','resource'] and parts[2] in definition.retained_displays:
        if len(parts) != 4 or parts[3] not in {'comment','label'}:
            raise ValueError(f'retained display permits only comment/label metadata: {key}')
        return key
    if len(parts) >= 4 and parts[:2] in (['desired','resource'], ['display','resource']):
        if parts[2] not in definition.resources:
            raise ValueError(f'undeclared local resource: {key}')
        parts[2] = resources[parts[2]]
    elif len(parts) >= 4 and parts[:2] == ['desired','row']:
        if parts[2] not in definition.rows:
            raise ValueError(f'undeclared local row: {key}')
        parts[2] = rows[parts[2]]
    return '.'.join(parts)


def resolve(value, context, *, structured=False):
    if isinstance(value, dict):
        if any(variables(key) for key in value):
            raise ValueError('JSON object keys cannot be parameterized')
        return {key: resolve(item, context, structured=True) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, context, structured=True) for item in value]
    if not isinstance(value, str):
        return value
    names = variables(value)
    if names - context.keys():
        raise ValueError(f'undefined variables: {sorted(names-context.keys())}')
    match = TOKEN.fullmatch(value)
    if structured and match:
        return context[match[1]]
    if any(not isinstance(context[name], str) for name in names):
        if not structured and match:
            return json_text(context[match[1]])
        raise ValueError('non-string parameter embedded in string')
    if not names:
        return value
    try:
        import pystache
    except ImportError as error:
        raise ValueError('install framework/scripts/requirements.txt to expand templates') from error
    parsed = pystache.parse(value, delimiters=('<<', '>>'))
    return pystache.Renderer(escape=lambda text: text, missing_tags='strict').render(parsed, context)


def prepare_instances(definitions, parameters, observed):
    exact(parameters, {'version','instances'}, 'service parameters')
    exact(observed, {'version','values'}, 'observed')
    if type(parameters['version']) is not int or parameters['version'] != 1 or type(observed['version']) is not int or observed['version'] != 1:
        raise ValueError('unsupported source version')
    if not isinstance(parameters['instances'], list) or not isinstance(observed['values'], dict):
        raise ValueError('instances must be an array and observed.values an object')
    prepared, instance_ids, resource_ids, row_ids = [], set(), set(), set()
    retained_displays = set()
    for instance in parameters['instances']:
        exact(instance, {'id','definition','resources','rows','parameters'}, 'instance')
        identity, name = instance['id'], instance['definition']
        if not isinstance(identity, str) or not NAME.fullmatch(identity) or identity in instance_ids:
            raise ValueError(f'invalid/duplicate instance id: {identity}')
        if not isinstance(name, str) or name not in definitions:
            raise ValueError(f'unknown definition: {name}')
        instance_ids.add(identity)
        definition = bound_definition(definitions[name], instance['parameters'])
        for mapping, locals_ in ((instance['resources'], definition.resources), (instance['rows'], definition.rows)):
            if not isinstance(mapping, dict) or set(mapping) != set(locals_) or any(not isinstance(v, str) or not IDENTITY.fullmatch(v) for v in mapping.values()):
                raise ValueError(f'invalid/missing local ID map: {identity}')
        for local, owner in definition.rows.items():
            if instance['rows'][local].rpartition('-')[0] != instance['resources'][owner]:
                raise ValueError(f'row owner mismatch: {identity}/{local}')
        for mapping, seen in ((instance['resources'], resource_ids), (instance['rows'], row_ids)):
            if len(set(mapping.values())) != len(mapping) or set(mapping.values()) & seen:
                raise ValueError(f'duplicate fixed Model identity: {identity}')
            seen.update(mapping.values())
        exact(instance['parameters'], definition.parameters, f'parameters for {identity}')
        if retained_displays & definition.retained_displays:
            raise ValueError('duplicate retained display identity')
        retained_displays.update(definition.retained_displays)
        prepared.append((instance,definition))
    if retained_displays & resource_ids:
        raise ValueError('retained display must not identify an active resource')
    return prepared


def expand(template, parameters, observed, bindings, environment=None, *, _parsed=None):
    from model_parameter_inputs import human_instances
    result = expand_inputs(template, parameters, observed, bindings, environment, human_instances, _parsed)
    validate_local(result[0])
    return result


def expand_for_edit(template, parameters, observed, bindings, environment=None, *, _parsed=None, display=False):
    from model_parameter_inputs import edit_instances
    from functools import partial
    return expand_inputs(template, parameters, observed, bindings, environment, partial(edit_instances, display=display), _parsed)


def expand_inputs(template, parameters, observed, bindings, environment, bind_inputs, _parsed):
    definitions, source_files = parse_template(template) if _parsed is None else _parsed
    files = dict(source_files)
    stack_bindings = None
    if isinstance(bindings, dict) and 'stacks' in bindings:
        if template.name != 'cloudformation-stacks.properties.tpl':
            raise ValueError('stack bindings belong only to cloudformation-stacks')
        bindings = dict(bindings)
        stack_bindings = bindings.pop('stacks')
        if not isinstance(stack_bindings, dict):
            raise ValueError('stack bindings must be an object')
    parameters, references = bind_inputs(template, parameters, bindings, definitions, environment)
    files.update(references)
    prepared = prepare_instances(definitions, parameters, observed)
    values, provenance = {}, {}
    for instance, definition in prepared:
        context = dict(instance['parameters'])
        context.update({'Id_'+k:v for k,v in instance['resources'].items()})
        for local in definition.resources:
            raw = definition.values[f'desired.resource.{local}.anchor']
            # Local anchors may reference explicit parameters/IDs, never recursively other anchors.
            context['Anchor_'+local] = resolve(raw,context)
        for key, raw in definition.values.items():
            output_key = remap_key(key,definition,instance['resources'],instance['rows'])
            if output_key in values:
                raise ValueError(f'duplicate expanded Model key: {output_key}')
            structured = key.endswith('.document') or any(selected_key == key for selected_key, _ in definition.optional_json) or any(selected_key == key and pointer is not None for selected_key, pointer, _ in definition.choices)
            value = template_document_text(key, resolve(template_document(key, raw), context, structured=True)) if structured else resolve(raw,context)
            if not isinstance(value,str) or len(value.splitlines()) > 1 or any(c in value for c in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029'):
                raise ValueError(f'Properties scalar must be one line: {output_key}; use a JSON document string')
            values[output_key] = value
            file, line = definition.locations[key]
            dependencies = variables(raw)
            dependencies.update(selector for selected_key, selector in definition.optional.items() if selected_key == key)
            dependencies.update(selector for (selected_key, _), selector in definition.optional_json.items() if selected_key == key)
            dependencies.update(selector for selected_key, _, selector in definition.choices if selected_key == key)
            for local in definition.resources:
                if 'Anchor_'+local in dependencies:
                    dependencies |= variables(definition.values[f'desired.resource.{local}.anchor'])
            key_parts = key.split('.')
            traced_resources = {local: identity for local, identity in instance['resources'].items()
                                if 'Id_'+local in dependencies or 'Anchor_'+local in dependencies or
                                len(key_parts) >= 4 and key_parts[1] == 'resource' and key_parts[2] == local}
            traced_rows = {local: identity for local, identity in instance['rows'].items()
                           if len(key_parts) >= 4 and key_parts[1] == 'row' and key_parts[2] == local}
            provenance[output_key] = {'template':str(file),'line':line,'definition':instance['definition'],
                                     'key':key,'instance':instance['id'],'parameters':sorted(dependencies&instance['parameters'].keys()), 'resources':traced_resources, 'rows':traced_rows}
            leaf_locations = {position[1]: {'file': str(location[0]), 'line': location[1]}
                              for position, location in definition.locations.items()
                              if isinstance(position, tuple) and len(position) == 2 and position[0] == key}
            if leaf_locations:
                provenance[output_key]['sourceLocations'] = leaf_locations
    for key, value in restore_observed(values, observed['values']).items():
        values[key] = value
        desired_key = 'desired.'+key.removeprefix('observed.')
        provenance[key] = ({**provenance[desired_key], 'derivedFrom':desired_key}
                           if key.endswith(('.property', '.comment')) else {'observed':key})
    from model_projection import document_sha256
    for key, value in list(values.items()):
        if key.startswith('desired.row.') and key.endswith('.document'):
            hash_key = key.removesuffix('.document')+'.artifactSha256'
            values[hash_key] = document_sha256(json_read(value))
            provenance[hash_key] = {**provenance[key], 'derivedFrom': key}
    if stack_bindings is not None:
        from model_core import stack_model
        stacks = dict(stack_model(values)[1])
        exact(stack_bindings, stacks, 'fixed stack bindings')
        names = set()
        current = {stack['name']: identity for identity, stack in stacks.items()}
        for identity, name in stack_bindings.items():
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,127}', name):
                raise ValueError('invalid fixed stack name')
            if name in names or name in current and current[name] != identity:
                raise ValueError('conflicting fixed stack binding')
            names.add(name)
    return dict(sorted(values.items())), provenance, files


def validate_local(values):
    from model_files import resource_row_index
    resource_row_index(values)
    resources = entries(values, 'desired.resource.')
    anchors = [resource.get('anchor') for _,resource in resources]
    if None in anchors or len(anchors) != len(set(anchors)):
        raise ValueError('missing/duplicate resource anchor')
    parents = {}
    for identity,resource in resources:
        if 'parentReference' in resource:
            match = LINK.fullmatch(resource['parentReference'])
            if not match or match[2] or match[3] not in anchors:
                raise ValueError('broken local parentReference')
            parents[resource['anchor']] = match[3]
    for anchor in parents:
        seen = set()
        current = anchor
        while current in parents:
            if current in seen:
                raise ValueError('cyclic parentReference')
            seen.add(current); current = parents[current]
    for _,row in entries(values,'desired.row.'):
        match = LINK.fullmatch(row.get('value',''))
        if match and not match[2] and match[3] not in anchors:
            raise ValueError('broken same-service reference')


class Expansion(NamedTuple):
    values: dict
    provenance: dict
    files: dict




@scoped_read
@memoized
def _reference_inputs(path, _context=None):
    """Validate one producer once per immutable input snapshot."""
    from model_parameter_inputs import human_instances, yaml_read
    registered = service_source(path)
    if registered is None:
        raise ValueError(f'YAML Model inputs missing: {path}')
    root, template, directory = registered
    with publication_lock(root):
        definitions, files = parse_template(template)
        selected = parameter_files(directory)
        for file in selected:
            safe(root, file)
            files[file] = input_bytes(file).decode('utf-8')
        observed, observed_files = read_observed(directory)
        files.update(observed_files)
        parameters = yaml_read(files[directory/'parameters.yaml'])
        bindings = json_read(files[directory/'bindings.json'])
        parameters, dependencies = human_instances(template, parameters, bindings, definitions,
            path.parent.parent.name, resolve_references=False)
        files.update(dependencies)
        prepared = prepare_instances(definitions, parameters, observed)
        fields = {}
        for instance, definition in prepared:
            for key, value in definition.values.items():
                output = remap_key(key, definition, instance['resources'], instance['rows'])
                if output in fields:
                    raise ValueError(f'duplicate expanded Model key: {output}')
                fields[output] = instance, definition, value
        validate_observed(fields, observed['values'])
        return registered, (definitions, files, observed, parameters, bindings, fields)


@scoped_read
@memoized
def reference_values(path, identity, kind, mode, _context=None):
    """Resolve selected producer attributes, without expanding unrelated references."""
    from model_files import LoadedModel
    from model_parameter_inputs import parameter_value
    path = path.absolute()
    registered, inputs = _reference_inputs(path)
    root, template, directory = registered
    with publication_lock(root):
        definitions, files, observed, parameters, bindings, fields = inputs
        files = dict(files)
        parameter_values, values = {}, {}

        def context_for(instance, value):
            definition = definitions[instance['definition']]
            context = {}
            for name in variables(value):
                if name.startswith('Id_'):
                    context[name] = instance['resources'][name[3:]]
                elif name.startswith('Anchor_'):
                    context[name] = field_value('desired.resource.'+instance['resources'][name[7:]]+'.anchor')
                elif name in definition.parameters:
                    key = instance['id'], name
                    if key not in parameter_values:
                        parameter_values[key] = parameter_value(template, instance, name, parameters['instances'],
                            bindings, definitions, path.parent.parent.name, files, context_for)
                    context[name] = parameter_values[key]
            return context

        def field_value(key):
            if key in values:
                return values[key]
            chain = getattr(_local, 'reference_chain', ())
            dependency = str(path), key
            if dependency in chain:
                route = ' -> '.join(f'{p}:{attribute}' for p, attribute in (*chain, dependency))
                raise ValueError('cyclic attribute reference: '+route)
            _local.reference_chain = (*chain, dependency)
            try:
                instance, definition, value = fields[key]
                value = resolve(value, context_for(instance, value))
                if not isinstance(value, str) or any(c in value for c in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029'):
                    raise ValueError(f'Properties scalar must be one line: {key}')
                values[key] = value
                return value
            finally:
                _local.reference_chain = chain

        type_key = f'desired.resource.{identity}.resourceType'
        stack_name = f'desired.stack.{identity}.name'
        if kind == 'CloudFormation.Stack' and stack_name in fields:
            if type_key in fields:
                raise ValueError(f'ambiguous resource/stack reference: {identity}')
            if mode != 'name':
                raise ValueError('stack reference requires format:name')
            prefix = f'desired.stack.{identity}.'
            exact({key.removeprefix(prefix): None for key in fields if key.startswith(prefix)},
                  {'name', 'template', 'parameters', 'deployOrder'}, 'stack reference target')
            if 'stacks' in bindings:
                identities = {key.split('.')[2] for key in fields
                              if key.startswith('desired.stack.') and key.endswith('.name')}
                exact(bindings['stacks'], identities, 'fixed stack bindings')
                names = list(bindings['stacks'].values())
                if any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,127}', name) for name in names):
                    raise ValueError('invalid fixed stack name')
                if len(names) != len(set(names)):
                    raise ValueError('conflicting fixed stack binding')
            name = field_value(stack_name)
            if not name or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,127}', name):
                raise ValueError('reference producer requires a valid stack name')
            if 'stacks' in bindings and any(bound == name and key != identity for key, bound in bindings['stacks'].items()):
                raise ValueError('conflicting fixed stack binding')
            return LoadedModel('', values, {}, files)
        if type_key not in fields or field_value(type_key) != kind:
            return LoadedModel('', values, {}, files)
        if isinstance(mode, tuple) and mode[0] == 'physical':
            from model_core import LINK
            attributes = set(mode[1])
            for leaf in ('anchor', 'logicalId', 'resourceMode'):
                key = f'desired.resource.{identity}.' + leaf
                if key in fields:
                    field_value(key)
            for key in fields:
                if not key.startswith(f'desired.row.{identity}-') or not key.endswith('.property'):
                    continue
                prop = field_value(key)
                if prop not in attributes:
                    continue
                value_key = key.removesuffix('.property') + '.value'
                observed_key = value_key.replace('desired.', 'observed.', 1)
                if observed_key in observed['values']:
                    values[observed_key] = observed['values'][observed_key]
                instance, definition, raw = fields[value_key]
                # Identity lookup never follows another resource's logical value.
                if not LINK.fullmatch(raw) and not any(
                        definition.parameters.get(name, {}).get('type') == 'reference'
                        for name in variables(raw)):
                    field_value(value_key)
            return LoadedModel('', values, {}, files)
        if mode not in {'name', 'identifier'}:
            field_value(f'desired.resource.{identity}.anchor')
            for leaf in ('logicalId', 'resourceMode', 'cfn-logicalId') if mode == 'preservation' else ():
                key = f'desired.resource.{identity}.' + leaf
                if key in fields:
                    field_value(key)
        if mode == 'identifier':
            selected_observed = {key: value for key, value in observed['values'].items()
                                 if key.startswith(f'observed.row.{identity}-')}
            for key in selected_observed:
                for field in ('property', 'comment'):
                    desired = 'desired.'+key.removeprefix('observed.').removesuffix('value')+field
                    if desired in fields:
                        values[key.removesuffix('value')+field] = field_value(desired)
            values.update(selected_observed)
        if mode == 'anchor':
            return LoadedModel('', values, {}, files)
        for key in fields:
            if not key.startswith(f'desired.row.{identity}-') or not key.endswith('.property'):
                continue
            property_name = field_value(key)
            if mode == 'identifier':
                from model_references import catalog_outputs
                if property_name in catalog_outputs(root, kind):
                    field_value(key.removesuffix('.property')+'.value')
                continue
            elif kind != 'KMS.Key' or mode == 'name':
                if property_name.rsplit('.', 1)[0] == kind and property_name.endswith(REFERENCE_NAME_SUFFIXES):
                    field_value(key.removesuffix('.property')+'.value')
        return LoadedModel('', values, {}, files)


@scoped_read
def load_expansion(path, _context=None):
    expanded = _load_expansion(path, _context)
    return expanded._replace(files=dict(expanded.files)) if expanded is not None else None


@memoized
def _load_expansion(path, _context=None):
    return load_sources(path, expand)


def load_for_edit(path, source_files=None, *, display=False):
    """Read only this service; input constraints and reference checks belong to validation."""
    from functools import partial
    return load_sources(path, partial(expand_for_edit, display=display), source_files)


def load_sources(path, expander, source_files=None):
    source_files = source_files or {}
    registered = service_source(path)
    if registered is None:
        return None
    root, template, directory = registered
    with publication_lock(root):
        selected = parameter_files(directory)
        for file in (template, *selected, directory / 'observed.json'):
            safe(root,file)
        inputs = {p: source_files[p] if p in source_files else input_bytes(p).decode('utf-8') for p in selected}
        observed_path = directory / 'observed.json'
        if observed_path in source_files:
            raw = source_files[observed_path]
            observed, observed_files = (json_read(raw), {observed_path: raw}) if raw is not None else ({'version': 1, 'values': {}}, {})
        else:
            observed, observed_files = read_observed(directory)
        inputs.update(observed_files)
        from model_parameter_inputs import yaml_read
        parameters = yaml_read(inputs[selected[0]])
        bindings = json_read(inputs[selected[1]])
        parsed = parse_template(template, source_files)
        values, provenance, files = expander(template,parameters,observed,bindings,path.parent.parent.name, _parsed=parsed)
        files.update(inputs)
        definitions = parsed[0]
        execution_account = None
        if any(isinstance(spec, dict) and spec.get('source') == 'consumer.executionAccountId'
               for definition in definitions.values() for spec in definition.parameters.values()):
            from model_parameter_inputs import consumer_execution_account
            execution_account = consumer_execution_account(template, path.parent.parent.name)
        for source in provenance.values():
            source['sourceFile'] = str(directory/'observed.json' if 'observed' in source else selected[0])
            if 'parameters' in source:
                definition = definitions[source['definition']]
                source['inputs'] = {name: {'description':definition.parameters[name]['description'],
                                          'value': (execution_account if definition.parameters[name].get('source') == 'consumer.executionAccountId' else
                                                    path.parent.parent.name if definition.parameters[name].get('source') == 'consumer.environment' else
                                                    parameters.get('parameters', {}).get(name, definition.parameters[name].get('default')) if definition.parameters[name].get('source') == 'service' else
                                                    parameters['instances'][source['instance']]['parameters'].get(name, definition.parameters[name].get('default'))),
                                          'source': definition.parameters[name].get('source', 'instance'),
                                          'type':definition.parameters[name]['type'], 'required':definition.parameters[name]['required'],
                                          'modelKey': source['key'],
                                          'constraints':definition.parameters[name].get('constraints', {}),
                                          **({'default':definition.parameters[name]['default']} if 'default' in definition.parameters[name] else {})}
                                    for name in source['parameters'] if not definition.parameters[name].get('internal') and definition.parameters[name].get('source') != 'template'}
                source['references'] = {name: definition.parameters[name] for name in source['parameters']
                                        if definition.parameters[name].get('source') == 'template'}
                source['bindingFile'] = str(selected[1])
                source['internalParameters'] = [name for name in source['parameters'] if definition.parameters[name].get('internal')]
                if source['inputs'] and all(s['source'] == 'consumer.executionAccountId' for s in source['inputs'].values()):
                    source['sourceFile'] = str(root/'project.json')
                elif source['instance'] not in parameters['instances']:
                    source['sourceFile'] = str(selected[1])
                if source['internalParameters'] and not source['inputs']:
                    source['sourceFile'] = str(selected[1])
                elif source['references'] and not source['inputs']:
                    source['sourceFile'] = str(template)
        return Expansion(values,provenance,files)


def observed_outputs(path, values):
    registered = service_source(path)
    if registered is None:
        return None
    _, _, directory = registered
    from model_files import load_model
    original = load_model(path).values
    if {k:v for k,v in original.items() if not k.startswith('observed.')} != {k:v for k,v in values.items() if not k.startswith('observed.')} :
        raise ValueError('observed writer cannot change design/template/parameters')
    observed = {}
    for key, value in values.items():
        if not key.startswith('observed.'):
            continue
        if key.endswith(('.property', '.comment')):
            if values.get('desired.'+key.removeprefix('observed.')) != value:
                raise ValueError(f'observed metadata differs from desired: {key}')
            if key.rsplit('.',1)[0]+'.value' not in values:
                raise ValueError(f'orphan observed metadata: {key}')
        else:
            observed[key] = value
    validate_observed(values, observed)
    output = {directory/'observed.json':json_text({'version':1,'values':observed})+'\n' if observed else None}
    return output


def source_inputs(path):
    from model_files import load_model
    with phase("dependency-model:" + "/".join(path.parts[-3:]), total=1):
        files = set(load_model(path).files)
        advance()
        return files


@input_scope
def affected(root, changed, *, before=None):
    changed = {Path(raw) for raw in changed}
    result, propagating = set(), set()
    for raw in changed:
        parts = Path(raw).parts
        if (parts[:2] == ('model', 'templates') and
                (len(parts) == 4 and parts[3].endswith('.properties.tpl') or
                 len(parts) == 5 and parts[3].endswith('.properties') and parts[4].endswith('.properties'))):
            filename = parts[3]
            service = filename.removesuffix('.tpl').removesuffix('.properties')
            targets = consumers(root,parts[2],service)
            result.update(targets)
            propagating.update(targets)
        elif (len(parts) == 6 and parts[:2] == ('model', 'parameters') and
                parts[5] in {'parameters.yaml', 'bindings.json', 'observed.json'}):
            result.add(tuple(parts[2:5]))
            propagating.add(tuple(parts[2:5]))
        elif len(parts) == 4 and source_paths(root/raw) is not None:
            result.add((parts[1], parts[2], parts[3].removesuffix('.properties')))
            propagating.add((parts[1], parts[2], parts[3].removesuffix('.properties')))
    from model_impact import dependency_impact
    return dependency_impact(root, changed, result, propagating, before=before)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--alias',required=True)
    parser.add_argument('--service',required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--affected',action='store_true')
    mode.add_argument('--create',action='store_true',help='validate YAML/bindings for a new service; absent observed means unobserved')
    mode.add_argument('--inputs',action='store_true',help='show human input definitions, current values and traced Model destinations')
    mode.add_argument('--publish-edit', type=Path, help='publish changed source candidates for a Model-only update contract')
    parser.add_argument('--environment')
    args=parser.parse_args()
    for name in (args.alias,args.service):
        if not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*',name):
            parser.error('invalid alias/service')
    if args.publish_edit is not None:
        from task_contract import model_operation, task_path
        root = args.repository_root.resolve()
        operation = model_operation(task_path(root).read_text(encoding='utf-8'))
        if operation is None or operation.scope != (args.environment, args.alias, args.service):
            parser.error('publish-edit selectors must match the exact Model-only update contract')
        for file in publish_edit(root, args.publish_edit):
            print(file)
        return 0
    if args.create:
        if not args.environment or not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', args.environment):
            parser.error('--create requires a valid --environment')
        create_service(args.repository_root.resolve()/'model'/args.environment/args.alias/(args.service+'.properties'))
        return 0
    for entry in sorted(consumers(args.repository_root.resolve(),args.alias,args.service)):
        if args.environment and entry[0] != args.environment:
            continue
        if args.affected:
            print('/'.join(entry))
        else:
            path = args.repository_root/'model'/entry[0]/entry[1]/(entry[2]+'.properties')
            expansion = load_expansion(path)
            displayed = {}
            for key, trace in expansion.provenance.items():
                for name, item in trace.get('inputs', {}).items():
                    identity = (item['source'] if item['source'] != 'instance' else trace['instance'], name)
                    info = displayed.setdefault(identity, {**item, 'modelKeys':[]})
                    info['modelKeys'].append(key)
            for (instance, name), item in displayed.items():
                print('/'.join(entry)+' / '+instance+' / '+name+': '+json_text(item))
    return 0


if __name__ == '__main__':
    # Shared readers import this module; use the same publication lock in CLI mode.
    from model_templates import main
    raise SystemExit(main())


def design_source_digest(path):
    registered = service_source(path)
    if registered is None:
        return ''
    _, template, directory = registered
    from model_files import load_model
    files = load_model(path).files
    return digest({str(p): text.encode('utf-8').hex() for p, text in files.items()
                   if p != directory/'observed.json'})


def authority_snapshot(root, environment, directory):
    from model_files import load_model
    return {p: data for entrance in model_paths(root, environment, directory)
            for p, data in input_snapshot(entrance).items()}


from import_scope import scoped_impact
affected = scoped_impact(affected)
