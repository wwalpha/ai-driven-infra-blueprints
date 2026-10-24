"""Exact Import read and write scopes; producer reads never confer publication rights."""

import re
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

import task_contract_core as _imports_task_contract
import task_contract_core as _imports_validation_scope
from task_contract_core import _selected_contract, task_read_scope, task_snapshot
from utils.function_wrapper import FunctionWrapper
from utils.input_cache import memoized

import model.core as _imports_model_core
import model.importing.repository as _imports_model_importing_repository
import model.sources as _imports_model_sources

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


@task_read_scope
def selected(root, *, contract_file=None):
    if _scope.get() is not None:
        return _scope.get()
    # Reading scope grants no execution/write rights; those boundaries check paths/status.
    path, text = _selected_contract(root, selected=contract_file, allow_empty=True)
    if path is None:
        return None
    name = path.relative_to(root).as_posix()
    # Select the current task and its IMPORT scope.
    if contract_file is None:
        return _selection(root, name, text)
    return _selection(root, name, text, contract_file)


@memoized
def _selection(root, name, text, contract_file=None):
    section = _imports_task_contract.section
    active_scope = _imports_validation_scope.active_scope
    if '- Workflow: `import`' not in section(text, '## Task contract'):
        return None
    targets = re.findall(r'^- IMPORT target: `([^`]+)`$', '\n'.join(section(text, '## Task contract')), re.M)
    if len(targets) > 1:
        raise ValueError('duplicate fixed IMPORT target')
    if targets:
        parts = tuple(targets[0].split('/'))
        if len(parts) != 3 or any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', part) for part in parts):
            raise ValueError('invalid fixed IMPORT target')
        return parts
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


@task_read_scope
def readable(root):
    active_scope = _imports_validation_scope.active_scope

    has_baseline = _imports_model_importing_repository.has_baseline
    if _consumers.get() is not None:
        return _consumers.get()
    identity = selected(root)
    if identity is None:
        return None

    scope = active_scope(root) if has_baseline(root) and task_snapshot(root, required=False) is not None else None
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


def _invoke_scoped(function, /, root, *args, **kwargs):
    identity = selected(root)
    with restrict(identity), read_consumers(readable(root)) if identity is not None else nullcontext():
        return function(root, *args, **kwargs)


def scoped(function):
    wrapped = FunctionWrapper(function, _invoke_scoped)
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
    load_model = _imports_model_sources.load_model
    inputs = load_model(model_path(root, identity)).dependencies
    return tuple(sorted(inputs)), dict(inputs)


def allowed_source(root, file, identity):
    source_scope = _imports_model_sources.source_scope
    try:
        scope = source_scope(root, file)
    except ValueError:
        return False
    return (scope.environment, scope.target, scope.service) == identity


def placement_names(path, required=None):
    entries = _imports_model_core.entries
    load_model = _imports_model_sources.load_model
    with reference_reader(path):
        model = load_model(path)
    names = {stack['placementName']: stack['name'] for _, stack in entries(model.authoritative, 'desired.stack.')}
    if required is not None and not set(required) <= names.keys():
        ReferenceResolutionError = _imports_model_core.ReferenceResolutionError
        raise ReferenceResolutionError('cfn-logicalId references an undeclared fixed Stack placement')
    return set(names), dict(model.files)


def placement_files(path, expansion=None):
    return {} if expansion is None else dict(expansion.files)
