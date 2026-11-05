"""Post-success synchronization and execution-bound deletion evidence."""

import re
from functools import partial as _bind_framework_callback

import design.layout as _imports_design_layout
import utils.cloudformation.format as _imports_cfn_format
import utils.cloudformation.inputs as _imports_cfn_inputs
from aws_mapping_catalog import project
from contracts.model import MODEL_PENDING_DEPLOY, RESOURCE_TYPE_KEY
from contracts.target import (
    AWS_ACCOUNT_ID_KEY,
    AWS_EXECUTION_ACCOUNT_ID_KEY,
    AWS_REGION_KEY,
)
from design.catalog import DesignSchemaCatalog
from model.adapters.aws import MISSING, AcquisitionError, Unresolved, service_module
from model.adapters.observation_sources import (
    cloudcontrol_source,
    codebuild_source,
    permission_source,
    physical_identifier_source,
)
from model.adapters.observed import (
    active_outputs,
    ambiguous,
    identifier_source,
    observed_destinations,
    own_key,
    propagate_references,
    resolve_resources,
    static_export_handle,
)
from model.importing.inventory import pointer_value, properties_json
from model.reference_nodes import parse as parse_reference
from task_contract_core import task_snapshot
from utils.aws.client import AwsError
from utils.cloudformation.export_resolution import resolve_exports
from utils.cloudformation.inputs import Blocked as Blocked
from utils.json_format import fingerprint
from utils.reference_contracts import REF_ATTRIBUTES
from validation_scope import active_scope

import deploy.observed_resume as _dependency_deploy_observed_resume
from deploy import change_sets, current_state
from deploy import deferred as deferred_work
from deploy import scope as execution_scope
from model import dependency_index


def _visit_evidence(
    document,
    parameters,
    stack,
    pseudo,
    _condition_stack,
    definitions,
    conditions,
    needed,
    seen,
    value,
):
    if isinstance(value, list):
        for item in value:
            _visit_evidence(
                document,
                parameters,
                stack,
                pseudo,
                _condition_stack,
                definitions,
                conditions,
                needed,
                seen,
                item,
            )
    elif isinstance(value, dict):
        if set(value) == {"Fn::If"}:
            argument = value["Fn::If"]
            if not isinstance(argument, list) or len(argument) != 3:
                raise Blocked("invalid Fn::If expression")
            name = argument[0]
            if not isinstance(name, str) or name in _condition_stack:
                raise Blocked("cyclic or invalid condition")
            condition = {"Condition": name}
            if not checked_evidence_parameters(
                document,
                parameters,
                stack,
                condition,
                pseudo,
                _condition_stack | {name},
            ):
                raise Blocked("condition parameters unavailable")
            _visit_evidence(
                document,
                parameters,
                stack,
                pseudo,
                _condition_stack,
                definitions,
                conditions,
                needed,
                seen,
                condition,
            )
            selected = _imports_cfn_inputs.output_value(
                document, parameters, pseudo or {}, value
            )
            _visit_evidence(
                document,
                parameters,
                stack,
                pseudo,
                _condition_stack,
                definitions,
                conditions,
                needed,
                seen,
                selected,
            )
            return
        if "Ref" in value and value["Ref"] in definitions:
            needed.add(value["Ref"])
        if "Fn::Sub" in value:
            sub = value["Fn::Sub"]
            text = sub if isinstance(sub, str) else sub[0]
            overrides = {} if isinstance(sub, str) else sub[1]
            for name in re.findall(r"\$\{([^}!]+)\}", text):
                if name in definitions and name not in overrides:
                    needed.add(name)
        for key in ("Condition", "Fn::If"):
            name = value.get(key)
            if key == "Fn::If" and isinstance(name, list) and name:
                name = name[0]
            if isinstance(name, str) and name in conditions and name not in seen:
                seen.add(name)
                _visit_evidence(
                    document,
                    parameters,
                    stack,
                    pseudo,
                    _condition_stack,
                    definitions,
                    conditions,
                    needed,
                    seen,
                    conditions[name],
                )
        for item in value.values():
            _visit_evidence(
                document,
                parameters,
                stack,
                pseudo,
                _condition_stack,
                definitions,
                conditions,
                needed,
                seen,
                item,
            )


def _permission_attribute(
    backend, actuals, mapped, document, parameters, pseudo, stack, logical, name
):
    entry = mapped.get(logical)
    matches = [item for item in actuals if item.get("LogicalResourceId") == logical]
    if entry is None or len(matches) != 1:
        raise Blocked("GetAtt resource mapping unavailable")
    resource, actual = entry[2], matches[0]
    catalog = DesignSchemaCatalog(backend.root)
    kind = resource[RESOURCE_TYPE_KEY]
    schema = catalog.schema(kind)
    primary = schema.get("primaryIdentifier", [])
    physical = actual.get("PhysicalResourceId")
    if (
        actual.get("ResourceType") != catalog.cloudformation_type(kind)
        or actual.get("ResourceStatus")
        not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
        or not isinstance(physical, str)
        or not physical
        or "|" in physical
        or len(primary) != 1
        or "read" not in schema.get("handlers", {})
        or "/properties/" + name not in schema.get("readOnlyProperties", [])
    ):
        raise Blocked("GetAtt resource identity or attribute unsupported")
    if kind == "Events.Rule" and name == "Arn":
        definition = document["Resources"][logical]
        props = definition.get("Properties", {})
        evidence = {key: props[key] for key in ("Name", "EventBusName") if key in props}
        if not checked_evidence_parameters(
            document, parameters, stack, evidence, pseudo
        ):
            raise Blocked("rule identity parameters unavailable")
        selected = {
            key: _imports_cfn_inputs.output_value(document, parameters, pseudo, value)
            for key, value in evidence.items()
        }
        resolved = {
            key: _imports_cfn_inputs.resolve_value(
                permission_expression(
                    val, backend, actuals, mapped, document, parameters, pseudo, stack
                ),
                parameters,
                pseudo,
                conditions=document.get("Conditions"),
            )
            for key, val in selected.items()
            if val != {"Ref": "AWS::NoValue"}
        }
        rule_name = resolved.get("Name", physical)
        bus = resolved.get("EventBusName", "default")
        bus_expression = _imports_cfn_inputs.output_value(
            document, parameters, pseudo, props.get("EventBusName", "default")
        )
        if isinstance(bus_expression, dict) and set(bus_expression) == {"Ref"}:
            bus_logical = bus_expression["Ref"]
            if bus_logical in document.get("Resources", {}) and (
                document["Resources"][bus_logical].get("Type")
                != "AWS::Events::EventBus"
                or bus_logical not in mapped
                or mapped[bus_logical][2][RESOURCE_TYPE_KEY] != "Events.EventBus"
            ):
                raise Blocked("event bus resource type mismatch")
        partition = stack["StackId"].split(":")[1]
        account = backend.target.get(
            AWS_EXECUTION_ACCOUNT_ID_KEY, backend.target[AWS_ACCOUNT_ID_KEY]
        )
        if isinstance(bus, str) and bus.startswith("arn:"):
            prefix = f"arn:{partition}:events:{backend.target[AWS_REGION_KEY]}:{account}:event-bus/"
            if not bus.startswith(prefix):
                raise Blocked("event bus ARN identity mismatch")
            bus = bus[len(prefix) :]
        if (
            rule_name != physical
            or not isinstance(bus, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", bus)
        ):
            raise Blocked("rule identity ambiguous")
        response = service_module("eventbridge").fetch(
            PermissionContext(backend),
            PermissionResource(
                rule_name, {"Name": rule_name, "EventBusName": bus}, physical
            ),
            "base",
        )
        prefix = (
            f"arn:{partition}:events:{backend.target[AWS_REGION_KEY]}:{account}:rule/"
        )
        expected = prefix + ("" if bus == "default" else bus + "/") + rule_name
        if (
            response.get("Name") != rule_name
            or response.get("EventBusName") != bus
            or response.get("Arn") != expected
        ):
            raise Blocked("rule provider identity mismatch")
        return response["Arn"]
    response = backend.aws(
        "get_resource",
        service="cloudcontrol",
        TypeName=catalog.cloudformation_type(kind),
        Identifier=physical,
    )
    description = (
        response.get("ResourceDescription") if isinstance(response, dict) else None
    )
    if not isinstance(description, dict) or description.get("Identifier") != physical:
        raise Blocked("GetAtt provider identity mismatch")
    payload = properties_json(description.get("Properties"))
    result = pointer_value(payload, "/properties/" + name)
    if (
        pointer_value(payload, primary[0]) != physical
        or not isinstance(result, str)
        or not result
    ):
        raise Blocked("GetAtt provider attribute unavailable")
    return result


def removed_resources(units, states):
    result = {}
    for unit in units:
        state = states[unit["name"]]
        evidence = state.get("executionEvidence")
        changes = (
            evidence.get("resources", []) if evidence else state.get("changes", [])
        )
        removed = {}
        for change in changes:
            if change["Action"] != "Remove":
                continue
            definition = {
                "Type": change["ResourceType"],
                "PolicyAction": change.get("PolicyAction"),
                "PhysicalResourceId": change.get("PhysicalResourceId"),
            }
            if change.get("parentLogicalId"):
                definition["Properties"] = {
                    change["parentProperty"]: {"Ref": change["parentLogicalId"]}
                }
            removed[change["LogicalResourceId"]] = definition
        result[unit["name"]] = removed
    return result


def removal_candidate(name, logical, removal):
    """Deletion intent can require synchronization, but never proves destruction."""
    policy = removal.get("PolicyAction")
    if policy in {"Retain", "RetainExceptOnCreate"}:
        return False
    if policy not in {"Delete", "Snapshot"}:
        ambiguous(f"{name}/{logical}: removal policy is unknown")
    return True


def selected_resources(document, parameters, pseudo, removed, grouped):
    """Select the same possible identifier updates before and after execution."""
    selected = {
        logical
        for logical, definition in document.get("Resources", {}).items()
        if logical not in removed
        and _imports_cfn_inputs.condition_active(
            document, parameters, pseudo, definition
        )
    }
    for logical, definition in removed.items():
        if definition["Type"] not in grouped:
            selected.add(logical)
    return selected


def security_group_rule_id(
    backend, stack, document, parameters, pseudo, actuals, logical, actual, output
):
    """Confirm a Stack output against one rule selected by the deployed template."""
    if current_state.category(stack) != "SUCCESS" or actual.get(
        "ResourceStatus"
    ) not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}:
        return None
    try:
        deployed = backend.aws("get_template", StackName=stack["StackId"]).get(
            "TemplateBody"
        )
        if isinstance(deployed, str):
            deployed, errors = _imports_cfn_format.decode(deployed)
            if errors:
                return None
        if deployed != document or document.get("Transform"):
            return None
        props = document["Resources"][logical]["Properties"]
        names = {
            "GroupId",
            "IpProtocol",
            "FromPort",
            "ToPort",
            "CidrIp",
            "CidrIpv6",
            "SourcePrefixListId",
            "DestinationPrefixListId",
            "SourceSecurityGroupId",
            "DestinationSecurityGroupId",
        }
        definition = document["Resources"][logical]
        evidence = [
            definition.get("Condition"),
            {key: val for key, val in props.items() if key in names},
        ]
        if definition.get("Condition"):
            evidence[0] = {"Condition": definition["Condition"]}
        if not checked_evidence_parameters(
            document, parameters, stack, evidence, pseudo
        ):
            return None
        references = {
            item["LogicalResourceId"]: item["PhysicalResourceId"]
            for item in actuals
            if item.get("ResourceType") == "AWS::EC2::SecurityGroup"
            and item.get("ResourceStatus")
            in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
            and isinstance(item.get("PhysicalResourceId"), str)
        }
        expected = {}
        for key, value in props.items():
            if key not in names:
                continue
            if isinstance(value, dict) and "Fn::GetAtt" in value:
                ref = value["Fn::GetAtt"]
                ref = ref.split(".", 1) if isinstance(ref, str) else ref
                if (
                    isinstance(ref, list)
                    and len(ref) == 2
                    and ref[1] == "GroupId"
                    and ref[0] in references
                ):
                    value = {"Ref": ref[0]}
            expected[key] = _imports_cfn_inputs.resolve_value(
                value,
                parameters,
                pseudo | references,
                conditions=document.get("Conditions"),
            )
        group = expected.pop("GroupId")
        if not isinstance(group, str) or not re.fullmatch(r"sg-[0-9a-f]+", group):
            return None
        for key in ("FromPort", "ToPort"):
            if key in expected:
                expected[key] = int(expected[key])
        records = current_state.pages(
            lambda operation, **kw: backend.aws(operation, service="ec2", **kw),
            "describe_security_group_rules",
            "SecurityGroupRules",
            Filters=[{"Name": "group-id", "Values": [group]}],
        )
        egress = (
            document["Resources"][logical]["Type"] == "AWS::EC2::SecurityGroupEgress"
        )
        candidates = service_module("security-group").rule_candidates(
            records, group, egress, expected
        )
        if len(candidates) != 1 or candidates[0].get("SecurityGroupRuleId") != output:
            return None
        after = current_state.read(backend.aws, stack["StackId"])
        if current_state.identity(stack) != current_state.identity(after) or stack.get(
            "Outputs", []
        ) != after.get("Outputs", []):
            return None
        return (
            output
            if isinstance(output, str) and re.fullmatch(r"sgr-[0-9a-f]+", output)
            else None
        )
    except (AwsError, Blocked, Unresolved, KeyError, TypeError, ValueError):
        return None


def checked_evidence_parameters(
    document, parameters, stack, expressions, pseudo=None, _condition_stack=frozenset()
):
    """Compare only parameters used by identity evidence or its conditions."""
    definitions = document.get("Parameters", {})
    conditions = document.get("Conditions", {})
    if not isinstance(definitions, dict) or not isinstance(conditions, dict):
        raise ValueError("parameter or condition declarations invalid")
    needed, seen = set(), set()

    visit = _bind_framework_callback(
        _visit_evidence,
        document,
        parameters,
        stack,
        pseudo,
        _condition_stack,
        definitions,
        conditions,
        needed,
        seen,
    )

    visit(expressions)
    actual = stack.get("Parameters", [])
    if (
        not isinstance(actual, list)
        or any(
            not isinstance(item, dict) or not isinstance(item.get("ParameterKey"), str)
            for item in actual
        )
        or len({item["ParameterKey"] for item in actual}) != len(actual)
    ):
        return False
    observed = {item["ParameterKey"]: item.get("ParameterValue") for item in actual}
    if any(observed.get(key) in (None, "****") for key in needed):
        return False
    subset = {"Parameters": {key: definitions[key] for key in needed}}
    checked = _imports_cfn_inputs.checked_parameters
    deployed = [
        {"ParameterKey": key, "ParameterValue": observed[key]} for key in needed
    ]
    local = [
        {"ParameterKey": key, "ParameterValue": parameters[key]}
        for key in needed
        if key in parameters
    ]
    return checked(subset, deployed) == checked(subset, local)


def cloudcontrol_observation(
    backend, stack, document, parameters, actual, resource, prop, catalog
):
    """Confirm a provider response against the exact current Stack resource."""
    source = cloudcontrol_source(backend.root, catalog, resource, prop)
    if source is None:
        return None, "unsupported acquisition contract"
    pointer, item = source
    physical = actual.get("PhysicalResourceId")
    account = backend.target.get(
        AWS_EXECUTION_ACCOUNT_ID_KEY, backend.target[AWS_ACCOUNT_ID_KEY]
    )
    region = backend.target[AWS_REGION_KEY]
    stack_id = stack.get("StackId", "")
    if not stack_id.startswith(f"arn:aws:cloudformation:{region}:{account}:stack/"):
        return None, "stack account or region identity mismatch"
    if not isinstance(physical, str) or not physical or "|" in physical:
        return None, "physical identifier unavailable"
    if current_state.category(stack) != "SUCCESS" or actual.get(
        "ResourceStatus"
    ) not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}:
        return None, "stack or resource state unconfirmed"
    try:
        deployed = backend.aws("get_template", StackName=stack_id).get("TemplateBody")
        if isinstance(deployed, str):
            deployed, errors = _imports_cfn_format.decode(deployed)
            if errors:
                return None, "deployed template unavailable"
        if deployed != document or document.get("Transform"):
            return None, "deployed template mismatch"
        logical = actual.get("LogicalResourceId")
        definitions = document.get("Resources", {})
        selected = (
            [definitions[logical]]
            if logical in definitions
            else list(definitions.values())
        )
        expressions = [
            {"Condition": item["Condition"]} for item in selected if "Condition" in item
        ]
        if not checked_evidence_parameters(document, parameters, stack, expressions):
            return None, "required deployed parameters unavailable or mismatch"
        try:
            response = backend.aws(
                "get_resource",
                service="cloudcontrol",
                TypeName=catalog.cloudformation_type(resource[RESOURCE_TYPE_KEY]),
                Identifier=physical,
            )
        except AwsError as error:
            return None, "cloudcontrol.get_resource: " + str(error.code)
        if not isinstance(response, dict) or not isinstance(
            response.get("ResourceDescription"), dict
        ):
            return None, "Cloud Control ResourceDescription missing or invalid"
        description = response["ResourceDescription"]
        if description.get("Identifier") != physical:
            return None, "Cloud Control identifier mismatch"
        try:
            payload = properties_json(description.get("Properties"))
        except ValueError:
            return None, "Cloud Control Properties missing or invalid"
        if pointer_value(payload, pointer) != physical:
            return None, "Cloud Control resource identity mismatch"
        value = project(item, payload)
        after = current_state.read(backend.aws, stack_id)
        if current_state.identity(stack) != current_state.identity(after) or stack.get(
            "Outputs", []
        ) != after.get("Outputs", []):
            return None, "stack changed during acquisition"
        return value, None
    except AwsError as error:
        return None, "CloudFormation evidence API: " + str(error.code)
    except (AttributeError, Blocked, Unresolved, KeyError, TypeError, ValueError):
        return None, "Cloud Control response or deployed evidence unavailable"


def codebuild_observation(
    backend, stack, document, parameters, actual, resource, prop, stack_name
):
    item = codebuild_source(backend.root, resource, prop)
    if item is None:
        return None, "unsupported acquisition contract"
    account = backend.target.get(
        AWS_EXECUTION_ACCOUNT_ID_KEY, backend.target[AWS_ACCOUNT_ID_KEY]
    )
    region = backend.target[AWS_REGION_KEY]
    stack_id = stack.get("StackId", "")
    physical = actual.get("PhysicalResourceId")
    logical = actual.get("LogicalResourceId")
    definition = document.get("Resources", {}).get(logical, {})
    if (
        not stack_id.startswith(
            f"arn:aws:cloudformation:{region}:{account}:stack/{stack_name}/"
        )
        or not stack_id.removeprefix(
            f"arn:aws:cloudformation:{region}:{account}:stack/{stack_name}/"
        )
        or definition.get("Type") != "AWS::CodeBuild::Project"
        or actual.get("ResourceType") != "AWS::CodeBuild::Project"
        or not isinstance(physical, str)
        or not physical
        or current_state.category(stack) != "SUCCESS"
        or actual.get("ResourceStatus")
        not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
    ):
        return None, "stack or resource identity unconfirmed"
    try:
        deployed = backend.aws("get_template", StackName=stack_id).get("TemplateBody")
        if isinstance(deployed, str):
            deployed, errors = _imports_cfn_format.decode(deployed)
            if errors:
                return None, "deployed template unavailable"
        if deployed != document or document.get("Transform"):
            return None, "deployed template mismatch"
        expressions = (
            [{"Condition": definition["Condition"]}]
            if "Condition" in definition
            else []
        )
        if not checked_evidence_parameters(document, parameters, stack, expressions):
            return None, "required deployed parameters unavailable or mismatch"
        try:
            response = backend.aws(
                "batch_get_projects", service="codebuild", names=[physical]
            )
        except AwsError as error:
            after = current_state.read(backend.aws, stack_id)
            if current_state.identity(stack) != current_state.identity(
                after
            ) or stack.get("Outputs", []) != after.get("Outputs", []):
                return None, "stack changed during acquisition"
            return None, "codebuild.batch_get_projects: " + str(error.code)
        projects = response.get("projects")
        if (
            not isinstance(projects, list)
            or len(projects) != 1
            or not isinstance(projects[0], dict)
            or response.get("projectsNotFound", []) != []
        ):
            return None, "CodeBuild project missing or response incomplete"
        project_data = projects[0]
        value = project(item, project_data)
        if (
            value != physical
            or project_data.get("arn")
            != f"arn:aws:codebuild:{region}:{account}:project/{physical}"
        ):
            return None, "CodeBuild project identity mismatch"
        after = current_state.read(backend.aws, stack_id)
        if current_state.identity(stack) != current_state.identity(after) or stack.get(
            "Outputs", []
        ) != after.get("Outputs", []):
            return None, "stack changed during acquisition"
        return value, None
    except AwsError as error:
        return None, "evidence API: " + str(error.code)
    except (
        AttributeError,
        Blocked,
        Unresolved,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ):
        return None, "CodeBuild or deployed evidence unavailable"


class PermissionContext:
    def __init__(self, backend):
        self.backend = backend

    def call(self, service, operation, **kwargs):
        return self.backend.aws(operation, service=service, **kwargs)


class PermissionResource:
    kind = "Lambda.Permission"

    def __init__(self, function, expected, physical):
        self.function = function
        self.expected = expected
        self.physical = physical

    def parent(self):
        return self

    def value(self, name, *args):
        return self.function if name == "FunctionName" else self.expected[name]

    def current(self, name):
        return self.physical

    def optional(self, name, default=None, **kwargs):
        return self.expected.get(name, default)


def permission_expression(
    value, backend, actuals, mapped, document, parameters, pseudo, stack
):
    """Resolve GetAtt only from a uniquely mapped, identity-checked provider read."""

    attribute = _bind_framework_callback(
        _permission_attribute,
        backend,
        actuals,
        mapped,
        document,
        parameters,
        pseudo,
        stack,
    )

    if isinstance(value, list):
        return [
            permission_expression(
                item, backend, actuals, mapped, document, parameters, pseudo, stack
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    if set(value) == {"Fn::If"}:
        selected = _imports_cfn_inputs.output_value(document, parameters, pseudo, value)
        return permission_expression(
            selected, backend, actuals, mapped, document, parameters, pseudo, stack
        )
    if set(value) == {"Ref"} and value["Ref"] in mapped:
        logical = value["Ref"]
        resource = mapped[logical][2]
        kind = resource[RESOURCE_TYPE_KEY]
        attr = REF_ATTRIBUTES.get(kind)
        catalog = DesignSchemaCatalog(backend.root)
        primary, _ = identifier_source(
            catalog, resource, set(), logical, kind + "." + str(attr), {}
        )
        matches = [item for item in actuals if item.get("LogicalResourceId") == logical]
        if (
            not primary
            or len(matches) != 1
            or matches[0].get("ResourceType") != catalog.cloudformation_type(kind)
            or matches[0].get("ResourceStatus")
            not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
            or not isinstance(matches[0].get("PhysicalResourceId"), str)
            or not matches[0]["PhysicalResourceId"]
        ):
            raise Blocked("Ref resource identity unsupported")
        return matches[0]["PhysicalResourceId"]
    if set(value) == {"Fn::GetAtt"}:
        ref = value["Fn::GetAtt"]
        ref = ref.split(".", 1) if isinstance(ref, str) else ref
        if (
            not isinstance(ref, list)
            or len(ref) != 2
            or not all(isinstance(part, str) for part in ref)
        ):
            raise Blocked("GetAtt expression invalid")
        return attribute(*ref)
    if set(value) == {"Fn::Sub"}:
        sub = value["Fn::Sub"]
        text, overrides = (sub, {}) if isinstance(sub, str) else sub
        overrides = {
            key: permission_expression(
                item, backend, actuals, mapped, document, parameters, pseudo, stack
            )
            for key, item in overrides.items()
        }
        for logical in re.findall(r"\$\{([A-Za-z0-9]+)\}", text):
            if logical in mapped and logical not in overrides:
                overrides[logical] = permission_expression(
                    {"Ref": logical},
                    backend,
                    actuals,
                    mapped,
                    document,
                    parameters,
                    pseudo,
                    stack,
                )
        for logical, name in re.findall(r"\$\{([A-Za-z0-9]+)\.([A-Za-z0-9]+)\}", text):
            key = logical + "." + name
            if key not in overrides:
                overrides[key] = attribute(logical, name)
        return {"Fn::Sub": [text, overrides]}
    return {
        key: permission_expression(
            item, backend, actuals, mapped, document, parameters, pseudo, stack
        )
        for key, item in value.items()
    }


def permission_observation(
    backend,
    stack,
    document,
    parameters,
    pseudo,
    actuals,
    mapped,
    logical,
    actual,
    resource,
):
    """Confirm one Lambda statement using its explicit parent and CloudFormation identity."""
    stack_id = stack.get("StackId", "")
    account = backend.target.get(
        AWS_EXECUTION_ACCOUNT_ID_KEY, backend.target[AWS_ACCOUNT_ID_KEY]
    )
    region = backend.target[AWS_REGION_KEY]
    if not stack_id.startswith(f"arn:aws:cloudformation:{region}:{account}:stack/"):
        return None, "stack account or region identity mismatch"
    if current_state.category(stack) != "SUCCESS" or actual.get(
        "ResourceStatus"
    ) not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}:
        return None, "stack or resource state unconfirmed"
    try:
        physical = actual["PhysicalResourceId"]
        if not isinstance(physical, str) or not physical:
            return None, "permission physical identifier unavailable"
        deployed = backend.aws("get_template", StackName=stack_id).get("TemplateBody")
        if isinstance(deployed, str):
            deployed, errors = _imports_cfn_format.decode(deployed)
            if errors:
                return None, "deployed template unavailable"
        if deployed != document or document.get("Transform"):
            return None, "deployed template mismatch"
        definition = document["Resources"][logical]
        if not checked_evidence_parameters(
            document, parameters, stack, definition, pseudo
        ):
            return None, "required deployed parameters unavailable or mismatch"
        props = document["Resources"][logical].get("Properties", {})
        pseudo = pseudo | {"AWS::Partition": stack_id.split(":", 2)[1]}
        names = change_sets.import_names(
            {
                "Resources": {logical: definition},
                "Conditions": document.get("Conditions", {}),
            },
            parameters,
            pseudo,
        )
        exports = (
            {
                key: value["Value"]
                for key, value in resolve_exports(backend.aws, names).items()
            }
            if names
            else {}
        )
        if set(props) - {
            "FunctionName",
            "Action",
            "Principal",
            "SourceArn",
            "SourceAccount",
        }:
            return None, "permission attributes not supported"
        parent_reference = parse_reference(resource["parentReference"])
        if parent_reference.attribute != "FunctionName":
            return None, "permission parent reference attribute mismatch"
        parent_id = parent_reference.logical_id
        parents = [
            (name, entry)
            for name, entry in mapped.items()
            if entry[2][RESOURCE_TYPE_KEY] == "Lambda.Function"
            and entry[2]["logicalId"] == parent_id
        ]
        if len(parents) != 1:
            return None, "permission parent identity mismatch"
        parent_logical, parent = parents[0]
        if logical not in mapped or parent[0] != mapped[logical][0]:
            return None, "permission parent Model scope mismatch"
        matching = [
            entry
            for entry in actuals
            if entry.get("LogicalResourceId") == parent_logical
            and entry.get("ResourceType") == "AWS::Lambda::Function"
            and entry.get("ResourceStatus")
            in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
        ]
        if len(matching) != 1:
            return None, "permission parent identity mismatch"
        parent_name = matching[0].get("PhysicalResourceId")
        if (
            not isinstance(parent_name, str)
            or not parent_name
            or parent_name.startswith("arn:")
        ):
            return None, "function name unavailable"
        function = _imports_cfn_inputs.resolve_value(
            permission_expression(
                props["FunctionName"],
                backend,
                actuals,
                mapped,
                document,
                parameters,
                pseudo,
                stack,
            ),
            parameters,
            pseudo | {parent_logical: parent_name},
            exports=exports,
            conditions=document.get("Conditions"),
        )
        if not isinstance(function, str):
            return None, "function name or qualifier mismatch"
        arn_pattern = (
            r"arn:(aws[a-z-]*):lambda:([^:]+):([0-9]{12}):function:([^:]+)(?::([^:]+))?"
        )
        function_arn = re.fullmatch(arn_pattern, function)
        if function_arn:
            partition = stack_id.split(":", 2)[1]
            if function_arn.groups()[:4] != (partition, region, account, parent_name):
                return None, "function ARN identity mismatch"
            qualifier = function_arn.group(5)
        else:
            match = re.fullmatch(
                re.escape(parent_name) + r"(?::([A-Za-z0-9_$-]+))?", function
            )
            if not match:
                return None, "function name or qualifier mismatch"
            qualifier = match.group(1)
        for entry in actuals:
            if (
                entry.get("LogicalResourceId") == logical
                or entry.get("ResourceType") != "AWS::Lambda::Permission"
                or entry.get("PhysicalResourceId") != physical
            ):
                continue
            other = mapped.get(entry.get("LogicalResourceId"))
            if other is None:
                return None, "permission Sid ownership unavailable"
            other_parent = parse_reference(other[2]["parentReference"])
            other_functions = [
                name
                for name, item in mapped.items()
                if item[2].get(RESOURCE_TYPE_KEY) == "Lambda.Function"
                and item[2].get("logicalId") == other_parent.logical_id
                and item[0] == other[0]
            ]
            other_actuals = [
                item
                for item in actuals
                if len(other_functions) == 1
                and item.get("LogicalResourceId") == other_functions[0]
                and item.get("ResourceType") == "AWS::Lambda::Function"
                and item.get("ResourceStatus")
                in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
            ]
            if len(other_actuals) != 1 or not other_actuals[0].get(
                "PhysicalResourceId"
            ):
                return None, "permission Sid ownership unavailable"
            if other_actuals[0]["PhysicalResourceId"] == parent_name:
                return None, "permission Sid is shared by the same function"
        expected = {}
        for key, value in props.items():
            if key == "FunctionName":
                continue
            selected = _imports_cfn_inputs.output_value(
                document, parameters, pseudo, value
            )
            if selected == {"Ref": "AWS::NoValue"}:
                continue
            expected[key] = _imports_cfn_inputs.resolve_value(
                permission_expression(
                    selected,
                    backend,
                    actuals,
                    mapped,
                    document,
                    parameters,
                    pseudo,
                    stack,
                ),
                parameters,
                pseudo,
                exports=exports,
                conditions=document.get("Conditions"),
            )
        if not {"Action", "Principal"} <= expected.keys():
            return None, "permission attributes unavailable"

        statement = service_module("lambda").fetch(
            PermissionContext(backend),
            PermissionResource(function, expected, physical),
            "permission",
        )
        if statement.get("Sid") != physical or any(
            statement.get(key) != expected[key] for key in expected
        ):
            return None, "permission statement attributes or Sid mismatch"
        if any(
            statement.get(key, MISSING) != expected.get(key, MISSING)
            for key in ("SourceArn", "SourceAccount")
        ):
            return None, "permission source condition mismatch"
        condition = statement.get("Condition", {})
        if not isinstance(condition, dict) or set(condition) - {
            "ArnLike",
            "ArnEquals",
            "StringEquals",
        }:
            return None, "permission condition unsupported"
        allowed_conditions = {
            "ArnLike": {"AWS:SourceArn"},
            "ArnEquals": {"AWS:SourceArn"},
            "StringEquals": {"AWS:SourceAccount"},
        }
        if any(
            not isinstance(value, dict) or set(value) - allowed_conditions[key]
            for key, value in condition.items()
        ):
            return None, "permission condition unsupported"
        arn = statement.get("Resource")
        match = re.fullmatch(arn_pattern, arn) if isinstance(arn, str) else None
        if (
            not match
            or match.groups()
            != (stack_id.split(":", 2)[1], region, account, parent_name, qualifier)
            or (function_arn and arn != function)
        ):
            return None, "permission function or qualifier mismatch"
        after = current_state.read(backend.aws, stack_id)
        if current_state.identity(stack) != current_state.identity(after) or stack.get(
            "Outputs", []
        ) != after.get("Outputs", []):
            return None, "stack changed during acquisition"
        return physical, None
    except AwsError as error:
        return None, "permission evidence API: " + str(error)
    except AcquisitionError as error:
        return None, "permission evidence API: " + str(error.api) + ": " + str(
            error.code
        )
    except (Blocked, Unresolved) as error:
        return None, "permission evidence unconfirmed: " + str(error)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None, "permission evidence unavailable or ambiguous"


def readiness(backend, unit, state=None):
    """Check only this Stack's known synchronization inputs; never publish placeholders."""
    name = unit["name"]
    check = "dependency index"
    try:
        dependency_index.load(backend.root)
        document, parameters = backend.templates[name]
        removed = removed_resources([unit], {name: state or {}})
        key = (name, fingerprint([document, parameters, removed, state is not None]))
        checked = getattr(backend, "observed_checks", set())
        if key in checked:
            return
        pseudo = {
            "AWS::StackName": name,
            "AWS::Region": backend.target[AWS_REGION_KEY],
            "AWS::AccountId": backend.target.get(
                AWS_EXECUTION_ACCOUNT_ID_KEY, backend.target[AWS_ACCOUNT_ID_KEY]
            ),
        }
        grouped = {
            DesignSchemaCatalog(backend.root).cloudformation_type(kind)
            for kind, rule in _imports_design_layout.GROUPED.items()
            if rule["identityProperty"] is None
        }
        check = "CloudFormation resource selection"
        selected = selected_resources(
            document, parameters, pseudo, removed[name], grouped
        )
        check = "Model resource mapping"
        loaded, mapped = resolve_resources(
            backend.root,
            backend.environment,
            backend.directory,
            backend.templates,
            [unit],
            {name: selected},
            removed,
            target=backend.target,
            check_scope=False,
        )
        check = "fixed resource scope"
        execution_scope.check_fixed_resources(
            backend.root,
            mapped,
            keys={(name, logical) for logical in document.get("Resources", {})},
        )
        check = "owner Validation scope"
        scope = active_scope(backend.root)
        missing = [
            {
                "logicalId": logical,
                "service": path.stem,
                "resource": resource["logicalId"],
            }
            for logical, (path, _identity, resource, _rows, _outputs) in mapped[
                name
            ].items()
            if scope is not None
            and (backend.environment, backend.directory, path.stem) not in scope
        ]
        if missing:
            error = Blocked(f"{name}: owning services are outside Validation scope")
            error.deploy_failure = {
                "stage": "PREPARATION",
                "classification": "OWNER_SCOPE_MISSING",
                "executionState": "NOT_SUBMITTED",
                "owners": sorted(missing, key=lambda item: item["logicalId"]),
            }
            raise error
        check = "Observed reference propagation"
        changes, identifiers = {}, {}
        for path, _identity, resource, rows, outputs in (
            mapped[name].values() if state is not None else ()
        ):
            for rid, row in rows:
                if row["property"] in outputs:
                    changes.setdefault(path, {})[f"observed.row.{rid}.value"] = (
                        "`PENDING_DEPLOY`"
                    )
                    identifiers[own_key(path, resource)] = MODEL_PENDING_DEPLOY
        if changes:
            deferred = []
            propagate_references(
                backend.root,
                loaded,
                changes,
                identifiers,
                allowed_services=active_scope(backend.root)
                if task_snapshot(backend.root, required=False) is not None
                else None,
                deferred=deferred,
                reference_consumers=deferred_work.approved(
                    getattr(backend, "run_context", {})
                ),
            )
            if state is not None and deferred:
                deferred_work.remember({unit["name"]: state}, deferred, loaded)
            observed_destinations(
                backend.root, backend.environment, backend.directory, loaded, changes
            )
        checked.add(key)
        backend.observed_checks = checked
    except (OSError, ValueError, Blocked) as error:
        wrapped = Blocked(f"{name}: Observed readiness: {error}")
        if hasattr(error, "deploy_failure"):
            wrapped.deploy_failure = error.deploy_failure
        else:
            wrapped.deploy_failure = {}
        wrapped.deploy_failure.setdefault("stage", "PREPARATION")
        wrapped.deploy_failure.setdefault("classification", "INPUT_CANDIDATE")
        wrapped.deploy_failure.setdefault("code", "OBSERVED_READINESS")
        wrapped.deploy_failure.setdefault("executionState", "NOT_EXECUTED")
        reason = str(error)
        detail = (
            "the dependency index is missing"
            if "dependency index missing" in reason
            else "the dependency index seal is invalid"
            if "sealed evidence" in reason or "evidence was modified" in reason
            else "the dependency index is invalid"
            if "invalid Model dependency index" in reason
            else "the dependency index does not match the Model"
            if "dependency index differs" in reason
            else "more than one Model Resource claims the same CloudFormation Resource"
            if "duplicate ownership" in reason
            else "the Model and CloudFormation Resource types do not match"
            if "type mismatch" in reason
            else "the Model Resource mapping is ambiguous or missing"
            if "AMBIGUOUS_OBSERVED_MAPPING" in reason
            else "the Task scope does not permit the required observation"
            if "task scope violation" in reason
            else f"{check} could not be validated"
        )
        wrapped.deploy_failure.setdefault(
            "message", f"{name}: Observed readiness: {detail}."
        )
        wrapped.deploy_failure.setdefault(
            "requiredAction", f"Review {check} for this Stack before deployment."
        )
        if "dependency index missing" in reason:
            wrapped.deploy_failure["message"] += (
                " Run python framework/scripts/model/cli.py index --repository-root <repository-root>."
            )
            wrapped.deploy_failure["requiredAction"] = (
                "Build the Model dependency index for the current repository, then retry."
            )
        document = backend.templates.get(name, ({}, {}))[0]
        resources = [
            logical
            for logical in document.get("Resources", {})
            if isinstance(logical, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", logical)
            and re.search(
                r"(?<![A-Za-z0-9])" + re.escape(logical) + r"(?![A-Za-z0-9])", reason
            )
        ]
        if resources:
            wrapped.deploy_failure.setdefault("resources", sorted(resources))
        wrapped.deploy_failure.setdefault("retryable", False)
        raise wrapped from error


def complete_stack_observation(stack, actuals):
    outputs = stack.get("Outputs", [])
    if not isinstance(outputs, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("OutputKey"), str)
        or not item["OutputKey"]
        or not isinstance(item.get("OutputValue"), str)
        for item in outputs
    ):
        return False
    if len({item["OutputKey"] for item in outputs}) != len(outputs):
        return False
    return all(
        isinstance(item, dict)
        and all(
            isinstance(item.get(key), str) and item[key]
            for key in ("LogicalResourceId", "ResourceType", "ResourceStatus")
        )
        for item in actuals
    )


def collect_successful(backend, units, states, *, generated_views=None):
    """Resolve exact candidates from fresh successful Stack reads without writing."""
    GROUPED = _imports_design_layout.GROUPED
    root, environment, directory = backend.root, backend.environment, backend.directory
    removed = removed_resources(units, states)
    selected = {}
    grouped = {
        DesignSchemaCatalog(root).cloudformation_type(kind)
        for kind, rule in GROUPED.items()
        if rule["identityProperty"] is None
    }
    for unit in units:
        name = unit["name"]
        if name not in backend.templates:
            backend.load_inputs(unit)
        document, parameters = backend.templates[name]
        pseudo = {
            "AWS::StackName": name,
            "AWS::Region": backend.target[AWS_REGION_KEY],
            "AWS::AccountId": backend.target.get(
                AWS_EXECUTION_ACCOUNT_ID_KEY, backend.target[AWS_ACCOUNT_ID_KEY]
            ),
        }
        selected[name] = selected_resources(
            document, parameters, pseudo, removed[name], grouped
        )
    loaded, mapped = resolve_resources(
        root,
        environment,
        directory,
        backend.templates,
        units,
        selected,
        removed,
        target=backend.target,
    )
    execution_scope.check_fixed_resources(
        root,
        mapped,
        keys={
            (unit["name"], logical)
            for unit in units
            for logical in backend.templates[unit["name"]][0].get("Resources", {})
        },
    )
    catalog = DesignSchemaCatalog(root) if loaded else None
    for unit in units:
        states[unit["name"]]["observedServices"] = sorted(
            {entry[0].stem for entry in mapped[unit["name"]].values()}
        )
    changes, identifiers = {}, {}
    for unit in units:
        name = unit["name"]
        state = states[name]
        stack = current_state.read(backend.aws, name)
        actuals, complete = [], False
        if current_state.category(stack) not in {"ABSENT", "UNKNOWN"}:
            try:
                actuals = current_state.pages(
                    backend.aws,
                    "list_stack_resources",
                    "StackResourceSummaries",
                    StackName=stack["StackId"],
                )
                after = current_state.read(backend.aws, name)
                complete = current_state.identity(stack) == current_state.identity(
                    after
                )
                if complete and not complete_stack_observation(stack, actuals):
                    complete = False
                    stack = {
                        **stack,
                        "reason": "INCOMPLETE_RESOURCE_OR_OUTPUT_RESPONSE",
                    }
                    actuals = []
                elif not complete:
                    stack = after
                    actuals = []
            except (AwsError, OSError, Blocked):
                stack = {**stack, "reason": "RESOURCE_READ_FAILED"}
        state["currentStack"] = current_state.observation(stack)
        state["stackId"], state["stackStatus"] = (
            stack.get("StackId"),
            stack["StackStatus"],
        )
        outputs = (
            {
                item["OutputKey"]: item["OutputValue"]
                for item in stack.get("Outputs", [])
            }
            if complete
            else {}
        )
        by_logical = {}
        for actual in actuals:
            logical = actual["LogicalResourceId"]
            if logical in by_logical:
                ambiguous(f"{name}/{logical}: duplicate actual resource")
            by_logical[logical] = actual
        document, parameters = backend.templates[name]
        pseudo = {
            "AWS::StackName": name,
            "AWS::AccountId": backend.target.get(
                AWS_EXECUTION_ACCOUNT_ID_KEY, backend.target[AWS_ACCOUNT_ID_KEY]
            ),
            "AWS::Region": backend.target[AWS_REGION_KEY],
        }
        coverage = {}
        state["observedCoverage"] = coverage
        for logical, (path, _identity, resource, rows, selected_outputs) in mapped[
            name
        ].items():
            actual = by_logical.get(logical)
            if actual and actual.get("ResourceType") != document.get(
                "Resources", {}
            ).get(logical, removed.get(name, {}).get(logical, {})).get("Type"):
                actual = None
                stack["reason"] = "RESOURCE_TYPE_UNCONFIRMED"
            if not selected_outputs:
                coverage[logical] = {"status": "NO_IDENTIFIER"}
                continue
            unknown, updated, absent = False, False, False
            reasons = {}
            if logical in removed.get(name, {}) and complete:
                try:
                    absent = deleted_resource(
                        backend,
                        name,
                        logical,
                        removed[name][logical],
                        state,
                        by_logical,
                    )
                except Blocked:
                    absent = False
            if (
                logical in removed.get(name, {})
                and not absent
                and (
                    not actual
                    or actual.get("ResourceStatus")
                    in {"DELETE_COMPLETE", "DELETE_SKIPPED"}
                )
            ):
                coverage[logical] = {"status": "UNCONFIRMED"}
                continue
            for rid, row in rows:
                prop = row["property"]
                if prop not in selected_outputs:
                    continue
                value = None
                if absent:
                    value = MODEL_PENDING_DEPLOY
                elif (
                    actual
                    and isinstance(actual.get("ResourceStatus"), str)
                    and actual["ResourceStatus"]
                    and actual["ResourceStatus"]
                    not in {
                        "DELETE_COMPLETE",
                        "DELETE_SKIPPED",
                    }
                ):
                    primary, keys = identifier_source(
                        catalog,
                        resource,
                        selected_outputs,
                        logical,
                        prop,
                        active_outputs(document, parameters, pseudo),
                    )
                    values = [outputs[key] for key in keys if key in outputs]
                    candidate = actual.get("PhysicalResourceId")
                    physical = (
                        candidate
                        if primary
                        or (
                            isinstance(candidate, str)
                            and physical_identifier_source(resource, prop, candidate)
                        )
                        else None
                    )
                    if resource[RESOURCE_TYPE_KEY] in {
                        "EC2.SecurityGroupIngress",
                        "EC2.SecurityGroupEgress",
                    }:
                        declarations = active_outputs(document, parameters, pseudo)
                        id_keys = [
                            key for key in keys if declarations[key] != {"Ref": logical}
                        ]
                        if (
                            complete
                            and id_keys
                            and all(key in outputs for key in id_keys)
                        ):
                            ids = {outputs[key] for key in id_keys}
                            if len(ids) == 1:
                                value = security_group_rule_id(
                                    backend,
                                    stack,
                                    document,
                                    parameters,
                                    pseudo,
                                    actuals,
                                    logical,
                                    actual,
                                    ids.pop(),
                                )
                    elif values and (
                        len(set(values)) != 1
                        or physical is not None
                        and physical != values[0]
                    ):
                        # A moving/partial Stack cannot confirm mutually inconsistent reads.
                        value = None
                    elif values and len(values) == len(keys):
                        value = values[0]
                    else:
                        value = physical
                    source = cloudcontrol_source(backend.root, catalog, resource, prop)
                    if source is not None and (not primary or bool(keys)):
                        api_value, reason = cloudcontrol_observation(
                            backend,
                            stack,
                            document,
                            parameters,
                            actual,
                            resource,
                            prop,
                            catalog,
                        )
                        if reason:
                            unavailable = reason.startswith(
                                (
                                    "cloudcontrol.get_resource: ",
                                    "CloudFormation evidence API: ",
                                )
                            ) and any(
                                word in reason.lower()
                                for word in (
                                    "accessdenied",
                                    "unauthorized",
                                    "timeout",
                                    "timedout",
                                    "deadlineexceeded",
                                )
                            )
                            if not (
                                unavailable
                                and values
                                and len(values) == len(keys)
                                and value is not None
                            ):
                                value = None
                                reasons[prop] = reason
                        elif (
                            values
                            and (
                                len(values) != len(keys)
                                or any(candidate != api_value for candidate in values)
                            )
                        ) or (physical is not None and physical != api_value):
                            value = None
                            reasons[prop] = (
                                "Output or physical identifier disagrees with Cloud Control"
                            )
                        else:
                            value = api_value
                    elif (
                        resource[RESOURCE_TYPE_KEY] == "CodeBuild.Project"
                        and prop == "CodeBuild.Project.Id"
                    ):
                        api_value, reason = codebuild_observation(
                            backend,
                            stack,
                            document,
                            parameters,
                            actual,
                            resource,
                            prop,
                            name,
                        )
                        if reason:
                            unavailable = reason.startswith(
                                "codebuild.batch_get_projects: "
                            ) and any(
                                word in reason.lower()
                                for word in (
                                    "accessdenied",
                                    "unauthorized",
                                    "timeout",
                                    "timedout",
                                    "deadlineexceeded",
                                )
                            )
                            if not (
                                unavailable
                                and values
                                and len(values) == len(keys)
                                and value is not None
                                and value == actual.get("PhysicalResourceId")
                            ):
                                value = None
                                reasons[prop] = reason
                        elif values and (
                            len(values) != len(keys)
                            or any(candidate != api_value for candidate in values)
                        ):
                            value = None
                            reasons[prop] = "Output disagrees with CodeBuild"
                        else:
                            value = api_value
                    elif permission_source(backend.root, resource, prop):
                        api_value, reason = permission_observation(
                            backend,
                            stack,
                            document,
                            parameters,
                            pseudo,
                            actuals,
                            mapped[name],
                            logical,
                            actual,
                            resource,
                        )
                        if reason:
                            value = None
                            reasons[prop] = reason
                        elif values and (
                            len(values) != len(keys)
                            or any(candidate != api_value for candidate in values)
                        ):
                            value = None
                            reasons[prop] = "Output disagrees with Lambda policy"
                        else:
                            value = api_value
                    elif value is None:
                        reasons[prop] = (
                            "no verified Output, physical identifier, or supported API getter"
                        )
                    if (
                        not isinstance(value, str)
                        or not value
                        or value in {MODEL_PENDING_DEPLOY, "UNKNOWN"}
                        or re.search(r"\barn:aws[a-z-]*:", value, re.I)
                        or any(c in value for c in "\r\n`")
                    ):
                        value = None
                        reasons.setdefault(
                            prop, "acquired value is missing, invalid, or prohibited"
                        )
                if value is None:
                    reasons.setdefault(
                        prop,
                        stack.get("reason", "resource identity or state unconfirmed"),
                    )
                key = f"observed.row.{rid}.value"
                raw = f"`{value}`" if value is not None else None
                changed = loaded[path].get(key) != raw or (key in loaded[path]) != (
                    raw is not None
                )
                updated |= changed
                unknown |= value is None
                changes.setdefault(path, {})[key] = raw
                identifiers[own_key(path, resource)] = value
            coverage[logical] = {
                **({"reasons": reasons} if reasons else {}),
                "status": "UNCONFIRMED"
                if unknown
                else "UPDATED"
                if updated
                else "MATCHED",
            }
        for logical in document.get("Resources", {}) | removed.get(name, {}):
            if logical not in coverage:
                if logical in selected[name] and not static_export_handle(
                    document, logical, parameters, pseudo
                ):
                    ambiguous(f"{name}/{logical}: selected resource was not mapped")
                coverage[logical] = {
                    "status": "EXCLUDED",
                    "reason": "Condition inactive or static/retained scaffold",
                }
        state["currentStack"] = current_state.observation(stack)
    if not changes:
        changes = {
            entry[0]: {} for mapping in mapped.values() for entry in mapping.values()
        }
        if not changes:
            return {}, [], None
    deleted_identifiers = {
        key for key, value in identifiers.items() if value == MODEL_PENDING_DEPLOY
    }
    deferred = []
    propagate_references(
        root,
        loaded,
        changes,
        identifiers,
        reset_references=deleted_identifiers,
        allowed_services=active_scope(root)
        if task_snapshot(root, required=False) is not None
        else None,
        deferred=deferred,
        reference_consumers=deferred_work.approved(getattr(backend, "run_context", {})),
    )
    deferred_work.remember(states, deferred, loaded)
    destinations, views, sync = observed_destinations(
        root, environment, directory, loaded, changes
    )
    if generated_views is not None:
        generated_views.update(views)
    return destinations, sorted({path.stem for path in changes}), sync


def sync_successful(backend, units, states):
    """Confirm the Model barrier; generated views have their own durable queue."""
    if backend.run_context.get("pendingObserved"):
        names = list(backend.run_context["pendingObserved"]["evidence"])
        destinations = _dependency_deploy_observed_resume.finish(backend, units)
    else:
        views = set()
        destinations, services, _ = collect_successful(
            backend, units, states, generated_views=views
        )
        names = [unit["name"] for unit in units]
        if destinations or views:
            _dependency_deploy_observed_resume.prepare(
                backend, units, destinations, services, views
            )
            destinations = _dependency_deploy_observed_resume.finish(backend, units)
    for name in names:
        states[name]["observedSynced"] = True
    return destinations or None


def deleted_resource(runtime, name, logical, removal, state, actuals):
    """A Remove is intent. Only execution-bound physical destruction resets an identifier."""
    if not removal_candidate(name, logical, removal):
        return False
    evidence = state.get("executionEvidence", {})
    if any(
        evidence.get(key) != state.get(field)
        for key, field in (
            ("StackId", "stackId"),
            ("ChangeSetId", "changeSetId"),
            ("changeDigest", "changeDigest"),
            ("clientToken", "clientToken"),
        )
    ):
        ambiguous(f"{name}/{logical}: original execution evidence missing or changed")
    if not evidence or not removal.get("PhysicalResourceId"):
        ambiguous(f"{name}/{logical}: physical deletion identity unknown")
    actual = actuals.get(logical)
    if actual and actual.get("ResourceStatus") == "DELETE_SKIPPED":
        return False
    if (
        actual
        and actual.get("ResourceStatus") == "DELETE_COMPLETE"
        and all(
            actual.get(key) == removal.get(key if key != "ResourceType" else "Type")
            for key in ("PhysicalResourceId", "ResourceType")
        )
    ):
        return True
    events = runtime.aws("describe_stack_events", StackName=evidence["StackId"])[
        "StackEvents"
    ]
    matched = [
        event
        for event in events
        if event.get("LogicalResourceId") == logical
        and event.get("ResourceType") == removal["Type"]
        and event.get("PhysicalResourceId") == removal["PhysicalResourceId"]
        and event.get("ClientRequestToken") == evidence["clientToken"]
        and event.get("StackId") == evidence["StackId"]
    ]
    if any(event.get("ResourceStatus") == "DELETE_SKIPPED" for event in matched):
        return False
    if not any(event.get("ResourceStatus") == "DELETE_COMPLETE" for event in matched):
        ambiguous(f"{name}/{logical}: physical destruction is unconfirmed")
    return True
