"""Fixed service-local Resource identities and internal, scope-checked addresses."""

import json
import posixpath as _imports_posixpath
import re

import design.catalog as _imports_design_catalog
import utils.aws_catalogs as _imports_utils_aws_catalogs
import utils.reference_contracts as _imports_reference_contracts
from utils.reference_contracts import reference_attribute

import model.importing.scope as _imports_model_importing_scope
import model.sources as _imports_model_sources
from model.core import COUNTERS as COUNTERS
from model.core import ReferenceResolutionError, entries
from model.core import counters as counters
from model.core import prefix as prefix
from model.core import resource_index as resource_index
from model.core import resource_link as resource_link
from model.core import sequence as sequence
from model.format import LINKS, link_scope


def allocate(values, resource_ids):
    """Prepare explicit additions in caller-selected order; publish the returned map once."""
    result, state = dict(values), counters(values)
    resources = dict(entries(values, 'desired.resource.'))
    selected = tuple(resource_ids)
    if len(selected) != len(set(selected)):
        raise ValueError('duplicate allocation selection')
    for number in selected:
        resource = resources[number]
        if resource.get('logicalId'):
            raise ValueError('cannot reallocate a saved logicalId: ' + number)
        kind = resource['resourceType']
        state[kind] = state.get(kind, 0) + 1
        result[f'desired.resource.{number}.logicalId'] = f'{prefix(kind)}_{state[kind]:03d}'
    result[COUNTERS] = json.dumps(state, sort_keys=True, separators=(',', ':'))
    resource_index(result)
    return result


def preserve_allocation(before, after):
    old, new = counters(before), counters(after)
    for kind, number in old.items():
        if new.get(kind, -1) < number:
            raise ValueError('lastAllocated cannot decrease or disappear: ' + kind)
    previous = dict(entries(before, 'desired.resource.'))
    current = dict(entries(after, 'desired.resource.'))
    resource_index(after)
    additions = {}
    for number, resource in current.items():
        if number in previous:
            if resource.get('logicalId') != previous[number].get('logicalId'):
                raise ValueError('saved logicalId cannot change: ' + number)
        else:
            kind = resource['resourceType']
            serial = sequence(kind, resource.get('logicalId'))
            if serial <= old.get(kind, 0):
                raise ValueError('logicalId sequence was already allocated: ' + resource['logicalId'])
            additions.setdefault(kind, []).append(serial)
    for kind in old.keys() | new.keys():
        expected = old.get(kind, 0) + len(additions.get(kind, ()))
        if new.get(kind, 0) != expected or sorted(additions.get(kind, ())) != list(range(old.get(kind, 0) + 1, expected + 1)):
            raise ValueError('allocation state does not match Resource additions: ' + kind)


def address(scope, resource, *, consumer_scope=None, label=None):
    """Build only explicitly requested new links, using the saved Resource anchor."""
    posixpath = _imports_posixpath
    destination = '/'.join((scope.environment, scope.target, scope.service + '.md'))
    filename = scope.service + '.md'
    if consumer_scope is not None:
        filename = ('' if scope == consumer_scope else posixpath.relpath(
            destination, '/'.join((consumer_scope.environment, consumer_scope.target))))
    return f"[{label or resource['logicalId']}]({filename}#{resource['anchor']})"




def parse_reference(value, scope):
    match = resource_link(value)
    if not match:
        raise ValueError('invalid Markdown Resource reference: ' + str(value))
    producer = link_scope(scope.environment, scope.target, scope.service, match[2])
    return (*producer.split('/'), match[3])


def reference_tokens(text):
    for match in LINKS.finditer(text):
        if resource_link(match[0]):
            yield match


def display_anchor(resource):
    anchor = resource.get('anchor')
    if not anchor:
        raise ReferenceResolutionError('Resource has no saved anchor')
    if not isinstance(anchor, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', anchor) is None:
        raise ValueError('invalid Resource anchor: ' + str(anchor))
    return anchor


def anchor_index(values):
    """Retain ambiguous anchors for semantic diagnostics, without guessing identities."""
    result = {}
    for number, resource in entries(values, 'desired.resource.'):
        anchor = resource.get('anchor')
        if anchor:
            result.setdefault(anchor, []).append((number, resource))
    return result


def select_anchor(index, anchor, reference):
    matches = index.get(anchor, ())
    if len(matches) != 1:
        raise ReferenceResolutionError('Resource anchor is absent or ambiguous', reference=reference)
    return matches[0]


class Resolver:
    """One anchor index per immutable service snapshot, shared across references."""
    def __init__(self, root, reads=None):
        FileReads = _imports_model_sources.FileReads
        self.root, self.reads, self.models, self.indexes = root, reads or FileReads(), {}, {}
        self.logical_indexes = {}
        self.catalog = None

    def resolve(self, value, scope):
        Scope = _imports_model_sources.Scope
        _source_snapshot = _imports_model_sources._source_snapshot
        target_for = _imports_model_sources.target_for
        environment, target, service, anchor = parse_reference(value, scope)
        producer = Scope(self.root, environment, target, service)
        if producer.path not in self.models:
            target_for(producer, self.reads)
            reference_reader = _imports_model_importing_scope.reference_reader
            if self.reads.kind(producer.path) == 'missing':
                self.reads.read(producer.path)
                raise ReferenceResolutionError('producer Model is absent', reference=value)
            with reference_reader(producer.path):
                snapshot = _source_snapshot(producer, self.reads)
            resource_index(snapshot.authoritative)
            self.models[producer.path] = snapshot
            self.indexes[producer.path] = anchor_index(snapshot.authoritative)
        if producer.path not in self.indexes:
            self.indexes[producer.path] = anchor_index(self.models[producer.path].authoritative)
        return self.models[producer.path], *select_anchor(self.indexes[producer.path], anchor, value)

    def resolve_logical(self, logical_id, scope):
        """Index exactly one environment/target snapshot once, retaining ambiguity."""
        sources = _imports_model_sources
        key = scope.environment, scope.target
        if key not in self.logical_indexes:
            index = {}
            scopes = {producer.path: producer for producer in sources.list_models(scope, self.reads)}
            scopes.update({path: snapshot.scope for path, snapshot in self.models.items() if snapshot is not None
                           and (snapshot.scope.environment, snapshot.scope.target) == key})
            for producer in scopes.values():
                if producer.service == 'cloudformation-stacks':
                    continue
                if producer.path not in self.models:
                    with _imports_model_importing_scope.reference_reader(producer.path):
                        self.models[producer.path] = sources._source_snapshot(producer, self.reads)
                snapshot = self.models[producer.path]
                if snapshot is None:
                    raise ReferenceResolutionError('producer Model is unreadable', reference=logical_id)
                for logical, (number, resource) in resource_index(snapshot.authoritative).items():
                    index.setdefault(logical, []).append((snapshot, number, resource))
            self.logical_indexes[key] = index
        matches = self.logical_indexes[key].get(logical_id, ())
        if len(matches) != 1:
            raise ReferenceResolutionError('producer logicalId is absent' if not matches else
                                           'producer logicalId is ambiguous', reference=logical_id)
        return matches[0]

    def validate_attribute(self, kind, attribute, *, field=None, context=None):
        declared = _imports_reference_contracts.contract(field, context) if field else {}
        if field and _imports_reference_contracts.configuration_contract(field, context) == {}:
            raise ReferenceResolutionError('CodePipeline ActionTypeId or Configuration reference contract unproven')
        if declared and kind not in declared:
            raise ReferenceResolutionError('JSON Resource reference type differs from receiving property')
        if not isinstance(attribute, str) or not attribute:
            raise ValueError('JSON Resource attribute must be a nonempty string')
        if self.catalog is None:
            self.catalog = _imports_design_catalog.DesignSchemaCatalog(self.root)
        returned = reference_attribute(kind, attribute)
        if (declared and reference_attribute(kind, attribute) not in {reference_attribute(kind, form) for form in declared[kind]} or
                (kind, attribute) not in _imports_reference_contracts.ARN_FORMS and
                kind + '.' + attribute not in _imports_reference_contracts.attributes_for(kind) and
                attribute not in _imports_utils_aws_catalogs.catalogs_for(self.root).selected(kind) and
                '/properties/' + returned.replace('.', '/') not in self.catalog.schema(kind).get('readOnlyProperties', ())):
            raise ReferenceResolutionError('unsupported JSON Resource attribute: ' + kind + '.' + attribute)
    def validate_reference_type(self, kind, attribute, field):
        """Typed nodes occupy one complete value; legacy links may select array elements."""
        returned = reference_attribute(kind, attribute)
        try:
            actual = self.catalog.property_schema(kind, returned).get('type')
        except KeyError:
            actual = 'string' if (kind, attribute) in _imports_reference_contracts.ARN_FORMS or kind + '.' + attribute in _imports_reference_contracts.attributes_for(kind) else None
        consumer_kind = '.'.join(field.split('.')[:2])
        try:
            expected = self.catalog.property_schema(consumer_kind, field.removeprefix(consumer_kind + '.')).get('type')
        except KeyError:
            expected = None
        actual_types = set(actual if isinstance(actual, list) else [actual])
        expected_types = set(expected if isinstance(expected, list) else [expected])
        if (expected is not None and (actual is None or not actual_types <= expected_types) or
                expected is None and actual is not None and 'string' not in actual_types):
            raise ReferenceResolutionError('Resource reference type is unproven or differs from receiving property schema')

    def operand(self, value, scope, *, attribute=None, field=None):
        """Validate a JSON reference without requiring its physical identifier."""
        snapshot, number, resource = self.resolve(value, scope)
        kind = resource['resourceType']
        declared = _imports_reference_contracts.contract(field) if field else {}
        if attribute is None:
            forms = declared.get(kind, ())
            if len(forms) != 1:
                raise ReferenceResolutionError('JSON Resource reference requires an explicit attribute', reference=value)
            attribute, = forms
        self.validate_attribute(kind, attribute, field=field)
        return snapshot, number, resource, attribute
