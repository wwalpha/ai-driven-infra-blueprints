"""Import Review integrity; the LLM owns explicit Human consent in conversation."""
from datetime import datetime, timedelta, timezone
from model_core import LINK, entries
from model_files import resource_row_index
from model_templates import Expansion, REFERENCE_NAME_SUFFIXES
from import_guard import digest, require_fresh_acquisition, validate_inventory
from import_sources import selection_records, verify_values, typed_row, typed_equal, has_reference, pending_items, reference_state
from import_inventory import type_name


def review_binding(review, acquisition):
    """Bind verified Review content to its acquisition; this is not Human authentication."""
    verify_review(review, review)
    require_fresh_acquisition(acquisition)
    expected = {'task': acquisition['task'], 'worktree': acquisition['root'],
                'scope': acquisition['scope'], 'acquisitionDigest': digest(acquisition),
                'sourceBaselineDigest': digest(acquisition['sources'])}
    if any(not typed_equal(review.get(k), v) for k, v in expected.items()):
        raise ValueError('IMPORT Review belongs to another acquisition/Task/Worktree/baseline')
    if any(item['operation'] == 'unresolved' for item in review['dispositions']):
        raise ValueError('IMPORT all Resource selections must be answered before final approval/publication')
    return verify_review_binding({**expected, 'reviewDigest': review['reviewDigest'],
            'recordsDigest': digest(review['dispositions']), 'selectionDigest': digest(review['selection']),
            'referencesDigest': digest(review['referenceProvenance']),
            'proposedValuesDigest': review['proposedValuesDigest'],
            'impactDigest': digest(review.get('referenceImpact', {})),
            'acquiredAt': acquisition['acquiredAt'], 'expiresAt': review['expiresAt']})


def verify_review_binding(binding):
    """Validate receipt structure/lifetime, never authenticate conversational consent."""
    hashes = {'acquisitionDigest', 'sourceBaselineDigest', 'reviewDigest', 'recordsDigest',
              'selectionDigest', 'referencesDigest', 'proposedValuesDigest', 'impactDigest'}
    fields = hashes | {'task', 'worktree', 'scope', 'acquiredAt', 'expiresAt'}
    if (not isinstance(binding, dict) or set(binding) != fields
            or any(not isinstance(binding[k], str) or len(binding[k]) != 64
                   or any(c not in '0123456789abcdef' for c in binding[k]) for k in hashes)
            or any(not isinstance(binding[k], str) or not binding[k] for k in ('task', 'worktree'))
            or not isinstance(binding['scope'], list) or len(binding['scope']) != 3
            or any(not isinstance(v, str) or not v for v in binding['scope'])):
        raise ValueError('IMPORT invalid Review binding')
    require_fresh_acquisition(binding)
    try:
        acquired = datetime.fromisoformat(binding['acquiredAt'])
        expiry = datetime.fromisoformat(binding['expiresAt'])
        if (expiry.tzinfo is None or not datetime.now(timezone.utc) < expiry <= acquired + timedelta(days=7)):
            raise ValueError('expiry')
    except (ValueError, TypeError) as error:
        raise ValueError('IMPORT Review binding expired or has invalid expiry') from error
    return binding


def checkpoint(acquisition, answers):
    """Wrap LLM-owned partial answers; never choose a question, target or default."""
    value = {'acquisitionDigest': digest(acquisition), 'sourceBaselineDigest': digest(acquisition['sources']),
             'task': acquisition['task'], 'worktree': acquisition['root'], 'scope': acquisition['scope'],
             'answers': answers}
    verify_checkpoint(acquisition, value)
    return value


def verify_checkpoint(acquisition, value):
    """Mechanical resume check; caller first reloads evidence and compares live sources."""
    require_fresh_acquisition(acquisition)
    expected = {'acquisitionDigest': digest(acquisition), 'sourceBaselineDigest': digest(acquisition['sources']),
                'task': acquisition['task'], 'worktree': acquisition['root'], 'scope': acquisition['scope']}
    if (not isinstance(value, dict) or set(value) != {*expected, 'answers'}
            or any(not typed_equal(value[k], v) for k, v in expected.items())
            or not isinstance(value['answers'], list)):
        raise ValueError('IMPORT stale or invalid answer checkpoint')
    records = {r['record'] for r in acquisition['records']}
    seen, targets = set(), set()
    for answer in value['answers']:
        if (not isinstance(answer, dict) or answer.get('record') not in records
                or answer['record'] in seen or answer.get('action') not in {'add', 'refresh', 'replace', 'bind', 'excluded'}
                or not isinstance(answer.get('reason'), str) or not answer['reason'].strip()):
            raise ValueError('IMPORT invalid or duplicate checkpoint answer')
        seen.add(answer['record'])
        if answer['action'] != 'excluded':
            target = answer.get('resource')
            if not isinstance(target, str) or not target or target in targets:
                raise ValueError('IMPORT duplicate or missing checkpoint Model Resource ID')
            targets.add(target)
    return value['answers']


def build_review(acquisition, selection, before, proposed, risks, property_schema, *, proposed_references=None, reference_impact=None):
    """Validate an LLM-authored proposed expanded snapshot; never edit source files."""
    require_fresh_acquisition(acquisition)
    if not isinstance(proposed, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                             for k, v in proposed.items()):
        raise ValueError('IMPORT Review proposedValues must be expanded Model string fields')
    proposed = {**before.values, **proposed}
    records = acquisition['records']
    inventory = validate_inventory(acquisition)
    if any(record['kind'] not in inventory for record in records):
        raise ValueError('IMPORT Review inventory must cover every acquired Resource Type')
    ids = {r['record'] for r in records}
    if len(ids) != len(records) or not isinstance(risks, dict) or set(risks) != ids or any(
            not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items)
            for items in risks.values()):
        raise ValueError('IMPORT Review risks must cover every acquired record exactly once')
    reference_impact = reference_impact or {'inputs': {}, 'warnings': []}
    warnings, matching = list(reference_impact['warnings']), {}
    selected = selection_records(selection, records, before.values, proposed, property_schema,
                                 warnings, matching=matching)
    for key, value in before.values.items():
        if proposed.get(key) == value:
            continue
        parts = key.split('.')
        owner = parts[2].rpartition('-')[0] if len(parts) == 4 and parts[1] == 'row' else parts[2] if len(parts) == 4 and parts[1] == 'resource' else None
        if owner not in selected:
            raise ValueError('IMPORT Review changes an unselected Resource or service field: ' + key)
    prior_references = reference_provenance(before)
    proposed_references = prior_references if proposed_references is None else proposed_references
    validate_reference_proposal(proposed_references, proposed)
    for key in prior_references.keys() | proposed_references.keys():
        if typed_equal(prior_references.get(key), proposed_references.get(key)):
            continue
        parts = key.split('.')
        owner = parts[2].rpartition('-')[0] if parts[1] == 'row' else parts[2]
        if owner not in selected:
            raise ValueError('IMPORT Review changes an unselected Resource reference: ' + key)
    after = Expansion(proposed, proposed_references, {})
    verify_values(before._replace(provenance=prior_references), after, selected, property_schema, warnings=warnings)
    pending = pending_items(selection, selected, proposed, property_schema)
    old_resources = dict(entries(before.values, 'desired.resource.'))
    new_resources = dict(entries(proposed, 'desired.resource.'))
    old_rows, new_rows = resource_row_index(before.values), resource_row_index(proposed)
    decisions = {item['record']: item for item in selection['resources']}
    decisions.update({item['record']: {**item, 'action': 'excluded'} for item in selection['excluded']})
    decisions.update({item['record']: {**item, 'action': 'unresolved'}
                      for item in selection['unreflected'] if 'property' not in item})

    def rows(values, indexed, rid, prop):
        result = []
        for row_id, row in indexed.get(rid, []):
            if row['property'] != prop:
                continue
            raw = row.get('document', row['value'])
            value = raw if LINK.fullmatch(raw) or '<<' in raw else typed_row(row, raw, property_schema(prop))
            current = values.get('observed.row.' + row_id + '.value')
            result.append({'row': row_id, 'desired': value,
                           'nativeType': {str: 'string', bool: 'boolean', int: 'integer', float: 'number',
                                          list: 'array', dict: 'object', type(None): 'null'}[type(value)],
                           'observed': None if current is None else typed_row(
                               {'property': prop}, current, property_schema(prop)),
                           'observedPresent': current is not None,
                           'reference': raw if has_reference(raw) or '<<' in raw else None})
        return result

    dispositions = []
    for record in records:
        decision = decisions[record['record']]
        rid = decision.get('resource')
        details = matching[record['record']]
        # Excluded/unresolved records still show their existing exact matches.
        existing = details['existingResources']
        prior = rid if rid in old_resources else existing[0] if len(existing) == 1 else None
        properties = []
        for prop, capture in sorted(record['properties'].items()):
            withheld = capture.get('reason') == 'sensitive Property'
            left = [] if withheld else rows(before.values, old_rows, prior, prop)
            right = left if rid is None else [] if withheld else rows(proposed, new_rows, rid, prop)
            properties.append({'property': prop, 'acquisition': capture,
                               'before': left, 'after': right, 'changed': not typed_equal(left, right)})
        names = {p: c['value'] for p, c in record['properties'].items()
                 if p.endswith(REFERENCE_NAME_SUFFIXES) and c.get('status') == 'captured'}
        tag_keys = record['properties'].get(record['kind'] + '.Tags[].Key', {}).get('value')
        tag_values = record['properties'].get(record['kind'] + '.Tags[].Value', {}).get('value')
        if isinstance(tag_keys, list) and isinstance(tag_values, list) and len(tag_keys) == len(tag_values):
            tagged = [value for key, value in zip(tag_keys, tag_values) if key == 'Name']
            if tagged:
                names['Tags[Name]'] = tagged
        dispositions.append({
            'record': record['record'], 'resourceType': record['kind'], 'awsResourceType': type_name(record['kind']),
            'physicalId': record.get('identityComponents', record['identity']),
            'name': names or {'status': 'not-acquired'}, 'matching': details,
            'operation': decision['action'], 'targetResource': rid, 'reason': decision['reason'],
            'beforeResource': old_resources.get(prior), 'afterResource': new_resources.get(rid),
            'properties': properties,
            'unreflected': [item for item in pending if item['record'] == record['record']],
            'risks': [*risks[record['record']], *[w for w in warnings if w.get('record') == record['record']
                      or rid is not None and w.get('resource') == rid]]})
    review = {'version': 3, 'task': acquisition['task'], 'worktree': acquisition['root'],
              'scope': acquisition['scope'], 'connection': acquisition['connection'],
              'acquiredAt': acquisition['acquiredAt'], 'acquisitionDigest': digest(acquisition),
              'expiresAt': (datetime.fromisoformat(acquisition['acquiredAt']) + timedelta(days=7)).isoformat(),
              'sourceBaselineDigest': digest(acquisition['sources']),
              'inventory': inventory, 'selection': selection,
              'dispositions': dispositions, 'warnings': warnings,
              'referenceProvenance': {'before': prior_references, 'after': proposed_references},
              'referenceImpact': reference_impact,
              'proposedValuesDigest': digest(proposed), 'approvalBoundary': 'llm-explicit-consent'}
    return {**review, 'reviewDigest': digest(review)}


def verify_review(review, expected):
    """Integrity/meaning comparison only; a matching digest never grants approval."""
    content = {key: value for key, value in review.items() if key != 'reviewDigest'}
    if review.get('reviewDigest') != digest(content) or not typed_equal(review, expected):
        raise ValueError('IMPORT Review changed or stale; present the changed records/values/references/risks again')


def reference_provenance(expansion):
    """Extract the same declarations/selectors checked by verify_values()."""
    result = {}
    fields = {'type', 'source', 'service', 'resourceType', 'format', 'property', 'target', 'instance'}
    for key, trace in expansion.provenance.items():
        state = {group: {name: {k: v for k, v in spec.items() if k in fields | ({'value'} if group == 'inputs' else set())}
                         for name, spec in declarations.items()}
                 for group, declarations in reference_state(trace).items()}
        if key.startswith(('desired.row.', 'desired.resource.')) and (state['references'] or state['inputs']):
            result[key] = {**state, **{name: trace[name] for name in ('definition', 'instance', 'key') if name in trace}}
    return result


def validate_reference_proposal(proposal, values):
    """Validate declarations with the existing input contract, without resolving producers."""
    from model_parameter_inputs import schema, check_type, reference_schema
    if not isinstance(proposal, dict):
        raise ValueError('IMPORT Review referenceProvenance must be an object')
    for key, state in proposal.items():
        if (key not in values or not key.startswith('desired.') or len(key.split('.')) != 4
                or key.split('.')[1] not in {'row', 'resource'} or not isinstance(state, dict)
                or set(state) - {'references', 'inputs', 'definition', 'instance', 'key'}
                or not {'references', 'inputs'} <= state.keys()):
            raise ValueError('IMPORT Review invalid Reference provenance: ' + str(key))
        for group in ('references', 'inputs'):
            if not isinstance(state[group], dict):
                raise ValueError('IMPORT Review invalid Reference declarations')
            for name, declaration in state[group].items():
                if not isinstance(name, str) or not isinstance(declaration, dict):
                    raise ValueError('IMPORT Review invalid Reference declaration')
                spec = {k: v for k, v in declaration.items() if k != 'value'}
                if spec.get('source') == 'instance':
                    spec.pop('source')
                checked = schema({**spec, 'description': 'Import Review reference', 'required': True})
                if checked['type'] != 'reference' or group == 'references' and checked.get('source') != 'template':
                    raise ValueError('IMPORT Review requires a Reference declaration')
                if group == 'inputs':
                    check_type(checked, declaration.get('value'), name)
                else:
                    target = {k: checked[k] for k in ('service', 'resourceType', 'format', 'property') if k in checked}
                    target['instance' if 'instance' in checked or 'service' not in checked else 'resource'] = checked.get('target')
                    reference_schema(target)
        normalized = reference_provenance(Expansion(values, {key: state}, {}))
        if normalized.get(key) != state:
            raise ValueError('IMPORT Review requires normalized Reference provenance')
