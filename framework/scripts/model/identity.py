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
from model.core import (
    FrameworkUnsupportedError,
    ModelNeedsFixError,
    ReferenceResolutionError,
    entries,
)
from model.core import counters as counters
from model.core import prefix as prefix
from model.core import resource_index as resource_index
from model.core import resource_link as resource_link
from model.core import sequence as sequence
from model.format import LINKS, link_scope


def allocate(values, resource_ids):
    """Prepare explicit additions in caller-selected order; publish the returned map once."""
    result, state = dict(values), counters(values)
    resources = dict(entries(values, "desired.resource."))
    selected = tuple(resource_ids)
    if len(selected) != len(set(selected)):
        raise ValueError("duplicate allocation selection")
    for number in selected:
        resource = resources[number]
        if resource.get("logicalId"):
            raise ValueError("cannot reallocate a saved logicalId: " + number)
        kind = resource["resourceType"]
        state[kind] = state.get(kind, 0) + 1
        result[f"desired.resource.{number}.logicalId"] = (
            f"{prefix(kind)}_{state[kind]:03d}"
        )
    result[COUNTERS] = json.dumps(state, sort_keys=True, separators=(",", ":"))
    resource_index(result)
    return result


def preserve_allocation(before, after):
    old, new = counters(before), counters(after)
    for kind, number in old.items():
        if new.get(kind, -1) < number:
            raise ValueError("lastAllocated cannot decrease or disappear: " + kind)
    previous = dict(entries(before, "desired.resource."))
    current = dict(entries(after, "desired.resource."))
    resource_index(after)
    additions = {}
    for number, resource in current.items():
        if number in previous:
            if resource.get("logicalId") != previous[number].get("logicalId"):
                raise ValueError("saved logicalId cannot change: " + number)
        else:
            kind = resource["resourceType"]
            serial = sequence(kind, resource.get("logicalId"))
            if serial <= old.get(kind, 0):
                raise ValueError(
                    "logicalId sequence was already allocated: " + resource["logicalId"]
                )
            additions.setdefault(kind, []).append(serial)
    for kind in old.keys() | new.keys():
        expected = old.get(kind, 0) + len(additions.get(kind, ()))
        if new.get(kind, 0) != expected or sorted(additions.get(kind, ())) != list(
            range(old.get(kind, 0) + 1, expected + 1)
        ):
            raise ValueError(
                "allocation state does not match Resource additions: " + kind
            )


def address(scope, resource, *, consumer_scope=None, label=None):
    """Build only explicitly requested new links, using the saved Resource anchor."""
    posixpath = _imports_posixpath
    destination = "/".join((scope.environment, scope.target, scope.service + ".md"))
    filename = scope.service + ".md"
    if consumer_scope is not None:
        filename = (
            ""
            if scope == consumer_scope
            else posixpath.relpath(
                destination,
                "/".join((consumer_scope.environment, consumer_scope.target)),
            )
        )
    return f"[{label or resource['logicalId']}]({filename}#{resource['anchor']})"


def parse_reference(value, scope):
    match = resource_link(value)
    if not match:
        raise ValueError("invalid Markdown Resource reference: " + str(value))
    producer = link_scope(scope.environment, scope.target, scope.service, match[2])
    return (*producer.split("/"), match[3])


def reference_tokens(text):
    for match in LINKS.finditer(text):
        if resource_link(match[0]):
            yield match


def display_anchor(resource):
    anchor = resource.get("anchor")
    if not anchor:
        raise ReferenceResolutionError("Resource has no saved anchor")
    if (
        not isinstance(anchor, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", anchor) is None
    ):
        raise ValueError("invalid Resource anchor: " + str(anchor))
    return anchor


def anchor_index(values):
    """Retain ambiguous anchors for semantic diagnostics, without guessing identities."""
    result = {}
    for number, resource in entries(values, "desired.resource."):
        anchor = resource.get("anchor")
        if anchor:
            result.setdefault(anchor, []).append((number, resource))
    return result


def select_anchor(index, anchor, reference):
    matches = index.get(anchor, ())
    if len(matches) != 1:
        raise ReferenceResolutionError(
            "Resource anchor is absent or ambiguous", reference=reference
        )
    return matches[0]


class Resolver:
    """One anchor index per immutable service snapshot, shared across references."""

    def __init__(self, root, reads=None):
        FileReads = _imports_model_sources.FileReads
        self.root, self.reads, self.models, self.indexes = (
            root,
            reads or FileReads(),
            {},
            {},
        )
        self.overrides = {}
        self.reference_revision = getattr(self.reads, "reference_revision", None)
        self.logical_indexes = {}
        self.catalog = None

    def refresh(self):
        revision = getattr(self.reads, "reference_revision", None)
        mutable = any(
            not isinstance(
                snapshot.authoritative, _imports_model_sources.SnapshotValues
            )
            for snapshot in self.overrides.values()
        )
        if revision is not self.reference_revision or mutable:
            self.models = dict(self.overrides)
            self.indexes.clear()
            self.logical_indexes.clear()
            self.reference_revision = revision

    def target(self, scope):
        target, _ = _imports_model_sources.target_for(scope, self.reads)
        return target

    def resolve(self, value, scope):
        Scope = _imports_model_sources.Scope
        _source_snapshot = _imports_model_sources._source_snapshot
        target_for = _imports_model_sources.target_for
        environment, target, service, anchor = parse_reference(value, scope)
        producer = Scope(self.root, environment, target, service)
        if producer.path not in self.models:
            target_for(producer, self.reads)
            reference_reader = _imports_model_importing_scope.reference_reader
            if self.reads.kind(producer.path) == "missing":
                self.reads.read(producer.path)
                raise ReferenceResolutionError(
                    "producer Model is absent", reference=value
                )
            with reference_reader(producer.path):
                snapshot = _source_snapshot(producer, self.reads)
            resource_index(snapshot.authoritative)
            self.models[producer.path] = snapshot
            self.indexes[producer.path] = anchor_index(snapshot.authoritative)
        if producer.path not in self.indexes:
            self.indexes[producer.path] = anchor_index(
                self.models[producer.path].authoritative
            )
        return self.models[producer.path], *select_anchor(
            self.indexes[producer.path], anchor, value
        )

    def resolve_logical(self, logical_id, scope):
        """Index exactly one environment/target snapshot once, retaining ambiguity."""
        sources = _imports_model_sources
        key = (
            (scope.environment, scope.target, logical_id)
            if sources.session_reads(self.root) is not None
            else (scope.environment, scope.target)
        )
        if key not in self.logical_indexes:
            index = {}
            scopes = {
                producer.path: producer
                for producer in (
                    sources.session_reads(self.root).logical_models(scope, logical_id)
                    if sources.session_reads(self.root) is not None
                    else sources.list_models(scope, self.reads)
                )
            }
            scopes.update(
                {
                    path: snapshot.scope
                    for path, snapshot in self.models.items()
                    if snapshot is not None
                    and (snapshot.scope.environment, snapshot.scope.target)
                    == (scope.environment, scope.target)
                }
            )
            for producer in scopes.values():
                if producer.service == "cloudformation-stacks":
                    continue
                try:
                    if producer.path not in self.models:
                        with _imports_model_importing_scope.reference_reader(
                            producer.path
                        ):
                            self.models[producer.path] = sources._source_snapshot(
                                producer, self.reads
                            )
                    snapshot = self.models[producer.path]
                    if snapshot is None:
                        raise FrameworkUnsupportedError(
                            "producer Model is unreadable", targetLogicalId=logical_id
                        )
                    resources = resource_index(snapshot.authoritative)
                except ModelNeedsFixError as error:
                    error.diagnostic.update(
                        producerModel=str(producer.path),
                        fixModels=[str(producer.path)],
                    )
                    raise
                for logical, (number, resource) in resources.items():
                    index.setdefault(logical, []).append((snapshot, number, resource))
            self.logical_indexes[key] = index
        matches = self.logical_indexes[key].get(logical_id, ())
        if len(matches) != 1:
            raise ModelNeedsFixError(
                "producer logicalId is absent"
                if not matches
                else "producer logicalId is ambiguous",
                code="MODEL_REF_TARGET_MISSING"
                if not matches
                else "MODEL_REF_TARGET_AMBIGUOUS",
                targetLogicalId=logical_id,
                fixModels=sorted(
                    {str(snapshot.scope.path) for snapshot, _, _ in matches}
                )
                if matches
                else [str(scope.path)],
            )
        return matches[0]

    def validate_attribute(
        self, kind, attribute, *, field=None, context=None, operand=False
    ):
        declared = (
            _imports_reference_contracts.contract(field, context) if field else {}
        )
        if (
            field
            and not declared
            and _imports_reference_contracts.requires_context(field, context)
        ):
            reason = (
                "CodePipeline ActionTypeId or Configuration"
                if _imports_reference_contracts.configuration_contract(field, context)
                is not None
                else "reference context or receiving property"
            )
            raise FrameworkUnsupportedError(reason + " contract unproven: " + field)
        if declared and kind not in declared:
            raise ModelNeedsFixError(
                "JSON Resource reference type differs from receiving property",
                code="MODEL_REF_TYPE_MISMATCH",
            )
        if not isinstance(attribute, str) or not attribute:
            raise ModelNeedsFixError(
                "JSON Resource attribute must be a nonempty string",
                code="MODEL_REF_INVALID_ATTRIBUTE",
            )
        if self.catalog is None:
            self.catalog = _imports_design_catalog.DesignSchemaCatalog(self.root)
        try:
            self.catalog.schema(kind)
        except KeyError as error:
            raise FrameworkUnsupportedError(
                "Framework unsupported producer ResourceType: " + kind
            ) from error
        returned = reference_attribute(kind, attribute)
        if (
            declared
            and not operand
            and reference_attribute(kind, attribute)
            not in {reference_attribute(kind, form) for form in declared[kind]}
            or not (
                kind in _imports_reference_contracts.ARN_SHAPES
                and returned == reference_attribute(kind, "Arn")
            )
            and returned != _imports_reference_contracts.REF_ATTRIBUTES.get(kind)
            and not _imports_reference_contracts.getatt_attribute(
                kind, returned, self.catalog.schema(kind)
            )
            and (kind, attribute) not in _imports_reference_contracts.ARN_FORMS
            and kind + "." + attribute
            not in _imports_reference_contracts.attributes_for(kind)
            and attribute
            not in _imports_utils_aws_catalogs.catalogs_for(self.root).selected(kind)
        ):
            raise ModelNeedsFixError(
                "unsupported JSON Resource attribute: " + kind + "." + attribute,
                code="MODEL_REF_INVALID_ATTRIBUTE",
            )

    def validate_reference_type(self, kind, attribute, field):
        """Typed nodes occupy one complete value; legacy links may select array elements."""
        returned = reference_attribute(kind, attribute)
        try:
            actual = self.catalog.property_schema(kind, returned).get("type")
        except KeyError:
            actual = _imports_reference_contracts.RETURN_TYPES.get((kind, returned))
            if actual is None and (
                returned == _imports_reference_contracts.REF_ATTRIBUTES.get(kind)
                or (kind, attribute) in _imports_reference_contracts.ARN_FORMS
                or kind + "." + attribute
                in _imports_reference_contracts.attributes_for(kind)
            ):
                actual = "string"
        consumer_kind = ".".join(field.split(".")[:2])
        try:
            expected = self.catalog.property_schema(
                consumer_kind, field.removeprefix(consumer_kind + ".")
            ).get("type")
        except KeyError:
            expected = None
        actual_types = set(actual if isinstance(actual, list) else [actual])
        expected_types = set(expected if isinstance(expected, list) else [expected])
        if (
            expected is not None
            and (actual is None or not actual_types <= expected_types)
            or expected is None
            and actual is not None
            and "string" not in actual_types
        ):
            raise (
                FrameworkUnsupportedError
                if actual is None or expected is None
                else ModelNeedsFixError
            )(
                "Resource reference type is unproven or differs from receiving property schema",
                code="FRAMEWORK_UNSUPPORTED"
                if actual is None or expected is None
                else "MODEL_REF_TYPE_MISMATCH",
            )

    def operand(self, value, scope, *, attribute=None, field=None):
        """Validate a JSON reference without requiring its physical identifier."""
        snapshot, number, resource = self.resolve(value, scope)
        kind = resource["resourceType"]
        declared = _imports_reference_contracts.contract(field) if field else {}
        if attribute is None:
            forms = declared.get(kind, ())
            if len(forms) != 1:
                raise ReferenceResolutionError(
                    "JSON Resource reference requires an explicit attribute",
                    reference=value,
                )
            (attribute,) = forms
        self.validate_attribute(kind, attribute, field=field)
        return snapshot, number, resource, attribute
