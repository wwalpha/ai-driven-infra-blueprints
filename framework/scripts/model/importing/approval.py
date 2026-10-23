"""Import Review integrity; the LLM owns explicit Human consent in conversation."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from utils.type_contracts import JsonObject
from utils.type_contracts import JsonValue as JsonValue

from datetime import datetime, timedelta, timezone
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

import import_guard as _dependency_import_guard

import model.identity as _dependency_model_identity
import model.identity as _imports_model_identity
import model.importing.evidence as _dependency_model_importing_evidence
import model.importing.inventory as _dependency_model_importing_inventory
import model.importing.sources as _dependency_model_importing_sources
import model.references as _dependency_model_references
import model.sources as _dependency_model_sources
import model.sources as _imports_model_sources
from model.core import entries, resource_row_index
from model.format import FORMAT_FIELDS, REFERENCE_NAME_SUFFIXES, owner
from model.format import require_format as require_format


def review_binding(review: JsonObject, acquisition: JsonObject) -> JsonObject:
    """Bind verified Review content to its acquisition; this is not Human authentication."""
    verify_review(review, review)
    _dependency_model_importing_evidence.require_format(acquisition, 3, 'acquisition')
    _dependency_model_importing_evidence.require_fresh_acquisition(acquisition)
    expected = {'task': acquisition['task'], 'worktree': acquisition['root'],
                'scope': acquisition['scope'], 'acquisitionDigest': _dependency_import_guard.digest(acquisition),
                'sourceBaselineDigest': _dependency_import_guard.digest(acquisition['sources'])}
    if any(not _dependency_model_importing_sources.typed_equal(review.get(k), v) for k, v in expected.items()):
        raise ValueError('IMPORT Review belongs to another acquisition/Task/Worktree/baseline')
    if any(item['operation'] == 'unresolved' for item in review['dispositions']):
        raise ValueError('IMPORT all Resource selections must be answered before final approval/publication')
    return verify_review_binding({'version': 2, **FORMAT_FIELDS, **expected, 'reviewDigest': review['reviewDigest'],
            'recordsDigest': _dependency_import_guard.digest(review['dispositions']), 'selectionDigest': _dependency_import_guard.digest(review['selection']),
            'referencesDigest': _dependency_import_guard.digest(review['referenceProvenance']),
            'proposedValuesDigest': review['proposedValuesDigest'],
            'impactDigest': _dependency_import_guard.digest(review.get('referenceImpact', {})),
            'acquiredAt': acquisition['acquiredAt'], 'expiresAt': review['expiresAt']})


def verify_review_binding(binding: JsonObject) -> JsonObject:
    """Validate receipt structure/lifetime, never authenticate conversational consent."""
    _dependency_model_importing_evidence.require_format(binding, 2, 'Review binding')
    hashes = {'acquisitionDigest', 'sourceBaselineDigest', 'reviewDigest', 'recordsDigest',
              'selectionDigest', 'referencesDigest', 'proposedValuesDigest', 'impactDigest'}
    fields = hashes | {'task', 'worktree', 'scope', 'acquiredAt', 'expiresAt', 'version', *FORMAT_FIELDS}
    if (not isinstance(binding, dict) or set(binding) != fields
            or any(not isinstance(binding[k], str) or len(binding[k]) != 64
                   or any(c not in '0123456789abcdef' for c in binding[k]) for k in hashes)
            or any(not isinstance(binding[k], str) or not binding[k] for k in ('task', 'worktree'))
            or not isinstance(binding['scope'], list) or len(binding['scope']) != 3
            or any(not isinstance(v, str) or not v for v in binding['scope'])):
        raise ValueError('IMPORT invalid Review binding')
    _dependency_model_importing_evidence.require_fresh_acquisition(binding)
    try:
        acquired = datetime.fromisoformat(binding['acquiredAt'])
        expiry = datetime.fromisoformat(binding['expiresAt'])
        if (expiry.tzinfo is None or not datetime.now(timezone.utc) < expiry <= acquired + timedelta(days=7)):
            raise ValueError('expiry')
    except (ValueError, TypeError) as error:
        raise ValueError('IMPORT Review binding expired or has invalid expiry') from error
    return binding


def checkpoint(acquisition: JsonObject, answers: list[JsonObject]) -> JsonObject:
    """Wrap LLM-owned partial answers; never choose a question, target or default."""
    _dependency_model_importing_evidence.require_format(acquisition, 3, 'acquisition')
    value = {'version': 2, **FORMAT_FIELDS, 'acquisitionDigest': _dependency_import_guard.digest(acquisition), 'sourceBaselineDigest': _dependency_import_guard.digest(acquisition['sources']),
             'task': acquisition['task'], 'worktree': acquisition['root'], 'scope': acquisition['scope'],
             'answers': answers}
    verify_checkpoint(acquisition, value)
    return value


def verify_checkpoint(acquisition: JsonObject, value: JsonObject) -> list[JsonObject]:
    """Mechanical resume check; caller first reloads evidence and compares live sources."""
    _dependency_model_importing_evidence.require_fresh_acquisition(acquisition)
    _dependency_model_importing_evidence.require_format(acquisition, 3, 'acquisition')
    _dependency_model_importing_evidence.require_format(value, 2, 'checkpoint')
    expected = {'version': 2, **FORMAT_FIELDS, 'acquisitionDigest': _dependency_import_guard.digest(acquisition), 'sourceBaselineDigest': _dependency_import_guard.digest(acquisition['sources']),
                'task': acquisition['task'], 'worktree': acquisition['root'], 'scope': acquisition['scope']}
    if (not isinstance(value, dict) or set(value) != {*expected, 'answers'}
            or any(not _dependency_model_importing_sources.typed_equal(value[k], v) for k, v in expected.items())
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


def _callback_build_review_rows(property_schema, /, values, indexed, rid, prop):
    result = []
    for row_id, row in indexed.get(rid, []):
        if row['property'] != prop:
            continue
        raw = row.get('document', row['value'])
        value = raw if _dependency_model_identity.resource_link(raw) else _dependency_model_importing_sources.typed_row(row, raw, property_schema(prop))
        current = values.get('observed.row.' + row_id + '.value')
        result.append({'row': row_id, 'desired': value,
                       'nativeType': {str: 'string', bool: 'boolean', int: 'integer', float: 'number',
                                      list: 'array', dict: 'object', type(None): 'null'}[type(value)],
                       'observed': None if current is None else _dependency_model_importing_sources.typed_row(
                           {'property': prop}, current, property_schema(prop)),
                       'observedPresent': current is not None,
                       'reference': raw if _dependency_model_importing_sources.has_reference(raw) else None})
    return result


def build_review(
    acquisition: JsonObject,
    selection: JsonObject,
    before: _dependency_model_sources.ModelSnapshot,
    proposed: dict[str, str],
    risks: dict[str, list[str]],
    property_schema: Callable[[str], JsonObject],
    *,
    proposed_references: dict[str, dict[str, str]] | None = None,
    reference_impact: JsonObject | None = None,
) -> JsonObject:
    """Validate an LLM-authored proposed authoritative snapshot; never edit source files."""
    COUNTERS = _imports_model_identity.COUNTERS
    preserve_allocation = _imports_model_identity.preserve_allocation
    Scope = _imports_model_sources.Scope
    _dependency_model_importing_evidence.require_fresh_acquisition(acquisition)
    _dependency_model_importing_evidence.require_format(acquisition, 3, 'acquisition')
    if not isinstance(proposed, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                             for k, v in proposed.items()):
        raise ValueError('IMPORT Review candidate must contain authoritative Model string fields')
    records = acquisition['records']
    inventory = _dependency_model_importing_evidence.validate_inventory(acquisition)
    if any(record['kind'] not in inventory for record in records):
        raise ValueError('IMPORT Review inventory must cover every acquired Resource Type')
    ids = {r['record'] for r in records}
    if len(ids) != len(records) or not isinstance(risks, dict) or set(risks) != ids or any(
            not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items)
            for items in risks.values()):
        raise ValueError('IMPORT Review risks must cover every acquired record exactly once')
    reference_impact = reference_impact or {'inputs': {}, 'warnings': []}
    warnings, matching = list(reference_impact['warnings']), {}
    selected = _dependency_model_importing_sources.selection_records(selection, records, before.authoritative, proposed, property_schema,
                                 warnings, matching=matching)
    prior_references = reference_provenance(before)
    proposed_references = prior_references if proposed_references is None else proposed_references
    proposed = validate_reference_proposal(proposed_references, proposed)
    prior = before.authoritative
    preserve_allocation(prior, proposed)
    for key in prior.keys() | proposed.keys():
        if prior.get(key) == proposed.get(key) and (key in prior) == (key in proposed):
            continue
        if key == COUNTERS:
            continue
        owners = {owner(key, values) for values in (prior, proposed) if key in values}
        if not prior and key.startswith(('desired.service.', 'display.service.')):
            continue
        if any(kind != 'resource' or identity not in selected for kind, identity in owners):
            raise ValueError('IMPORT Review changes an unselected Resource or service field: ' + key)

    after = SimpleNamespace(authoritative=proposed, values=_dependency_model_sources.runtime_values(proposed),
                            scope=Scope(Path(acquisition['root']), *acquisition['scope']))
    _dependency_model_importing_sources.verify_values(before, after, selected, property_schema, warnings=warnings)
    pending = _dependency_model_importing_sources.pending_items(selection, selected, after.values, property_schema)
    old_resources = dict(entries(before.values, 'desired.resource.'))
    new_resources = dict(entries(proposed, 'desired.resource.'))
    old_rows, new_rows = resource_row_index(before.values), resource_row_index(proposed)
    canonical_changes, service_changes = {}, []
    for key in sorted(prior.keys() | proposed.keys()):
        if prior.get(key) == proposed.get(key) and (key in prior) == (key in proposed):
            continue
        change = {'key': key, 'before': {'present': key in prior, 'value': prior.get(key)},
                  'after': {'present': key in proposed, 'value': proposed.get(key)}}
        owners = {owner(key, values) for values in (prior, proposed) if key in values}
        for kind, identity in owners:
            if kind == 'resource':
                canonical_changes.setdefault(identity, []).append(change)
            else:
                service_changes.append(change)
    decisions = {item['record']: item for item in selection['resources']}
    decisions.update({item['record']: {**item, 'action': 'excluded'} for item in selection['excluded']})
    decisions.update({item['record']: {**item, 'action': 'unresolved'}
                      for item in selection['unreflected'] if 'property' not in item})

    rows = _bind_framework_callback(_callback_build_review_rows, property_schema)

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
                               'before': left, 'after': right, 'changed': not _dependency_model_importing_sources.typed_equal(left, right)})
        names = {p: c['value'] for p, c in record['properties'].items()
                 if p.endswith(REFERENCE_NAME_SUFFIXES) and c.get('status') == 'captured'}
        tag_keys = record['properties'].get(record['kind'] + '.Tags[].Key', {}).get('value')
        tag_values = record['properties'].get(record['kind'] + '.Tags[].Value', {}).get('value')
        if isinstance(tag_keys, list) and isinstance(tag_values, list) and len(tag_keys) == len(tag_values):
            tagged = [value for key, value in zip(tag_keys, tag_values, strict=False) if key == 'Name']
            if tagged:
                names['Tags[Name]'] = tagged
        dispositions.append({
            'record': record['record'], 'resourceType': record['kind'], 'awsResourceType': _dependency_model_importing_inventory.type_name(record['kind']),
            'physicalId': record.get('identityComponents', record['identity']),
            'name': names or {'status': 'not-acquired'}, 'matching': details,
            'operation': decision['action'], 'targetResource': rid, 'reason': decision['reason'],
            'beforeResource': old_resources.get(prior), 'afterResource': new_resources.get(rid),
            'changes': canonical_changes.get(rid, []),
            'properties': properties,
            'unreflected': [item for item in pending if item['record'] == record['record']],
            'risks': [*risks[record['record']], *[w for w in warnings if w.get('record') == record['record']
                      or rid is not None and w.get('resource') == rid]]})
    review = {'version': 4, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1, 'task': acquisition['task'], 'worktree': acquisition['root'],
              'scope': acquisition['scope'], 'connection': acquisition['connection'],
              'acquiredAt': acquisition['acquiredAt'], 'acquisitionDigest': _dependency_import_guard.digest(acquisition),
              'expiresAt': (datetime.fromisoformat(acquisition['acquiredAt']) + timedelta(days=7)).isoformat(),
              'sourceBaselineDigest': _dependency_import_guard.digest(acquisition['sources']),
              'inventory': inventory, 'selection': selection,
              'dispositions': dispositions, 'warnings': warnings, 'serviceChanges': service_changes,
              'referenceProvenance': {'before': prior_references, 'after': proposed_references},
              'referenceImpact': reference_impact,
              'proposedValuesDigest': _dependency_import_guard.digest(proposed), 'approvalBoundary': 'llm-explicit-consent'}
    return {**review, 'reviewDigest': _dependency_import_guard.digest(review)}


def verify_review(review: JsonObject, expected: JsonObject) -> None:
    """Integrity/meaning comparison only; a matching digest never grants approval."""
    _dependency_model_importing_evidence.require_format(review, 4, 'Review')
    _dependency_model_importing_evidence.require_format(expected, 4, 'expected Review')
    content = {key: value for key, value in review.items() if key != 'reviewDigest'}
    if review.get('reviewDigest') != _dependency_import_guard.digest(content) or not _dependency_model_importing_sources.typed_equal(review, expected):
        raise ValueError('IMPORT Review changed or stale; present the changed records/values/references/risks again')



def reference_provenance(snapshot: _dependency_model_sources.ModelSnapshot) -> dict[str, dict[str, str]]:
    return _dependency_model_references.declarations(snapshot.authoritative)


def validate_reference_proposal(proposal: dict[str, dict[str, str]], values: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(proposal, dict) or any(not isinstance(identity, str) or not isinstance(spec, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in spec.items())
            for identity, spec in proposal.items()):
        raise ValueError('IMPORT Review reference map requires fixed IDs and string fields')
    normalized = {key: value for key, value in values.items() if not key.startswith('desired.reference.')}
    normalized.update({f'desired.reference.{identity}.{field}': value
                       for identity, spec in proposal.items() for field, value in spec.items()})
    if _dependency_model_references.declarations(normalized) != proposal:
        raise ValueError('IMPORT Review reference map must use normalized fixed IDs')
    return normalized
