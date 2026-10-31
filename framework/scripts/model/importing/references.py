"""Exact local reference matching; no acquisition, source edits or publication."""

import json
import re
from functools import partial as _bind_framework_callback
from pathlib import Path

import aws_mapping as _imports_aws_mapping
import utils.aws_mappings as _imports_utils_aws_mappings
import utils.project_targets as _imports_project_targets
from utils.aws_mappings import mappings_for, owners
from utils.aws_sdk import aws_runtime
from utils.reference_contracts import (
    ARN_FORMS,
    CONFIGURATION_PROPERTIES,
    CONTEXT_PROPERTIES,
    RETURN_ATTRIBUTE_PROPERTIES,
    VALUE_IDENTITIES,
    attributes_for,
    contract,
    reference_attribute,
)

import model.core as _imports_model_core
import model.identity as _dependency_model_identity
import model.importing.scope as _imports_model_importing_scope
import model.importing.sources as _imports_model_importing_sources
import model.projection as _imports_model_projection
import model.references as _imports_model_references
import model.sources as _imports_model_sources
from model.core import (
    ReferenceDiagnosticError,
    ReferenceResolutionError,
    entries,
    literal,
)
from model.reference_nodes import is_reference, nodes
from model.reference_values import reference_value

_UNOBSERVED = object()


def known(value):
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {"UNSET", "PENDING_DEPLOY", "Pending", "TBD", "TODO", "未確定"}
        and not any(nodes(value))
        and not any(text in value for text in ("${", "{{resolve:"))
    )


def native_reference_value(raw):
    value = literal(raw)
    if value.startswith(("{", "[")):
        return json.loads(value)
    return value


def elements(raw):
    value = literal(raw)
    if value.startswith("["):
        try:
            result = json.loads(value)
        except ValueError:
            return [raw]
        if isinstance(result, list):
            return result
    return [raw]


def _recursive_verify_resource_verify_config(
    choices,
    context,
    location,
    prop,
    require_links,
    self,
    /,
    desired,
    actual,
    provider,
    pointer="",
):
    if isinstance(desired, list):
        if actual is not _UNOBSERVED and (
            not isinstance(actual, list) or len(desired) != len(actual)
        ):
            raise ValueError("IMPORT Configuration array dimensions differ")
        for i, left in enumerate(desired):
            _recursive_verify_resource_verify_config(
                choices,
                {
                    key: value[i]
                    if isinstance(value, list) and i < len(value)
                    else value
                    for key, value in context.items()
                },
                location,
                prop,
                require_links,
                self,
                left,
                _UNOBSERVED if actual is _UNOBSERVED else actual[i],
                provider[i]
                if isinstance(provider, list) and i < len(provider)
                else provider,
                pointer + "/" + str(i),
            )
    else:
        if not isinstance(desired, dict) or (
            actual is not _UNOBSERVED
            and (not isinstance(actual, dict) or desired.keys() != actual.keys())
        ):
            raise ValueError("IMPORT Configuration requires matching objects")
        for key, value in desired.items():
            target = choices.get((provider, key)) if isinstance(provider, str) else None
            contracts = {target[0]: (target[1],)} if target else {}
            self.verify(
                prop + "." + key,
                value,
                _UNOBSERVED if actual is _UNOBSERVED else actual[key],
                {
                    **context,
                    "ActionTypeId": {
                        key: context.get(
                            prop.rsplit(".", 1)[0] + ".ActionTypeId." + key
                        )
                        for key in ("Category", "Owner", "Provider", "Version")
                    },
                },
                contracts=contracts,
                require_links=require_links,
                location={
                    **location,
                    "pointer": pointer
                    + "/"
                    + key.replace("~", "~0").replace("/", "~1"),
                },
            )


class Resolver:
    def __init__(
        self,
        root,
        environment,
        target,
        *,
        definitions_root=None,
        local=None,
        read_context=None,
    ):
        definition_root = _imports_utils_aws_mappings.definition_root

        FileReads = _imports_model_sources.FileReads
        Scope = _imports_model_sources.Scope
        self.root, self.environment, self.target = Path(root), environment, target
        self.definitions_root = definitions_root or definition_root(root)
        self.local = local or {}
        self.files, self.indexes, self.targets = {}, {}, {}
        self.metrics = {"referenceModelReads": 0, "referenceResources": 0}
        self.context = None
        self.partition = None
        self.model_paths = set()
        self.warnings = []
        self.consumer_scope = Scope(self.root, environment, target, "")
        self.reads, self.models = read_context or FileReads(), {}

    def index(self, kind):
        mapping_path = _imports_aws_mapping.mapping_path

        reference_reader = _imports_model_importing_scope.reference_reader
        load_model = _imports_model_sources.load_model
        safe = _imports_model_sources.safe
        if kind in self.indexes:
            return self.indexes[kind]

        self.reads.read(
            Path(self.definitions_root) / "framework/mappings/aws/owners.json"
        )
        service = owners(self.definitions_root).get(kind)
        result = {}
        self.indexes[kind] = result
        self.targets[kind] = {}
        if service is None:
            return result
        properties = attributes_for(kind)
        returned_properties = {
            prop: kind
            + "."
            + RETURN_ATTRIBUTE_PROPERTIES.get(
                (kind, reference_attribute(kind, prop.removeprefix(kind + "."))),
                prop.removeprefix(kind + "."),
            )
            for prop in properties
        }
        self.reads.read(mapping_path(self.definitions_root, service))
        mapping = mappings_for(self.definitions_root).get(service)
        aliases = {
            prop: {prop, returned_properties[prop]}
            | {
                key
                for key, item in mapping.properties.items()
                if prop in mapping.properties
                and key.startswith(kind + ".")
                and item.field.getter
                and item.field.path
                and (item.field.getter, item.field.path)
                == (
                    mapping.properties[prop].field.getter,
                    mapping.properties[prop].field.path,
                )
                and item.transform == mapping.properties[prop].transform
            }
            for prop in properties
        }
        selected_properties = tuple(
            sorted(
                set(properties)
                | {alias for group in aliases.values() for alias in group}
            )
        )
        local_services = [
            name
            for name, model in self.local.items()
            if any(
                resource.get("resourceType") == kind
                for _, resource in entries(model.values, "desired.resource.")
            )
        ]
        if len(local_services) > 1:
            raise ReferenceResolutionError(
                "IMPORT ambiguous local producer service: " + kind
            )
        service = local_services[0] if local_services else service
        path = (
            self.root
            / "model"
            / self.environment
            / self.target
            / (service + ".properties")
        )
        if service in self.local:
            models = [self.local[service]]
        else:
            safe(self.root, path)
            if path not in self.models:
                if self.reads.kind(path) == "missing":
                    self.reads.read(path)
                    self.files[path] = None
                    self.models[path] = None
                else:
                    with reference_reader(path):
                        self.models[path] = load_model(path, self.reads)
                    self.model_paths.add(path)
                    self.metrics["referenceModelReads"] = len(self.model_paths)
            model = self.models[path]
            if model is None:
                return result
            self.files.update(
                {
                    file: None if raw is None else raw.decode("utf-8")
                    for file, raw in model.dependencies.items()
                }
            )
            self.warnings.extend(model.warnings)
            models = [model]
        for model in models:
            self.files.update(model.files)
            values = model.values
            resource_row_index = _imports_model_core.resource_row_index
            rows = resource_row_index(values)
            for rid, resource in entries(values, "desired.resource."):
                if resource.get("resourceType") != kind:
                    continue
                physical = {}
                for row_id, row in rows[rid]:
                    if (
                        row_id.rpartition("-")[0] != rid
                        or row.get("property") not in selected_properties
                    ):
                        continue
                    raw = values.get(
                        "observed.row." + row_id + ".value", row.get("value", "")
                    )
                    value = literal(raw)
                    if known(value) or value == "PENDING_DEPLOY":
                        physical.setdefault(
                            row["property"].removeprefix(kind + "."), set()
                        ).add(value)
                        for prop, group in aliases.items():
                            if row["property"] in group:
                                physical.setdefault(
                                    prop.removeprefix(kind + "."), set()
                                ).add(value)
                candidate = {
                    "service": service,
                    "id": rid,
                    "logicalId": resource["logicalId"],
                    "uri": _dependency_model_identity.address(model.scope, resource),
                    "anchor": resource.get("anchor"),
                    "scope": model.scope,
                    "kind": kind,
                }
                self.targets[kind][service, rid] = candidate
                for form, candidates in physical.items():
                    if len(candidates) != 1:
                        self.warnings.append(
                            {
                                "code": "reference.ambiguous_identifier",
                                "message": "IMPORT ambiguous producer physical identifier: "
                                + kind
                                + "."
                                + form,
                                "status": "unresolved",
                                "producer": "/".join(
                                    (self.environment, self.target, service, rid)
                                ),
                            }
                        )
                        continue
                    result.setdefault((form, next(iter(candidates))), {})[
                        service, rid
                    ] = candidate
                self.metrics["referenceResources"] += 1
        return result

    def arn_identity(self, kind, form, value):
        descriptor = ARN_FORMS.get((kind, form))
        if descriptor is None or not (match := re.fullmatch(descriptor[1], value)):
            return None
        parts = match.groupdict()
        if self.context is None:
            load_target = _imports_project_targets.load_target_directory
            self.context = load_target(self.root, self.environment, self.target)
            self.files[self.root / "project.json"] = (
                (self.root / "project.json").read_bytes().decode("utf-8")
            )
            get_session = aws_runtime().sdk_session
            self.partition = get_session().get_partition_for_region(
                self.context["awsRegion"]
            )
        if parts["partition"] != self.partition:
            return None
        if "account" in parts or "region" in parts:
            if (
                "account" in parts
                and parts["account"]
                != self.context.get(
                    "awsExecutionAccountId", self.context["awsAccountId"]
                )
                or "region" in parts
                and parts["region"] != self.context["awsRegion"]
            ):
                return None
        return (
            {attribute: parts[group] for attribute, group in descriptor[0].items()}
            if isinstance(descriptor[0], dict)
            else {descriptor[0]: parts["id"]}
        )

    def match(self, prop, value, context=None, *, contracts=None):
        contracts = contract(prop, context) if contracts is None else contracts
        matches = {}
        if not known(value):
            return None
        for kind, forms in contracts.items():
            index = self.index(kind)
            if not index:
                continue
            converted = [
                item
                for form in forms
                if (item := self.arn_identity(kind, form, value)) is not None
            ]
            converted += [
                {form: match["id"]}
                for form in forms
                if (pattern := VALUE_IDENTITIES.get((kind, form)))
                and (match := re.fullmatch(pattern, value))
            ]
            for form in forms:
                matches.update(index.get((form, value), {}))
            for components in converted:
                groups = [
                    index.get((form, raw), {}) for form, raw in components.items()
                ]
                for identity in set.intersection(*(set(group) for group in groups)):
                    matches[identity] = groups[0][identity]
        if len(matches) > 1:
            raise ReferenceResolutionError(
                "IMPORT ambiguous physical reference: " + prop + ": " + value
            )
        return next(iter(matches.values()), None)

    def verify(
        self,
        prop,
        raw,
        physical,
        context=None,
        *,
        contracts=None,
        require_links=True,
        location=None,
    ):
        position = (
            (location or {}).get("consumerKey"),
            (location or {}).get("pointer"),
        )
        if isinstance(raw, str) and (position, raw) in getattr(
            self, "literal_references", ()
        ):
            contracts = {}  # External metadata owns tracking; still compare the acquired literal.
        try:
            return self._verify(
                prop,
                raw,
                physical,
                context,
                contracts=contracts,
                require_links=require_links,
            )
        except ReferenceDiagnosticError as error:
            self.warnings.append(
                {
                    **error.diagnostic,
                    "property": prop,
                    "reference": raw,
                    **(
                        {"acquiredValue": physical}
                        if physical is not _UNOBSERVED
                        else {}
                    ),
                    **(location or {}),
                }
            )

    def _verify(
        self, prop, raw, physical, context=None, *, contracts=None, require_links=True
    ):
        reference = next(
            iter(nodes(literal(raw) if isinstance(raw, str) else raw)), None
        )
        if reference is not None:
            resolver = getattr(
                self, "current_resolver", None
            ) or _dependency_model_identity.Resolver(self.root, self.reads)
            resolver.models.update(
                {
                    model.scope.path: model
                    for model in self.local.values()
                    if model.scope.path not in resolver.overrides
                }
            )
            resolver.models.update(resolver.overrides)
            result = reference_value(
                resolver, self.consumer_scope, reference, field=prop, context=context
            )
            if physical is _UNOBSERVED:
                return
            if result.status == "resolved":
                if str(result.value) != str(physical):
                    raise ReferenceResolutionError(
                        "IMPORT reference differs from acquired physical reference: "
                        + prop
                    )
                return
            if physical == "PENDING_DEPLOY" and not require_links:
                return
            if result.diagnostic:
                raise ReferenceResolutionError(**result.diagnostic)
            raise ReferenceResolutionError("IMPORT reference is unconfirmed")
        if not require_links:
            return
        if physical is _UNOBSERVED:
            return
        if reference is None:
            typed_equal = _imports_model_importing_sources.typed_equal
            if not typed_equal(literal(raw) if isinstance(raw, str) else raw, physical):
                raise ValueError(
                    "IMPORT literal differs from acquired physical value: " + prop
                )
        expected = self.match(prop, physical, context, contracts=contracts)
        if expected is not None:
            raise ReferenceResolutionError(
                "IMPORT matching Model requires a Resource reference: " + prop
            )

    def verify_tree(
        self, prop, desired, actual, context, *, require_links=True, location=None
    ):
        if is_reference(desired):
            self.verify(
                prop,
                desired,
                actual,
                context,
                require_links=require_links,
                location=location,
            )
        elif isinstance(desired, (list, dict)):
            if actual is not _UNOBSERVED and (
                type(desired) is not type(actual)
                or (
                    desired.keys() != actual.keys()
                    if isinstance(desired, dict)
                    else len(desired) != len(actual)
                )
            ):
                raise ValueError(
                    "IMPORT reference/observation structure differs: " + prop
                )
            for key in desired if isinstance(desired, dict) else range(len(desired)):
                child_context = {
                    prop: value[key]
                    if isinstance(value, list)
                    and isinstance(key, int)
                    and key < len(value)
                    else value
                    for prop, value in context.items()
                }
                self.verify_tree(
                    prop + "." + key
                    if isinstance(desired, dict)
                    else prop
                    if prop.endswith("[]")
                    else prop + "[]",
                    desired[key],
                    _UNOBSERVED if actual is _UNOBSERVED else actual[key],
                    child_context,
                    require_links=require_links,
                    location={
                        **(location or {}),
                        "pointer": (location or {}).get("pointer", "")
                        + "/"
                        + str(key).replace("~", "~0").replace("/", "~1"),
                    },
                )
        else:
            self.verify(
                prop,
                desired,
                actual,
                context,
                require_links=require_links,
                location=location,
            )

    def verify_resource(
        self,
        values,
        rid,
        *,
        scope=None,
        require_links=True,
        identity_properties=None,
        properties=None,
        observed_only=False,
    ):
        resource_row_index = _imports_model_core.resource_row_index
        catalog_outputs = _imports_model_projection.catalog_outputs
        declarations = _imports_model_references.declarations
        Scope = _imports_model_sources.Scope
        services = [
            fields["serviceId"]
            for _, fields in entries(values, "desired.service.")
            if "serviceId" in fields
        ]
        self.consumer_scope = scope or Scope(
            self.root,
            self.environment,
            self.target,
            services[0] if len(services) == 1 else "",
        )
        self.current_resolver = _imports_model_projection.reference_resolver(
            values, self.consumer_scope, self.root
        )
        self.literal_references = {
            ((spec["consumerKey"], spec["pointer"]), spec["text"])
            for spec in declarations(values).values()
            if spec["consumerKey"].startswith("desired.row." + rid + "-")
            and "pointer" in spec
            and spec["format"] in {"identifier", "name"}
        }
        if identity_properties is None:
            identity_properties = catalog_outputs(
                self.definitions_root, values[f"desired.resource.{rid}.resourceType"]
            )
        rows = resource_row_index(values).get(rid, [])
        context = {}
        for row_id, row in rows:
            prop = row["property"]
            raw = row.get("value", "")
            observed = values.get("observed.row." + row_id + ".value")
            location = {
                "resource": rid,
                "consumerKey": "desired.row."
                + row_id
                + (".document" if "document" in row else ".value"),
            }
            location["key"] = location["consumerKey"]
            if prop.endswith((".Type", ".Provider", ".Category", ".Owner", ".Version")):
                try:
                    context[prop] = json.loads(literal(raw))
                except ValueError:
                    context[prop] = literal(raw)
            if properties is not None and prop not in properties:
                continue
            refs = tuple(nodes(literal(raw)))
            if (
                prop in identity_properties
                and len(refs) == 1
                and refs[0].pointer == ""
                and refs[0].logical_id
                == values.get(f"desired.resource.{rid}.logicalId")
                and reference_attribute(
                    values[f"desired.resource.{rid}.resourceType"], refs[0].attribute
                )
                == reference_attribute(
                    values[f"desired.resource.{rid}.resourceType"],
                    prop.removeprefix(
                        values[f"desired.resource.{rid}.resourceType"] + "."
                    ),
                )
            ):
                self.current_resolver.validate_attribute(
                    values[f"desired.resource.{rid}.resourceType"], refs[0].attribute
                )
                continue
            if prop in CONFIGURATION_PROPERTIES:
                selector, choices = CONFIGURATION_PROPERTIES[prop]
                desired = json.loads(row.get("document", literal(raw)))
                actual = (
                    native_reference_value(observed)
                    if observed is not None
                    else _UNOBSERVED
                    if observed_only
                    else desired
                )
                verify_config = _bind_framework_callback(
                    _recursive_verify_resource_verify_config,
                    choices,
                    context,
                    location,
                    prop,
                    require_links,
                    self,
                )
                verify_config(desired, actual, context.get(selector))
                continue
            has_reference = _imports_model_importing_sources.has_reference
            if literal(raw).startswith(("[", "{")) and (
                has_reference(row.get("document", raw))
                or contract(prop, context)
                or prop in CONTEXT_PROPERTIES
            ):
                desired = json.loads(row.get("document", literal(raw)))
                actual = (
                    native_reference_value(observed)
                    if observed is not None
                    else _UNOBSERVED
                    if observed_only
                    else desired
                )
                self.verify_tree(
                    prop,
                    desired,
                    actual,
                    context,
                    require_links=require_links,
                    location=location,
                )
                continue
            # Scalar values retain their native comparison and identity guards.
            links = elements(raw)
            physical = (
                [_UNOBSERVED] * len(links)
                if observed_only and observed is None
                else elements(observed if observed is not None else raw)
            )
            if len(links) != len(physical):
                raise ValueError(
                    "IMPORT reference/observation element count differs: " + prop
                )
            if not contract(prop, context) and not has_reference(raw):
                continue
            for value, actual in zip(links, physical, strict=True):
                self.verify(
                    prop,
                    value,
                    _UNOBSERVED if actual is _UNOBSERVED else literal(actual),
                    context,
                    require_links=require_links,
                    location=location,
                )
