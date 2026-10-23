"""Shared candidate authority checks and dedicated Import/operation evidence boundaries."""

import hashlib
import io
import subprocess
import tarfile
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

import issue_gate as _imports_issue_gate
import model.adapters.task as _compat_model_adapters_task
import model.core as _imports_model_core
import model.impact as _imports_model_impact
import model.importing.evidence as _compat_model_importing_evidence
import model.importing.evidence as _dependency_model_importing_evidence
import model.importing.repository as _imports_model_importing_repository
import model.operations as _imports_model_operations
import model.sources as _dependency_model_sources
import task_contract_core as _imports_task_contract
import utils.sealed_evidence as _sealed_evidence
import validation_scope as _imports_validation_scope
from model.configuration import resource_configuration
from sync_files import save_files
from task_contract_core import contract_path, contracts, section, task_path
from utils.aws_mappings import definition_root, mapping_alias
from utils.input_cache import _baselines as _baselines
from utils.input_cache import baseline_scope as baseline_scope
from utils.input_cache import (
    input_bytes,
    input_is_file,
    input_scope,
    input_select,
    input_text,
)
from utils.json_format import (
    document_sha256 as digest,  # noqa: F401 - compatibility export used by import fixtures
)


def workflow(root, *, contract_file=None):
    path = (contract_path(root, selected=contract_file) if contract_file is not None else task_path(root))
    text = input_text(path, encoding='utf-8')
    contract = section(text, '## Task contract')
    if '- Task type: `design`' not in contract or contract.count('- Workflow: `import`') != 1:
        raise ValueError('IMPORT configuration changes require the registered design /import workflow')
    return path.relative_to(root).as_posix()


def proof_path(root, *, contract_file=None):
    return _sealed_evidence.evidence_store(root) / ((contract_path(root, selected=contract_file) if contract_file is not None else task_path(root)).stem + '.json')


def working_revision(root):
    working_revision = _imports_model_importing_repository.working_revision
    return working_revision(root)


def base_revision(root, *, contract_file=None):
    head = working_revision(root)
    if head is None:
        return None
    if contracts(root):
        task_start_commit = _imports_model_importing_repository.task_start_commit
        path = contract_path(root, selected=contract_file) if contract_file is not None else task_path(root, required=False)
        start = task_start_commit(root, path.relative_to(root).as_posix()) if path is not None else None
        if start is not None:
            return start
    return head


def changed_sources(root, supplied=None, *, contract_file=None):
    if supplied is None:
        changed_paths = _imports_model_importing_repository.changed_paths
        supplied = changed_paths(root, task_file=contract_file)
    return {str(p) for p in supplied if str(p).startswith('model/') or str(p) == 'project.json'}






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
                    _dependency_model_sources.safe(root, path)
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
    report_reference_warnings = _imports_model_core.report_reference_warnings
    has_baseline = _imports_model_importing_repository.has_baseline
    model_operation = _imports_task_contract.model_operation
    model_refactor = _imports_task_contract.model_refactor
    if contract_file is not None and (output is not None or generation or final_candidate is not None):
        raise ValueError('contract reference is limited to read-only integration checks')
    root = root.resolve()
    if not has_baseline(root):
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
        matches = _imports_task_contract.matches
        paths_in = _imports_task_contract.paths_in
        safe_path = _imports_task_contract.safe_path
        validate_contract = _imports_task_contract.validate_contract
        validate_contract(root, path.relative_to(root).as_posix(), text)
        declared, allowed = paths_in(text, '## Modified files'), paths_in(text, '## Allowed paths')
        for relative in sources:
            safe_path(root, relative)
            if relative not in declared or not any(matches(relative, pattern) for pattern in allowed):
                raise ValueError('Model source outside Modified files/Allowed paths: ' + relative)
    operation = model_operation(text)
    refactor = model_refactor(text)
    if operation is not None:
        affected = _imports_model_impact.affected
        if generation:
            return  # Source/view generation does not decide final Model operation meaning.
        base = final_candidate.base_commit if final_candidate is not None else base_revision(root, contract_file=contract_file)
        if base is None:
            raise ValueError('IMPORT Model-only operation requires a versioned baseline')
        verify_model_operation = _imports_model_operations.verify_model_operation
        with snapshots(root, base, output or {}, detached=contract_file is not None) as (before, after):
            if operation.action in {'import-retarget', 'import-delete'}:
                active_scope = _imports_validation_scope.active_scope
                scope = set(final_candidate.scope) if final_candidate is not None else active_scope(root, contract_file=contract_file)
                required = {tuple(address.split('/')[:3]) for ref in operation.references
                            for address in (ref.consumer, ref.source, ref.destination)}
                required |= operation.scopes | affected(after, sources)
                if scope is None or not required <= scope:
                    raise ValueError('Model operation requires all producers/consumers in Validation scope')
            warnings = verify_model_operation(before, after, operation, sources)
    elif refactor is not None:
        verify_model_refactor = _imports_model_operations.verify_model_refactor
        active_scope = _imports_validation_scope.active_scope
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
        validate_candidates = _imports_model_operations.validate_candidates
        active_scope = _imports_validation_scope.active_scope
        scope = active_scope(root, contract_file=contract_file)
        if final_candidate is not None:
            scope = set(final_candidate.scope)
        if operation is None and refactor is None and scope is not None:
            require_no_issues = _imports_issue_gate.require_no_issues
            require_no_issues(root, scope, contract_file=contract_file)
        warnings.extend(validate_candidates(root, sources, output or {}, scope,
            base=final_candidate.base_commit if final_candidate is not None else None, contract_file=contract_file))
    report_reference_warnings(warnings)
    return warnings



def text_hash(text):
    return None if text is None else hashlib.sha256(text.encode('utf-8')).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None




def managed_source_write(root: Path, task_file: str) -> bool:
    """Select the guarded intermediate path only for a real managed Model operation."""
    task_start_commit = _imports_model_importing_repository.task_start_commit
    model_operation = _imports_task_contract.model_operation
    task_revision = _imports_task_contract.task_revision
    _, text = task_revision(root, selected=task_file)
    return bool(text and model_operation(text) is not None and task_start_commit(root, task_file) is not None)


resource_config = resource_configuration


def source_write_context(root, task_file):
    return _compat_model_adapters_task.source_write_context(root, task_file)


def acquired(root, identity, ctx, records, sources, consumers, dry_run, *, source_sets):
    return _compat_model_importing_evidence.acquired(root, identity, ctx, records, sources, consumers, dry_run, source_sets=source_sets)


def acquisition_complete(value):
    return _compat_model_importing_evidence.acquisition_complete(value)


def copy_import_proof(root, snapshot):
    return _compat_model_importing_evidence.copy_import_proof(root, snapshot)


def discard_acquisition(root, file):
    return _compat_model_importing_evidence.discard_acquisition(root, file)


def discard_import_proof(root, task_name):
    return _compat_model_importing_evidence.discard_import_proof(root, task_name)


def finish_import(root, model=None, markdown=None):
    return _compat_model_importing_evidence.finish_import(root, model, markdown)


def read_acquisition(root, file, identity, dry_run):
    return _compat_model_importing_evidence.read_acquisition(root, file, identity, dry_run)


def record_import(root, output, evidence, plan, complete=True, *, review_binding=None):
    return _compat_model_importing_evidence.record_import(root, output, evidence, plan, complete, review_binding=review_binding)


def read_proof(root, *, contract_file=None):
    return _dependency_model_importing_evidence.read_proof(root, contract_file=contract_file)
