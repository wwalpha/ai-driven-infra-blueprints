"""Prepare ordinary properties candidates; consume existing guarded save contexts."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from dataclasses import replace as replace
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn

import array_display as _imports_array_display
import generation_inputs as _imports_generation_inputs
import import_guard as _imports_import_guard
import task_contract_core as _imports_task_contract
import task_contract_core as _imports_task_contract_core
import utils.input_cache as _imports_utils_input_cache
from task_contract_core import DependencyDetach, ModelOperation
from utils.source_reads import CandidateReads as CandidateReads
from utils.type_contracts import JsonObject
from utils.type_contracts import JsonValue as JsonValue

import model.adapters.task as _task_adapter
import model.core as _imports_model_core
import model.identity as _dependency_model_identity
import model.identity as _imports_model_identity
import model.impact as _imports_model_impact
import model.observed as _imports_model_observed
import model.references as _dependency_model_references
import model.sources as _dependency_model_sources
import model.sources as _imports_model_sources
import model.validation as _imports_model_validation
from model.configuration import ConfigurationIndex as ConfigurationIndex
from model.configuration import _observed_index
from model.configuration import resource_configuration as resource_configuration
from model.core import ReferenceResolutionError
from model.core import entries as entries
from model.format import owner


def _same(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(value, right[key]) for key, value in left.items())
    if isinstance(left, (tuple, list)):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right, strict=False))
    return left == right


def _field_value(key, value):
    return _dependency_model_references._json(key, value)[0]


def _warn(warnings, message, **details):
    warnings.append({'code': 'reference.operation_impact', 'message': message, **details})


def operation_values(values: Mapping[str, str], number: str) -> dict[str, str]:
    """All canonical fields owned by a Resource, including its reference declarations."""
    return {key: value for key, value in values.items() if owner(key, values) == ('resource', number)}






def preserve_fixed_fields(
    before: _dependency_model_sources.ModelSnapshot,
    after: _dependency_model_sources.ModelSnapshot,
    operation: ModelOperation | _task_adapter.ObservedOperation,
) -> None:
    entries = _imports_model_core.entries
    preserve_allocation = _imports_model_identity.preserve_allocation
    old, new = before.authoritative, after.authoritative
    preserve_allocation(old, new)
    previous_refs, current_refs = declarations(old), declarations(new)
    removed_refs = previous_refs.keys() - current_refs.keys()
    added_refs = current_refs.keys() - previous_refs.keys()
    if any(previous_refs[old_id] == current_refs[new_id] for old_id in removed_refs for new_id in added_refs):
        raise ValueError('dedicated operations cannot renumber fixed reference IDs')
    previous, current = dict(entries(old, 'desired.resource.')), dict(entries(new, 'desired.resource.'))
    moved = {pair.destination.rsplit('/', 1)[1] for pair in getattr(operation, 'pairs', ())
             if tuple(pair.destination.split('/')[:3]) == (before.scope.environment, before.scope.target, before.scope.service)}
    if operation.action in {'import-merge', 'import-delete', 'import-retarget'}:
        removed = set(getattr(operation, 'delete_sources', ())) | {pair.source for pair in getattr(operation, 'pairs', ())}
        permitted = {address.rsplit('/', 1)[1] for address in removed if tuple(address.split('/')[:3]) ==
                     (before.scope.environment, before.scope.target, before.scope.service)}
        if previous.keys() - current.keys() - permitted or current.keys() - previous.keys():
            raise ValueError('Model-only save changed undeclared Resource composition')
        old_rows, new_rows = dict(entries(old, 'desired.row.')), dict(entries(new, 'desired.row.'))
        if any(row.rpartition('-')[0] in current and row.rpartition('-')[0] not in moved for row in old_rows.keys() - new_rows.keys()):
            raise ValueError('Model-only save removed a retained Resource Row')
        if any(row.rpartition('-')[0] not in moved for row in new_rows.keys() - old_rows.keys()):
            raise ValueError('Model-only save added an undeclared Resource Row')
    parent_changes = {ref.consumer.rsplit('/', 1)[1] for ref in getattr(operation, 'references', ())
                      if ref.field == 'parentReference' and tuple(ref.consumer.split('/')[:3]) ==
                      (before.scope.environment, before.scope.target, before.scope.service)}
    old_observed = new_observed = None
    for rid in previous.keys() & current.keys():
        fields = {'resourceType', 'logicalId', 'anchor', 'resourceMode', 'cfn-logicalId', 'parentProperty'}
        if rid not in parent_changes:
            fields.add('parentReference')
        if any(old.get(f'desired.resource.{rid}.' + field) != new.get(f'desired.resource.{rid}.' + field) for field in fields):
            raise ValueError('Model fixed identity or parent relationship changed: ' + rid)
        if previous[rid].get('resourceMode') == 'IMPORT' and operation.action != 'import' and rid not in moved:
            if old_observed is None:
                old_observed, new_observed = _observed_index(old), _observed_index(new)
            before_observed, after_observed = old_observed.get(rid, {}), new_observed.get(rid, {})
            if before_observed != after_observed:
                require_observable_row = _imports_model_observed.require_observable_row
                for key in before_observed.keys() | after_observed.keys():
                    if before_observed.get(key) != after_observed.get(key) or (key in before_observed) != (key in after_observed):
                        require_observable_row(before, key.removeprefix('observed.row.').removesuffix('.value'))
    for row_id, row in dict(entries(old, 'desired.row.')).items():
        key = f'desired.row.{row_id}.property'
        if key in new and new[key] != row['property']:
            raise ValueError('existing Row fixed Property changed: ' + row_id)
    for identity, stack in entries(old, 'desired.stack.'):
        key = f'desired.stack.{identity}.placementName'
        if key in new and new[key] != stack['placementName']:
            raise ValueError('fixed Stack placementName changed: ' + identity)




@dataclass(frozen=True, init=False)
class EditPlan:
    before: _dependency_model_sources.ModelSnapshot
    candidate: _dependency_model_sources.ModelSnapshot
    changes: Mapping[Path, str | None]
    policy: _dependency_model_sources.SourceWriteContext

    def __init__(self, *args: NoReturn, **kwargs: NoReturn) -> NoReturn:
        raise TypeError('use prepare_edit or prepare_observed; an EditPlan constructor grants no save authority')

    @classmethod
    def _prepared(cls, before, candidate, changes, policy):
        plan = object.__new__(cls)
        for field, value in (('before', before), ('candidate', candidate), ('changes', changes), ('policy', policy)):
            object.__setattr__(plan, field, value)
        return plan




def _preserve_layout_relative(snapshot, path):
    return path.relative_to(snapshot.scope.root)


def _callback_preserve_layout_order(values, prefix=None):
    return list(dict.fromkeys(owner(key, values) if prefix is None else key[len(prefix):].partition('.')[0]
                              for key in values if prefix is None or key.startswith(prefix)))


def preserve_layout(
    before: _dependency_model_sources.ModelSnapshot,
    after: _dependency_model_sources.ModelSnapshot,
) -> None:
    relative = _preserve_layout_relative
    old_parts = [relative(before, path) for path in before.parts]
    new_parts = [relative(after, path) for path in after.parts]
    retained = set(old_parts) & set(new_parts)
    if [path for path in old_parts if path in retained] != [path for path in new_parts if path in retained]:
        raise ValueError('dedicated operations must preserve retained part order')
    promotion = old_parts == [relative(before, before.scope.path)] and after.scope.path not in after.parts
    for key in before.authoritative.keys() & after.authoritative.keys():
        if owner(key, before.authoritative) != owner(key, after.authoritative):
            continue
        previous = relative(before, before.locations[key][0])
        expected = new_parts[0] if promotion else previous
        if relative(after, after.locations[key][0]) != expected:
            raise ValueError('dedicated operations must preserve existing block placement: ' + key)
    order = _callback_preserve_layout_order
    for prefix in (None, 'desired.row.'):
        old, new = order(before.authoritative, prefix), order(after.authoritative, prefix)
        common = set(old) & set(new)
        if [block for block in old if block in common] != [block for block in new if block in common]:
            raise ValueError('dedicated operations must preserve retained block/Row order')


def _context(snapshot, policy):
    if not isinstance(policy, _dependency_model_sources.SourceWriteContext) or policy.closed:
        raise ValueError('Model edit requires an open authorized source context; names and flags grant no rights')
    if snapshot.scope.root != policy.root:
        raise ValueError('Model snapshot belongs to another save context')
    for path, raw in snapshot.dependencies.items():
        if policy.snapshot.read(path) != raw:
            raise ValueError('Model snapshot differs from authorized inputs: ' + str(path))


def prepare_edit(
    snapshot: _dependency_model_sources.ModelSnapshot | Path,
    candidate: Mapping[Path, str | None],
    policy: _dependency_model_sources.SourceWriteContext,
) -> EditPlan:
    validate_json_settings = _imports_model_validation.validate_json_settings
    if isinstance(snapshot, Path):
        edit_base = _imports_model_sources.edit_base
        raw_model = _imports_model_sources.raw_model
        reader = raw_model
        if policy.operation.action == 'edit':
            reader = edit_base
        snapshot = reader(snapshot, policy.snapshot)
    _context(snapshot, policy)
    output = {}
    entry = snapshot.scope.path
    for path, text in candidate.items():
        if not isinstance(path, Path) or not path.is_absolute() or '..' in path.parts:
            raise ValueError('Model candidates require absolute canonical paths')
        _dependency_model_sources.safe(policy.root, path)
        if path not in policy.paths or not (path == entry or path.parent == entry.with_suffix('') and path.suffix == '.properties'):
            raise ValueError('unregistered Model candidate path: ' + str(path))
        if text is not None and not isinstance(text, str):
            raise ValueError('Model candidate must contain ordinary UTF-8 properties or a deletion')
        before = policy.snapshot.read(path)
        if before != (None if text is None else text.encode('utf-8')):
            output[path] = text
    reads = CandidateReads(policy.snapshot, output)
    after = load_model(snapshot.scope, reads)
    warnings = list(after.warnings)
    validate_json_settings(after.authoritative, entry, warnings=warnings)
    after = after._replace(warnings=tuple(warnings))
    if policy.operation.action == 'observed':
        verify_observed_outputs = _imports_model_observed.verify_observed_outputs
        verify_observed_outputs({path: text.encode('utf-8') for path, text in snapshot.files.items()}, output)
        changed_keys = {key for key in snapshot.authoritative.keys() | after.authoritative.keys()
                        if snapshot.authoritative.get(key) != after.authoritative.get(key) or
                        (key in snapshot.authoritative) != (key in after.authoritative)}
        if any((entry, key) not in policy.operation.keys for key in changed_keys):
            raise ValueError('observed candidate changed a Row outside the authorized selection')
    if policy.operation.action != 'edit':
        preserve_fixed_fields(snapshot, after, policy.operation)
        preserve_layout(snapshot, after)
    policy._require_current(output)
    return EditPlan._prepared(snapshot, after, MappingProxyType(output), policy)


def _verify_published_inputs(context, changes):
    """Only planned bytes/file additions may differ from the input snapshot after a save."""
    GenerationInputs = _imports_generation_inputs.GenerationInputs
    overlay = CandidateReads(context.snapshot, changes)
    for path in tuple(context.snapshot.contents):
        expected = overlay.read(path)
        if (path.read_bytes() if path.is_file() else None) != expected:
            raise ValueError('Model inputs changed during publication: ' + str(path))
    for path in tuple(context.snapshot.kinds):
        if GenerationInputs.live_kind(path) != overlay.kind(path):
            raise ValueError('Model input kind changed during publication: ' + str(path))
    for base, pattern, recursive, kinds in tuple(context.snapshot.selections):
        expected = overlay.select(base, pattern, recursive, kinds)
        if tuple(GenerationInputs.live_select(base, pattern, recursive, kinds)) != expected:
            raise ValueError('Model input file set changed during publication: ' + str(base))
    if context.snapshot.task_selector != _imports_task_contract._selector(context.root):
        raise ValueError('Task changed during Model publication')


def publish_edit(plan: EditPlan, context: _dependency_model_sources.SourceWriteContext) -> tuple[Path, ...]:
    return _publish_plans((plan,), context)


def _callback__publish_plans_finish(changes, context, /):
    if context._finish is not None:
        context._finish()
    _verify_published_inputs(context, changes)


def _publish_plans(plans, context):
    if context.closed or not plans or any(not isinstance(plan, EditPlan) or plan.policy is not context for plan in plans):
        raise ValueError('Model plan/context is unauthorized or already consumed')
    changes = {}
    for plan in plans:
        if changes.keys() & plan.changes.keys():
            raise ValueError('Model batch contains overlapping source writes')
        changes.update(plan.changes)
    try:
        with _dependency_model_sources.publication_lock(context.root) as journal:
            for plan in plans:
                _context(plan.before, context)
            context._require_current(changes)
            if context.operation.action in {'import-retarget', 'edit'}:
                require_import_changes = _imports_import_guard.require_import_changes
                selected_task = _imports_task_contract_core.selected_task
                recording_inputs = _imports_utils_input_cache.recording_inputs
                with selected_task(context.root, context.snapshot.expected_task[0]), recording_inputs(context.snapshot):
                    require_import_changes(context.root, output=changes)
            context.snapshot.verify()
            finish = _bind_framework_callback(_callback__publish_plans_finish, changes, context)
            if changes or context._receipt is not None:
                _dependency_model_sources._publish_transaction(context.root, {p: text for p, text in changes.items() if text is not None},
                                     {p for p, text in changes.items() if text is None}, journal, start=context._start, finish=finish, receipt=context._receipt)
            else:
                finish()
            return tuple(sorted(changes))
    finally:
        context.close()


def operation_rows(values: Mapping[str, str], number: str) -> dict[str, tuple[str, dict[str, str]]]:
    """Formal Property and array position identify rows, never matching row numbers."""
    ROOT = _imports_array_display.ROOT
    array_template = _imports_array_display.array_template
    numbered_property = _imports_array_display.numbered_property

    resource_row_index = _imports_model_core.resource_row_index

    result, states = {}, {}
    for rid, row in resource_row_index(values)[number]:
        key = numbered_property(array_template(row['property'], values['desired.resource.' + number + '.resourceType'], ROOT), states)
        if key in result:
            raise ValueError('IMPORT ambiguous Property correspondence: ' + key)
        result[key] = rid, row
    return result



_SELF = object()
_REFERENCE = object()


def _self_value(value, reference):
    if isinstance(value, dict):
        return {key: _self_value(child, reference) for key, child in value.items()}
    if isinstance(value, list):
        return [_self_value(child, reference) for child in value]
    if isinstance(value, str) and _dependency_model_identity.resource_link(value):
        anchor_index = _imports_model_identity.anchor_index
        parse_reference = _imports_model_identity.parse_reference
        select_anchor = _imports_model_identity.select_anchor
        snapshot, resource = reference
        environment, target, service, anchor = parse_reference(value, snapshot.scope)
        scope = snapshot.scope
        if (environment, target, service) == (scope.environment, scope.target, scope.service):
            try:
                _, producer = select_anchor(anchor_index(snapshot.authoritative), anchor, value)
            except ReferenceResolutionError:
                return value
            if producer['logicalId'] == resource['logicalId']:
                return _SELF
    return value


def _pointer_parent(value, pointer):
    _dependency_model_references.pointer_leaf(value, pointer)
    tokens = [part.replace('~1', '/').replace('~0', '~') for part in pointer.split('/')[1:]]
    if not tokens:
        return None, None
    for token in tokens[:-1]:
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value, int(tokens[-1]) if isinstance(value, list) else tokens[-1]


def _mask_references(leaf, records):
    if not records:
        raise ValueError('Model reference edit must identify an existing saved reference leaf')
    spans = []
    for usage in sorted(records, key=lambda item: (item.start, item.end)):
        if spans and usage.start < spans[-1][1]:
            spans[-1] = spans[-1][0], max(spans[-1][1], usage.end)
        else:
            spans.append((usage.start, usage.end))
    result, cursor = [], 0
    for start, end in spans:
        result.extend((leaf[cursor:start], _REFERENCE))
        cursor = end
    result.append(leaf[cursor:])
    return tuple(result)


def _callback__compare_field_select(resolved, /, records, path, address):
    resources = [usage for usage in records if usage.producer_kind == 'resource']
    selected = [usage for usage in resources if resolved[path, usage] == address]
    if not selected:
        if len({(usage.start, usage.end) for usage in resources}) != 1:
            raise ValueError('Model reference declaration cannot identify an unambiguous saved resource occurrence')
        selected = resources
    return selected


def _compare_field(before, old_key, after, new_key, references, warnings, usages_by_path, *, self_anchors=None):
    left, structured_left = _dependency_model_references._json(old_key, before.authoritative[old_key])
    right, structured_right = _dependency_model_references._json(new_key, after.authoritative[new_key])
    if structured_left != structured_right:
        raise ValueError('Model operation changed JSON/backtick representation: ' + new_key)
    if self_anchors is not None and not references:
        left, right = _self_value(left, self_anchors[0]), _self_value(right, self_anchors[1])
    if not references:
        if not _same(left, right):
            raise ValueError('Model operation changed an undeclared value/type: ' + new_key)
        return
    left, right = copy.deepcopy(left), copy.deepcopy(right)
    for declaration in references:
        pointer = declaration.pointer
        if structured_left != (pointer is not None):
            raise ValueError('Model reference edit requires an explicit JSON string-leaf pointer')
        old_leaf = _dependency_model_references.pointer_leaf(left, pointer) if pointer is not None else left
        new_leaf = _dependency_model_references.pointer_leaf(right, pointer) if pointer is not None else right
        if not isinstance(old_leaf, str) or not isinstance(new_leaf, str):
            raise ValueError('Model reference edit requires string leaves')
        all_previous = [usage for usage in usages_by_path[before.scope.path]
                    if usage.consumer_key == old_key and usage.pointer == pointer]
        all_current = [usage for usage in usages_by_path[after.scope.path]
                   if usage.consumer_key == new_key and usage.pointer == pointer]
        resolved = usages_by_path['resolved']
        select = _bind_framework_callback(_callback__compare_field_select, resolved)
        previous = select(all_previous, before.scope.path, declaration.source)
        previous_ids = {usage.metadata_id for usage in previous if usage.metadata_id is not None}
        matching_ids = [usage for usage in all_current if usage.metadata_id in previous_ids]
        current = matching_ids or select(all_current, after.scope.path, declaration.destination)
        for snapshot, records in ((before, previous), (after, current)):
            usages_by_path['editable_ids'].setdefault(snapshot.scope.path, set()).update(
                usage.metadata_id for usage in records if usage.metadata_id is not None)
        for snapshot, records, chosen in ((before, all_previous, previous), (after, all_current, current)):
            usages_by_path['editable_text_ids'].setdefault(snapshot.scope.path, set()).update(
                usage.metadata_id for usage in records if usage.metadata_id is not None and any(
                    usage.start < selected.end and selected.start < usage.end for selected in chosen))
        if not previous_ids:
            specs = declarations(after.authoritative)
            if any(specs[usage.metadata_id]['format'] != 'link' for usage in current if usage.metadata_id is not None):
                raise ValueError('retarget cannot change a direct link into another reference format')
        addresses = usages_by_path['addresses']
        old_addresses = addresses.get((before.scope.path, old_key, pointer), set())
        new_addresses = addresses.get((after.scope.path, new_key, pointer), set())
        if declaration.source not in old_addresses or declaration.destination not in new_addresses:
            _warn(warnings, 'saved reference producer differs from the Task declaration', key=new_key,
                  declaredSource=declaration.source, declaredDestination=declaration.destination,
                  previousProducers=sorted(old_addresses), currentProducers=sorted(new_addresses))
        a, b = _mask_references(old_leaf, previous), _mask_references(new_leaf, current)
        if not _same(a, b):
            raise ValueError('Model reference edit changed literal affixes or occurrence structure: ' + new_key)
        if pointer is None:
            left, right = a, b
        else:
            x, field = _pointer_parent(left, pointer)
            y, other = _pointer_parent(right, pointer)
            if x is None:
                left, right = a, b
            else:
                x[field], y[other] = a, b
        _warn(warnings, 'explicit saved reference edit; producer diagnostics remain warnings', key=new_key,
              source=declaration.source, destination=declaration.destination, pointer=pointer)
    if not _same(left, right):
        raise ValueError('Model reference edit changed an undeclared JSON leaf: ' + new_key)


def _resource_references(operation, scope, rid, field, prop=None):
    address = '/'.join((*scope, rid))
    return [ref for ref in operation.references if ref.consumer == address and ref.field == field and ref.property_name == prop]


def _models(root, targets, *, raw=False):
    reads = _dependency_model_sources.FileReads()
    reader = load_model
    if raw:
        reader = _dependency_model_sources.raw_model
    return {(scope.environment, scope.target, scope.service): reader(scope, reads)
            for scope in _dependency_model_sources.list_models(root, reads) if (scope.environment, scope.target) in targets}


def _check_reference_metadata(before, after, editable, moved_keys, removed, warnings, editable_ids, text_ids, detached=frozenset()):
    old, new = declarations(before.authoritative), declarations(after.authoritative)
    scope = '/'.join((before.scope.environment, before.scope.target, before.scope.service))
    replaced = set(moved_keys.values())
    expected = {}
    for identity, spec in old.items():
        key = spec['consumerKey']
        if key not in moved_keys:
            continue
        mapped = {**spec, 'consumerKey': moved_keys[key]}
        previous_owner = owner(key, before.authoritative)
        current_owner = owner(mapped['consumerKey'], after.authoritative)
        self_reference = (spec['producerKind'] == 'resource' and spec['producerScope'] == scope
                          and spec['producerLogicalId'] == before.authoritative.get(f'desired.resource.{previous_owner[1]}.logicalId'))
        if self_reference:
            mapped['producerLogicalId'] = after.authoritative[f'desired.resource.{current_owner[1]}.logicalId']
        expected.setdefault(mapped['consumerKey'], []).append((identity, mapped, self_reference))
    for key in replaced:
        candidates = [(identity, spec) for identity, spec in new.items() if spec['consumerKey'] == key]
        for identity, spec, self_reference in expected.get(key, ()):
            found = None
            for index, (_, actual) in enumerate(candidates):
                _ = (key, spec.get('pointer'))
                ignored = {'text'} if self_reference else set()
                if identity in editable_ids.get(before.scope.path, set()):
                    ignored |= {'producerScope', 'producerId', 'producerLogicalId', 'text'}
                elif identity in text_ids.get(before.scope.path, set()):
                    ignored.add('text')
                if {k: v for k, v in spec.items() if k not in ignored} == {k: v for k, v in actual.items() if k not in ignored}:
                    found = index
                    break
            if found is None:
                raise ValueError('Model merge lost a source reference meaning: ' + identity)
            candidates.pop(found)
        if any(identity not in editable_ids.get(after.scope.path, set()) for identity, spec in candidates):
            raise ValueError('Model merge added a reference absent from the source: ' + key)
    for identity in old.keys() | new.keys():
        previous, current = old.get(identity), new.get(identity)
        if previous == current:
            continue
        if identity in detached and current is None:
            continue
        old_key = previous['consumerKey'] if previous is not None else None
        new_key = current['consumerKey'] if current is not None else None
        if current is not None and old_key in moved_keys and new_key != moved_keys[old_key]:
            raise ValueError('Model merge moved a fixed reference ID to an unrelated field: ' + identity)
        if current is not None and old_key in replaced and new_key != old_key:
            raise ValueError('Model merge moved a destination reference ID: ' + identity)
        if previous is not None and new_key in replaced and old_key not in replaced and old_key not in moved_keys:
            raise ValueError('Model merge reused an unrelated reference ID: ' + identity)
        if old_key in moved_keys or old_key in replaced or new_key in replaced:
            continue  # The complete transferred reference meanings were compared above.
        if previous is not None and owner(old_key, before.authoritative) in removed and current is None:
            continue
        positions = {(spec['consumerKey'], spec.get('pointer')) for spec in (previous, current) if spec is not None}
        if not positions <= editable:
            raise ValueError('Model operation changed an undeclared reference position: ' + identity)
        if previous is None or current is None:
            if previous is not None:
                raise ValueError('retarget cannot delete a fixed reference ID; use an explicit detach: ' + identity)
            if identity not in editable_ids.get(after.scope.path, set()):
                raise ValueError('retarget added unrelated reference metadata in the same leaf: ' + identity)
            if any(spec['consumerKey'] == (new_key or old_key) and spec.get('pointer') ==
                   (current or previous).get('pointer') for other, spec in old.items() if other != identity):
                raise ValueError('retarget cannot renumber fixed reference IDs: ' + identity)
        if previous is not None and current is not None and any(previous.get(field) != current.get(field)
                for field in previous.keys() | current.keys() if field not in {'producerId', 'producerLogicalId', 'producerScope', 'text'}):
            raise ValueError('retarget cannot change reference format, Property, label policy or occurrence: ' + identity)
        if previous is not None and current is not None and any(previous.get(field) != current.get(field)
                for field in ('producerId', 'producerLogicalId', 'producerScope')) and identity not in editable_ids.get(before.scope.path, set()):
            raise ValueError('retarget changed another reference producer in the same string leaf: ' + identity)
        if previous is not None and current is not None and previous.get('text') != current.get('text') and identity not in text_ids.get(before.scope.path, set()):
            raise ValueError('retarget changed another reference occurrence in the same string leaf: ' + identity)
        _warn(warnings, 'explicit reference metadata changed', reference=identity)


def _require_declared_sources(before, after, sources):
    """Detect raw changes outside the selected targets without parsing unrelated Models."""
    FileReads = _imports_model_sources.FileReads
    source_scope = _imports_model_sources.source_scope
    inventories = []
    for root in (before, after):
        reads, files = FileReads(), {}
        for path in reads.select(root / 'model', '*', recursive=True):
            if path.suffix != '.properties' or reads.kind(path) == 'dir':
                continue
            _dependency_model_sources.safe(root, path)
            source_scope(root, path)
            files[path.relative_to(root).as_posix()] = reads.read(path)
        inventories.append(files)
    previous, current = inventories
    changed = {path for path in previous.keys() | current.keys() if previous.get(path) != current.get(path)}
    if changed - set(sources):
        raise ValueError('Model operation has undeclared raw source changes')








def _verify_model_operation_raw_files(models, root):
    return {path.relative_to(root).as_posix(): text for model in models.values() for path, text in model.files.items()}


def _verify_model_operation_remaining(values, handled):
    return {key: _field_value(key, value) for key, value in values.items() if key not in handled and (not key.startswith('desired.reference.'))}


def _verify_model_operation_explicit(values, identity):
    prefix = f'desired.resource.{identity}.'
    return {key[len(prefix):]: value for key, value in values.items() if key.startswith(prefix)}


def verify_model_operation(
    before: Path,
    after: Path,
    operation: ModelOperation,
    sources: Iterable[str],
) -> list[JsonObject]:
    """Final latest-base proof for exactly declared deletions, transfers and reference edits."""
    source_scope = _imports_model_sources.source_scope
    _require_declared_sources(before, after, sources)
    # Source identity is independent of changes to a mutable Stack name.
    if (before / 'project.json').read_bytes() != (after / 'project.json').read_bytes():
        raise ValueError('Model-only operation cannot change project configuration')
    selected = set(operation.scopes)
    targets = {scope[:2] for scope in selected}
    old_models, new_models = _models(before, targets, raw=True), _models(after, targets)
    if old_models.keys() != new_models.keys():
        raise ValueError('Model-only operation cannot add/remove service Models')
    raw_files = _verify_model_operation_raw_files
    old_raw, new_raw = raw_files(old_models, before), raw_files(new_models, after)
    changed_raw = {path for path in old_raw.keys() | new_raw.keys() if old_raw.get(path) != new_raw.get(path)}
    if changed_raw - set(sources):
        raise ValueError('Model-only operation has undeclared raw source changes')
    if operation.action == 'import-retarget' and old_raw.keys() != new_raw.keys():
        raise ValueError('retarget cannot change the authority file set')
    for relative in sources:
        if not relative.startswith('model/'):
            raise ValueError('Model-only operation changed a non-Model path: ' + relative)
        scope = source_scope(after, after / relative)
        if (scope.environment, scope.target, scope.service) not in selected:
            raise ValueError('Model-only operation source is outside its exact scope: ' + relative)
    deleted = {}
    for address in (*operation.delete_sources, *(pair.source for pair in operation.pairs)):
        *scope, rid = address.split('/')
        scope = tuple(scope)
        old = old_models.get(scope)
        if old is None or old.authoritative.get(f'desired.resource.{rid}.resourceMode') != 'IMPORT':
            raise ValueError('Model operation requires an existing IMPORT source: ' + address)
        deleted.setdefault(scope, set()).add(rid)
    pairs = {tuple(pair.destination.split('/')[:3]) + (pair.destination.rsplit('/', 1)[1],): pair for pair in operation.pairs}
    warnings = [warning for collection in (old_models, new_models) for model in collection.values() for warning in model.warnings]
    for ref in operation.references:
        for address in (ref.consumer, ref.source, ref.destination):
            *identity, rid = address.split('/')
            model = old_models.get(tuple(identity))
            if model is None or f'desired.resource.{rid}.resourceType' not in model.authoritative:
                raise ValueError('Model reference operation names an absent fixed Resource: ' + address)
            if operation.action == 'import-retarget' and address in {ref.source, ref.destination} and model.authoritative.get(
                    f'desired.resource.{rid}.resourceMode', 'CREATE') != 'IMPORT':
                raise ValueError('retarget requires existing IMPORT producers')
        if operation.action == 'import-retarget':
            *identity, rid = ref.consumer.split('/')
            consumer = old_models[tuple(identity)]
            kind = consumer.authoritative[f'desired.resource.{rid}.resourceType']
            if 'Subnet' in kind or 'Association' in kind or 'Subnet' in (ref.property_name or ''):
                raise ValueError('retarget cannot change Subnet associations')
            if ref.property_name not in operation_rows(consumer.authoritative, rid):
                raise ValueError('retarget missing or ambiguous formal Property: ' + str(ref.property_name))
    detached = _verify_detaches(old_models, new_models, operation.detaches)
    caches = {model.scope.path: model for collection in (old_models, new_models) for model in collection.values()}
    usage_records = {path: _dependency_model_references.usages(model, _cache=caches) for path, model in list(caches.items())}
    addresses, resolved = {}, {}
    for path, records in usage_records.items():
        model = caches[path]
        for usage in records:
            producer = usage.producer_id
            producer_address = usage.producer_scope + ('/stack/' if usage.producer_kind == 'stack' else '/') + (producer or '#' + (usage.logical_id or '?'))
            addresses.setdefault((path, usage.consumer_key, usage.pointer), set()).add(producer_address)
            resolved[path, usage] = producer_address
    usage_records['addresses'] = addresses
    usage_records['resolved'] = resolved
    usage_records['editable_ids'] = {}
    usage_records['editable_text_ids'] = {}
    used_references = set()
    for scope, old in old_models.items():
        new = new_models[scope]
        preserve_layout(old, new)
        preserve_fixed_fields(old, new, operation)
        old_resources, new_resources = dict(entries(old.authoritative, 'desired.resource.')), dict(entries(new.authoritative, 'desired.resource.'))
        if new_resources.keys() != old_resources.keys() - deleted.get(scope, set()):
            raise ValueError('Model operation must delete exactly the declared source Resources')
        handled_old, handled_new, moved_keys, editable = set(), set(), {}, set()
        for rid in new_resources:
            pair = pairs.get((*scope, rid))
            address = '/'.join((*scope, rid))
            if pair is None and not any(ref.consumer == address for ref in operation.references) and not any(
                    detach.consumer == address for detach in operation.detaches):
                previous_block, current_block = operation_values(old.authoritative, rid), operation_values(new.authoritative, rid)
                if not _same({key: _field_value(key, value) for key, value in previous_block.items()},
                             {key: _field_value(key, value) for key, value in current_block.items()}):
                    raise ValueError('Model operation changed an unspecified Resource: ' + address)
                handled_old.update(previous_block)
                handled_new.update(current_block)
                continue
            source_id = pair.source.rsplit('/', 1)[1] if pair else rid
            source_model = old_models[tuple(pair.source.split('/')[:3])] if pair else old
            source_values, actual_values = source_model.authoritative, new.authoritative
            source_resource = dict(entries(source_values, 'desired.resource.'))[source_id]
            if pair and (old_resources[rid].get('resourceMode') != 'IMPORT' or source_resource['resourceType'] != old_resources[rid]['resourceType']):
                raise ValueError('Model merge requires matching existing IMPORT Resource Types')
            fixed = {'resourceType', 'logicalId', 'anchor', 'resourceMode', 'cfn-logicalId', 'parentProperty', 'parentReference'}
            explicit = _verify_model_operation_explicit
            source_fields, actual_fields = explicit(source_values, source_id), explicit(actual_values, rid)
            ignored = fixed if pair else set()
            if source_fields.keys() - ignored != actual_fields.keys() - ignored:
                raise ValueError('Model source Resource settings were not fully retained/transferred')
            for field in source_fields.keys() - ignored:
                old_key, new_key = f'desired.resource.{source_id}.{field}', f'desired.resource.{rid}.{field}'
                if pair:
                    moved_keys[old_key] = new_key
                refs = _resource_references(operation, scope, rid, field)
                used_references.update(refs)
                if refs:
                    editable.update((new_key, ref.pointer) for ref in refs)
                _compare_field(source_model, old_key, new, new_key, refs, warnings, usage_records)
            source_rows, destination_rows, current_rows = operation_rows(source_values, source_id), operation_rows(old.authoritative, rid), operation_rows(actual_values, rid)
            if source_rows.keys() != current_rows.keys():
                raise ValueError('Model source Properties were not fully retained/transferred')
            for prop, (row_id, row) in current_rows.items():
                previous_id, previous_row = source_rows[prop]
                if prop in destination_rows and row_id != destination_rows[prop][0]:
                    raise ValueError('Model destination fixed Row ID changed: ' + prop)
                if pair and prop not in destination_rows and f'desired.row.{row_id}.property' in old.authoritative:
                    raise ValueError('Model merge reused an existing Row ID: ' + row_id)
                expected_comment = destination_rows[prop][1]['comment'] if pair and prop in destination_rows else previous_row['comment']
                if row['comment'] != expected_comment or row.keys() != previous_row.keys():
                    raise ValueError('Model Row structure/comment changed outside the transfer: ' + prop)
                for field in previous_row:
                    old_key, new_key = f'desired.row.{previous_id}.{field}', f'desired.row.{row_id}.{field}'
                    if pair and (field != 'comment' or prop not in destination_rows):
                        moved_keys[old_key] = new_key
                    if field == 'comment' or pair and field == 'value' and 'document' in previous_row:
                        continue
                    refs = _resource_references(operation, scope, rid, field, prop)
                    used_references.update(refs)
                    editable.update((new_key, ref.pointer) for ref in refs)
                    _compare_field(source_model, old_key, new, new_key, refs, warnings, usage_records,
                        self_anchors=((source_model, source_resource), (new, new_resources[rid])) if pair else None)
                old_observed, new_observed = f'observed.row.{previous_id}.value', f'observed.row.{row_id}.value'
                if (old_observed in source_values) != (new_observed in actual_values) or source_values.get(old_observed) != actual_values.get(new_observed):
                    raise ValueError('Model source observation was not fully retained/transferred: ' + prop)
            old_display = {key: value for key, value in operation_values(old.authoritative, rid).items() if key.startswith('display.')}
            new_display = {key: value for key, value in operation_values(actual_values, rid).items() if key.startswith('display.')}
            if old_display != new_display:
                raise ValueError('Model destination display metadata changed')
            handled_old.update(operation_values(old.authoritative, rid))
            handled_new.update(operation_values(new.authoritative, rid))
        for rid in deleted.get(scope, set()):
            handled_old.update(operation_values(old.authoritative, rid))
        remaining = _verify_model_operation_remaining
        if not _same(remaining(old.authoritative, handled_old), remaining(new.authoritative, handled_new)):
            raise ValueError('Model operation changed an unrelated service, Stack or display field')
        _check_reference_metadata(old, new, editable, moved_keys,
                                  {('resource', rid) for rid in deleted.get(scope, set())}, warnings,
                                  usage_records['editable_ids'], usage_records['editable_text_ids'], detached.get(scope, frozenset()))
    if used_references != set(operation.references):
        _warn(warnings, 'unused Model reference declaration')
    return warnings






def _verify_detaches(old_models, new_models, declarations_):
    """Detach saved literal metadata only when the value and all other meanings are unchanged."""
    removed = {}
    for declaration in declarations_:
        scope = tuple(declaration.consumer.split('/')[:3])
        old, new = old_models.get(scope), new_models.get(scope)
        rid = declaration.consumer.rsplit('/', 1)[1]
        if old is None or new is None or old.authoritative.get(f'desired.resource.{rid}.resourceMode') != 'IMPORT':
            raise ValueError('dependency detach requires a surviving IMPORT consumer')
        producer_scope = tuple(declaration.producer.split('/')[:3])
        producer_id = declaration.producer.rsplit('/', 1)[1]
        producer = old_models.get(producer_scope)
        if producer is None or f'desired.resource.{producer_id}.resourceType' not in producer.authoritative:
            raise ValueError('dependency detach names an absent fixed producer')
        producer_logical = producer.authoritative[f'desired.resource.{producer_id}.logicalId']
        key = declaration.key
        if owner(key, old.authoritative) != ('resource', rid) or not key.startswith('desired.row.') or not key.endswith(('.value', '.document')):
            raise ValueError('dependency detach requires its exact consumer value/document')
        if key not in new.authoritative or not _same(_field_value(key, old.authoritative[key]), _field_value(key, new.authoritative[key])):
            raise ValueError('dependency detach changed a saved native value')
        matches = {identity for identity, spec in declarations(old.authoritative).items()
                   if spec['consumerKey'] == key and spec['producerKind'] == 'resource' and
                   spec['producerScope'] == '/'.join(producer_scope) and spec['producerLogicalId'] == producer_logical and
                   (declaration.pointer is None or spec.get('pointer') == declaration.pointer)}
        current = declarations(new.authoritative)
        if not matches or matches & current.keys():
            raise ValueError('declared dependency metadata is absent before or retained after detach')
        if any(usage.producer_scope == '/'.join(producer_scope) and
               usage.producer_id == producer_id and
               usage.consumer_key == key and (declaration.pointer is None or usage.pointer == declaration.pointer)
               for usage in _dependency_model_references.usages(new)):
            raise ValueError('declared dependency still has a direct or declared usage after detach')
        removed.setdefault(scope, set()).update(matches)
    return removed


def verify_model_refactor(
    before: Path,
    after: Path,
    detaches: Iterable[DependencyDetach],
    sources: Iterable[str],
    validation_scope: set[tuple[str, str, str]] | None,
) -> list[JsonObject]:
    source_scope = _imports_model_sources.source_scope
    _require_declared_sources(before, after, sources)
    direct = {tuple(declaration.consumer.split('/')[:3]) for declaration in detaches}
    for relative in sources:
        scope = source_scope(after, after / relative)
        direct.add((scope.environment, scope.target, scope.service))
    if validation_scope is None or not direct <= validation_scope:
        raise ValueError('Model refactor requires all direct consumers in Validation scope')
    if (before / 'project.json').read_bytes() != (after / 'project.json').read_bytes():
        raise ValueError('Model refactor cannot change project configuration')
    targets = {scope[:2] for scope in direct}
    old_models, new_models = _models(before, targets, raw=True), _models(after, targets)
    if old_models.keys() != new_models.keys():
        raise ValueError('Model refactor cannot add/remove service Models')
    removed = _verify_detaches(old_models, new_models, detaches)
    warnings = []
    for scope, old in old_models.items():
        new = new_models[scope]
        preserve_layout(old, new)
        excluded = tuple('desired.reference.' + identity + '.' for identity in removed.get(scope, ()))
        previous = {key: _field_value(key, value) for key, value in old.authoritative.items() if not key.startswith(excluded)}
        current = {key: _field_value(key, value) for key, value in new.authoritative.items()}
        if not _same(previous, current):
            raise ValueError('Model refactor changed a value, fixed identity or an undeclared reference meaning: ' + '/'.join(scope))
        changed = {path.relative_to(before).as_posix() for path in old.files
                   if old.files[path] != new.files.get(after / path.relative_to(before))}
        if changed - set(sources):
            raise ValueError('Model refactor has undeclared source changes')
        warnings.extend((*old.warnings, *new.warnings))
    return warnings


def validate_candidates(
    root: Path,
    sources: Iterable[str],
    output: Mapping[Path, str | None],
    scope: set[tuple[str, str, str]] | None,
    *,
    base: str | None = None,
    contract_file: str | None = None,
) -> list[JsonObject]:
    """Common ordinary-save/Task/integration check: validate only the final authority."""
    scope_diagnostic = _imports_model_impact.scope_diagnostic
    task_impact = _imports_model_impact.task_impact
    _ = _imports_model_sources.FileReads
    source_scope = _imports_model_sources.source_scope
    original = _dependency_model_sources._invocation_reads(root)
    reads = CandidateReads(original, output) if output else original
    required = set(task_impact(root, sources, output=output, base=base,
                              contract_file=contract_file, read_context=original).services)
    if scope is not None and not required <= scope:
        raise ValueError('Model changes require all affected services in Validation scope: ' + scope_diagnostic(required, scope))
    warnings = []
    for identity in sorted(required):
        path = root / 'model' / identity[0] / identity[1] / (identity[2] + '.properties')
        if reads.kind(path) == 'missing':
            continue  # Incoming consumers are still checked, including deleted producers.
        model = load_model(source_scope(root, path), reads)
        validate_json_settings = _imports_model_validation.validate_json_settings
        validate_json_settings(model.authoritative, path, warnings=warnings)
        display_anchor = _imports_model_identity.display_anchor
        anchors = [display_anchor(resource) for _, resource in entries(model.authoritative, 'desired.resource.')]
        if len(anchors) != len(set(anchors)):
            raise ValueError('duplicate Resource anchor: ' + str(path))
        for warning in model.warnings:
            if warning['message'] in {'producer Model is absent', 'producer Stack is absent',
                    'producer Resource is absent or ambiguous', 'producer Resource Type differs',
                    'producer Property is absent or ambiguous',
                    'producer Property does not belong to the expected Resource Type'}:
                raise ValueError('invalid candidate reference: ' + str(path) + ': ' + warning['message'])
            warnings.append(warning)
    return warnings


def load_model(
    scope: _dependency_model_sources.Scope | str | Path,
    read_context: _dependency_model_sources.ReadContext | None = None,
) -> _dependency_model_sources.ModelSnapshot:
    return _dependency_model_sources.load_model(scope, read_context)


def declarations(values: Mapping[str, str]) -> dict[str, dict[str, str]]:
    return _dependency_model_references.declarations(values)
