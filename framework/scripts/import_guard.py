"""Enforce IMPORT configuration authority at existing save, validation and Git boundaries."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import io
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
from task_contract import contracts, section, task_path, task_changes, worktree_identity
from validation_cache import digest_files


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
    name = path.relative_to(root).as_posix()
    if name not in contracts(root):
        raise ValueError('import workflow contract must belong to this Worktree')
    text = path.read_text(encoding='utf-8')
    contract = section(text, '## Task contract')
    if '- Task type: `design`' not in contract or contract.count('- Workflow: `import`') != 1:
        raise ValueError('IMPORT configuration changes require the registered design /import workflow')
    return path.relative_to(root).as_posix()


def proof_path(root):
    name = task_path(root).relative_to(root).as_posix()
    key = hashlib.sha256((worktree_identity(root) + '\0' + name).encode()).hexdigest()
    return Path(tempfile.gettempdir()) / 'blueprint-import-authority' / (key + '.json')


def base_revision(root):
    result = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=root, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        valid = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=root, capture_output=True)
        if valid.returncode:
            raise ValueError('cannot determine the versioned IMPORT baseline')
        return None  # Initial registration has no previous versioned configuration.
    if contracts(root):
        from worktree_task import committed_task_paths, load
        name = task_path(root).relative_to(root).as_posix()
        if committed_task_paths(root, name) is not None:
            return load(root, Path(name).stem)[3]['start']
    return result.stdout.strip()


def changed_sources(root, supplied=None):
    if supplied is None:
        from worktree_task import changed_paths, committed_task_paths
        supplied = changed_paths(root)
        if contracts(root):
            name = task_path(root).relative_to(root).as_posix()
            supplied |= committed_task_paths(root, name) or set()
            # This selects changed sources for the mechanical IMPORT guard, not write permission.
            supplied = task_changes(root, supplied, name, check_conflicts=False)
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
def snapshots(root, base, output):
    for path in output:
        if not path.resolve().is_relative_to(root) or '..' in path.relative_to(root).parts:
            raise ValueError('unsafe candidate Model source path')
    with tempfile.TemporaryDirectory(prefix='blueprint-import-guard-') as directory:
        before, after = Path(directory).resolve() / 'before', Path(directory).resolve() / 'after'
        after.mkdir()
        paths = ['model', 'project.json']
        cache = _baselines.get()
        if cache is not None:
            framework = [p for p in (root / 'framework').rglob('*') if p.is_file() or p.is_symlink()]
            key = (root, base, tuple(paths), digest_files(root, framework))
            before = cache[1].get(key)
        if cache is None or before is None:
            if cache is None:
                before.mkdir()
            else:
                before = Path(tempfile.mkdtemp(dir=cache[0])).resolve()
            archive_sources(root, base, paths, before)
            if (root / 'framework').is_dir():
                shutil.copytree(root / 'framework', before / 'framework')
            if cache is not None:
                cache[1][key] = before
        if (root / 'framework').is_dir():
            shutil.copytree(root / 'framework', after / 'framework')
        if (root / 'model').is_dir():
            shutil.copytree(root / 'model', after / 'model')
        if (root / 'project.json').is_file():
            shutil.copyfile(root / 'project.json', after / 'project.json')
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
            text = output[path] if output and path in output else path.read_bytes().decode('utf-8') if path.is_file() else None
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
        proof = json.loads(file.read_text(encoding='utf-8'))
        if (proof['version'] != 2 or proof['worktree'] != worktree_identity(root)
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


def record_import(root, output, scope, ctx, plan, complete=True):
    """Bind the acquired plan to exact source bytes before the guarded transaction."""
    from import_scope import selected
    identity = selected(root)
    if not ctx.verified or scope != {identity} or ctx.services != (identity[2],) or (ctx.target['environment'], ctx.target['directory']) != identity[:2]:
        raise ValueError('import evidence requires the verified selected AWS context')
    planned = {p.relative_to(root).as_posix(): text for p, text in output.items()}
    if plan.get('sources') != planned or not ctx.trace:
        raise ValueError('import evidence requires the acquired source plan')
    prior = {}
    if changed_sources(root):
        require_import_changes(root, generation=True)
        prior = read_proof(root)['sources']
    sources = {**prior, **{p.relative_to(root).as_posix(): None if text is None else hashlib.sha256(text.encode('utf-8')).hexdigest()
                         for p, text in output.items()}}
    proof = {'version': 2, 'task': workflow(root), 'worktree': worktree_identity(root), 'base': base_revision(root),
             'scope': list(identity), 'sources': sources, 'before': {p.relative_to(root).as_posix():
                 hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None for p in output},
             'plan': digest(plan), 'acquisition': digest(ctx.trace), 'ownedArtifacts': plan['ownedArtifacts'],
             'connection': {key: ctx.target.get(key) for key in ('environment', 'directory', 'awsExecutionAccountId', 'awsAccountId', 'awsRegion', 'awsProfile')},
             'complete': complete,
             'model': 'pending', 'markdown': 'not-run', 'designValidation': 'not-run'}
    file = proof_path(root)
    file.parent.mkdir(parents=True, exist_ok=True)
    atomic_files({file: json_text(proof) + '\n'}, staging_directory=file.parent)


def finish_import(root, model=None, markdown=None):
    require_import_changes(root, generation=True)
    proof = read_proof(root)
    if model is not None:
        proof['model'] = model
    if markdown is not None:
        proof['markdown'] = markdown
    file = proof_path(root)
    atomic_files({file: json_text(proof) + '\n'}, staging_directory=file.parent)


def copy_import_proof(root, snapshot):
    """Carry only currently valid evidence into an existing staged validation snapshot."""
    source = proof_path(root)
    if not source.is_file():
        return
    require_import_changes(root)
    proof = json.loads(source.read_text(encoding='utf-8'))
    proof['worktree'] = worktree_identity(snapshot)
    destination = proof_path(snapshot)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_files({destination: json_text(proof) + '\n'}, staging_directory=destination.parent)
