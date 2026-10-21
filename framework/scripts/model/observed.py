"""Observation-only proposals preserve every non-observed byte and field."""
import re
from model.format import patch
from model.operations import _context, prepare_edit


def verify_observed_outputs(previous, outputs):
    """Prove the writer's outputs contain only explicit observation patches, byte for byte."""
    from model.format import parse
    for file, text in outputs.items():
        if file not in previous or previous[file] is None or not isinstance(text, str):
            raise ValueError('observed publication cannot add an authority file: ' + str(file))
        before, after = parse(previous[file].decode('utf-8')), parse(text)
        changes = {key: after.values.get(key) for key in before.values.keys() | after.values.keys()
                   if before.values.get(key) != after.values.get(key) or (key in before.values) != (key in after.values)}
        if any(re.fullmatch(r'observed\.row\.[A-Za-z0-9_-]+\.value', key) is None for key in changes):
            raise ValueError('observed publication changed non-observed authority: ' + str(file))
        if patch(before, changes) != text:
            raise ValueError('observed publication changed unrelated original bytes: ' + str(file))


def foreign_observation(snapshot, row):
    """Prove a Row observes only foreign Resources and is not a native physical ID."""
    from model.core import entries
    from model.references import usages
    resource_id = row.rpartition('-')[0]
    resource = dict(entries(snapshot.authoritative, 'desired.resource.'))[resource_id]
    key = f'desired.row.{row}.value'
    own_scope = '/'.join((snapshot.scope.environment, snapshot.scope.target, snapshot.scope.service))
    uses = [use for use in usages(snapshot, _coalesce=False) if use.consumer_key == key]
    if not uses or any(use.producer_kind != 'resource' or use.producer_scope == own_scope and
                       use.producer_id == resource_id for use in uses):
        return False
    from model.projection import catalog_outputs
    from utils.aws_schemas import schemas_for
    kind = resource['resourceType']
    try:
        schema = schemas_for(snapshot.scope.root).cloudformation('AWS::' + kind.replace('.', '::', 1))
    except KeyError:
        raise ValueError('IMPORT physical identity cannot be proven without its schema: ' + kind) from None
    identities = catalog_outputs(snapshot.scope.root, kind) | {
        kind + '.' + pointer.removeprefix('/properties/').replace('/', '.')
        for pointer in schema.get('primaryIdentifier', ())}
    return bool(schema.get('primaryIdentifier')) and snapshot.authoritative[f'desired.row.{row}.property'] not in identities


def require_observable_row(snapshot, row):
    resource_id = row.rpartition('-')[0]
    if (snapshot.authoritative.get(f'desired.resource.{resource_id}.resourceMode') == 'IMPORT' and
            not foreign_observation(snapshot, row)):
        raise ValueError('general observation updates cannot change an IMPORT physical identity: ' + row)


def prepare_observed(snapshot, changes, policy):
    _context(snapshot, policy)
    by_file = {}
    for key, value in changes.items():
        match = re.fullmatch(r'observed\.row\.([A-Za-z0-9_-]+)\.value', key)
        if not match or value is not None and not isinstance(value, str):
            raise ValueError('observation changes require observed.row.<id>.value string fields only')
        row = match[1]
        desired = 'desired.row.' + row + '.value'
        if desired not in snapshot.authoritative:
            raise ValueError('observation has no desired Row: ' + key)
        if snapshot.authoritative.get(key) != value or (key in snapshot.authoritative) != (value is not None):
            require_observable_row(snapshot, row)
        if value is not None:
            from model.core import entries
            from model.projection import observed_value
            observed_value(row, dict(entries(snapshot.authoritative, 'desired.row.'))[row], value, ())
        file = snapshot.locations[desired][0]
        by_file.setdefault(file, {})[key] = value
    output = {file: patch(snapshot.documents[file], changes) for file, changes in by_file.items()}
    plan = prepare_edit(snapshot, output, policy)
    previous = {key: value for key, value in snapshot.authoritative.items() if not key.startswith('observed.')}
    current = {key: value for key, value in plan.candidate.authoritative.items() if not key.startswith('observed.')}
    if previous != current:
        raise ValueError('observation proposal changed non-observed authority')
    return plan


def observed_outputs(path, values):
    """Produce only byte-preserving observation patches; no derived metadata is serialized."""
    from model.sources import load_model
    from model.core import entries
    from model.projection import observed_value
    snapshot = load_model(path)
    if {key: value for key, value in snapshot.values.items() if not key.startswith('observed.')} != {
            key: value for key, value in values.items() if not key.startswith('observed.')}:
        raise ValueError('observed writer cannot change desired, display or derived design values')
    changes = {key: values.get(key) for key in snapshot.values.keys() | values.keys()
               if key.startswith('observed.') and key.endswith('.value') and
               (snapshot.values.get(key) != values.get(key) or (key in snapshot.values) != (key in values))}
    by_file = {}
    rows = dict(entries(snapshot.authoritative, 'desired.row.'))
    for key, value in changes.items():
        match = re.fullmatch(r'observed\.row\.([A-Za-z0-9_-]+)\.value', key)
        if not match or match[1] not in rows:
            raise ValueError('observed writer requires an existing desired Row')
        row = match[1]
        require_observable_row(snapshot, row)
        if value is not None:
            observed_value(row, rows[row], value, ())
        file = snapshot.locations[f'desired.row.{row}.value'][0]
        by_file.setdefault(file, {})[key] = value
    return {file: patch(snapshot.documents[file], updates) for file, updates in by_file.items()}


def publish_observed_candidates(root, outputs, inputs=None):
    """Recheck selected Rows under the real Task context and publish one atomic Model batch."""
    from model.sources import load_model, source_scope
    from model.adapters.task import observed_write_context
    from model.format import parse
    from model.operations import _publish_plans
    changes, candidates = {}, {}
    for file, text in outputs.items():
        scope = source_scope(root, file)
        snapshot = load_model(scope)
        verify_observed_outputs({path: value.encode('utf-8') for path, value in snapshot.files.items()}, {file: text})
        old, new = snapshot.documents[file].values, parse(text).values
        updates = {key: new.get(key) for key in old.keys() | new.keys()
                   if old.get(key) != new.get(key) or (key in old) != (key in new)}
        changes.setdefault(scope.path, {}).update(updates)
        candidates.setdefault(scope.path, {})[file] = text
    if not any(changes.values()):
        return ()
    with observed_write_context(root, changes) as context:
        if inputs is not None and any(context.snapshot.read(path) != raw for path, raw in inputs.items()):
            raise ValueError('observed input snapshot changed before publication')
        plans = []
        for path, updates in changes.items():
            if not updates:
                continue
            snapshot = load_model(path, context.snapshot)
            plan = prepare_observed(snapshot, updates, context)
            if dict(plan.changes) != candidates[path]:
                raise ValueError('observed candidate differs from the authorized exact patch')
            plans.append(plan)
        return _publish_plans(tuple(plans), context)
