"""One acquisition inventory per verified Context; static definitions remain shared."""

import json
from copy import deepcopy
from functools import partial as _bind_framework_callback
from threading import RLock

import aws_mapping_compare as mapping_compare
from aws_mapping import readonly
from aws_mapping_catalog import project
from contracts.mapping import MAPPING_RESOURCE_TYPE_KEY
from contracts.model import RESOURCE_LOGICAL_ID_KEY
from contracts.target import AWS_ACCOUNT_ID_KEY, AWS_EXECUTION_ACCOUNT_ID_KEY
from services.registry import REGISTRY
from utils.aws_mappings import owners
from utils.aws_schemas import schemas_for
from utils.json_format import policy_json
from utils.lazy_definitions import load_once
from utils.property_path import definition_path
from utils.script_loader import module

import model.importing.sdk_inventory as sdk_inventory
import model.projection as _imports_model_projection
from model.importing import limitations
from model.importing.discovery import (
    filter_parents,
    resolve,
    type_name,
)
from model.reference_nodes import nodes


def comparator():
    return module("model/adapters/aws.py", "model.adapters.aws")


def properties_json(value):
    if not isinstance(value, str):
        raise ValueError("Cloud Control Properties must be a JSON string")
    result = policy_json(value)
    if not isinstance(result, dict):
        raise ValueError("Cloud Control Properties must be an object")
    return result


def pointer_value(properties, pointer):
    if not pointer.startswith("/properties/"):
        raise ValueError("unsupported primary identifier pointer")
    result = properties
    for part in pointer[len("/properties/") :].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(result, dict) or part not in result:
            return None
        result = result[part]
    return result


def cloud_identity_matches(
    list_identifier, request_identifier, detail_identifier, properties, pointers
):
    """Confirm List, request, Get and all primary identifier components agree."""
    if not isinstance(pointers, (list, tuple)) or not pointers:
        return False
    try:
        values = [pointer_value(properties, pointer) for pointer in pointers]
    except (TypeError, ValueError, AttributeError):
        return False
    if any(not isinstance(value, str) or not value or "|" in value for value in values):
        return False
    return (
        isinstance(list_identifier, str)
        and bool(list_identifier)
        and list_identifier
        == request_identifier
        == detail_identifier
        == "|".join(values)
    )


def cloudcontrol_value(ctx, resource, getter):
    """Read a Mapping provider getter only with a complete, verified selector."""
    ctx.require_resource_scope(resource)
    if not ctx.import_mode and resource.kind not in getattr(
        resource.module, "CLOUDCONTROL_RESOURCE_TYPES", ()
    ):
        raise ValueError("Cloud Control resource is outside the read-only allowlist")
    if (
        getter.get("service") != "cloudcontrol"
        or getter.get("operation") != "get_resource"
        or getter.get(MAPPING_RESOURCE_TYPE_KEY) != resource.kind
    ):
        raise ValueError("invalid Cloud Control getter")
    inventory = inventory_for(ctx)
    schema = inventory.schema(resource.kind)
    if tuple(getter.get("identifier", ())) != tuple(
        schema.get("primaryIdentifier", ())
    ):
        raise ValueError("Cloud Control identifier differs from Schema")
    if "read" not in schema.get("handlers", {}):
        raise comparator().Unresolved("Cloud Control read unsupported")
    components = []
    for pointer in getter["identifier"]:
        prop = pointer.removeprefix("/properties/").replace("/", ".")
        current = resource.current(prop)
        if current is None:
            rows = resource.rows_for(prop)
            if any(
                node.logical_id == resource.spec[RESOURCE_LOGICAL_ID_KEY]
                for _, row in rows
                for node in nodes(row["value"].strip("`"))
            ):
                raise comparator().Unresolved(
                    "provider self identity has no confirmed observation"
                )
            current = resource.value(prop)
        components.append(current)
    if any(
        not isinstance(value, str) or not value or "|" in value for value in components
    ):
        raise comparator().Unresolved(
            "Cloud Control identifier requires confirmed components"
        )
    ctx.allowed.add(("cloudcontrol", "get_resource"))
    response = ctx.call(
        "cloudcontrol",
        "get_resource",
        TypeName=type_name(resource.kind),
        Identifier="|".join(components),
    )
    return properties_json(response["ResourceDescription"]["Properties"])


def _callback_ImportInventory___new___create(cls, ctx, /):
    result = object.__new__(cls)
    result.ctx = ctx
    result._lock, result._cache = RLock(), {}
    result._statuses = {}
    return result


def _callback_ImportInventory_once_run(key, load, self, /):
    with self._lock:
        self.ctx.metrics["inventory_" + key[0] + "_runs"] += 1
    return load()


def _callback_ImportInventory_resource_types_resolve(self, service, /):
    mapping, _ = self.mapping(service)
    index = owners(self.ctx.root)
    kinds = tuple(sorted(kind for kind, owner in index.items() if owner == service))
    if set(kinds) != mapping.resource_types:
        raise ValueError("IMPORT Mapping ownership mismatch")
    return kinds


def _callback_ImportInventory_schema_load(kind, self, /):
    try:
        return readonly(schemas_for(self.ctx.root).cloudformation(type_name(kind)))
    except KeyError:
        raise comparator().AcquisitionError(
            "cloudcontrol", "SchemaUnsupported", "unsupported"
        ) from None


def _callback_ImportInventory_identity_resolve(kind, record, self, /):
    catalog_outputs = _imports_model_projection.catalog_outputs
    mapping, mapped = self.mapping(owners(self.ctx.root)[kind])
    if "identityComponents" in record:
        return {
            key: record[key]
            for key in (
                "identityProperty",
                "identityProperties",
                "identityComponents",
                "identityStatus",
            )
        }
    if "cloudProperties" in record:
        pointers = self.schema(kind).get("primaryIdentifier", ())
        values = [
            pointer_value(record["cloudProperties"], pointer) for pointer in pointers
        ]
        props = [
            kind + "." + pointer.removeprefix("/properties/").replace("/", ".")
            for pointer in pointers
        ]
        known = bool(values) and all(
            value is not None and value != "" for value in values
        )
        return {
            "identityProperty": props[0] if len(props) == 1 else None,
            "identityProperties": props,
            "identityComponents": [
                {"property": prop, "value": value}
                for prop, value in zip(props, values, strict=False)
            ],
            "identityStatus": "known" if known else "unknown",
        }
    descriptor = mapping.identities[kind]
    props = [
        p
        for p, item in mapped.items()
        if p.startswith(kind + ".")
        and item.field.path == descriptor.id_path
        and item.field.getter == descriptor.getter
    ]
    outputs = catalog_outputs(self.ctx.root, kind)
    props.sort(key=lambda prop: prop not in outputs)
    return {
        "identityProperty": props[0] if props else None,
        "identityProperties": props,
    }


def _callback_ImportInventory_normalize_run(normalize, record, self, service, /):
    result = normalize(self.ctx, service, [record])[0]
    required = self.ctx.catalog.required_properties(record["kind"])
    allows_missing = REGISTRY.import_profile(record["kind"]).allows_missing
    missing_required = any(
        value["status"] == "missing"
        and prop.removeprefix(record["kind"] + ".").split(".")[0] in required
        and not (allows_missing and allows_missing(prop, value, result["properties"]))
        for prop, value in result["properties"].items()
    )
    if (
        missing_required
        or result.get("identityStatus") == "unknown"
        or any(
            value["status"] == "unavailable" for value in result["properties"].values()
        )
    ):
        denied = any(
            capture.get("errorCode")
            in {
                "AccessDenied",
                "AccessDeniedException",
                "UnauthorizedOperation",
                "UnauthorizedException",
            }
            for capture in result["properties"].values()
        )
        self.status(
            record["kind"],
            "permission_denied" if denied else "failed",
            "Property or identity acquisition incomplete",
        )
    else:
        gaps = [
            {"record": result["record"], "property": prop, "status": capture["status"]}
            for prop, capture in result["properties"].items()
            if capture["status"] in {"unobservable", "withheld", "not_returned"}
        ]
        if gaps:
            self.status(record["kind"], "limited", limitations=gaps)
    return result


def _callback_ImportInventory_inventory_collect(filters, kind, self, service, /):
    mapping, mapped = self.mapping(service)
    plan = resolve(mapping, mapped, kind)
    if plan.mode == "not_modelled":
        self.status(kind, "not_modelled")
        return []
    try:
        if plan.mode == "scoped_sdk":
            scoped = REGISTRY.import_profile(kind).scoped
            if scoped.filter_error and filters is not None:
                raise ValueError(scoped.filter_error)
            parents = None
            if plan.parents:
                parent = plan.parents[0]
                parents = self.inventory(service, parent)
                if self.statuses[parent]["status"] not in {"complete", "empty"}:
                    raise comparator().AcquisitionError(
                        kind, "ParentInventoryIncomplete"
                    )
            records = sdk_inventory.collect(self.ctx, kind, parents=parents)
        elif plan.mode == "adapter":
            records = adapter_inventory(self.ctx, service, (kind,))
        elif plan.mode == "parent_derived":
            # Associations belong to the existing subnet expansion, not independent candidates.
            records = []
        else:
            records = self.cloud_inventory(service, kind, filters)
        self.status(kind, "complete" if records else "empty")
        return records
    except (
        comparator().AcquisitionError,
        ValueError,
        KeyError,
        TypeError,
        comparator().Unresolved,
    ) as error:
        self.failure(kind, error)
    return []


class ImportInventory:
    def __new__(cls, ctx):
        if not ctx.verified:
            raise ValueError("IMPORT Inventory requires a verified AWS Context")
        create = _bind_framework_callback(
            _callback_ImportInventory___new___create, cls, ctx
        )
        return ctx.once(("import_inventory",), create)

    def once(self, key, load):
        with self._lock:
            self.ctx.metrics[
                "inventory_cache_hits"
                if key in self._cache
                else "inventory_cache_misses"
            ] += 1
        run = _bind_framework_callback(
            _callback_ImportInventory_once_run, key, load, self
        )
        return load_once(self._lock, self._cache, key, run)

    def mapping(self, service):
        return self.once(
            ("mapping", service), lambda: import_comparison(self.ctx.root, service)
        )

    def resource_types(self, service):
        resolve = _bind_framework_callback(
            _callback_ImportInventory_resource_types_resolve, self, service
        )
        return self.once(("resource_types", service), resolve)

    def schema(self, kind):
        load = _bind_framework_callback(
            _callback_ImportInventory_schema_load, kind, self
        )
        return self.once(("schema", kind), load)

    def property_schema(self, prop):
        kind = ".".join(prop.split(".")[:2])
        path = prop.removeprefix(kind + ".")
        if REGISTRY.import_profile(kind).name_tag and path == "Name":
            path = "Tags[].Value"
        return deepcopy(
            self.once(
                ("property_schema", kind, prop),
                lambda: self.ctx.catalog.property_schema(kind, definition_path(path)),
            )
        )

    def identity(self, kind, record):
        resolve = _bind_framework_callback(
            _callback_ImportInventory_identity_resolve, kind, record, self
        )
        return deepcopy(self.once(("identity", kind, record["identity"]), resolve))

    def normalize(self, service, record, normalize):
        run = _bind_framework_callback(
            _callback_ImportInventory_normalize_run, normalize, record, self, service
        )
        return deepcopy(
            self.once(("normalize", service, record["kind"], record["identity"]), run)
        )

    @property
    def statuses(self):
        with self._lock:
            return deepcopy(self._statuses)

    def discover(self, service, resource_types=None):
        available = self.resource_types(service)
        selected = tuple(resource_types) if resource_types else available
        if len(set(selected)) != len(selected) or any(
            kind not in available for kind in selected
        ):
            raise ValueError(
                "IMPORT Resource Types must have the selected Mapping owner"
            )
        records = []
        dependencies = dict.fromkeys(
            dependency
            for kind in selected
            for dependency in REGISTRY.import_profile(kind).dependencies
            if dependency not in selected and dependency in available
        )
        for kind in (*selected, *dependencies):
            records.extend(self.inventory(service, kind))
        for record in records:
            derived = REGISTRY.import_profile(record["kind"]).derived
            if derived:
                derived.attach(record, records)
        return [
            record
            for record in records
            if record["kind"] in selected
            and not REGISTRY.import_profile(record["kind"]).derived
        ]

    def status(self, kind, status, reason=None, *, limitations=None, diagnostic=None):
        with self._lock:
            current = self._statuses.get(kind, {}).get("status")
            if current in {
                "failed",
                "permission_denied",
                "unsupported",
                "requires_filter",
            }:
                return
            existing = self._statuses.get(kind, {}).get("limitations", [])
            self._statuses[kind] = {
                "status": status,
                **({"reason": reason} if reason else {}),
                **(diagnostic or {}),
                **(
                    {
                        "enumerationComplete": True,
                        "propertiesComplete": False,
                        "limitations": [
                            *existing,
                            *(item for item in limitations if item not in existing),
                        ],
                    }
                    if status == "limited"
                    else {}
                ),
            }

    def failure(self, kind, error):
        if isinstance(error, comparator().AcquisitionError):
            status = (
                "permission_denied"
                if error.code
                in {
                    "AccessDenied",
                    "AccessDeniedException",
                    "UnauthorizedOperation",
                    "UnauthorizedException",
                }
                else "unsupported"
                if error.code
                in {"UnsupportedActionException", "UnsupportedOperationException"}
                else error.status
                if error.status in {"requires_filter", "unsupported"}
                else "failed"
            )
            self.status(
                kind,
                status,
                error.code,
                diagnostic={
                    "failureCategory": error.failure_category,
                    "classificationSource": error.classification_source,
                },
            )
        else:
            self.status(kind, "failed", type(error).__name__)

    def inventory(self, service, kind, filters=None):
        collect = _bind_framework_callback(
            _callback_ImportInventory_inventory_collect, filters, kind, self, service
        )
        return deepcopy(
            self.once(("inventory", kind, json.dumps(filters, sort_keys=True)), collect)
        )

    def cloud_inventory(self, service, kind, filters):
        m = comparator()
        schema = self.schema(kind)
        handlers = schema.get("handlers", {})
        if "list" not in handlers:
            raise m.AcquisitionError(
                "cloudcontrol.list_resources", "ListUnsupported", "unsupported"
            )
        required = handlers["list"].get("handlerSchema", {}).get("required", ())
        account_filter = REGISTRY.import_profile(kind).account_filter
        if account_filter and tuple(required) == (account_filter.selector,):
            account = self.ctx.target.get(AWS_ACCOUNT_ID_KEY)
            execution = self.ctx.target.get(AWS_EXECUTION_ACCOUNT_ID_KEY, account)
            if not isinstance(account, str) or not account or account != execution:
                raise m.AcquisitionError(
                    "cloudcontrol.list_resources",
                    "TargetAccountMismatch",
                    "requires_filter",
                )
            if filters is None:
                filters = {account_filter.selector: account}
            elif (
                not isinstance(filters, dict)
                or filters.get(account_filter.selector) != account
            ):
                raise m.AcquisitionError(
                    "cloudcontrol.list_resources",
                    "TargetAccountMismatch",
                    "requires_filter",
                )
        if required and (
            filters is None or any(name not in filters for name in required)
        ):
            # Resolve a required list selector only from one same-owner primary identifier.
            candidates = filter_parents(
                self.resource_types(service), kind, required, self.schema
            )
            if len(candidates) != 1:
                raise m.AcquisitionError(
                    "cloudcontrol.list_resources", "RequiredFilter", "requires_filter"
                )
            parent = candidates[0]
            parents = self.inventory(service, parent)
            if self._statuses[parent]["status"] not in {"complete", "empty"}:
                raise m.AcquisitionError(
                    "cloudcontrol.list_resources", "RequiredFilter", "requires_filter"
                )
            records = []
            for record in parents:
                values = {
                    name: pointer_value(
                        record.get("cloudProperties", {}), "/properties/" + name
                    )
                    for name in required
                }
                if any(value is None for value in values.values()):
                    raise m.AcquisitionError(
                        "cloudcontrol.list_resources",
                        "RequiredFilter",
                        "requires_filter",
                    )
                records.extend(self.inventory(service, kind, values))
            return records
        inputs = {"TypeName": type_name(kind)}
        if filters:
            inputs["ResourceModel"] = json.dumps(filters, sort_keys=True)
        response = self.ctx.pages("cloudcontrol", "list_resources", **inputs)
        descriptions = response.get("ResourceDescriptions")
        if not isinstance(descriptions, list):
            raise ValueError("invalid Cloud Control inventory")
        mapping, mapped = self.mapping(service)
        records = []
        for description in descriptions:
            try:
                record = self.cloud_record(
                    service, kind, description, schema, mapping, mapped
                )
                if account_filter:
                    selector = account_filter.selector
                    account = filters[selector]
                    if record["cloudProperties"].get(selector) != account:
                        raise m.AcquisitionError(
                            "cloudcontrol.list_resources", account_filter.scope_mismatch
                        )
                    record["selectorProperties"] = {kind + "." + selector: account}
                    record["provenance"] = {
                        "api": "cloudcontrol.list_resources",
                        "selectors": {selector: account},
                    }
                records.append(record)
            except (
                m.AcquisitionError,
                ValueError,
                KeyError,
                TypeError,
                m.Unresolved,
            ) as error:
                self.failure(kind, error)
        if len({record["identity"] for record in records}) != len(records):
            raise ValueError("duplicate Cloud Control identifier")
        return records

    def cloud_record(self, service, kind, description, schema, mapping, mapped):
        m = comparator()
        handlers = schema.get("handlers", {})
        identifier = description.get("Identifier")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("missing Cloud Control identifier")
        props = (
            properties_json(description["Properties"])
            if "Properties" in description
            else {}
        )
        verified_detail = False
        needed = [
            prop
            for key, prop in mapped.items()
            if key.startswith(kind + ".")
            and prop.include
            and mapping.getters.get(prop.field.getter, {}).get("kind") == "cloudcontrol"
        ]
        profile = REGISTRY.import_profile(kind)
        if any(not props.get(field) for field in profile.verify_list_fields):
            raise m.Unresolved(profile.verify_list_error)
        if any(project(prop, props) == m.MISSING for prop in needed) or any(
            pointer_value(props, pointer) is None
            for pointer in schema.get("primaryIdentifier", ())
        ):
            if "read" not in handlers:
                raise m.AcquisitionError(
                    "cloudcontrol.get_resource", "ReadUnsupported", "unsupported"
                )
            detail = self.ctx.call(
                "cloudcontrol",
                "get_resource",
                TypeName=type_name(kind),
                Identifier=identifier,
            )
            if detail["ResourceDescription"].get("Identifier") != identifier:
                raise ValueError("Cloud Control detail identifier mismatch")
            props = properties_json(detail["ResourceDescription"]["Properties"])
            verified_detail = cloud_identity_matches(
                identifier,
                identifier,
                detail["ResourceDescription"].get("Identifier"),
                props,
                schema.get("primaryIdentifier", ()),
            ) and limitations.response_structure(props, schema)
        getters = {
            name: props
            for name, definition in mapping.getters.items()
            if definition.get("kind") == "cloudcontrol"
            and definition.get(MAPPING_RESOURCE_TYPE_KEY) == kind
        }
        seeds = {
            key: m.select(props, key.removeprefix(kind + "."))
            for key in mapped
            if key.startswith(kind + ".")
        }
        seeds = {
            key: value
            for key, value in seeds.items()
            if value != m.MISSING and value is not None
        }
        record = {
            "kind": kind,
            "identity": identifier,
            "getters": getters,
            "cloudProperties": props,
            "seedProperties": seeds,
            "verifiedDetailGetters": list(getters) if verified_detail else [],
        }
        return record


def inventory_for(ctx):
    return ImportInventory(ctx)


def adapter_inventory(ctx, service, resource_types):
    mapping, _ = inventory_for(ctx).mapping(service)
    profiles = [(kind, REGISTRY.import_profile(kind)) for kind in resource_types]
    ctx.allowed.update(
        profile.adapter[:2] for _, profile in profiles if profile.adapter
    )
    records = []
    for kind, profile in profiles:
        if profile.derived:
            continue  # Parent inventory emits the related records.
        if profile.adapter is None:
            raise KeyError(kind)
        api, operation, collection = profile.adapter
        inputs = (
            {
                profile.execution_account_input: ctx.target.get(
                    AWS_EXECUTION_ACCOUNT_ID_KEY, ctx.target[AWS_ACCOUNT_ID_KEY]
                )
            }
            if profile.execution_account_input
            else {}
        )
        response = ctx.pages(api, operation, **inputs)
        if collection is not None and (
            collection not in response or not isinstance(response[collection], list)
        ):
            raise comparator().AcquisitionError(
                api + "." + operation, "InvalidInventoryResponse"
            )
        items = response[collection] if collection else [response]
        if profile.batch:
            items = profile.batch(ctx, items)
        for item in items:
            detail = profile.detail if profile.batch is None else None
            if detail:
                key = detail.selector
                selector = item if detail.list_returns_selector else item[key]
                response = ctx.call(api, detail.operation, **inputs, **{key: selector})
                item = response if detail.result == "$" else response[detail.result]
                if detail.mismatch and item.get(key) != selector:
                    raise ValueError(detail.mismatch)
                if inputs:
                    item = dict(item, **inputs)
            record = dict(item)
            if profile.decorate:
                profile.decorate(record)
            descriptor = mapping.identities[kind]
            getter, id_path = descriptor.getter, descriptor.id_path
            identity = comparator().select(record, id_path)
            if (
                not isinstance(identity, str)
                or not identity
                or identity == comparator().MISSING
            ):
                raise ValueError(
                    "IMPORT inventory has no confirmed resource identifier"
                )
            getters = {getter: record}
            if profile.additional_getters:
                getters.update(profile.additional_getters(ctx, record, inputs))
            records.append({"kind": kind, "identity": identity, "getters": getters})
            if profile.related_records:
                records.extend(profile.related_records(record))
    if len({(r["kind"], r["identity"]) for r in records}) != len(records):
        raise ValueError("IMPORT inventory contains duplicate identifiers")
    return records


def import_comparison(root, service):
    return mapping_compare.import_comparison(root, service)
