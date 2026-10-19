"""Exact import boundary shared by acquisition, publication and generation."""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
import hashlib
import json
from validation_cache import memoized

_scope = ContextVar('import_scope', default=None)
_consumers = ContextVar('import_local_consumers', default=None)
_reference = ContextVar('import_create_reference', default=None)
_views = ContextVar('import_generated_views', default=None)
_additions = ContextVar('import_new_reference_resources', default=frozenset())
_updates = ContextVar('import_updated_reference_properties', default=None)
_display_resources = ContextVar('import_preserved_reference_view', default=frozenset())


@contextmanager
def new_references(before, selected):
    """Resolve new resources and captured Properties of explicitly selected updates."""
    from model_core import entries
    resources = dict(entries(before.values, 'desired.resource.'))
    existing = set(selected) & resources.keys()
    if any(selected[rid].get('_action') not in {'refresh', 'replace'} or
           resources[rid].get('resourceMode') != 'IMPORT' for rid in existing):
        raise ValueError('IMPORT references require selected new Resource IDs')
    token = _additions.set(frozenset(set(selected) - existing))
    updates = _updates.set({rid: {prop for prop, capture in selected[rid]['properties'].items()
                                if capture.get('status') == 'captured'} for rid in existing})
    try:
        yield
    finally:
        _additions.reset(token)
        _updates.reset(updates)


@contextmanager
def preserved_reference_view(before):
    """After guarded source publication, resolve unchanged old selectors for display."""
    from model_core import entries
    token = _display_resources.set(frozenset(dict(entries(before.values, 'desired.resource.'))))
    try:
        yield
    finally:
        _display_resources.reset(token)


def resolves_reference(item, definition=None, name=None):
    if definition is None:
        return bool(set(item.get('resources', {}).values()) & (_additions.get() | _display_resources.get()))
    from model_templates import bound_definition, resolve, variables
    definition = bound_definition(definition, item['parameters'])
    uses = [key for key, raw in definition.values.items() if name in variables(raw)]
    for key in uses:
        if not key.startswith('desired.row.') or key.rsplit('.', 1)[1] not in {'value', 'document'}:
            return False
        rid = item['resources'].get(definition.rows[key.split('.')[2]])
        prop = resolve(definition.values[key.rsplit('.', 1)[0] + '.property'], item['parameters'])
        if rid not in (_additions.get() | _display_resources.get()) and prop not in (_updates.get() or {}).get(rid, set()):
            return False
    return bool(uses)


@contextmanager
def reference_reader(path):
    """A producer is read-only and always in the selected environment/target."""
    root = path.parents[3]
    identity = selected(root)
    if identity is not None and path.parent != model_path(root, identity).parent:
        raise ValueError('IMPORT reference is outside selected environment/target')
    token = _reference.set(path.absolute())
    try:
        yield
    finally:
        _reference.reset(token)


def selected(root, *, contract_file=None):
    if _scope.get() is not None:
        return _scope.get()
    from task_contract import contracts, task_path, contract_path
    records = contracts(root)
    if not records:
        return None
    path = contract_path(root, selected=contract_file) if contract_file is not None else task_path(root)
    name = path.relative_to(root).as_posix()
    # Select the current task and its IMPORT scope.
    if contract_file is None:
        return _selection(root, name, records.get(name, ''))
    return _selection(root, name, records.get(name, ''), contract_file)


@memoized
def _selection(root, name, text, contract_file=None):
    from task_contract import section
    if '- Workflow: `import`' not in section(text, '## Task contract'):
        return None
    import re
    targets = re.findall(r'^- IMPORT target: `([^`]+)`$', '\n'.join(section(text, '## Task contract')), re.M)
    if len(targets) > 1:
        raise ValueError('duplicate fixed IMPORT target')
    if targets:
        parts = tuple(targets[0].split('/'))
        if len(parts) != 3 or any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', part) for part in parts):
            raise ValueError('invalid fixed IMPORT target')
        return parts
    from validation_scope import active_scope
    scope = active_scope(root, contract_file=contract_file)
    if scope is None or len(scope) != 1:
        raise ValueError('IMPORT requires exactly one environment/target/service in Validation scope')
    return next(iter(scope))


@contextmanager
def restrict(identity):
    token = _scope.set(identity)
    try:
        yield
    finally:
        _scope.reset(token)


@contextmanager
def read_consumers(identities):
    """Local Model access only; the AWS identity remains fixed by restrict()."""
    token = _consumers.set(set(identities))
    try:
        yield
    finally:
        _consumers.reset(token)


def readable(root):
    if _consumers.get() is not None:
        return _consumers.get()
    identity = selected(root)
    if identity is None:
        return None
    from validation_scope import active_scope
    from task_contract import contracts
    scope = active_scope(root) if (root / '.git').exists() and contracts(root) else None
    return (scope or set()) | {identity}


def read_context(root):
    identity = selected(root)
    if identity is None:
        return None
    return identity, tuple(sorted(readable(root))), _reference.get()


def require_readable(root, path):
    if selected(root) is not None and path.absolute() not in {model_path(root, item) for item in readable(root)} and not reference_input(path):
        raise ValueError('IMPORT reference is outside selected environment/target/service')


def scoped_read(function):
    """Authorize before cache lookup, and keep permission/reference contexts separate."""
    @wraps(function)
    def wrapped(path, *args):
        from model_templates import source_paths
        source = source_paths(path)
        context = None
        if source is not None:
            path = path.absolute()
            context = read_context(source[0])
            if context is not None:
                require_readable(source[0], path)
        return function(path, *args, context)
    return wrapped


@contextmanager
def view_scope(identities):
    token = _views.set(set(identities))
    try:
        yield
    finally:
        _views.reset(token)


def view_targets(root):
    return _views.get() or readable(root)


def model_path(root, identity):
    environment, target, service = identity
    return root / 'model' / environment / target / (service + '.properties')


def scoped(function):
    @wraps(function)
    def wrapped(root, *args, **kwargs):
        identity = selected(root)
        with restrict(identity), read_consumers(readable(root)) if identity is not None else nullcontext():
            return function(root, *args, **kwargs)
    return wrapped


def scoped_impact(function):
    @wraps(function)
    def wrapped(root, changed, *args, **kwargs):
        identity = selected(root)
        if identity is None:
            return function(root, changed, *args, **kwargs)
        changed = {str(path) for path in changed}
        if not changed:
            return set()
        return preservation_scope(root, identity, changed)
    return wrapped


def outside_design(root, path):
    identity = selected(root)
    if identity is None:
        return False
    documents = {root / 'docs/designs' / env / target / (service + '.md')
                 for env, target, service in (_views.get() or {identity})}
    return not any(path == own or path.is_relative_to(own.with_suffix('')) for own in documents)


def source_paths(identity):
    environment, target, service = identity
    return (f'model/templates/{target}/{service}.properties.tpl',
            f'model/templates/{target}/{service}.properties',
            f'model/parameters/{environment}/{target}/{service}')


def input_paths(root, identity):
    from model_templates import input_snapshot
    with restrict(selected(root) or identity):
        inputs = input_snapshot(model_path(root, identity))
    inputs.update({file: text.encode('utf-8') for file, text in placement_files(model_path(root, identity)).items()})
    for file in list(inputs):
        if file.name == 'parameters.yaml':
            inputs.setdefault(file.parent / 'observed.json', None)
    return tuple(sorted(file.relative_to(root).as_posix() for file in inputs))


def placement_names(path, required=None):
    """Read CREATE placement names through the existing narrow stack reference reader."""
    from model_templates import _reference_inputs, reference_values
    root = path.parents[3]
    identity = selected(root)
    if identity is None or path.stem != 'cloudformation-stacks' or path.parent.parts[-2:] not in {item[:2] for item in readable(root)}:
        raise ValueError('IMPORT placement reference is outside local scope')
    token = _reference.set(path.absolute())
    try:
        _, (_, files, _, _, bindings, fields) = _reference_inputs(path)
        names = set()
        bound = bindings.get('stacks', {})
        identities = {key for key, name in bound.items() if required is None or name in required}
        if bound and not identities:
            identities = {next(iter(bound))}
        for key in fields:
            if key.startswith('desired.stack.') and key.endswith('.name') and (not bound or key.split('.')[2] in identities):
                value = reference_values(path, key.split('.')[2], 'CloudFormation.Stack', 'name')
                files = {**files, **value.files}
                names.add(value.values[key])
        return set(bindings.get('stacks', {}).values()) or names, files
    finally:
        _reference.reset(token)


def placement_files(path, expansion=None):
    from model_templates import load_expansion
    expansion = expansion or load_expansion(path)
    values = expansion.values
    from model_core import entries
    from iac_values import cfn_resource_identity
    names = {cfn_resource_identity(resource['cfn-logicalId'])[0] for _, resource in entries(values, 'desired.resource.')
             if resource.get('resourceMode', 'CREATE') != 'IMPORT' and resource.get('cfn-logicalId')}
    if names:
        return placement_names(path.with_name('cloudformation-stacks.properties'), names)[1]
    return {}


def reference_input(path):
    return _reference.get() == path.absolute()


@contextmanager
def create_reference(template, item, name, definitions, environment):
    """Read declared CREATE/new IMPORT producers; old IMPORT selectors are view-only."""
    from model_templates import bound_definition, resolve, variables
    from model_parameter_inputs import schema
    root = template.parents[3]
    identity = selected(root)
    spec = schema(definitions[item['definition']].parameters[name])
    if identity is None or spec['service'] == identity[2]:
        yield
        return
    consumer = (environment, template.parent.name, template.name.removesuffix('.properties.tpl'))
    if consumer != identity and consumer in (_consumers.get() or set()):
        path = root / 'model' / environment / template.parent.name / (spec['service'] + '.properties')
        token = _reference.set(path.absolute())
        try:
            yield
        finally:
            _reference.reset(token)
        return
    if consumer != identity:
        raise ValueError('IMPORT reference is outside selected environment/target/service')
    definition = bound_definition(definitions[item['definition']], item['parameters'])
    uses = [(key, raw) for key, raw in definition.values.items() if name in variables(raw)]
    if resolves_reference(item, definition, name):
        with reference_reader(root / 'model' / environment / template.parent.name / (spec['service'] + '.properties')):
            yield
        return
    if not uses or spec.get('format') not in (None, 'anchor', 'identifier'):
        raise ValueError('IMPORT reference is outside selected CREATE logical links')
    for key, raw in uses:
        parts = key.split('.')
        if len(parts) != 4 or parts[:2] != ['desired', 'row'] or parts[3] != 'value' or raw != '<<' + name + '>>':
            raise ValueError('IMPORT reference is outside selected CREATE logical links')
        owner = definition.rows[parts[2]]
        mode = resolve(definition.values.get(f'desired.resource.{owner}.resourceMode', 'CREATE'), item['parameters'])
        if mode != 'CREATE' and item.get('resources', {}).get(owner) not in _additions.get():
            raise ValueError('IMPORT reference is outside selected CREATE logical links')
    path = root / 'model' / environment / template.parent.name / (spec['service'] + '.properties')
    token = _reference.set(path.absolute())
    try:
        yield
    finally:
        _reference.reset(token)


def preservation_scope(root, identity, sources):
    """Only changed shared-service inputs enlarge local Model validation, never AWS."""
    from model_templates import consumers
    template, parts, _ = source_paths(identity)
    shared = any(path == template or path.startswith(parts + '/') for path in sources)
    scope = {identity} | (consumers(root, identity[1], identity[2]) if shared else set())
    scope |= {tuple(path.split('/')[2:5]) for path in sources
              if path.startswith('model/parameters/') and len(path.split('/')) == 6}
    return scope


def allowed_source(root, file, identity):
    """Only selected service templates and selected environment inputs are writable."""
    import re
    template, parts, parameters = source_paths(identity)
    return (file == root / template or
            file.parent == root / parts and re.fullmatch(r'part-[0-9]{3}\.properties', file.name) is not None or
            file.parent == root / parameters and file.name in {'parameters.yaml', 'bindings.json', 'observed.json'})
