"""Offline Import capability inspection; static paths never claim AWS success."""

import argparse
import ast
import inspect
import json
import sys
import textwrap
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aws_mapping import response_shape, runtime_registry
from aws_mapping_catalog import sdk_shape, under
from design.catalog import DesignSchemaCatalog
from utils.aws_mappings import owners
from utils.aws_schemas import schemas_for
from utils.aws_sdk import aws_runtime, sdk_for
from utils.mapping_types import Property, Registry
from utils.script_loader import module

from model.importing.discovery import (
    ADAPTER_INVENTORIES,
    SCOPED_INVENTORIES,
    DiscoveryPlan,
    adapter_detail,
    resolve,
    type_name,
)
from model.importing.limitations import sensitive

Diagnostic = dict[str, Any]


def diagnostic(status: str, code: str, reason: str, **details: Any) -> Diagnostic:
    return {"status": status, "reasonCode": code, "reason": reason, **details}


def selector_paths(node: ast.AST, resource: str) -> list[str] | None:
    if isinstance(node, ast.Constant):
        return []
    if isinstance(node, (ast.List, ast.Tuple)):
        result = []
        for child in node.elts:
            paths = selector_paths(child, resource)
            if paths is None:
                return None
            result.extend(paths)
        return result
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == resource
        and node.func.attr == "value"
        and 1 <= len(node.args) <= 2
        and not node.keywords
        and all(
            isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            for arg in node.args
        )
    ):
        return [node.args[0].value]
    return None


class Coverage:
    """Reuse process-local Mapping/Schema/SDK providers without creating an AWS client."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.schemas = schemas_for(root)
        self.sdk = sdk_for(root)
        self.catalog = DesignSchemaCatalog(root, definitions=self.schemas)
        self.adapter = module("model/adapters/aws.py", "model.adapters.aws")

    def schema(self, kind: str) -> Mapping[str, Any]:
        return self.schemas.cloudformation(type_name(kind))

    def operation(self, api: str, operation: str) -> Any:
        if not operation.startswith(("get_", "describe_", "list_", "batch_get_")):
            raise ValueError(
                "Inventory API must be read-only: " + api + "." + operation
            )
        model = self.sdk.service_model(api)
        name = aws_runtime().operation_name(model, operation)
        if name is None:
            raise ValueError("Unknown SDK operation: " + api + "." + operation)
        return model.operation_model(name)

    def service_adapter(self, service: str) -> Any:
        return (
            self.adapter.service_module(service)
            if service in self.adapter.SERVICES
            else None
        )

    def inventory_shape(self, kind: str, adapter: Any) -> Any:
        api, operation, collection = ADAPTER_INVENTORIES[kind]
        operation_model = self.operation(api, operation)
        supplied = {"AwsAccountId"} if api == "quicksight" else set()
        if (
            operation_model.input_shape
            and set(operation_model.input_shape.required_members) - supplied
        ):
            raise ValueError("Inventory requires additional SDK input selectors")
        shape = operation_model.output_shape
        if collection:
            shape = response_shape(shape, collection)
            if shape.type_name != "list":
                raise ValueError("Inventory collection is not an SDK list")
            shape = shape.member
        detail = adapter_detail(kind)
        if detail:
            operation, selector, result = detail
            selected = (
                shape
                if kind in {"KinesisFirehose.DeliveryStream", "CodeBuild.Project"}
                else response_shape(shape, selector)
            )
            if selected.type_name != "string":
                raise ValueError("Inventory detail selector is not a string")
            if (api, operation) not in getattr(adapter, "APIS", ()):
                raise ValueError("Inventory detail API is outside adapter allowlist")
            detail_model = self.operation(api, operation)
            if detail_model.input_shape and set(
                detail_model.input_shape.required_members
            ) - (supplied | {selector}):
                raise ValueError(
                    "Inventory detail requires additional SDK input selectors"
                )
            shape = (
                detail_model.output_shape
                if result == "$"
                else response_shape(detail_model.output_shape, result)
            )
        return shape

    def scoped_shape(self, kind: str) -> Any:
        spec = SCOPED_INVENTORIES[kind]
        for operation in spec.operations:
            self.operation(spec.api, operation)
        operation, path = spec.payload
        shape = self.operation(spec.api, operation).output_shape
        return shape if path == "$" else response_shape(shape, path)

    def identifier(
        self, mapping: Registry, kind: str, plan: DiscoveryPlan, adapter: Any
    ) -> Diagnostic:
        if plan.mode == "scoped_sdk":
            try:
                self.scoped_shape(kind)
                for parent in plan.parents:
                    parent_plan = resolve(
                        mapping, mapping.properties, parent, self.schema
                    )
                    if (
                        parent_plan.mode != "cloudcontrol"
                        or parent_plan.status != "ready"
                    ):
                        raise ValueError(
                            "Required parent inventory is unavailable: " + parent
                        )
                for prop in SCOPED_INVENTORIES[kind].components:
                    if kind + "." + prop not in mapping.properties:
                        raise ValueError("Identity component has no Mapping: " + prop)
            except ValueError as error:
                return diagnostic("broken", "SCOPED_IDENTITY_INVALID", str(error))
            return diagnostic(
                "uncertain" if kind == "SQS.QueuePolicy" else "ready",
                "STRUCTURE_REVIEW_REQUIRED"
                if kind == "SQS.QueuePolicy"
                else "SCOPED_SDK_IDENTITY",
                "Original queue grouping requires explicit Human structure selection"
                if kind == "SQS.QueuePolicy"
                else "Parent selectors and composite identity are preserved by the SDK inventory; live scope and uniqueness require runtime checks",
                components=list(SCOPED_INVENTORIES[kind].components),
                inputValidation="Not statically verified; operation existence does not validate runtime inputs",
                scope=["executionAccount", "region", "resourceType"],
            )
        if plan.mode == "not_modelled":
            return diagnostic(
                "not_modelled", "NO_MODEL_PROPERTIES", "No Import candidate"
            )
        if plan.mode == "parent_derived":
            parent = resolve(mapping, mapping.properties, "EC2.RouteTable", self.schema)
            subnet = resolve(mapping, mapping.properties, "EC2.Subnet", self.schema)
            if parent.mode != "adapter" or subnet.mode != "adapter":
                return diagnostic(
                    "broken",
                    "DERIVED_PARENT_UNAVAILABLE",
                    "Existing expansion requires SDK route-table and subnet inventories",
                )
            for parent_kind, parent_plan in (
                ("EC2.RouteTable", parent),
                ("EC2.Subnet", subnet),
            ):
                parent_identity = self.identifier(
                    mapping, parent_kind, parent_plan, adapter
                )
                if parent_identity["status"] != "ready":
                    return diagnostic(
                        "broken",
                        "DERIVED_PARENT_IDENTITY",
                        parent_kind + ": " + parent_identity["reason"],
                    )
            try:
                shape = self.inventory_shape("EC2.RouteTable", adapter)
                response_shape(shape, "Associations[].RouteTableAssociationId")
                response_shape(shape, "Associations[].SubnetId")
            except ValueError as error:
                return diagnostic("broken", "DERIVED_IDENTITY_UNRESOLVED", str(error))
            return diagnostic(
                "ready",
                "DERIVED_ASSOCIATION_ID",
                "RouteTableAssociationId is retained; association is attached by SubnetId, never independently published",
                components=["RouteTableAssociationId", "SubnetId"],
                scope=["executionAccount", "region", "resourceType"],
            )
        if kind in ADAPTER_INVENTORIES:
            descriptor = mapping.identities.get(kind)
            if descriptor is None:
                # Runtime deliberately falls back to Cloud Control in this case.
                missing = "Registered SDK inventory has no Mapping identity; "
            else:
                getter = mapping.getters.get(descriptor.getter, {})
                if kind not in getter.get("resources", (getter.get("resourceType"),)):
                    return diagnostic(
                        "broken",
                        "IDENTITY_GETTER_UNREGISTERED",
                        "Identity getter does not support this resource",
                        getter=descriptor.getter,
                    )
                if getter.get("kind") not in {"adapter", "sdk"}:
                    return diagnostic(
                        "broken",
                        "IDENTITY_GETTER_INVALID",
                        "SDK inventory identity must use an adapter or SDK getter",
                    )
                try:
                    leaf = response_shape(
                        self.inventory_shape(kind, adapter), descriptor.id_path
                    )
                except ValueError as error:
                    return diagnostic(
                        "broken",
                        "IDENTITY_PATH_INVALID",
                        str(error),
                        getter=descriptor.getter,
                        path=descriptor.id_path,
                    )
                if leaf.type_name != "string":
                    return diagnostic(
                        "broken",
                        "IDENTITY_NOT_SCALAR",
                        "SDK inventory requires a nonempty string identity",
                        path=descriptor.id_path,
                    )
                return diagnostic(
                    "ready",
                    "SDK_IDENTITY",
                    "Identity path exists in the actual inventory payload; AWS uniqueness remains runtime-checked",
                    getter=descriptor.getter,
                    components=[descriptor.id_path],
                    scope=["executionAccount", "region", "resourceType"],
                    limitations=[
                        "Static schemas do not prove uniqueness or nonempty values on AWS"
                    ],
                )
        else:
            missing = ""
        try:
            schema = self.schema(kind)
        except KeyError:
            return diagnostic(
                "broken",
                "IDENTITY_UNRESOLVED",
                missing + "No provider primary identifier or executable SDK identity",
            )
        pointers = schema.get("primaryIdentifier", ())
        if not pointers:
            return diagnostic(
                "broken",
                "IDENTITY_UNRESOLVED",
                missing + "Provider primaryIdentifier is absent",
            )
        try:
            for pointer in pointers:
                if not pointer.startswith("/properties/"):
                    raise ValueError(
                        "Unsupported primary identifier pointer: " + pointer
                    )
                path = (
                    pointer.removeprefix("/properties/")
                    .replace("/", ".")
                    .replace("~1", "/")
                    .replace("~0", "~")
                )
                if under(path, schema.get("writeOnlyProperties", ())):
                    raise ValueError("Write-only provider identity: " + pointer)
                self.catalog.property_schema(kind, path)
        except (KeyError, ValueError) as error:
            return diagnostic(
                "broken", "IDENTITY_PATH_INVALID", str(error), components=list(pointers)
            )
        if missing:
            return diagnostic(
                "broken",
                "SDK_IDENTITY_MISSING",
                missing
                + "Cloud Control fallback has a provider identity but does not repair the SDK registration",
                components=list(pointers),
            )
        return diagnostic(
            "ready" if "read" in schema.get("handlers", {}) else "uncertain",
            "PROVIDER_IDENTITY"
            if "read" in schema.get("handlers", {})
            else "IDENTITY_LIST_ONLY",
            "All primary-identifier components are retained; an opaque provider Identifier preserves composite scope. Values, delimiters and AWS uniqueness require runtime confirmation",
            components=list(pointers),
            scope=["executionAccount", "region", "resourceType", *pointers],
        )

    def discovery(
        self,
        mapping: Registry,
        kind: str,
        plan: DiscoveryPlan,
        identity: Diagnostic,
        adapter: Any,
    ) -> Diagnostic:
        result = asdict(plan)
        result["reasonCode"] = result.pop("reason_code")
        result["requiredFilters"] = list(result.pop("required_filters"))
        result["parents"] = list(result["parents"])
        if plan.mode == "scoped_sdk":
            result["operations"] = list(SCOPED_INVENTORIES[kind].operations)
            result.update(identity)
        elif plan.mode == "adapter":
            result["inventory"] = list(ADAPTER_INVENTORIES[kind])
            result.update(
                diagnostic(
                    "ready" if identity["status"] == "ready" else "broken",
                    "SDK_INVENTORY"
                    if identity["status"] == "ready"
                    else "SDK_INVENTORY_INCOMPLETE",
                    "Inventory operation, payload and string identity verified offline"
                    if identity["status"] == "ready"
                    else identity["reason"],
                )
            )
        elif plan.mode == "parent_derived":
            result.update(identity)
        elif plan.reason_code == "PARENT_FILTER":
            parent = plan.parents[0]
            parent_plan = resolve(mapping, mapping.properties, parent, self.schema)
            parent_identity = self.identifier(mapping, parent, parent_plan, adapter)
            if parent_identity["status"] != "ready":
                result.update(
                    diagnostic(
                        "uncertain",
                        "PARENT_IDENTITY_UNRESOLVED",
                        parent + ": " + parent_identity["reason"],
                    )
                )
        return result

    def sdk_selector(
        self,
        mapping: Registry,
        kind: str,
        getter: Mapping[str, Any],
        plan: DiscoveryPlan,
        adapter: Any,
    ) -> Diagnostic:
        """Prove only direct SDK calls; arbitrary Python branches remain uncertain."""
        function = adapter.fetch_sdk
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        except (OSError, TypeError, SyntaxError) as error:
            return diagnostic(
                "uncertain",
                "SDK_SELECTOR_UNCONFIRMED",
                "Selector source cannot be inspected: " + str(error),
            )
        body = tree.body[0].body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        if (
            len(body) != 1
            or not isinstance(body[0], ast.Return)
            or not isinstance(body[0].value, ast.Call)
        ):
            return diagnostic(
                "uncertain",
                "SDK_SELECTOR_UNCONFIRMED",
                "Conditional or indirect fetch_sdk selector is not statically proven",
                adapterFunction="fetch_sdk",
            )
        call = body[0].value
        parameters = list(inspect.signature(function).parameters)
        if (
            len(parameters) != 3
            or not isinstance(call.func, ast.Attribute)
            or not isinstance(call.func.value, ast.Name)
            or call.func.value.id != parameters[0]
            or call.func.attr != "call"
            or len(call.args) != 2
            or not isinstance(call.args[0], ast.Constant)
            or call.args[0].value != getter["service"]
            or not isinstance(call.args[1], ast.Name)
            or call.args[1].id != parameters[2]
        ):
            return diagnostic(
                "uncertain",
                "SDK_SELECTOR_UNCONFIRMED",
                "fetch_sdk does not directly return the registered SDK operation",
            )
        names = {kw.arg for kw in call.keywords}
        inputs = self.operation(getter["service"], getter["operation"]).input_shape
        if None in names:
            return diagnostic(
                "uncertain",
                "SDK_SELECTOR_UNCONFIRMED",
                "Dynamic SDK keyword inputs require runtime evidence",
            )
        if inputs and set(inputs.required_members) - names:
            return diagnostic(
                "broken",
                "SDK_INPUT_MISSING",
                "fetch_sdk omits required SDK inputs: "
                + ", ".join(sorted(set(inputs.required_members) - names)),
            )
        if inputs and names - inputs.members.keys():
            return diagnostic(
                "broken",
                "SDK_INPUT_UNKNOWN",
                "fetch_sdk supplies unknown SDK inputs: "
                + ", ".join(sorted(names - inputs.members.keys())),
            )
        selectors = []
        for keyword in call.keywords:
            paths = selector_paths(keyword.value, parameters[1])
            if paths is None:
                return diagnostic(
                    "uncertain",
                    "SDK_SELECTOR_UNCONFIRMED",
                    "Computed or indirect resource selector requires runtime evidence",
                )
            for path in paths:
                prop = mapping.properties.get(kind + "." + path)
                if prop is None:
                    return diagnostic(
                        "broken",
                        "SDK_SELECTOR_PROPERTY_MISSING",
                        "Resource selector has no Mapping property: " + path,
                    )
                if plan.mode != "cloudcontrol" or prop.source != "aws":
                    return diagnostic(
                        "uncertain",
                        "SDK_SELECTOR_UNCONFIRMED",
                        "Selector is not proven from provider seedProperties: " + path,
                    )
                try:
                    schema = self.schema(kind)
                    self.catalog.property_schema(kind, path)
                except (KeyError, ValueError):
                    return diagnostic(
                        "uncertain",
                        "SDK_SELECTOR_UNCONFIRMED",
                        "Selector property is absent from the provider payload schema: "
                        + path,
                    )
                if under(path, schema.get("writeOnlyProperties", ())):
                    return diagnostic(
                        "broken",
                        "SDK_SELECTOR_WRITE_ONLY",
                        "Selector requires an unobservable write-only value: " + path,
                    )
                selectors.append(path)
        return diagnostic(
            "capturable" if selectors else "uncertain",
            "SDK_SELECTOR" if selectors else "SDK_SELECTOR_UNCONFIRMED",
            "Direct SDK selector inputs are seeded from readable provider properties; optional values and AWS uniqueness still require runtime confirmation"
            if selectors
            else "No resource selector can be proven from fetch_sdk",
            selectors=sorted(set(selectors)),
        )

    def property(
        self,
        mapping: Registry,
        kind: str,
        key: str,
        prop: Property,
        plan: DiscoveryPlan,
        identity: Diagnostic,
        adapter: Any,
    ) -> Diagnostic:
        getter = mapping.getters.get(prop.field.getter, {})
        refs = {
            "mapping": "framework/mappings/aws/" + mapping.service + ".yaml#" + key,
            "getter": prop.field.getter or None,
            "adapter": "framework/scripts/aws-compare-services/"
            + mapping.service
            + ".py"
            if adapter
            else None,
            "path": prop.field.path,
            "source": prop.source,
        }
        result = self.property_path(
            mapping, kind, key, prop, getter, plan, identity, adapter
        )
        return {"property": key, **result, "references": refs}

    def property_path(
        self,
        mapping: Registry,
        kind: str,
        key: str,
        prop: Property,
        getter: Mapping[str, Any],
        plan: DiscoveryPlan,
        identity: Diagnostic,
        adapter: Any,
    ) -> Diagnostic:
        if (
            adapter
            and callable(getattr(adapter, "sensitive", None))
            and sensitive(SimpleNamespace(module=adapter), key)
        ):
            return diagnostic(
                "unobservable",
                "SENSITIVE_VALUE_WITHHELD",
                "API output is withheld by the Import sensitive-property contract",
            )
        if (
            key == "Glue.Connection.CatalogId"
            and plan.reason_code == "TARGET_ACCOUNT_FILTER"
        ):
            return diagnostic(
                "capturable",
                "VALIDATED_SELECTOR",
                "CatalogId is checked against both the verified target account and returned resource identity",
                source="verified_selector",
            )
        if plan.mode == "scoped_sdk":
            spec = SCOPED_INVENTORIES[kind]
            if key.removeprefix(kind + ".") in spec.selectors:
                return diagnostic(
                    "capturable",
                    "VALIDATED_SELECTOR",
                    "Verified account/parent selector retained separately from AWS response values",
                    source="verified_selector",
                )
            if prop.source == "aws":
                try:
                    shape = self.scoped_shape(kind)
                    path = prop.field.path
                    if (
                        kind == "DataZone.Project"
                        and getter.get("kind") == "cloudcontrol"
                    ):
                        path = {"DomainId": "domainId", "Id": "id", "Name": "name"}[
                            path
                        ]
                    if kind != "SQS.QueuePolicy":
                        response_shape(shape, path)
                    if getter.get("kind") == "sdk" and (
                        getter["service"],
                        getter["operation"],
                    ) not in getattr(adapter, "APIS", ()):
                        raise ValueError("SDK API is outside adapter allowlist")
                    if getter.get("kind") == "sdk" and (
                        getattr(adapter, "SDK_OPERATIONS", {}).get(kind)
                        != getter["operation"]
                        or not callable(getattr(adapter, "fetch_sdk", None))
                    ):
                        raise ValueError(
                            "SDK operation/resource selector is not registered"
                        )
                    if prop.field.classification != "supported":
                        raise ValueError(prop.field.reason or "Getter unavailable")
                except (ValueError, KeyError) as error:
                    return diagnostic("broken", "SCOPED_PROPERTY_INVALID", str(error))
                return diagnostic(
                    "capturable",
                    "SCOPED_SDK_PAYLOAD",
                    "Property is read from the registered inventory payload; optional absence remains a runtime result",
                )
        if prop.source != "aws":
            return diagnostic(
                "unobservable",
                "LOCAL_METADATA"
                if prop.field.classification == "local_metadata"
                or prop.source in {"model", "target"}
                else "EXPLICIT_UNOBSERVABLE",
                prop.constraint or prop.field.reason,
                source=prop.source,
                inputProjection=bool(prop.field.getter),
                limitation="Input/projection or explicitly unavailable output; not an AWS-confirmed value",
            )
        if prop.field.classification != "supported":
            return diagnostic(
                "broken",
                "GETTER_CLASSIFICATION",
                prop.field.reason or prop.field.classification,
            )
        if not getter:
            return diagnostic(
                "broken", "GETTER_MISSING", "Mapping getter is not registered"
            )
        if getter.get("kind") == "sdk":
            try:
                shape = sdk_shape(self.sdk, getter)
                if prop.field.path != "$":
                    response_shape(shape, prop.field.path)
            except ValueError as error:
                return diagnostic("broken", "SDK_PATH_INVALID", str(error))
            api = (getter["service"], getter["operation"])
            if api not in getattr(adapter, "APIS", ()):
                return diagnostic(
                    "broken",
                    "API_NOT_ALLOWED",
                    "Mapping API is outside the existing adapter read-only allowlist: "
                    + ".".join(api),
                )
            if (
                getter.get("resourceType") != kind
                or getattr(adapter, "SDK_OPERATIONS", {}).get(kind)
                != getter["operation"]
                or not callable(getattr(adapter, "fetch_sdk", None))
            ):
                return diagnostic(
                    "broken",
                    "SDK_SELECTOR_MISSING",
                    "No matching SDK_OPERATIONS/fetch_sdk resource selector",
                )
            return self.sdk_selector(mapping, kind, getter, plan, adapter)
        if getter.get("kind") == "cloudcontrol":
            try:
                schema = self.schema(kind)
            except KeyError:
                return diagnostic(
                    "broken",
                    "SCHEMA_UNSUPPORTED",
                    "Cloud Control getter has no CloudFormation schema",
                )
            if (
                getter.get("service"),
                getter.get("operation"),
                getter.get("result"),
                getter.get("resourceType"),
            ) != (
                "cloudcontrol",
                "get_resource",
                "ResourceDescription.Properties",
                kind,
            ):
                return diagnostic(
                    "broken",
                    "PROVIDER_GETTER_INVALID",
                    "Invalid Cloud Control read envelope/resource",
                )
            if "read" not in schema.get("handlers", {}):
                return diagnostic(
                    "broken",
                    "READ_UNSUPPORTED",
                    "CloudFormation schema has no Read handler",
                )
            if not getter.get("identifier") or tuple(getter["identifier"]) != tuple(
                schema.get("primaryIdentifier", ())
            ):
                return diagnostic(
                    "broken",
                    "PROVIDER_IDENTIFIER_MISMATCH",
                    "Getter identifier differs from provider primaryIdentifier",
                )
            path = key.removeprefix(kind + ".")
            if path != prop.field.path or under(
                path, schema.get("writeOnlyProperties", ())
            ):
                return diagnostic(
                    "broken",
                    "PROVIDER_PATH_INVALID",
                    "Provider path differs from property or is write-only",
                )
            try:
                self.catalog.property_schema(kind, path)
            except (KeyError, ValueError) as error:
                return diagnostic("broken", "PROVIDER_PATH_INVALID", str(error))
            if plan.mode != "cloudcontrol":
                return diagnostic(
                    "uncertain",
                    "PROVIDER_SELECTOR_UNCONFIRMED",
                    "SDK inventory does not seed this provider getter; provider selector must be reconstructed from confirmed Model rows",
                )
            if identity["status"] != "ready":
                return diagnostic(
                    "uncertain", "PROVIDER_IDENTITY_UNCONFIRMED", identity["reason"]
                )
            return diagnostic(
                "capturable",
                "PROVIDER_READ",
                "Read handler, complete primary identifier and readable property path exist; acquisition success remains unverified",
            )
        if getter.get("kind") != "adapter":
            return diagnostic("broken", "GETTER_KIND_INVALID", "Unknown getter kind")
        if kind not in getter.get("resources", ()) or not callable(
            getattr(adapter, "fetch", None)
        ):
            return diagnostic(
                "broken", "ADAPTER_GETTER_MISSING", "No adapter fetch/resource contract"
            )
        if not getattr(adapter, "APIS", ()):
            return diagnostic(
                "broken",
                "ADAPTER_API_MISSING",
                "Adapter has no read-only API allowlist",
            )
        if (
            plan.mode == "adapter"
            and mapping.identities[kind].getter == prop.field.getter
        ):
            try:
                response_shape(self.inventory_shape(kind, adapter), prop.field.path)
            except ValueError as error:
                return diagnostic(
                    "uncertain",
                    "ADAPTER_PROJECTION_UNCONFIRMED",
                    "Inventory payload requires an adapter projection: " + str(error),
                )
            return diagnostic(
                "capturable",
                "INVENTORY_PAYLOAD",
                "Getter is seeded by the inventory; Path exists in the SDK payload shape",
            )
        if (
            plan.mode == "parent_derived"
            and prop.field.getter == "association"
            and prop.field.path == "RouteTableId"
        ):
            return diagnostic(
                "capturable",
                "DERIVED_ASSOCIATION",
                "Existing route-table expansion seeds RouteTableId and attaches it to the subnet",
            )
        return diagnostic(
            "uncertain",
            "ADAPTER_SELECTOR_UNCONFIRMED",
            "Adapter fetch/resource and API allowlist exist, but getter branch, selectors and projected output are not declaratively proven; fetch alone is insufficient",
            adapterFunction="fetch",
            apis=[list(api) for api in sorted(adapter.APIS)],
        )

    def resource(self, mapping: Registry, kind: str) -> Diagnostic:
        plan = resolve(mapping, mapping.properties, kind, self.schema)
        adapter = self.service_adapter(mapping.service)
        identity = self.identifier(mapping, kind, plan, adapter)
        discovery = self.discovery(mapping, kind, plan, identity, adapter)
        properties = [
            self.property(mapping, kind, key, prop, plan, identity, adapter)
            for key, prop in sorted(mapping.properties.items())
            if key.startswith(kind + ".") and prop.include
        ]
        counts = Counter(p["status"] for p in properties)
        status = (
            "not_modelled"
            if plan.mode == "not_modelled"
            else "broken"
            if discovery["status"] in {"broken", "unsupported"}
            or identity["status"] == "broken"
            or counts["broken"]
            else "uncertain"
            if discovery["status"] == "uncertain"
            or identity["status"] == "uncertain"
            or counts["uncertain"]
            or counts["unobservable"]
            else "ready"
        )
        return {
            "resourceType": kind,
            "service": mapping.service,
            "modelled": plan.mode != "not_modelled",
            "discovery": discovery,
            "identity": identity,
            "properties": {
                name: counts[name]
                for name in ("capturable", "unobservable", "broken", "uncertain")
            },
            "propertyDiagnostics": properties,
            "staticStatus": status,
            "runtimeVerified": False,
            "references": {
                "mapping": "framework/mappings/aws/"
                + mapping.service
                + ".yaml#"
                + kind,
                "schema": type_name(kind),
                "inventory": "framework/scripts/model/importing/discovery.py",
                "adapter": "framework/scripts/aws-compare-services/"
                + mapping.service
                + ".py"
                if adapter
                else None,
            },
        }


def report(root: Path, service: str | None = None) -> Diagnostic:
    if not root.is_dir():
        raise ValueError("Repository root is not a directory: " + str(root))
    index = owners(root)
    if service is not None and service not in index.values():
        raise ValueError("Unknown Mapping service: " + service)
    inspector = Coverage(root)
    results = []
    for selected in sorted(set(index.values())):
        if service is not None and service != selected:
            continue
        mapping = runtime_registry(root, selected)
        expected = {kind for kind, owner in index.items() if owner == selected}
        if mapping.resource_types != expected:
            raise ValueError("Mapping ownership mismatch: " + selected)
        results.extend(inspector.resource(mapping, kind) for kind in sorted(expected))
    results.sort(key=lambda item: item["resourceType"])
    return {
        "runtimeVerified": False,
        "limitations": [
            "Offline capability only: no AWS clients, credentials, permissions or live resource uniqueness verified",
            "Optional, sensitive, conditional and unresolved input values may remain unavailable at acquisition",
            "Adapter projections/selector branches without a static contract remain uncertain",
        ],
        "summary": {
            "registeredTypes": len(results),
            "modelledTypes": sum(r["modelled"] for r in results),
            "discoveryReady": sum(r["discovery"]["status"] == "ready" for r in results),
            "identityReady": sum(r["identity"]["status"] == "ready" for r in results),
            "propertyGapTypes": sum(
                any(r["properties"][s] for s in ("broken", "uncertain", "unobservable"))
                for r in results
            ),
            "staticStatuses": dict(
                sorted(Counter(r["staticStatus"] for r in results).items())
            ),
        },
        "resources": results,
    }


def text_report(result: Diagnostic) -> str:
    lines = ["Import Coverage (offline; runtimeVerified=false)"]
    lines.extend(f"{key}: {value}" for key, value in result["summary"].items())
    for item in result["resources"]:
        if item["staticStatus"] in {"ready", "not_modelled"}:
            continue
        lines.append(item["resourceType"] + " [" + item["staticStatus"] + "]")
        for layer in ("discovery", "identity"):
            entry = item[layer]
            if entry["status"] != "ready":
                lines.append(f"  {layer}: {entry['reasonCode']}: {entry['reason']}")
        for prop in item["propertyDiagnostics"]:
            if prop["status"] != "capturable":
                lines.append(
                    f"  {prop['property']}: {prop['status']} / {prop['reasonCode']}: {prop['reason']}"
                )
    lines.extend(result["limitations"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--service")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = report(args.repository_root.absolute(), args.service)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        aws_runtime().BotoCoreError,
    ) as error:
        print("Import Coverage failed: " + str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.format == "json"
        else text_report(result)
    )
    return int(
        args.strict and any(r["staticStatus"] == "broken" for r in result["resources"])
    )
