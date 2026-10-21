"""Versioned Import acquisition, Review-bound receipts and external evidence retention."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import shutil
import tempfile
from model.sources import json_text

FORMAT_FIELDS = {'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1}


def require_format(value, version, label):
    expected = {'version': version, **FORMAT_FIELDS}
    if not isinstance(value, dict) or any(type(value.get(key)) is not int or value[key] != item for key, item in expected.items()):
        raise ValueError('IMPORT ' + label + ' format is incompatible; requires ' + str(expected))

def read_proof(root, *, contract_file=None):
    from import_guard import base_revision, digest, proof_path, read_sealed, workflow
    from model.importing.scope import selected
    from task_contract import safe_path
    reference = {} if contract_file is None else {'contract_file': contract_file}
    file = proof_path(root, **reference)
    try:
        if file.is_symlink():
            raise ValueError('symlink import evidence')
        proof = read_sealed(root, file)
        require_format(proof, 6, 'receipt')
        require_fresh_acquisition(proof)
        if (proof['version'] != 6
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
        from model.importing.approval import verify_review_binding
        binding = verify_review_binding(proof['reviewBinding'])
        if proof['reviewBindingDigest'] != digest(binding):
            raise ValueError('IMPORT Review binding checksum differs')
        if (binding['task'] != proof['task'] or binding['worktree'] != str(root.resolve())
                or binding['scope'] != proof['scope'] or binding['acquisitionDigest'] != proof['acquisition']
                or binding['acquiredAt'] != proof['acquiredAt']):
            raise ValueError('IMPORT Review binding belongs to another Task/Worktree/scope/acquisition')
        return proof
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('IMPORT change has no verified /import evidence: ' + str(error)) from error


def record_import(root, output, evidence, plan, complete=True, *, review_binding=None):
    """Bind a verified cross-process acquisition and checked candidate to exact bytes."""
    from import_guard import base_revision, digest, file_hash, proof_path, text_hash, workflow, write_sealed
    from model.importing.approval import verify_review_binding
    source_hashes = {p.relative_to(root).as_posix(): text_hash(text) for p, text in output.items()}
    verify_review_binding(review_binding)
    from model.importing.scope import selected
    identity = selected(root)
    acquisition = read_acquisition(root, evidence, identity, False)
    if (acquisition['root'] != str(root.resolve()) or acquisition['task'] != workflow(root)
            or acquisition['scope'] != list(identity) or acquisition['dryRun']):
        raise ValueError('IMPORT evidence does not authorize this source publication')
    planned = {p.relative_to(root).as_posix(): text for p, text in output.items()}
    if (not isinstance(review_binding, dict) or review_binding.get('task') != acquisition['task']
            or review_binding.get('worktree') != acquisition['root'] or review_binding.get('scope') != acquisition['scope']
            or review_binding.get('acquisitionDigest') != digest(acquisition)
            or review_binding.get('sourceBaselineDigest') != digest(acquisition['sources'])
            or review_binding.get('selectionDigest') != digest(plan.get('selection'))):
        raise ValueError('IMPORT Review binding differs from acquisition/selection/baseline')
    if plan.get('sources') != planned:
        raise ValueError('IMPORT evidence requires the checked candidate sources')
    if proof_path(root).exists():
        raise ValueError('IMPORT Task already published; use display recovery or a new Task')
    sources = source_hashes
    proof = {'version': 6, **FORMAT_FIELDS, 'reviewBinding': review_binding, 'reviewBindingDigest': digest(review_binding), 'task': workflow(root), 'base': base_revision(root),
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
    from import_guard import proof_path, require_import_changes, write_sealed
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
    from import_guard import proof_path, require_import_changes, write_sealed
    require_import_changes(root)
    proof = read_proof(root)
    destination = proof_path(snapshot)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_sealed(snapshot, destination, proof)


def discard_import_proof(root, task_name):
    """Remove only this task's sealed receipt after verified integration/snapshot use."""
    from import_guard import evidence_store, read_sealed
    from task_contract import TASK_NAME
    if not TASK_NAME.fullmatch(task_name):
        raise ValueError('invalid evidence task identity')
    file = evidence_store(root, create=False) / (Path(task_name).stem + '.json')
    if file.exists() or file.is_symlink():
        proof = read_sealed(root, file)
        if proof.get('task') != task_name:
            raise ValueError('IMPORT evidence belongs to another task')
        file.unlink()


def acquired(root, identity, ctx, records, sources, consumers, dry_run, *, source_sets):
    from import_guard import base_revision, evidence_store, workflow, write_sealed, working_revision, managed_task_state
    if not ctx.verified or ctx.services != (identity[2],) or not ctx.trace:
        raise ValueError('IMPORT acquisition requires a verified single-service AWS context')
    from model.importing.inventory import inventory_for
    if not dry_run:
        from worktree_task import task_start_commit
        name = workflow(root)
        if task_start_commit(root, name) is not None:
            managed_task_state(root, name)
    directory = Path(tempfile.mkdtemp(prefix='session-', dir=evidence_store(root)))
    try:
        value = {'version': 3, **FORMAT_FIELDS, 'root': str(root.resolve()), 'task': None if dry_run else workflow(root),
                 'base': base_revision(root), 'head': working_revision(root), 'scope': list(identity), 'dryRun': dry_run,
                 'acquiredAt': datetime.now(timezone.utc).isoformat(), 'status': 'acquired',
                 'connection': {key: ctx.target.get(key) for key in ('environment', 'directory', 'awsExecutionAccountId', 'awsAccountId', 'awsRegion', 'awsProfile')},
                 'sts': {'account': ctx.target.get('awsExecutionAccountId', ctx.target['awsAccountId']), 'verified': True},
                 'trace': ctx.trace, 'records': records, 'sources': sources, 'sourceSets': source_sets,
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
    from import_guard import base_revision, evidence_store, read_sealed, workflow, working_revision, managed_task_state
    file = Path(file).absolute()
    store = evidence_store(root)
    if file.name != 'acquisition.json' or file.parent.parent != store or not file.parent.name.startswith('session-') or file.parent.is_symlink():
        raise ValueError('IMPORT acquisition must use its original external evidence identifier')
    value = read_sealed(root, file)
    require_format(value, 3, 'acquisition')
    require_fresh_acquisition(value)
    if (value.get('version') != 3 or value.get('root') != str(root.resolve())
            or value.get('scope') != list(identity) or value.get('dryRun') is not dry_run
            or value.get('base') != base_revision(root) or 'head' not in value or value['head'] != working_revision(root)
            or value.get('status') != 'acquired'
            or value.get('task') != (None if dry_run else workflow(root))
            or value.get('sts', {}).get('verified') is not True):
        raise ValueError('IMPORT acquisition is stale or belongs to another Task/Worktree/scope')
    if not dry_run:
        from worktree_task import task_start_commit
        name = workflow(root)
        if task_start_commit(root, name) is not None:
            managed_task_state(root, name)
    validate_inventory(value)
    if not isinstance(value.get('sourceSets'), list):
        raise ValueError('IMPORT acquisition has no properties v2 input file-set snapshot')
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
    require_format(value, 3, 'acquisition')
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
    from import_guard import evidence_store
    file = Path(file).absolute()
    if file.name != 'acquisition.json' or file.parent.parent != evidence_store(root) or not file.parent.name.startswith('session-') or file.parent.is_symlink():
        raise ValueError('IMPORT refusing to remove an unknown temporary directory')
    shutil.rmtree(file.parent)

