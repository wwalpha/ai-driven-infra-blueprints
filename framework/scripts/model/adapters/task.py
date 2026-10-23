"""One-use Model save authority issued by the existing managed Task boundary."""

from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import replace as replace
from functools import partial as _bind_framework_callback
from pathlib import Path

import generation_inputs as _imports_generation_inputs
import import_guard as _imports_import_guard
import issue_gate as _imports_issue_gate
import task_contract_core as _imports_task_contract
import utils.input_cache as _imports_validation_cache
import validation_scope as _imports_validation_scope

import model.importing.repository as _imports_model_importing_repository
import model.sources as _dependency_model_sources
import model.sources as _imports_model_sources


@dataclass(frozen=True)
class ObservedOperation:
    scopes: frozenset
    keys: frozenset
    action: str = 'observed'


@dataclass(frozen=True)
class EditOperation:
    scopes: frozenset
    action: str = 'edit'


@contextmanager
def edit_write_context(root, scopes, task_file):
    if not scopes:
        raise ValueError('ordinary Model editing requires an explicit service set')
    with _write_context(root, task_file, requested=EditOperation(frozenset(scopes))) as context:
        yield context


@contextmanager
def source_write_context(root, task_file):
    with _write_context(root, task_file) as context:
        yield context


@contextmanager
def observed_write_context(root, changes, task_file=None):

    task_path = _imports_task_contract.task_path

    scope_for = _imports_model_sources.scope_for
    root = Path(root).resolve()
    name = task_file or task_path(root).relative_to(root).as_posix()
    scopes, keys = set(), set()
    for path, updates in changes.items():
        scope = scope_for(path)
        if scope.root != root:
            raise ValueError('observed scope belongs to another repository')
        scopes.add((scope.environment, scope.target, scope.service))
        keys.update((path, key) for key in updates)
    if not keys:
        raise ValueError('observed publication requires explicit selected Rows')
    with _write_context(root, name, requested=ObservedOperation(frozenset(scopes), frozenset(keys))) as context:
        yield context


def _callback__write_context_require_current(allowed, declared, head, managed_task_state, matches, name, root, safe_path, state, task_head, task_revision, text, writable, /, changes):
    if task_revision(root, selected=name) != (name, text):
        raise ValueError('parent task changed before source publication')
    if managed_task_state(root, name) != state or task_head(root) != head:
        raise ValueError('managed worktree revision changed before source publication')
    for file in changes:
        relative = file.relative_to(root).as_posix()
        safe_path(root, relative)
        if file not in writable or relative not in declared or not any(matches(relative, p) for p in allowed):
            raise ValueError('source write is outside Modified files/Allowed paths: ' + relative)


@contextmanager
def _write_context(root, task_file, *, requested=None):
    """Authorize one Model-only intermediate save, without running final validation."""
    GenerationInputs = _imports_generation_inputs.GenerationInputs
    managed_task_state = _imports_import_guard.managed_task_state
    require_no_issues = _imports_issue_gate.require_no_issues
    matches = _imports_task_contract.matches
    model_operation = _imports_task_contract.model_operation
    paths_in = _imports_task_contract.paths_in
    safe_path = _imports_task_contract.safe_path
    selected_task = _imports_task_contract.selected_task
    status = _imports_task_contract.status
    task_revision = _imports_task_contract.task_revision
    validate_contract = _imports_task_contract.validate_contract
    input_context = _imports_validation_cache.input_context
    recording_inputs = _imports_validation_cache.recording_inputs
    active_scope = _imports_validation_scope.active_scope
    root = Path(root).resolve()
    with selected_task(root, task_file):
        name, text = task_revision(root, selected=task_file)
        if name != task_file or text is None or status(text) != 'running':
            raise ValueError('source write requires an explicit running parent task')
        validate_contract(root, name, text)
        operation = requested or model_operation(text)
        if operation is None:
            raise ValueError('source write requires a Model-only update operation')
        if operation.action == 'observed':
            model_refactor = _imports_task_contract.model_refactor
            section = _imports_task_contract.section
            lines = set(section(text, '## Task contract'))
            design = {'- Task type: `design`', '- Workflow: `update`'} <= lines
            infrastructure = '- Task type: `infrastructure`' in lines and any(
                '- Infrastructure phase: `' + phase + '`' in lines for phase in ('deploy', 'update', 'destroy'))
            if not (design or infrastructure) or model_operation(text) is not None or model_refactor(text) is not None:
                raise ValueError('observation publication requires its ordinary design/update or infrastructure observation Task')
        if operation.action == 'edit':
            section = _imports_task_contract.section
            lines = section(text, '## Task contract')
            if '- Task type: `design`' not in lines or '- Workflow: `import`' in lines:
                raise ValueError('ordinary Model editing requires a design Task; infrastructure design inputs remain immutable')
            if model_operation(text) is not None:
                raise ValueError('Model-only operations require their limited source write context')
        state = managed_task_state(root, name)
        task_head = _imports_model_importing_repository.task_head
        head = task_head(root)
        with input_context(), _dependency_model_sources.publication_lock(root):
            snapshot = GenerationInputs(root, task_file=name)
            context = None
            try:
                with recording_inputs(snapshot):
                    scope = active_scope(root, task_file=name)
                    required = set(operation.scopes)
                    if operation.action == 'import-retarget':
                        required |= {tuple(address.split('/')[:3]) for ref in operation.references
                                     for address in (ref.source, ref.destination)}
                    if scope is None or not required <= scope:
                        raise ValueError('source write requires exact service Validation scope')
                    require_no_issues(root, scope if operation.action == 'import-retarget' else required,
                                      task_file=name)
                    declared, allowed = paths_in(text, '## Modified files'), paths_in(text, '## Allowed paths')
                    writable = set()
                    for relative in declared:
                        file = root / relative
                        if not relative.startswith('model/'):
                            continue
                        selected = _dependency_model_sources.source_scope(root, file)
                        if (selected.environment, selected.target, selected.service) not in operation.scopes:
                            continue
                        _dependency_model_sources._safe(root, file, snapshot)
                        snapshot.read(file)
                        writable.add(file)
                    # Freeze real Models and producer dependencies; discovery grants no write rights.
                    targets = {identity[:2] for identity in required}
                    for selected in _dependency_model_sources.list_models(root, snapshot):
                        if (selected.environment, selected.target) in targets:
                            if operation.action == 'observed':
                                _dependency_model_sources.load_model(selected, snapshot)
                            else:
                                edit_base = _imports_model_sources.edit_base
                                edit_base(selected.path, snapshot)
                    for identity in operation.scopes:
                        file = root / 'model' / identity[0] / identity[1] / (identity[2] + '.properties')
                        snapshot.read(file)

                require_current = _bind_framework_callback(_callback__write_context_require_current, allowed, declared, head, managed_task_state, matches, name, root, safe_path, state, task_head, task_revision, text, writable)

                context = _dependency_model_sources.SourceWriteContext._authorized(root, snapshot, operation, require_current, frozenset(writable),
                                                         finish=lambda: require_current({}))
            except BaseException:
                snapshot.close()
                raise
        try:
            yield context
        finally:
            context.close()
