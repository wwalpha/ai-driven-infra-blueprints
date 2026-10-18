"""Enforce IMPORT configuration authority at existing save, validation and Git boundaries."""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import hashlib
import io
import hmac
import os
import secrets
import stat
from datetime import datetime, timezone
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
from task_contract import contracts, section, task_path
from validation_cache import input_bytes, input_text, input_is_file, input_select
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


def workflow(root):
    path = task_path(root)
    text = input_text(path, encoding='utf-8')
    contract = section(text, '## Task contract')
    if '- Task type: `design`' not in contract or contract.count('- Workflow: `import`') != 1:
        raise ValueError('IMPORT configuration changes require the registered design /import workflow')
    return path.relative_to(root).as_posix()


def proof_path(root):
    from task_contract import safe_path
    return safe_path(root, '.blueprint/import/' + task_path(root).stem + '.json')


def base_revision(root):
    result = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=root, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        valid = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=root, capture_output=True)
        if valid.returncode:
            raise ValueError('cannot determine the versioned IMPORT baseline')
        return None  # Initial registration has no previous versioned configuration.
    if contracts(root):
        from worktree_task import task_start_commit
        name = task_path(root).relative_to(root).as_posix()
        start = task_start_commit(root, name)
        if start is not None:
            return start
    return result.stdout.strip()


def changed_sources(root, supplied=None):
    if supplied is None:
        from worktree_task import changed_paths, committed_task_paths
        supplied = changed_paths(root)
        if contracts(root):
            name = task_path(root).relative_to(root).as_posix()
            supplied |= committed_task_paths(root, name) or set()
    return {str(p) for p in supplied if str(p).startswith(('model/templates/', 'model/parameters/')) or str(p) == 'project.json'}


def resource_config(values, number, path=None, expansion=None):
    spec = dict(entries(values, 'desired.resource.'))[number]
    rows = resource_row_index(values)[number]
    if path is not None:
        from model_templates import load_expansion
        from import_preservation import preserved_values
        expansion = expansion or load_expansion(path)
        compared = preserved_values(path, expansion._replace(values=values))
    else:
        compared = values
    configuration = []
    observed = []
    for rid, row in rows:
        if 'document' in row:
            value = json.loads(row['document'])
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
    if path is not None and spec.get('resourceMode', 'CREATE') != 'IMPORT':
        from model_templates import load_expansion, parse_template, service_source, json_read
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
def snapshots(root, base, output, definitions_root=None):
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
        if output:
            after = Path(directory).resolve() / 'after'
            after.mkdir()
            lifetime.enter_context(mapping_alias(definitions_root, after))
            for path in (*input_select(root / 'model', '*', recursive=True, kinds=('file',)), root / 'project.json'):
                if input_is_file(path):
                    destination = after / path.relative_to(root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(input_bytes(path))
            save_files({after / p.relative_to(root): text for p, text in output.items() if text is not None})
            for path, text in output.items():
                if text is None:
                    (after / path.relative_to(root)).unlink(missing_ok=True)
        yield before, after


def changes(root, sources, output=None, include_create=False):
    root = root.resolve()
    from import_scope import selected
    identity = selected(root)
    base = base_revision(root)
    if not sources or base is None:
        return base, {}
    with snapshots(root, base, output or {}) as (before, after):
        scope = affected(after, sources, before=before)
        # Include deleted consumers, which cannot authorize removal of IMPORT resources.
        scope |= {tuple(Path(p).parts[2:5]) for p in sources if p.startswith('model/parameters/') and len(Path(p).parts) == 6}
        found = {}
        for env, target, service in sorted(scope):
            relative = Path('model') / env / target / (service + '.properties')
            old_path, new_path = before / relative, after / relative
            old_exists = old_path in model_paths(before, env, target)
            new_exists = new_path in model_paths(after, env, target)
            old = load_model(old_path).values if old_exists else {}
            new = load_model(new_path).values if new_exists else {}
            old_resources, new_resources = dict(entries(old, 'desired.resource.')), dict(entries(new, 'desired.resource.'))
            for number in old_resources.keys() | new_resources.keys():
                previous, current = old_resources.get(number, {}), new_resources.get(number, {})
                imported = previous.get('resourceMode') == 'IMPORT' or current.get('resourceMode') == 'IMPORT'
                if not imported and not include_create:
                    continue
                left = resource_config(old, number, old_path if identity else None) if previous else None
                right = resource_config(new, number, new_path if identity else None) if current else None
                if left != right:
                    found['/'.join((env, target, service, number))] = {'before': digest(left), 'after': digest(right), 'mode': 'IMPORT' if imported else 'CREATE'}
        return base, found


def require_import_changes(root, supplied=None, output=None, generation=False):
    root = root.resolve()
    if not (root / '.git').exists():
        return  # Disposable generator stages have no Git baseline; the calling boundary is guarded.
    sources = changed_sources(root, supplied)
    if output:
        sources |= changed_sources(root, {p.relative_to(root).as_posix() for p in output})
    selected = task_path(root).relative_to(root).as_posix()
    import_task = '- Workflow: `import`' in section(contracts(root).get(selected, ''), '## Task contract')
    if import_task:
        if not sources and generation:
            return
        proof = read_proof(root)
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
    base, differences = changes(root, sources, output)
    if differences:
        raise ValueError('IMPORT configuration changes require the registered design /import workflow')


def read_proof(root):
    from import_scope import selected
    file = proof_path(root)
    try:
        if file.is_symlink():
            raise ValueError('symlink import evidence')
        proof = read_sealed(root, file)
        if (proof['version'] != 3
                or proof['task'] != workflow(root) or proof['base'] != base_revision(root)
                or proof['scope'] != list(selected(root)) or not proof['acquisition']
                or not isinstance(proof['sources'], dict) or not proof['plan']
                or type(proof['complete']) is not bool
                or proof['model'] not in {'pending', 'reflected', 'unchanged'}
                or proof['markdown'] not in {'not-run', 'failed', 'generated', 'unchanged'}
                or not isinstance(proof['ownedArtifacts'], list)):
            raise ValueError('stale import evidence')
        from task_contract import safe_path
        for relative, checksum in proof['sources'].items():
            safe_path(root, relative)
            if checksum is not None and (not isinstance(checksum, str) or len(checksum) != 64):
                raise ValueError('invalid source checksum')
        for relative in proof['ownedArtifacts']:
            safe_path(root, relative)
        return proof
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('IMPORT change has no verified /import evidence; flags and contract declarations are insufficient') from error


def record_import(root, output, evidence, plan, complete=True):
    """Bind a verified cross-process acquisition and checked candidate to exact bytes."""
    from import_scope import selected
    identity = selected(root)
    acquisition = read_acquisition(root, evidence, identity, False)
    if (acquisition['root'] != str(root.resolve()) or acquisition['task'] != workflow(root)
            or acquisition['scope'] != list(identity) or acquisition['dryRun']):
        raise ValueError('IMPORT evidence does not authorize this source publication')
    planned = {p.relative_to(root).as_posix(): text for p, text in output.items()}
    if plan.get('sources') != planned:
        raise ValueError('IMPORT evidence requires the checked candidate sources')
    prior = {}
    if changed_sources(root):
        require_import_changes(root, generation=True)
        prior = read_proof(root)['sources']
    sources = {**prior, **{name: text_hash(text) for name, text in planned.items()}}
    proof = {'version': 3, 'task': workflow(root), 'base': base_revision(root),
             'scope': list(identity), 'sources': sources,
             'before': {p.relative_to(root).as_posix(): file_hash(p) for p in output},
             'plan': digest(plan), 'acquisition': digest(acquisition),
             'acquiredAt': acquisition['acquiredAt'], 'ownedArtifacts': plan['ownedArtifacts'],
             'connection': acquisition['connection'], 'complete': complete,
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
    source = proof_path(root)
    if not source.is_file():
        return
    require_import_changes(root)
    proof = read_proof(root)
    destination = proof_path(snapshot)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_sealed(snapshot, destination, proof)


def text_hash(text):
    return None if text is None else hashlib.sha256(text.encode('utf-8')).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def evidence_store(root):
    """Private local seal, outside Git; not AWS credentials or a response snapshot."""
    base = Path(tempfile.gettempdir()).resolve() / ('blueprint-import-' + digest(str(Path.home()))[:16])
    directory = base / digest(str(root.resolve()))
    for path in (base, directory):
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
    directory = Path(tempfile.mkdtemp(prefix='session-', dir=evidence_store(root)))
    try:
        value = {'version': 1, 'root': str(root.resolve()), 'task': None if dry_run else workflow(root),
                 'base': base_revision(root), 'scope': list(identity), 'dryRun': dry_run,
                 'acquiredAt': datetime.now(timezone.utc).isoformat(), 'status': 'acquired',
                 'connection': {key: ctx.target.get(key) for key in ('environment', 'directory', 'awsExecutionAccountId', 'awsAccountId', 'awsRegion', 'awsProfile')},
                 'sts': {'account': ctx.target.get('awsExecutionAccountId', ctx.target['awsAccountId']), 'verified': True},
                 'trace': ctx.trace, 'records': records, 'sources': sources,
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
    if (value.get('version') != 1 or value.get('root') != str(root.resolve())
            or value.get('scope') != list(identity) or value.get('dryRun') is not dry_run
            or value.get('base') != base_revision(root) or value.get('status') != 'acquired'
            or value.get('task') != (None if dry_run else workflow(root))
            or value.get('sts', {}).get('verified') is not True):
        raise ValueError('IMPORT acquisition is stale or belongs to another Task/Worktree/scope')
    return value


def discard_acquisition(root, file):
    file = Path(file).absolute()
    if file.name != 'acquisition.json' or file.parent.parent != evidence_store(root) or not file.parent.name.startswith('session-') or file.parent.is_symlink():
        raise ValueError('IMPORT refusing to remove an unknown temporary directory')
    shutil.rmtree(file.parent)
