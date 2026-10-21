"""One-use Model save authority issued by the existing managed Task boundary."""
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass, replace

from model.sources import (SourceWriteContext, list_models, load_model,
                           publication_lock, source_scope, _safe)


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
    from task_contract import task_path
    from model.sources import scope_for
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


@contextmanager
def _write_context(root, task_file, *, requested=None):
    """Authorize one Model-only intermediate save, without running final validation."""
    from import_guard import managed_task_state
    from issue_gate import require_no_issues
    from generation_inputs import GenerationInputs
    from task_contract import (matches, model_operation, paths_in, safe_path,
                               status, task_revision, validate_contract, selected_task)
    from validation_cache import input_context, recording_inputs
    from validation_scope import active_scope
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
            from task_contract import section, model_refactor
            lines = set(section(text, '## Task contract'))
            design = {'- Task type: `design`', '- Workflow: `update`'} <= lines
            infrastructure = '- Task type: `infrastructure`' in lines and any(
                '- Infrastructure phase: `' + phase + '`' in lines for phase in ('deploy', 'update', 'destroy'))
            if not (design or infrastructure) or model_operation(text) is not None or model_refactor(text) is not None:
                raise ValueError('observation publication requires its ordinary design/update or infrastructure observation Task')
        if operation.action == 'edit':
            from task_contract import section, model_identity_rewrite
            if model_identity_rewrite(text):
                operation = replace(operation, action='identity-rewrite')
        if operation.action == 'edit':
            from task_contract import section
            lines = section(text, '## Task contract')
            if '- Task type: `design`' not in lines or '- Workflow: `import`' in lines:
                raise ValueError('ordinary Model editing requires a design Task; infrastructure design inputs remain immutable')
            if model_operation(text) is not None:
                raise ValueError('Model-only operations require their limited source write context')
        state = managed_task_state(root, name)
        from worktree_task import output
        head = output(root, 'rev-parse', 'HEAD')
        with input_context(), publication_lock(root):
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
                        selected = source_scope(root, file)
                        if (selected.environment, selected.target, selected.service) not in operation.scopes:
                            continue
                        _safe(root, file, snapshot)
                        snapshot.read(file)
                        writable.add(file)
                    # Freeze real Models and producer dependencies; discovery grants no write rights.
                    targets = {identity[:2] for identity in required}
                    for selected in list_models(root, snapshot):
                        if (selected.environment, selected.target) in targets:
                            if operation.action == 'identity-rewrite':
                                from model.identity_rewrite import baseline_snapshot
                                baseline_snapshot(selected, snapshot)
                            else:
                                load_model(selected, snapshot)
                    for identity in operation.scopes:
                        file = root / 'model' / identity[0] / identity[1] / (identity[2] + '.properties')
                        snapshot.read(file)

                def require_current(changes):
                    if task_revision(root, selected=name) != (name, text):
                        raise ValueError('parent task changed before source publication')
                    if managed_task_state(root, name) != state or output(root, 'rev-parse', 'HEAD') != head:
                        raise ValueError('managed worktree revision changed before source publication')
                    for file in changes:
                        relative = file.relative_to(root).as_posix()
                        safe_path(root, relative)
                        if file not in writable or relative not in declared or not any(matches(relative, p) for p in allowed):
                            raise ValueError('source write is outside Modified files/Allowed paths: ' + relative)

                context = SourceWriteContext._authorized(root, snapshot, operation, require_current, frozenset(writable),
                                                         finish=lambda: require_current({}))
            except BaseException:
                snapshot.close()
                raise
        try:
            yield context
        finally:
            context.close()
