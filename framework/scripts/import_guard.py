"""Shared candidate authority checks and dedicated Import/operation evidence boundaries."""
from contextlib import contextmanager, ExitStack
from collections.abc import Iterator
from model.sources import SourceWriteContext, safe
from utils.json_format import json_text
from contextvars import ContextVar
import hashlib
import io
import hmac
import os
import secrets
import stat
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

from utils.file_operations import atomic_files
from sync_files import save_files
from task_contract import contracts, section, task_path, contract_path
from validation_cache import input_bytes, input_text, input_is_file, input_select, input_scope
from utils.aws_mappings import definition_root, mapping_alias


_baselines = ContextVar('import_baselines', default=None)


@contextmanager
def baseline_scope():
    if _baselines.get() is not None:
        yield
        return
    with tempfile.TemporaryDirectory(prefix='blueprint-import-baselines-') as directory:
        token = _baselines.set((Path(directory).resolve(), {}))
        try:
            yield
        finally:
            _baselines.reset(token)


def workflow(root, *, contract_file=None):
    path = (contract_path(root, selected=contract_file) if contract_file is not None else task_path(root))
    text = input_text(path, encoding='utf-8')
    contract = section(text, '## Task contract')
    if '- Task type: `design`' not in contract or contract.count('- Workflow: `import`') != 1:
        raise ValueError('IMPORT configuration changes require the registered design /import workflow')
    return path.relative_to(root).as_posix()


def proof_path(root, *, contract_file=None):
    return evidence_store(root) / ((contract_path(root, selected=contract_file) if contract_file is not None else task_path(root)).stem + '.json')


def working_revision(root):
    result = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=root, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        valid = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=root, capture_output=True)
        if valid.returncode:
            raise ValueError('cannot determine the versioned IMPORT baseline')
        return None  # Initial registration has no previous versioned configuration.
    return result.stdout.strip()


def base_revision(root, *, contract_file=None):
    head = working_revision(root)
    if head is None:
        return None
    if contracts(root):
        from worktree_task import task_start_commit
        path = contract_path(root, selected=contract_file) if contract_file is not None else task_path(root, required=False)
        start = task_start_commit(root, path.relative_to(root).as_posix()) if path is not None else None
        if start is not None:
            return start
    return head


def changed_sources(root, supplied=None, *, contract_file=None):
    if supplied is None:
        from worktree_task import changed_paths, committed_task_paths
        supplied = changed_paths(root)
        if contracts(root):
            path = contract_path(root, selected=contract_file) if contract_file is not None else task_path(root, required=False)
            if path is not None:
                supplied |= committed_task_paths(root, path.relative_to(root).as_posix()) or set()
    return {str(p) for p in supplied if str(p).startswith('model/') or str(p) == 'project.json'}


from model.operations import resource_configuration as resource_config


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def archive_sources(root, base, paths, destination):
    files = subprocess.run(['git', 'ls-tree', '--name-only', base, '--', *paths],
                           cwd=root, capture_output=True, text=True, encoding='utf-8', check=True).stdout.splitlines()
    if not files:
        return
    archive = subprocess.run(['git', 'archive', base, '--', *files], cwd=root, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for entry in stream:
            if not entry.isfile():
                if entry.isdir():
                    continue
                raise ValueError('unsafe baseline Model source')
            path = destination / entry.name
            if not path.resolve().is_relative_to(destination):
                raise ValueError('unsafe baseline Model path')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(stream.extractfile(entry).read())


@contextmanager
def snapshots(root, base, output, definitions_root=None, *, detached=False, identity_inputs=False):
    definitions_root = definitions_root or definition_root(root)
    for path in output:
        if not path.resolve().is_relative_to(root) or '..' in path.relative_to(root).parts:
            raise ValueError('unsafe candidate Model source path')
    with ExitStack() as lifetime:
        directory = lifetime.enter_context(tempfile.TemporaryDirectory(prefix='blueprint-import-guard-'))
        before = Path(directory).resolve() / 'before'
        paths = ['model', 'project.json', *(['infra/cloudformation'] if identity_inputs else [])]
        cache = _baselines.get()
        key = (root, base, tuple(paths), definitions_root.resolve())
        if cache is not None:
            before = cache[1].get(key)
        if cache is None or before is None:
            if cache is None:
                before.mkdir()
            else:
                before = Path(tempfile.mkdtemp(dir=cache[0])).resolve()
            archive_sources(root, base, paths, before)
            if cache is not None:
                cache[1][key] = before
        lifetime.enter_context(mapping_alias(definitions_root, before))
        after = root
        if output or detached:
            after = Path(directory).resolve() / 'after'
            after.mkdir()
            lifetime.enter_context(mapping_alias(definitions_root, after))
            for path in (*input_select(root / 'model', '*', recursive=True, kinds=('file',)), root / 'project.json',
                         *(input_select(root / 'infra/cloudformation', '*', recursive=True, kinds=('file',)) if identity_inputs else ())):
                if input_is_file(path):
                    safe(root, path)
                    destination = after / path.relative_to(root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(input_bytes(path))
            save_files({after / p.relative_to(root): text for p, text in output.items() if text is not None})
            for path, text in output.items():
                if text is None:
                    (after / path.relative_to(root)).unlink(missing_ok=True)
        yield before, after


@input_scope
def require_import_changes(root, supplied=None, output=None, generation=False, *, final_candidate=None, contract_file=None):
    if contract_file is not None and (output is not None or generation or final_candidate is not None):
        raise ValueError('contract reference is limited to read-only integration checks')
    root = root.resolve()
    if not (root / '.git').exists():
        return  # Disposable generator stages have no Git baseline; the calling boundary is guarded.
    sources = ({p for p in final_candidate.changed_paths if p.startswith(('model/', 'project.json'))}
               if final_candidate is not None else changed_sources(root, supplied, contract_file=contract_file))
    if output:
        sources |= changed_sources(root, {p.relative_to(root).as_posix() for p in output})
    path = contract_path(root, selected=contract_file) if contract_file is not None else task_path(root, required=False)
    if path is None and sources:
        raise ValueError('selected task contract required for Model changes')
    text = '' if path is None else contracts(root)[path.relative_to(root).as_posix()]
    if sources:
        from task_contract import validate_contract, paths_in, matches, safe_path
        validate_contract(root, path.relative_to(root).as_posix(), text)
        declared, allowed = paths_in(text, '## Modified files'), paths_in(text, '## Allowed paths')
        for relative in sources:
            safe_path(root, relative)
            if relative not in declared or not any(matches(relative, pattern) for pattern in allowed):
                raise ValueError('Model source outside Modified files/Allowed paths: ' + relative)
    from task_contract import model_operation, model_refactor
    operation = model_operation(text)
    refactor = model_refactor(text)
    if operation is not None:
        from model.impact import affected
        if generation:
            return  # Source/view generation does not decide final Model operation meaning.
        base = final_candidate.base_commit if final_candidate is not None else base_revision(root, contract_file=contract_file)
        if base is None:
            raise ValueError('IMPORT Model-only operation requires a versioned baseline')
        from model.operations import verify_model_operation
        with snapshots(root, base, output or {}, detached=contract_file is not None) as (before, after):
            if operation.action in {'import-retarget', 'import-delete'}:
                from validation_scope import active_scope
                scope = set(final_candidate.scope) if final_candidate is not None else active_scope(root, contract_file=contract_file)
                required = {tuple(address.split('/')[:3]) for ref in operation.references
                            for address in (ref.consumer, ref.source, ref.destination)}
                required |= operation.scopes | affected(after, sources)
                if scope is None or not required <= scope:
                    raise ValueError('Model operation requires all producers/consumers in Validation scope')
            warnings = verify_model_operation(before, after, operation, sources)
    elif refactor is not None:
        from model.operations import verify_model_refactor
        from validation_scope import active_scope
        base = final_candidate.base_commit if final_candidate is not None else base_revision(root, contract_file=contract_file)
        if base is None:
            raise ValueError('Model refactor requires a versioned baseline')
        scope = set(final_candidate.scope) if final_candidate is not None else active_scope(root, contract_file=contract_file)
        with snapshots(root, base, output or {}, detached=contract_file is not None) as (before, after):
            warnings = verify_model_refactor(before, after, refactor, sources, scope)
    elif '- Workflow: `import`' in section(text, '## Task contract'):
        if not sources and generation:
            return
        proof = read_proof(root, contract_file=contract_file) if contract_file is not None else read_proof(root)
        expected = proof['sources']
        if sources - expected.keys():
            raise ValueError('IMPORT source change has no acquired change plan')
        for relative in expected:
            path = root / relative
            text = output[path] if output and path in output else input_bytes(path).decode('utf-8') if input_is_file(path) else None
            actual = None if text is None else hashlib.sha256(text.encode('utf-8')).hexdigest()
            if actual != expected[relative]:
                raise ValueError('IMPORT configuration differs from acquired change plan: ' + relative)
        if output is None and not generation and (proof['model'] not in {'reflected', 'unchanged'} or not proof['complete']):
            raise ValueError('IMPORT retrieval/reflection is incomplete; task remains unfinished')
        return
    else:
        warnings = []
    if sources:
        from model.operations import validate_candidates
        from validation_scope import active_scope
        scope = active_scope(root, contract_file=contract_file)
        if final_candidate is not None:
            scope = set(final_candidate.scope)
        if operation is None and refactor is None and scope is not None:
            from issue_gate import require_no_issues
            require_no_issues(root, scope, contract_file=contract_file)
        warnings.extend(validate_candidates(root, sources, output or {}, scope,
            base=final_candidate.base_commit if final_candidate is not None else None, contract_file=contract_file))
    from model.core import report_reference_warnings
    report_reference_warnings(warnings)
    return warnings



def text_hash(text):
    return None if text is None else hashlib.sha256(text.encode('utf-8')).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def evidence_store(root, *, create=True):
    """Private local seal, outside Git; not AWS credentials or a response snapshot."""
    base = Path(tempfile.gettempdir()).resolve() / ('blueprint-import-' + digest(str(Path.home()))[:16])
    directory = base / digest(str(root.resolve()))
    for path in (base, directory):
        if not create and not path.exists() and not path.is_symlink():
            return directory
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
            raise ValueError('IMPORT unsafe temporary evidence directory')
        if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError('IMPORT evidence directory must be private to the current user')
    return directory


def seal_key(root):
    path = evidence_store(root) / 'seal.key'
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = None
    if descriptor is not None:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(secrets.token_bytes(32))
    if path.is_symlink() or not path.is_file() or (os.name != 'nt' and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077)):
        raise ValueError('IMPORT unsafe local evidence seal')
    value = path.read_bytes()
    if len(value) != 32:
        raise ValueError('IMPORT invalid local evidence seal')
    return value


def sealed(root, value):
    payload = json_text(value)
    return json_text({'payload': value, 'signature': hmac.new(seal_key(root), payload.encode('utf-8'), 'sha256').hexdigest()}) + '\n'


def read_sealed(root, file):
    if file.is_symlink():
        raise ValueError('IMPORT symlink evidence is forbidden')
    envelope = json.loads(file.read_text(encoding='utf-8'))
    if set(envelope) != {'payload', 'signature'} or not isinstance(envelope['signature'], str):
        raise ValueError('IMPORT invalid sealed evidence')
    expected = hmac.new(seal_key(root), json_text(envelope['payload']).encode('utf-8'), 'sha256').hexdigest()
    if not hmac.compare_digest(expected, envelope['signature']):
        raise ValueError('IMPORT acquisition evidence was modified')
    return envelope['payload']


def write_sealed(root, file, value):
    atomic_files({file: sealed(root, value)}, staging_directory=file.parent)














def managed_source_write(root: Path, task_file: str) -> bool:
    """Select the guarded intermediate path only for a real managed Model operation."""
    from task_contract import model_operation, task_revision
    from worktree_task import task_start_commit
    _, text = task_revision(root, selected=task_file)
    return bool(text and model_operation(text) is not None and task_start_commit(root, task_file) is not None)


def managed_task_state(root: Path, name: str):
    """Check live Task/worktree ownership; callers bind the returned state to their save."""
    from worktree_task import load, task_worktree
    _, _, _, state = load(root, Path(name).stem)
    if state['task_file'] != name or Path(state['worktree']) != root or state['merged'] is not None:
        raise ValueError('source write task/worktree is mismatched or merged')
    if task_worktree(root, state) != root:
        raise ValueError('source write requires its managed worktree')
    return state


from model.adapters.task import source_write_context

from model.importing.evidence import (acquired, acquisition_complete, copy_import_proof, discard_acquisition, discard_import_proof, finish_import, read_acquisition, read_proof, record_import, require_fresh_acquisition, validate_inventory)
