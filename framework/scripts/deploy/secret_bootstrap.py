"""Proven CREATE Secret initialization with metadata-only reads and stable intent/token."""

import json
import re
import uuid
from functools import partial as _bind_framework_callback

import model.adapters.observed as _imports_model_adapters_observed
import utils.cloudformation.format as _imports_cfn_format
from task_contract_core import task_snapshot
from utils.cloudformation.export_resolution import (
    describe_exports,
    merge_hints,
    resolve_exports,
)
from utils.cloudformation.inputs import (
    Blocked,
    condition_active,
    output_value,
    resolve_value,
)
from validation_scope import active_scope as validation_scope

from deploy.change_sets import import_names
from deploy.guards import secret_value_missing
from deploy.scheduler import SUCCESS

_CALLBACK_DEFAULT = object()


BOOTSTRAP_STAGES = {
    "BOOTSTRAP_INTENT",
    "VALUE_CHECKED_MISSING",
    "PUT_SUBMITTED",
    "BOOTSTRAP_CONFIRMED",
}


def _callback_bootstrap_plan_visit_70(
    document,
    exports,
    local_secrets,
    parameters,
    pseudo,
    references,
    scalar_slots,
    _default_path,
    _default_used_exports,
    /,
    value,
    logical,
    kind,
    path=_CALLBACK_DEFAULT,
    used_exports=_CALLBACK_DEFAULT,
):
    if path is _CALLBACK_DEFAULT:
        path = _default_path
    if used_exports is _CALLBACK_DEFAULT:
        used_exports = _default_used_exports
    value = output_value(document, parameters, pseudo, value)
    if (
        isinstance(value, dict)
        and len(value) == 1
        and next(iter(value))
        in {"Ref", "Fn::Sub", "Fn::Join", "Fn::ImportValue", "Fn::GetAtt"}
    ):
        marked = "resolve:secretsmanager:" in json.dumps(value)
        used_exports |= import_names(
            {
                "Conditions": document.get("Conditions", {}),
                "Resources": {"Value": {"Properties": value}},
            },
            parameters,
            pseudo,
        )
        try:
            if "Fn::GetAtt" in value:
                argument = value["Fn::GetAtt"]
                logical_id, attribute = (
                    argument.split(".", 1) if isinstance(argument, str) else argument
                )
                if attribute != "Id" or logical_id not in local_secrets:
                    raise Blocked("unsupported Secret attribute")
                value = pseudo[logical_id]
            else:
                value = resolve_value(
                    value, parameters, pseudo, exports, document.get("Conditions", {})
                )
        except Blocked:
            if marked:
                raise Blocked(
                    "consumer Secret expression cannot be uniquely resolved"
                ) from None
            return
    if isinstance(value, dict):
        for key, child in value.items():
            _callback_bootstrap_plan_visit_70(
                document,
                exports,
                local_secrets,
                parameters,
                pseudo,
                references,
                scalar_slots,
                _default_path,
                _default_used_exports,
                child,
                logical,
                kind,
                path + (key,),
                used_exports,
            )
    elif isinstance(value, list):
        for child in value:
            _callback_bootstrap_plan_visit_70(
                document,
                exports,
                local_secrets,
                parameters,
                pseudo,
                references,
                scalar_slots,
                _default_path,
                _default_used_exports,
                child,
                logical,
                kind,
                path + ("[]",),
                used_exports,
            )
    elif isinstance(value, str) and "resolve:secretsmanager:" in value:
        match = re.fullmatch(
            r"\{\{resolve:secretsmanager:(.+?):SecretString(?::([^:]*))?(?::([^:]*))?(?::([^:]*))?\}\}",
            value,
        )
        if (
            not match
            or match[3] not in (None, "", "AWSCURRENT")
            or match[4] not in (None, "")
            or path not in scalar_slots.get(kind, set())
        ):
            raise Blocked(
                "consumer Secret schema/version selector unsupported or ambiguous"
            )
        references.append((logical, match[1], match[2] or "", used_exports))


def bootstrap_plan(
    root,
    environment,
    directory,
    target,
    templates,
    states,
    mapping_units,
    aws,
    check_secret_arn,
    unit,
    state,
):
    """Resolve consumer references and CREATE ownership through existing mappings."""
    resolve_resources = _imports_model_adapters_observed.resolve_resources
    scope = validation_scope(root)
    document, parameters = templates[unit["name"]]
    pseudo = {
        "AWS::AccountId": target.get("awsExecutionAccountId", target["awsAccountId"]),
        "AWS::Region": target["awsRegion"],
        "AWS::StackName": unit["name"],
    }
    failed = [
        event
        for event in state.get("failureEvents", [])
        if event.get("ResourceType") != "AWS::CloudFormation::Stack"
        and event.get("ResourceStatus", "").endswith("_FAILED")
        and "cancel" not in (event.get("ResourceStatusReason") or "").lower()
    ]
    if not failed or not all(
        secret_value_missing(e.get("ResourceStatusReason")) for e in failed
    ):
        raise Blocked(
            "runtime bootstrap requires only confirmed missing-current-value failures"
        )
    _, owned = resolve_resources(
        root,
        environment,
        directory,
        templates,
        [unit],
        {unit["name"]: {e["LogicalResourceId"] for e in failed}},
        target=target,
        identifiers=False,
    )
    for event in failed:
        logical = event["LogicalResourceId"]
        mapping = owned.get(unit["name"], {}).get(logical)
        definition = document.get("Resources", {}).get(logical, {})
        if (
            not mapping
            or definition.get("Type") != event["ResourceType"]
            or not scope
            or (environment, directory, mapping[0].stem) not in scope
            or mapping[2].get("resourceMode", "CREATE") != "CREATE"
        ):
            raise Blocked("consumer resource ownership/scope unknown")
    names = import_names(document, parameters, pseudo)
    boundary = {}
    for owner_state in states.values():
        if owner_state.get("stackId") and any(
            record.get("export") in names
            for record in owner_state.get("expectedOutputs", {}).values()
        ):
            describe_exports(aws, owner_state["stackId"], boundary)
    resolved = resolve_exports(
        aws,
        names,
        boundary=boundary,
        hints=merge_hints(
            value.get("delivery", {}).get("imports", {}) for value in states.values()
        ),
    )
    entries = list(resolved.values())
    exports = {name: entry["Value"] for name, entry in resolved.items()}
    local_secrets = {
        logical
        for logical, definition in document.get("Resources", {}).items()
        if definition["Type"] == "AWS::SecretsManager::Secret"
        and condition_active(document, parameters, pseudo, definition)
    }
    if local_secrets:
        actuals = aws("list_stack_resources", StackName=state["stackId"])[
            "StackResourceSummaries"
        ]
        for logical in local_secrets:
            matches = [
                r
                for r in actuals
                if r.get("LogicalResourceId") == logical
                and r.get("ResourceType") == "AWS::SecretsManager::Secret"
            ]
            if len(matches) != 1 or not matches[0].get("PhysicalResourceId"):
                raise Blocked("local Secret Ref ownership unknown")
            pseudo[logical] = pseudo[logical + ".Id"] = matches[0]["PhysicalResourceId"]

    references = []
    # These slots consume scalar credentials. Opaque JSON/rotation/application schemas are Human-only.
    scalar_slots = {
        "AWS::QuickSight::DataSource": {
            ("Credentials", "CredentialPair", "Username"),
            ("Credentials", "CredentialPair", "Password"),
        },
        "AWS::RDS::DBInstance": {("MasterUserPassword",)},
        "AWS::RDS::DBCluster": {("MasterUserPassword",)},
        "AWS::Glue::Connection": {
            ("ConnectionInput", "ConnectionProperties", "USERNAME"),
            ("ConnectionInput", "ConnectionProperties", "PASSWORD"),
        },
    }

    visit = _bind_framework_callback(
        _callback_bootstrap_plan_visit_70,
        document,
        exports,
        local_secrets,
        parameters,
        pseudo,
        references,
        scalar_slots,
        (),
        frozenset(),
    )
    for logical in {event["LogicalResourceId"] for event in failed}:
        definition = document["Resources"][logical]
        if condition_active(document, parameters, pseudo, definition):
            visit(definition.get("Properties", {}), logical, definition["Type"])
    affected = {e["LogicalResourceId"] for e in failed}
    identifiers = {r[1] for r in references if r[0] in affected}
    if len(identifiers) != 1:
        raise Blocked("failed consumer Secret reference missing/ambiguous")
    identifier = identifiers.pop()
    if identifier.startswith("arn:"):
        check_secret_arn(identifier)
    metadata = aws("describe_secret", SecretId=identifier, service="secretsmanager")
    arn = metadata.get("ARN")
    check_secret_arn(arn)
    if identifier not in {arn, metadata.get("Name")}:
        raise Blocked("consumer Secret identifier does not match canonical identity")
    owners = []
    units = {u["name"]: u for u in mapping_units}
    for name, candidate_unit in units.items():
        owner_state = states.get(name, {})
        if owner_state.get("status") != "SUCCESS" and not (
            name == unit["name"]
            and owner_state.get("stackStatus") == "UPDATE_ROLLBACK_COMPLETE"
        ):
            continue
        local, params = templates[name]
        candidates = {
            logical
            for logical, definition in local.get("Resources", {}).items()
            if definition.get("Type") == "AWS::SecretsManager::Secret"
        }
        if not candidates:
            continue
        summaries = aws("list_stack_resources", StackName=name)[
            "StackResourceSummaries"
        ]
        if len({r["LogicalResourceId"] for r in summaries}) != len(summaries):
            raise Blocked("Secret stack resource mapping ambiguous")
        matching = {
            r["LogicalResourceId"]
            for r in summaries
            if r.get("LogicalResourceId") in candidates
            and r.get("PhysicalResourceId") == arn
            and r.get("ResourceType") == "AWS::SecretsManager::Secret"
            and r.get("ResourceStatus") in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}
        }
        if matching:
            _, resolved = resolve_resources(
                root,
                environment,
                directory,
                templates,
                [candidate_unit],
                {name: matching},
                target=target,
                identifiers=False,
            )
            owners.extend(
                (name, logical, resolved[name][logical]) for logical in matching
            )
    if len(owners) != 1:
        raise Blocked("Secret CREATE owner is unknown/external/ambiguous")
    name, logical, mapping = owners[0]
    source, identity, resource = mapping[:3]
    if (
        resource.get("resourceMode", "CREATE") != "CREATE"
        or resource.get("cfn-logicalId") != name + "-" + logical
        or (environment, directory, source.stem) not in scope
        or name not in units
    ):
        raise Blocked("Secret is IMPORT or outside CREATE deployment ownership/scope")
    current = boundary.get("exportStacks", {}).get(name)
    if current is None:
        current = aws("describe_stacks", StackName=name)["Stacks"][0]
    stack_id = current.get("StackId")
    if (
        stack_id != states[name].get("stackId")
        or not isinstance(stack_id, str)
        or stack_id.split(":", 5)[2:5]
        != ["cloudformation", target["awsRegion"], pseudo["AWS::AccountId"]]
        or current.get("ParentId")
        or current.get("RootId")
        or current.get("StackStatus") not in SUCCESS | {"UPDATE_ROLLBACK_COMPLETE"}
    ):
        raise Blocked("Secret owner StackId/account/region/state unconfirmed")
    actual = aws("get_template", StackName=stack_id)["TemplateBody"]
    if isinstance(actual, str):
        decode_str = _imports_cfn_format.decode
        actual, errors = decode_str(actual)
        if errors:
            raise Blocked("Secret owner template unreadable")
    if not isinstance(actual, dict) or actual.get("Transform"):
        raise Blocked("Secret owner template dynamically generated/unknown")
    local, params = templates[name]
    actual_params = {
        key: str(value["Default"])
        for key, value in actual.get("Parameters", {}).items()
        if "Default" in value
    }
    actual_params.update(
        {p["ParameterKey"]: p["ParameterValue"] for p in current.get("Parameters", [])}
    )
    owner_pseudo = pseudo | {"AWS::StackName": name}
    for template, inputs in ((local, params), (actual, actual_params)):
        definition = template.get("Resources", {}).get(logical, {})
        if (
            definition.get("Type") != "AWS::SecretsManager::Secret"
            or not condition_active(template, inputs, owner_pseudo, definition)
            or any(
                k in definition.get("Properties", {})
                for k in ("SecretString", "SecretBinary", "GenerateSecretString")
            )
        ):
            raise Blocked(
                "Secret bootstrap differs from CREATE template ownership/initial-value design"
            )
        expected_name = definition.get("Properties", {}).get("Name")
        if expected_name is not None and resolve_value(
            expected_name,
            inputs,
            owner_pseudo,
            conditions=template.get("Conditions", {}),
        ) != metadata.get("Name"):
            raise Blocked("Secret name differs from owning template")
        for export in {e for r in references if r[1] == identifier for e in r[3]}:
            entries_for_export = [
                e
                for e in entries
                if e["Name"] == export
                and e.get("ExportingStackId") == stack_id
                and e["Value"] == arn
            ]
            outputs = [
                o
                for o in template.get("Outputs", {}).values()
                if "Export" in o
                and condition_active(template, inputs, owner_pseudo, o)
                and resolve_value(
                    o["Export"]["Name"],
                    inputs,
                    owner_pseudo,
                    conditions=template.get("Conditions", {}),
                )
                == export
                and output_value(template, inputs, owner_pseudo, o.get("Value"))
                in ({"Ref": logical}, {"Fn::GetAtt": [logical, "Id"]})
            ]
            if len(entries_for_export) != 1 or len(outputs) != 1:
                raise Blocked("Secret Export owner/value expression unconfirmed")
    keys = {r[2] for r in references if r[1] in {arn, metadata.get("Name")}}
    if not keys or "" in keys and len(keys) > 1:
        raise Blocked("mixed/unknown Secret string and JSON schema")
    return {
        "bootstrapType": "SECRETS_MANAGER_INITIAL_VALUE",
        "consumerStack": unit["name"],
        "failureClass": "|".join(
            sorted(logical + ":SecretCurrentValue" for logical in affected)
        ),
        "secretId": arn,
        "secretName": metadata["Name"],
        "account": pseudo["AWS::AccountId"],
        "region": target["awsRegion"],
        "owner": {
            "stack": name,
            "stackId": stack_id,
            "logicalId": logical,
            "model": source.relative_to(root).as_posix(),
            "resource": identity,
        },
        "requiredJsonKeys": sorted(keys - {""}),
        "valueType": "JSON" if keys != {""} else "STRING",
    }


def check_secret_arn(target, arn):
    match = re.fullmatch(
        r"arn:(aws|aws-cn|aws-us-gov):secretsmanager:([^:]+):(\d{12}):secret:([^:]+)",
        arn or "",
    )
    partition = (
        "aws-cn"
        if target["awsRegion"].startswith("cn-")
        else "aws-us-gov"
        if target["awsRegion"].startswith("us-gov-")
        else "aws"
    )
    if (
        not match
        or match[2] != target["awsRegion"]
        or match[1] != partition
        or match[3] != target.get("awsExecutionAccountId", target["awsAccountId"])
    ):
        raise Blocked("Secret account/region/identity mismatch")


def bootstrap_current(aws, entry):
    """Retrieve metadata only. Never return/log/persist SecretString or SecretBinary."""
    arn, token = entry["secretId"], entry["clientRequestToken"]
    metadata = aws("describe_secret", SecretId=arn, service="secretsmanager")
    if (
        metadata.get("ARN") != arn
        or metadata.get("Name") != entry["secretName"]
        or metadata.get("DeletedDate")
        or metadata.get("OwningService")
        or metadata.get("RotationEnabled")
        or metadata.get("ReplicationStatus")
        or metadata.get("PrimaryRegion") not in (None, entry["region"])
    ):
        raise Blocked(
            "Secret runtime identity/deletion/rotation/service ownership unsafe"
        )
    response = aws(
        "list_secret_version_ids",
        SecretId=arn,
        IncludeDeprecated=True,
        service="secretsmanager",
    )
    versions = response.get("Versions")
    if (
        not isinstance(versions, list)
        or response.get("NextToken")
        or response.get("ARN") != arn
    ):
        raise Blocked("Secret version inventory incomplete/ambiguous")
    if not all(isinstance(v, dict) for v in versions):
        raise Blocked("Secret version inventory invalid")
    stages = {v.get("VersionId"): v.get("VersionStages") for v in versions}
    summary = metadata.get("VersionIdsToStages", {})
    if (
        len(stages) != len(versions)
        or not all(
            isinstance(k, str)
            and isinstance(v, list)
            and all(isinstance(s, str) for s in v)
            and len(set(v)) == len(v)
            for k, v in stages.items()
        )
        or not isinstance(summary, dict)
        or not all(
            isinstance(v, list)
            and all(isinstance(s, str) for s in v)
            and len(set(v)) == len(v)
            for v in summary.values()
        )
        or {k: sorted(v) for k, v in summary.items()}
        != {k: sorted(v) for k, v in stages.items() if v}
    ):
        raise Blocked("Secret version metadata ambiguous/inconsistent")
    try:
        current = aws(
            "get_secret_value",
            SecretId=arn,
            VersionStage="AWSCURRENT",
            service="secretsmanager",
        )
    except Blocked as error:
        if not getattr(error, "current_missing", False) or any(
            "AWSCURRENT" in v for v in stages.values()
        ):
            raise Blocked(
                "Secret current-value check denied/failed/ambiguous"
            ) from None
        if set(stages) - {token}:
            raise Blocked(
                "Secret has existing noncurrent versions; initial bootstrap unsafe"
            ) from error
        if token in stages and (
            entry["stage"] != "PUT_SUBMITTED"
            or stages[token] != ["BLUEPRINT_BOOTSTRAP_" + token]
        ):
            raise Blocked(
                "Secret bootstrap version no longer in submitted initial state"
            ) from error
        return False, token in stages
    labels = current.get("VersionStages")
    if (
        current.get("ARN") != arn
        or current.get("HasValue") is not True
        or not isinstance(labels, list)
        or not all(isinstance(s, str) for s in labels)
        or len(set(labels)) != len(labels)
        or sorted(labels) != sorted(stages.get(current.get("VersionId"), []))
        or "AWSCURRENT" not in labels
    ):
        raise Blocked("Secret current-value response ambiguous")
    if current.get("VersionId") != token or entry["stage"] not in {
        "PUT_SUBMITTED",
        "BOOTSTRAP_CONFIRMED",
    }:
        raise Blocked("Secret already has a current value; never overwrite")
    return True, True


def bootstrap(
    root,
    states,
    guard,
    save,
    aws,
    bootstrap_plan,
    bootstrap_current,
    finish_repair,
    unit,
    state,
    entry=None,
):
    contract = task_snapshot(root).text
    if any(
        line not in contract.splitlines()
        for line in ("- AWS API execution: `allowed`", "- Deploy/apply: `allowed`")
    ):
        raise Blocked(
            "runtime bootstrap requires existing deploy mutation authorization"
        )
    plan = bootstrap_plan(unit, state)
    if entry is None:
        if state.get("bootstrapAttempted") or any(
            s.get("bootstrap", {}).get("secretId") == plan["secretId"]
            for s in states.values()
        ):
            raise Blocked("same Secret bootstrap already attempted in this run")
        entry = plan | {
            "classification": "RUNTIME_BOOTSTRAP",
            "clientRequestToken": uuid.uuid4().hex,
            "stage": "BOOTSTRAP_INTENT",
        }
        state["bootstrap"] = entry
        state["failureClassification"] = "RUNTIME_BOOTSTRAP"
        save()  # Intent and stable token MUST be durable before any Secrets Manager mutation.
    elif any(entry.get(k) != value for k, value in plan.items()) or not re.fullmatch(
        r"[0-9a-f]{32}", entry.get("clientRequestToken", "")
    ):
        raise Blocked("persisted bootstrap ownership/schema/identity changed")
    state["failureClassification"] = "RUNTIME_BOOTSTRAP"
    guard()
    confirmed, submitted = bootstrap_current(entry)
    if not confirmed:
        if not submitted:
            entry["stage"] = "VALUE_CHECKED_MISSING"
            save()
            guard()
            # Recheck after intent persistence, immediately before submission.
            confirmed, submitted = bootstrap_current(entry)
            if not confirmed and not submitted:
                entry["stage"] = "PUT_SUBMITTED"
                save()
                value = (
                    json.dumps(
                        {k: "DUMMY_DEPLOY_ONLY" for k in entry["requiredJsonKeys"]},
                        sort_keys=True,
                    )
                    if entry["valueType"] == "JSON"
                    else "DUMMY_DEPLOY_ONLY"
                )
                # Explicit private stage avoids moving an existing AWSCURRENT during a concurrent write.
                aws(
                    "put_secret_value",
                    SecretId=entry["secretId"],
                    SecretString=value,
                    ClientRequestToken=entry["clientRequestToken"],
                    VersionStages=[
                        "BLUEPRINT_BOOTSTRAP_" + entry["clientRequestToken"]
                    ],
                    service="secretsmanager",
                )
        confirmed, submitted = bootstrap_current(entry)
        if not confirmed:
            if not submitted:
                raise Blocked("bootstrap PUT not confirmed; resume same intent/token")
            # No RemoveFromVersionId: AWS refuses to move another version's AWSCURRENT.
            aws(
                "update_secret_version_stage",
                SecretId=entry["secretId"],
                VersionStage="AWSCURRENT",
                MoveToVersionId=entry["clientRequestToken"],
                service="secretsmanager",
            )
            confirmed, _ = bootstrap_current(entry)
            if not confirmed:
                raise Blocked("bootstrap current version not confirmed")
    entry["stage"] = "BOOTSTRAP_CONFIRMED"
    save()
    finish_repair(unit, state, entry)
    return True
