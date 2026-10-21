"""Exact Import read and write scopes; producer reads never confer publication rights."""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
from validation_cache import memoized

_scope = ContextVar('model_import_scope', default=None)
_consumers = ContextVar('model_import_read_consumers', default=None)
_reference = ContextVar('model_import_reference', default=None)
_views = ContextVar('model_import_views', default=None)

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


def require_readable(root, path):
    if selected(root) is not None and path.absolute() not in {model_path(root, item) for item in readable(root)} and not reference_input(path):
        raise ValueError('IMPORT reference is outside selected environment/target/service')


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


def outside_design(root, path):
    identity = selected(root)
    if identity is None:
        return False
    documents = {root / 'docs/designs' / env / target / (service + '.md')
                 for env, target, service in (_views.get() or {identity})}
    return not any(path == own or path.is_relative_to(own.with_suffix('')) for own in documents)



def read_context(root):
    identity = selected(root)
    return None if identity is None else (identity, tuple(sorted(readable(root))), _reference.get())


def reference_input(path):
    return _reference.get() == path.absolute()


def input_paths(root, identity):
    from model.sources import load_model
    inputs = load_model(model_path(root, identity)).dependencies
    return tuple(sorted(inputs)), dict(inputs)


def allowed_source(root, file, identity):
    from model.sources import source_scope
    try:
        scope = source_scope(root, file)
    except ValueError:
        return False
    return (scope.environment, scope.target, scope.service) == identity


def placement_names(path, required=None):
    from model.core import entries
    from model.sources import load_model
    with reference_reader(path):
        model = load_model(path)
    names = {stack['placementName']: stack['name'] for _, stack in entries(model.authoritative, 'desired.stack.')}
    if required is not None and not set(required) <= names.keys():
        from model.core import ReferenceResolutionError
        raise ReferenceResolutionError('cfn-logicalId references an undeclared fixed Stack placement')
    return set(names), dict(model.files)


def placement_files(path, expansion=None):
    return {} if expansion is None else dict(expansion.files)
