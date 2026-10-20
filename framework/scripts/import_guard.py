"""Enforce IMPORT configuration authority at existing save, validation and Git boundaries."""
from contextlib import contextmanager, ExitStack
from collections.abc import Iterator
from model_sources import SourceWriteContext, safe
from contextvars import ContextVar
import hashlib
import io
import hmac
import os
import secrets
import stat
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from model_core import entries
from model_files import load_model, resource_row_index
from model_templates import affected, json_text, model_paths
from policy_tables import literal
from sync_files import atomic_files, save_files
from task_contract import contracts, section, task_path, contract_path
from validation_cache import input_bytes, input_text, input_is_file, input_select, input_scope
from utils.aws_mappings import definition_root, mappings_for, mapping_alias


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


def base_revision(root, *, contract_file=None):
    result = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=root, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        valid = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=root, capture_output=True)
        if valid.returncode:
            raise ValueError('cannot determine the versioned IMPORT baseline')
        return None  # Initial registration has no previous versioned configuration.
    if contracts(root):
        from worktree_task import task_start_commit
        name = (contract_path(root, selected=contract_file) if contract_file is not None else task_path(root)).relative_to(root).as_posix()
        start = task_start_commit(root, name)
        if start is not None:
            return start
    return result.stdout.strip()


def changed_sources(root, supplied=None, *, contract_file=None):
    if supplied is None:
        from worktree_task import changed_paths, committed_task_paths
        supplied = changed_paths(root)
        if contracts(root):
            name = (contract_path(root, selected=contract_file) if contract_file is not None else task_path(root)).relative_to(root).as_posix()
            supplied |= committed_task_paths(root, name) or set()
    return {str(p) for p in supplied if str(p).startswith(('model/templates/', 'model/parameters/')) or str(p) == 'project.json'}


def resource_config(values, number, path=None, expansion=None, *, symbols=None):
    spec = dict(entries(values, 'desired.resource.'))[number]
    rows = resource_row_index(values)[number]
    if symbols is not None:
        compared = symbols
        spec = {key: symbols.get(f'desired.resource.{number}.' + key, value) for key, value in spec.items()}
    elif path is not None:
        from model_templates import load_for_analysis as load_expansion
        from import_preservation import preserved_values
        expansion = expansion or load_expansion(path)
        compared = preserved_values(path, expansion._replace(values=values))
    else:
        compared = values
    configuration = []
    observed = []
    for rid, row in rows:
        if 'document' in row:
            document = compared.get('desired.row.' + rid + '.document', row['document'])
            value = json.loads(document) if isinstance(document, str) else document
        else:
            raw = compared.get('desired.row.' + rid + '.value', row['value'])
            value = literal(raw) if isinstance(raw, str) else raw
            if isinstance(value, str) and value.startswith(('{', '[')):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
        configuration.append([row['property'], value])
        current = values.get('observed.row.' + rid + '.value')
        if current is not None:
            observed.append([row['property'], literal(current)])
    # Comments, source layout and literal backticks do not change AWS configuration.
    result = {'resource': spec, 'rows': configuration, 'observed': observed if spec.get('resourceMode') == 'IMPORT' else []}
    if symbols is None and path is not None and spec.get('resourceMode', 'CREATE') != 'IMPORT':
        from model_templates import load_for_analysis as load_expansion, parse_template, service_source, json_read
        from model_parameter_inputs import schema
        expansion = expansion or load_expansion(path)
        _, template, directory = service_source(path)
        definitions, _ = parse_template(template)
        bindings = json_read(expansion.files[directory / 'bindings.json'])['instances']
        references = {}
        for key, trace in expansion.provenance.items():
            parts = key.split('.')
            owner = parts[2] if parts[1] == 'resource' else parts[2].rpartition('-')[0] if parts[1] == 'row' else None
            if owner != number or 'definition' not in trace:
                continue
            declaration = definitions[trace['definition']]
            for name in trace['parameters']:
                reference = schema(declaration.parameters[name])
                if reference['type'] == 'reference' and 'service' in reference:
                    references.setdefault(key, {})[name] = {**reference, 'label': bindings[trace['instance']].get('labels', {}).get(name)}
        if references:
            result['references'] = references
    return result


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
def snapshots(root, base, output, definitions_root=None, *, detached=False):
    definitions_root = definitions_root or definition_root(root)
    for path in output:
        if not path.resolve().is_relative_to(root) or '..' in path.relative_to(root).parts:
            raise ValueError('unsafe candidate Model source path')
    with ExitStack() as lifetime:
        directory = lifetime.enter_context(tempfile.TemporaryDirectory(prefix='blueprint-import-guard-'))
        before = Path(directory).resolve() / 'before'
        paths = ['model', 'project.json']
        cache = _baselines.get()
        key = (root, base, tuple(paths), mappings_for(definitions_root))
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
            for path in (*input_select(root / 'model', '*', recursive=True, kinds=('file',)), root / 'project.json'):
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
def changes(root, sources, output=None, include_create=False, *, contract_file=None):
    root = root.resolve()
    from import_scope import selected
    identity = selected(root, contract_file=contract_file)
    base = base_revision(root, contract_file=contract_file)
    if not sources or base is None:
        return base, {}
    with snapshots(root, base, output or {}, detached=contract_file is not None) as (before, after):
        scope = affected(after, sources, before=before)
        # Include deleted consumers, which cannot authorize removal of IMPORT resources.
        scope |= {tuple(Path(p).parts[2:5]) for p in sources if p.startswith('model/parameters/') and len(Path(p).parts) == 6}
        found = {}
        for env, target, service in sorted(scope):
            relative = Path('model') / env / target / (service + '.properties')
            old_path, new_path = before / relative, after / relative
            old_exists = old_path in model_paths(before, env, target)
            new_exists = new_path in model_paths(after, env, target)
            from model_templates import load_for_analysis
            old_expansion = load_for_analysis(old_path) if old_exists else None
            new_expansion = load_for_analysis(new_path) if new_exists else None
            old = old_expansion.values if old_expansion else {}
            new = new_expansion.values if new_expansion else {}
            from model_reference_usage import _symbolic
            from model_operation_checks import reference_equal
            from model_core import report_reference_warnings
            warnings = [w for expansion in (old_expansion, new_expansion) if expansion for w in expansion.warnings]
            old_symbols = _symbolic(old_path, old_expansion, {}, warnings) if old_expansion else {}
            new_symbols = _symbolic(new_path, new_expansion, {}, warnings) if new_expansion else {}
            report_reference_warnings(warnings)
            old_resources, new_resources = dict(entries(old, 'desired.resource.')), dict(entries(new, 'desired.resource.'))
            for number in old_resources.keys() | new_resources.keys():
                previous, current = old_resources.get(number, {}), new_resources.get(number, {})
                imported = previous.get('resourceMode') == 'IMPORT' or current.get('resourceMode') == 'IMPORT'
                if not imported and not include_create:
                    continue
                left = resource_config(old, number, symbols=old_symbols) if previous else None
                right = resource_config(new, number, symbols=new_symbols) if current else None
                if not reference_equal(left, right):
                    left = resource_config(old, number) if previous else None
                    right = resource_config(new, number) if current else None
                    found['/'.join((env, target, service, number))] = {'before': digest(left), 'after': digest(right), 'mode': 'IMPORT' if imported else 'CREATE',
                        'action': 'add' if left is None else 'delete' if right is None else 'update'}
        return base, found


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
    selected = (contract_path(root, selected=contract_file) if contract_file is not None else task_path(root)).relative_to(root).as_posix()
    text = contracts(root).get(selected, '')
    from task_contract import model_operation, model_refactor
    operation = model_operation(text)
    refactor = model_refactor(text)
    if operation is not None:
        if generation:
            return  # Source/view generation does not decide final Model operation meaning.
        base = final_candidate.base_commit if final_candidate is not None else base_revision(root, contract_file=contract_file)
        if base is None:
            raise ValueError('IMPORT Model-only operation requires a versioned baseline')
        from model_operation_checks import verify_model_operation
        with snapshots(root, base, output or {}, detached=contract_file is not None) as (before, after):
            if operation.action in {'import-retarget', 'import-delete'}:
                from validation_scope import active_scope
                scope = set(final_candidate.scope) if final_candidate is not None else active_scope(root, contract_file=contract_file)
                required = {tuple(address.split('/')[:3]) for ref in operation.references
                            for address in (ref.consumer, ref.source, ref.destination)}
                required |= operation.scopes | affected(after, sources, before=before)
                if scope is None or not required <= scope:
                    raise ValueError('Model operation requires all producers/consumers in Validation scope')
            warnings = verify_model_operation(before, after, operation, sources)
        from model_core import report_reference_warnings
        report_reference_warnings(warnings)
        return warnings
    if refactor is not None:
        from model_operation_checks import verify_model_refactor
        from validation_scope import active_scope
        from task_contract import paths_in, matches, safe_path
        declared, allowed = paths_in(text, '## Modified files'), paths_in(text, '## Allowed paths')
        for relative in sources:
            safe_path(root, relative)
            if relative not in declared or not any(matches(relative, pattern) for pattern in allowed):
                raise ValueError('Model refactor source outside Modified files/Allowed paths: ' + relative)
        base = final_candidate.base_commit if final_candidate is not None else base_revision(root, contract_file=contract_file)
        if base is None:
            raise ValueError('Model refactor requires a versioned baseline')
        scope = set(final_candidate.scope) if final_candidate is not None else active_scope(root, contract_file=contract_file)
        with snapshots(root, base, output or {}, detached=contract_file is not None) as (before, after):
            warnings = verify_model_refactor(before, after, refactor, sources, scope)
        from model_core import report_reference_warnings
        report_reference_warnings(warnings)
        return warnings
    import_task = '- Workflow: `import`' in section(text, '## Task contract')
    if import_task:
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
    base, differences = changes(root, sources, output, contract_file=contract_file)
    if differences:
        raise ValueError('IMPORT configuration changes require the registered design /import workflow')


def read_proof(root, *, contract_file=None):
    from import_scope import selected
    from task_contract import safe_path
    reference = {} if contract_file is None else {'contract_file': contract_file}
    file = proof_path(root, **reference)
    legacy = safe_path(root, '.blueprint/import/' + (contract_path(root, selected=contract_file) if contract_file is not None else task_path(root)).stem + '.json')
    try:
        source = file if file.exists() else legacy
        if file.is_symlink() or source.is_symlink():
            raise ValueError('symlink import evidence')
        proof = read_sealed(root, source)
        require_fresh_acquisition(proof)
        if (proof['version'] != 4
                or proof['task'] != workflow(root, **reference) or proof['base'] != base_revision(root, **reference)
                or proof['scope'] != list(selected(root, **reference)) or not proof['acquisition']
                or not isinstance(proof['sources'], dict) or not proof['plan']
                or type(proof['complete']) is not bool
                or proof['model'] not in {'pending', 'reflected', 'unchanged'}
                or proof['markdown'] not in {'not-run', 'failed', 'generated', 'unchanged'}
                or not isinstance(proof['ownedArtifacts'], list)):
            raise ValueError('stale import evidence')
        for relative, checksum in proof['sources'].items():
            safe_path(root, relative)
            if checksum is not None and (not isinstance(checksum, str) or len(checksum) != 64):
                raise ValueError('invalid source checksum')
        for relative in proof['ownedArtifacts']:
            safe_path(root, relative)
        from import_approval import require_human_approval
        binding = proof['approval']
        if (binding['task'] != proof['task'] or binding['worktree'] != str(root.resolve())
                or binding['scope'] != proof['scope'] or binding['acquisitionDigest'] != proof['acquisition']):
            raise ValueError('IMPORT approval belongs to another Task/Worktree/scope/acquisition')
        require_human_approval(binding, proof['sources'])
        if legacy.exists():
            if any(file_hash(safe_path(root, relative)) != checksum for relative, checksum in proof['sources'].items()):
                raise ValueError('legacy IMPORT sources differ from acquired change plan')
            if read_sealed(root, legacy) != proof:
                raise ValueError('conflicting legacy import evidence')
            write_sealed(root, file, proof)
            legacy.unlink()
            for directory in (legacy.parent, legacy.parent.parent):
                if not any(directory.iterdir()):
                    directory.rmdir()
        return proof
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('IMPORT change has no verified /import evidence; flags and contract declarations are insufficient') from error


def record_import(root, output, evidence, plan, complete=True, *, approval=None):
    """Bind a verified cross-process acquisition and checked candidate to exact bytes."""
    from import_approval import require_human_approval
    source_hashes = {p.relative_to(root).as_posix(): text_hash(text) for p, text in output.items()}
    require_human_approval(approval, source_hashes)
    from import_scope import selected
    identity = selected(root)
    acquisition = read_acquisition(root, evidence, identity, False)
    if (acquisition['root'] != str(root.resolve()) or acquisition['task'] != workflow(root)
            or acquisition['scope'] != list(identity) or acquisition['dryRun']):
        raise ValueError('IMPORT evidence does not authorize this source publication')
    planned = {p.relative_to(root).as_posix(): text for p, text in output.items()}
    if (not isinstance(approval, dict) or approval.get('task') != acquisition['task']
            or approval.get('worktree') != acquisition['root'] or approval.get('scope') != acquisition['scope']
            or approval.get('acquisitionDigest') != digest(acquisition)
            or approval.get('sourceBaselineDigest') != digest(acquisition['sources'])
            or approval.get('selectionDigest') != digest(plan.get('selection'))):
        raise ValueError('IMPORT approval differs from acquisition/selection/baseline')
    if plan.get('sources') != planned:
        raise ValueError('IMPORT evidence requires the checked candidate sources')
    if proof_path(root).exists():
        raise ValueError('IMPORT Task already published; use display recovery or a new Task')
    sources = source_hashes
    proof = {'version': 4, 'approval': approval, 'task': workflow(root), 'base': base_revision(root),
             'scope': list(identity), 'sources': sources,
             'before': {p.relative_to(root).as_posix(): file_hash(p) for p in output},
             'plan': digest(plan), 'acquisition': digest(acquisition),
             'acquiredAt': acquisition['acquiredAt'], 'ownedArtifacts': plan['ownedArtifacts'],
             'connection': acquisition['connection'], 'complete': complete and acquisition_complete(acquisition),
             'model': 'pending', 'markdown': 'not-run', 'designValidation': 'not-run'}
    file = proof_path(root)
    file.parent.mkdir(parents=True, exist_ok=True)
    write_sealed(root, file, proof)


def finish_import(root, model=None, markdown=None):
    require_import_changes(root, generation=True)
    proof = read_proof(root)
    if model is not None:
        proof['model'] = model
    if markdown is not None:
        proof['markdown'] = markdown
    file = proof_path(root)
    write_sealed(root, file, proof)


def copy_import_proof(root, snapshot):
    """Carry only currently valid evidence into an existing staged validation snapshot."""
    require_import_changes(root)
    proof = read_proof(root)
    destination = proof_path(snapshot)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_sealed(snapshot, destination, proof)


def discard_import_proof(root, task_name):
    """Remove only this task's sealed receipt after verified integration/snapshot use."""
    from task_contract import TASK_NAME
    if not TASK_NAME.fullmatch(task_name):
        raise ValueError('invalid evidence task identity')
    file = evidence_store(root, create=False) / (Path(task_name).stem + '.json')
    if file.exists() or file.is_symlink():
        proof = read_sealed(root, file)
        if proof.get('task') != task_name:
            raise ValueError('IMPORT evidence belongs to another task')
        file.unlink()


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


def acquired(root, identity, ctx, records, sources, consumers, dry_run):
    if not ctx.verified or ctx.services != (identity[2],) or not ctx.trace:
        raise ValueError('IMPORT acquisition requires a verified single-service AWS context')
    from import_inventory import inventory_for
    directory = Path(tempfile.mkdtemp(prefix='session-', dir=evidence_store(root)))
    try:
        value = {'version': 2, 'root': str(root.resolve()), 'task': None if dry_run else workflow(root),
                 'base': base_revision(root), 'scope': list(identity), 'dryRun': dry_run,
                 'acquiredAt': datetime.now(timezone.utc).isoformat(), 'status': 'acquired',
                 'connection': {key: ctx.target.get(key) for key in ('environment', 'directory', 'awsExecutionAccountId', 'awsAccountId', 'awsRegion', 'awsProfile')},
                 'sts': {'account': ctx.target.get('awsExecutionAccountId', ctx.target['awsAccountId']), 'verified': True},
                 'trace': ctx.trace, 'records': records, 'sources': sources,
                 'inventory': inventory_for(ctx).statuses,
                 'metrics': dict(ctx.metrics),
                 'consumers': [list(item) for item in sorted(consumers)]}
        write_sealed(root, directory / 'acquisition.json', value)
        (directory / 'candidates').mkdir()
        # This is a disposition/evidence document, never a Model mutation language.
        (directory / 'selection.json').write_text(json_text({'resources': [], 'excluded': [], 'unreflected': []}) + '\n', encoding='utf-8')
        return directory / 'acquisition.json', value
    except Exception:
        shutil.rmtree(directory)
        raise


def read_acquisition(root, file, identity, dry_run):
    file = Path(file).absolute()
    store = evidence_store(root)
    if file.name != 'acquisition.json' or file.parent.parent != store or not file.parent.name.startswith('session-') or file.parent.is_symlink():
        raise ValueError('IMPORT acquisition must use its original external evidence identifier')
    value = read_sealed(root, file)
    require_fresh_acquisition(value)
    if (value.get('version') not in {1, 2} or value.get('root') != str(root.resolve())
            or value.get('scope') != list(identity) or value.get('dryRun') is not dry_run
            or value.get('base') != base_revision(root) or value.get('status') != 'acquired'
            or value.get('task') != (None if dry_run else workflow(root))
            or value.get('sts', {}).get('verified') is not True):
        raise ValueError('IMPORT acquisition is stale or belongs to another Task/Worktree/scope')
    if value['version'] == 2:
        validate_inventory(value)
    return value


def validate_inventory(value):
    inventory = value.get('inventory')
    allowed = {'complete', 'empty', 'unsupported', 'permission_denied', 'requires_filter', 'failed', 'not_modelled'}
    if not isinstance(inventory, dict) or not inventory or any(
            not isinstance(kind, str) or not isinstance(item, dict) or item.get('status') not in allowed
            for kind, item in inventory.items()):
        raise ValueError('IMPORT acquisition inventory status is invalid')
    return inventory


def acquisition_complete(value):
    if value.get('version') == 1:
        return True  # Sealed legacy sessions had all-or-error inventory acquisition.
    if value.get('version') != 2:
        raise ValueError('IMPORT unsupported acquisition evidence version')
    return all(item['status'] in {'complete', 'empty'} for item in validate_inventory(value).values())


def require_fresh_acquisition(value):
    """A receipt cannot indefinitely authorize replay against an unchanged Git baseline."""
    acquired_at = datetime.fromisoformat(value['acquiredAt'])
    if acquired_at.tzinfo is None:
        raise ValueError('IMPORT evidence time must include its timezone')
    age = datetime.now(timezone.utc) - acquired_at
    if age < -timedelta(minutes=5) or age > timedelta(days=7):
        raise ValueError('IMPORT acquisition evidence expired')


def discard_acquisition(root, file):
    file = Path(file).absolute()
    if file.name != 'acquisition.json' or file.parent.parent != evidence_store(root) or not file.parent.name.startswith('session-') or file.parent.is_symlink():
        raise ValueError('IMPORT refusing to remove an unknown temporary directory')
    shutil.rmtree(file.parent)


def managed_source_write(root: Path, task_file: str) -> bool:
    """Select the guarded intermediate path only for a real managed Model operation."""
    from task_contract import model_operation, task_revision
    from worktree_task import task_start_commit
    _, text = task_revision(root, selected=task_file)
    return bool(text and model_operation(text) is not None and task_start_commit(root, task_file) is not None)


@contextmanager
def source_write_context(root: Path, task_file: str) -> Iterator[SourceWriteContext]:
    """Authorize one raw save in the selected running, unmerged Model-only worktree.

    Records raw registered input bytes/file sets only, after journal recovery. Raises
    ValueError/OSError on task, worktree, scope or input changes. No expansion/staging,
    generation, final verification or task status changes occur here.
    """
    from model_sources import SourceWriteContext, read_sources, source_paths, consumers, publication_lock, safe
    from sync_runtime import GenerationInputs
    from task_contract import task_revision, validate_contract, model_operation, status, paths_in, matches, safe_path
    from validation_scope import active_scope
    from validation_cache import input_context, recording_inputs
    from issue_gate import require_no_issues
    from worktree_task import load, task_worktree
    root = root.resolve()
    name, text = task_revision(root, selected=task_file)
    if name != task_file or text is None or status(text) != 'running':
        raise ValueError('source write requires an explicit running parent task')
    validate_contract(root, name, text)
    operation = model_operation(text)
    if operation is None:
        raise ValueError('source write requires a Model-only update operation')

    def current_worktree():
        _, _, _, state = load(root, Path(name).stem)
        if state['task_file'] != name or Path(state['worktree']) != root or state['merged'] is not None:
            raise ValueError('source write task/worktree is mismatched or merged')
        if task_worktree(root, state) != root:
            raise ValueError('source write requires its managed worktree')
        return state

    current_worktree()
    with input_context(), publication_lock(root):
        snapshot = GenerationInputs(root, task_file=name)
        context = None
        try:
            writable, path_scopes = set(), {}
            with recording_inputs(snapshot):
                scope = active_scope(root, task_file=name)
                selected = set(operation.scopes)
                if operation.action == 'import-retarget':
                    selected |= {tuple(a.split('/')[:3]) for ref in operation.references for a in (ref.source, ref.destination)}
                if scope is None or not selected <= scope:
                    raise ValueError('source write requires exact service Validation scope')
                require_no_issues(root, scope if operation.action == 'import-retarget' else selected, task_file=name)
                for identity in sorted(selected):
                    env, alias, service = identity
                    model = root / 'model' / env / alias / (service + '.properties')
                    _, template, directory = source_paths(model)
                    files = read_sources(model, read_context=snapshot)
                    direct = consumers(root, alias, service)
                    for path in files:
                        if path.is_relative_to(root / 'model/templates'):
                            writable.add(path)
                            path_scopes[path] = direct
                        elif identity in operation.source_scopes or path.name == 'parameters.yaml' or (operation.action == 'import-delete' and path.name == 'bindings.json'):
                            writable.add(path)
                            path_scopes[path] = {identity}
                    for consumer in direct - {identity}:
                        cenv, calias, cservice = consumer
                        others = read_sources(root / 'model' / cenv / calias / (cservice + '.properties'), read_context=snapshot)
                        for path in others:
                            if path.name == 'parameters.yaml':
                                writable.add(path)
                                path_scopes[path] = {consumer}
                if operation.action == 'import-retarget':
                    # Freeze all authority files/sets before the caller can prepare its edit.
                    for path in snapshot.select(root / 'model', '*', recursive=True, kinds=('file',)):
                        safe(root, path)
                        snapshot.read(path)
                    snapshot.read(root / 'project.json')
                # Incoming sources are read dependencies only, never write authority.
                for directory in snapshot.select(root / 'model/parameters' / operation.scope[0] / operation.scope[1]):
                    safe(root, directory)
                    if snapshot.kind(directory) != 'dir':
                        raise ValueError('invalid registered Model service directory')
                    read_sources(root / 'model' / operation.scope[0] / operation.scope[1] / (directory.name + '.properties'), read_context=snapshot)
            declared = paths_in(text, '## Modified files')
            allowed = paths_in(text, '## Allowed paths')

            def require_current(changes):
                if task_revision(root, selected=name) != (name, text):
                    raise ValueError('parent task changed before source publication')
                current_worktree()
                for path in changes:
                    relative = path.relative_to(root).as_posix()
                    safe_path(root, relative)
                    if relative not in declared or not any(matches(relative, pattern) for pattern in allowed):
                        raise ValueError('source write is outside Modified files/Allowed paths: ' + relative)
                    if not path_scopes[path] <= scope:
                        raise ValueError('changed source requires all direct consumers in Validation scope')

            context = SourceWriteContext._authorized(root, snapshot, operation, require_current, frozenset(writable))
        except BaseException:
            snapshot.close()
            raise
    try:
        yield context
    finally:
        context.close()
