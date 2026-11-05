"""Post-success synchronization and execution-bound deletion evidence."""

import re

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
from model.adapters.observation_sources import cloudcontrol_source, permission_source
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
from utils.cloudformation.inputs import Blocked as Blocked
from utils.json_format import fingerprint
from validation_scope import active_scope

import deploy.observed_resume as _dependency_deploy_observed_resume
from deploy import current_state
from deploy import deferred as deferred_work
from deploy import scope as execution_scope
from model import dependency_index


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
        actual_parameters = stack.get("Parameters", [])
        if not isinstance(actual_parameters, list) or any(
            not isinstance(item, dict) or item.get("ParameterValue") in (None, "****")
            for item in actual_parameters
        ):
            return None
        actual_parameters = [
            {
                "ParameterKey": item["ParameterKey"],
                "ParameterValue": item["ParameterValue"],
            }
            for item in actual_parameters
        ]
        if len({item["ParameterKey"] for item in actual_parameters}) != len(
            actual_parameters
        ):
            return None
        checked = _imports_cfn_inputs.checked_parameters
        if checked(document, actual_parameters) != checked(
            document,
            [
                {"ParameterKey": key, "ParameterValue": value}
                for key, value in parameters.items()
            ],
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
        actual_parameters = stack.get("Parameters", [])
        checked = _imports_cfn_inputs.checked_parameters
        if (
            not isinstance(actual_parameters, list)
            or any(
                not isinstance(item, dict)
                or item.get("ParameterValue") in (None, "****")
                for item in actual_parameters
            )
            or len({item.get("ParameterKey") for item in actual_parameters})
            != len(actual_parameters)
        ):
            return None, "deployed parameters unavailable or mismatch"
        actual_parameters = [
            {
                "ParameterKey": item["ParameterKey"],
                "ParameterValue": item["ParameterValue"],
            }
            for item in actual_parameters
        ]
        if checked(document, actual_parameters) != checked(
            document,
            [
                {"ParameterKey": key, "ParameterValue": value}
                for key, value in parameters.items()
            ],
        ):
            return None, "deployed parameters unavailable or mismatch"
        response = backend.aws(
            "get_resource",
            service="cloudcontrol",
            TypeName=catalog.cloudformation_type(resource[RESOURCE_TYPE_KEY]),
            Identifier=physical,
        )
        description = response["ResourceDescription"]
        if description.get("Identifier") != physical:
            return None, "Cloud Control identifier mismatch"
        payload = properties_json(description["Properties"])
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
        return None, "cloudcontrol.get_resource: " + str(error.code)
    except (Blocked, Unresolved, KeyError, TypeError, ValueError):
        return None, "Cloud Control response or deployed evidence unavailable"


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

    def optional(self, name, **kwargs):
        return self.expected.get(name)


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
        stack_parameters = stack.get("Parameters", [])
        if (
            not isinstance(stack_parameters, list)
            or any(
                not isinstance(item, dict)
                or item.get("ParameterValue") in (None, "****")
                for item in stack_parameters
            )
            or len({item.get("ParameterKey") for item in stack_parameters})
            != len(stack_parameters)
        ):
            return None, "deployed parameters unavailable"
        checked = _imports_cfn_inputs.checked_parameters
        if checked(
            document,
            [
                {
                    "ParameterKey": x["ParameterKey"],
                    "ParameterValue": x["ParameterValue"],
                }
                for x in stack_parameters
            ],
        ) != checked(
            document,
            [{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
        ):
            return None, "deployed parameters mismatch"
        props = document["Resources"][logical].get("Properties", {})
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
            props["FunctionName"],
            parameters,
            pseudo | {parent_logical: parent_name},
            conditions=document.get("Conditions"),
        )
        if not isinstance(function, str) or not re.fullmatch(
            re.escape(parent_name) + r"(?::[A-Za-z0-9_$-]+)?", function
        ):
            return None, "function name or qualifier mismatch"
        if any(
            entry.get("LogicalResourceId") != logical
            and entry.get("ResourceType") == "AWS::Lambda::Permission"
            and entry.get("PhysicalResourceId") == physical
            for entry in actuals
        ):
            return None, "permission Sid is shared by multiple Stack resources"
        expected = {
            key: _imports_cfn_inputs.resolve_value(
                value, parameters, pseudo, conditions=document.get("Conditions")
            )
            for key, value in props.items()
            if key != "FunctionName"
        }
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
        expected_arn = f"arn:aws:lambda:{region}:{account}:function:{function}"
        if arn != expected_arn:
            return None, "permission function or qualifier mismatch"
        after = current_state.read(backend.aws, stack_id)
        if current_state.identity(stack) != current_state.identity(after) or stack.get(
            "Outputs", []
        ) != after.get("Outputs", []):
            return None, "stack changed during acquisition"
        return physical, None
    except (AwsError, AcquisitionError) as error:
        return None, "lambda.get_policy: " + str(error.code)
    except (Blocked, Unresolved, KeyError, TypeError, ValueError):
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
                if not complete:
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
                    physical = actual.get("PhysicalResourceId") if primary else None
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
