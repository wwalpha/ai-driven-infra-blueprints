"""Render detailed designs from authoritative service properties."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from iac_values import cfn_resource_identity
from array_display import indexed_rows

from design_layout import (
    ALIGNMENT, HEADER, DISPLAY_PROPERTY_ALIASES, GROUPED, HIDDEN_PROPERTIES,
    CODEBUILD_FORMAL_VARIABLE, GUARDDUTY_FORMAL_FEATURE, CLOUDTRAIL_FORMAL_DATA_RESOURCE,
    CLOUDTRAIL_RESOURCE_TYPES, resource_display_name,
    resource_name_fields, resource_anchor, resource_has_name_property, resource_mode,
    positive_integer, GROUPED_RESOURCE_TYPES, IMPLICIT_GROUPED_PROPERTIES, ROTATION_SCHEDULE, LAMBDA_PERMISSION,
    CODEBUILD_VPC_PROPERTIES, LINKED_LIST_PROPERTIES, SUBNET_LIST_SOURCE, subnet_list_items,
    ec2_display_rows, REQUIRED_NAME_TAG_TYPES,
    glue_argument_rows,
    catalog_property_order,
)
from policy_tables import literal, table, unique_object, invalid_constant
from design_catalog import DesignSchemaCatalog, design_material_files, property_paths_with_parents, selected_properties
from validation_cache import input_scope, memo_table, memoized


LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")
NAMING_EXEMPT_PROPERTIES = {
    "Config.ConfigurationRecorder.Name",
    "Config.DeliveryChannel.Name",
    "Glue.Connection.ConnectionInput.Name",
    "Glue.Database.DatabaseInput.Name",
    "Glue.Table.TableInput.Name",
    "GuardDuty.Detector.Name",
    "IAM.ManagedPolicy.ManagedPolicyName",
    "IAM.User.UserName",
    "IAM.InstanceProfile.InstanceProfileName",
    "Route53.HostedZone.Name",
    "Route53.RecordSet.Name",
}


def properties(text: str) -> dict[str, str]:
    # Keep caller mutation isolated while reusing an already validated invocation parse.
    memo = memo_table()
    key = (properties, text)
    if memo is not None and key in memo:
        return dict(memo[key])
    result = _parse_properties(text)
    if memo is not None:
        memo[key] = result
    return dict(result)


def _parse_properties(text: str) -> dict[str, str]:
    result = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in result or not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
            raise ValueError(f"invalid or duplicate model property at line {number}: {key}")
        result[key] = value
    return result


def entries(values: dict[str, str], prefix: str) -> list[tuple[str, dict[str, str]]]:
    memo = memo_table()
    key = (entries, id(values), prefix)
    if memo is not None and key in memo:
        return [(identity, dict(fields)) for identity, fields in memo[key][1]]
    groups: dict[str, dict[str, str]] = {}
    for key, value in values.items():
        if key.startswith(prefix):
            identity, separator, field = key[len(prefix):].partition(".")
            if not separator:
                raise ValueError(f"invalid model entry: {key}")
            groups.setdefault(identity, {})[field] = value
    if prefix == "desired.resource.":
        for identity, fields in groups.items():
            # Legacy identity remains readable; new models use their entry number internally.
            fields.setdefault("logicalId", identity)
            if 'deploymentEncryption' in fields and (fields.get('resourceType') != 'S3.Bucket' or fields['deploymentEncryption'] != 'default'):
                raise ValueError('deploymentEncryption is only default on an S3.Bucket')
            if "cfn-logicalId" in fields:
                cfn_resource_identity(fields["cfn-logicalId"])
    result = sorted(groups.items())
    if memo is not None:
        # Hold the immutable invocation input so object IDs cannot be recycled.
        memo[key] = (values, result)
        return [(identity, dict(fields)) for identity, fields in result]
    return result


def stack_model(values: dict[str, str]) -> tuple[int, list[tuple[str, dict[str, str]]]]:
    """Validate deployment inputs once for rendering, projection and execution."""
    limit = positive_integer(values.get("desired.deployment.maxConcurrentStacks", "1"), "MaxConcurrentStacks")
    stacks = entries(values, "desired.stack.")
    if not stacks:
        raise ValueError("stack model is empty")
    names, parameters = set(), set()
    allowed = {"name", "template", "parameters", "deployOrder"}
    for identity, stack in stacks:
        if set(stack) != allowed:
            raise ValueError(f"stack {identity} requires only {sorted(allowed)}; explicit DeployOrder migration required")
        positive_integer(stack["deployOrder"], "DeployOrder")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", stack["name"]):
            raise ValueError(f"invalid stack name: {stack['name']}")
        if stack["name"] in names:
            raise ValueError(f"duplicate stack name: {stack['name']}")
        if stack["parameters"] in parameters:
            raise ValueError(f"parameter file belongs to multiple stacks: {stack['parameters']}")
        names.add(stack["name"])
        parameters.add(stack["parameters"])
        for field, suffixes in (("template", {".yaml", ".yml"}), ("parameters", {".json"})):
            path = Path(stack[field])
            if path.name != stack[field] or "\\" in stack[field] or path.suffix not in suffixes:
                raise ValueError(f"invalid stack {field} filename: {stack[field]}")
    deployment_settings(values)
    unknown = [key for key in values if key.startswith("desired.") and
               not key.startswith(("desired.stack.", "desired.artifact.")) and
               key not in {"desired.deployment." + field for field in
                           ("maxConcurrentStacks", "templateBucket", "templateKeyPrefix")}]
    if unknown:
        raise ValueError(f"unknown stack design fields: {unknown}")
    return limit, sorted(stacks, key=lambda entry: (int(entry[1]["deployOrder"]), entry[1]["name"]))


ARTIFACT_FIELDS = ("stack", "resource", "property", "source", "bucket", "keyPrefix")
ARTIFACT_PROPERTIES = {
    ("AWS::Lambda::Function", "Code"): ("S3Bucket", "S3Key", "S3ObjectVersion"),
    ("AWS::Lambda::LayerVersion", "Content"): ("S3Bucket", "S3Key", "S3ObjectVersion"),
    ("AWS::StepFunctions::StateMachine", "DefinitionS3Location"): ("Bucket", "Key", "Version"),
    ("AWS::ApiGateway::RestApi", "BodyS3Location"): ("Bucket", "Key", "Version"),
    ("AWS::Glue::Job", "Command.ScriptLocation"): None,
}


def deployment_settings(values: dict[str, str]) -> tuple[dict[str, str], list[tuple[str, dict[str, str]]]]:
    settings = {field: values["desired.deployment." + field] for field in
                ("templateBucket", "templateKeyPrefix") if "desired.deployment." + field in values}
    if settings and set(settings) != {"templateBucket", "templateKeyPrefix"}:
        raise ValueError("TemplateBucket and TemplateKeyPrefix must be specified together")
    artifacts = entries(values, "desired.artifact.")
    names = {stack.get("name") for _, stack in entries(values, "desired.stack.")}
    destinations = set()
    for identity, artifact in artifacts:
        if set(artifact) != set(ARTIFACT_FIELDS) or not all(artifact.values()):
            raise ValueError(f"artifact {identity} requires only {list(ARTIFACT_FIELDS)}")
        if artifact["stack"] not in names or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", artifact["resource"]):
            raise ValueError(f"invalid artifact stack/resource: {identity}")
        if artifact["property"] not in {prop for _, prop in ARTIFACT_PROPERTIES}:
            raise ValueError(f"unsupported artifact property: {artifact['property']}")
        source = Path(artifact["source"])
        if source.is_absolute() or ".." in source.parts or "\\" in artifact["source"] or not artifact["source"].startswith("infra/cloudformation/artifacts/"):
            raise ValueError("artifact source must be a file under infra/cloudformation/artifacts/")
        destination = tuple(artifact[field] for field in ("stack", "resource", "property"))
        if destination in destinations:
            raise ValueError(f"duplicate artifact destination: {destination}")
        destinations.add(destination)
    if settings:
        validate_bucket_reference(settings["templateBucket"])
        validate_key_prefix(settings["templateKeyPrefix"])
    for _, artifact in artifacts:
        validate_bucket_reference(artifact["bucket"])
        validate_key_prefix(artifact["keyPrefix"])
        if any("|" in value or "\n" in value or "\r" in value for value in artifact.values()):
            raise ValueError("artifact fields must be single table cells")
    return settings, artifacts


def validate_bucket_reference(value: str) -> None:
    link = LINK.fullmatch(value)
    if not link or link.group(2) != "s3.md" or not re.fullmatch(r"[a-z0-9_.-]+", link.group(3)):
        raise ValueError("deployment bucket must reference s3.md in the same target")


def validate_key_prefix(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/", value) or len(value) > 800:
        raise ValueError("deployment keyPrefix must be an explicit relative prefix ending in /")


def deployment_bucket(reference: str, path: Path, root: Path) -> str:
    """Resolve the confirmed name from the referenced authoritative S3 model."""
    from model_files import read_model
    validate_bucket_reference(reference)
    link = LINK.fullmatch(reference)
    target_path = path.parent.relative_to(root / "docs/designs")
    try:
        values = properties(read_model(root / "model" / target_path / "s3.properties"))
    except OSError as error:
        raise ValueError("deployment bucket requires an existing authoritative S3 model") from error
    resources = [(identity, resource) for identity, resource in entries(values, "desired.resource.")
                 if resource.get("resourceType") == "S3.Bucket" and resource.get("anchor") == link.group(3)]
    if len(resources) != 1:
        raise ValueError("deployment bucket reference must identify one S3.Bucket")
    rows = entries(values, "desired.row.")
    names = [literal(row.get("value", "")) for identity, row in rows
             if identity.startswith(resources[0][0] + "-") and row.get("property") == "S3.Bucket.BucketName"]
    if len(names) != 1 or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", names[0]) or link.group(1) != names[0]:
        raise ValueError("deployment bucket requires the matching confirmed BucketName")
    return names[0]


@memoized
def naming_rule_files(root: Path, namespace: str | None = None) -> tuple[Path, ...]:
    """Read the common entry and only explicitly indexed service rules."""
    path = root / "framework/rules/aws-resource-naming.md"
    files = [path]
    for name, reference in re.findall(
        r"^\| `([A-Za-z0-9]+)` \| \[[^\]]+\]\((aws-resource-naming/[A-Za-z0-9]+\.md)\) \|$",
        path.read_text(encoding="utf-8"), re.MULTILINE,
    ):
        if namespace is None or name == namespace:
            files.append(path.parent / reference)
    return tuple(files)


def naming_target_matches(prop: str, targets: set[str], kind: str | None = None) -> bool:
    """Match a Naming Target at its declared root or exact nested property path."""
    normalized = {target.removeprefix(kind + ".") if kind else target for target in targets}
    return prop in normalized


@memoized
def naming_targets(root: Path, namespace: str | None = None) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    for path in naming_rule_files(root, namespace):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) in {5, 6} and cells[2].startswith("`") and re.fullmatch(r"`[^`]+`", cells[4]):
                for kind in re.findall(r"`([^`]+)`", cells[2]):
                    targets.setdefault(kind, set()).add(cells[3].strip("`"))
    return targets


def naming_coverage_errors(root: Path, kind: str, selected: set[str], name_tag: bool = False,
                           mode: str = "CREATE") -> list[str]:
    """Check rule existence without requiring any design values."""
    if mode not in {"CREATE", "IMPORT"}:
        raise ValueError(f"resourceMode must be CREATE or IMPORT: {mode!r}")
    if mode == "IMPORT":
        return []
    targets = naming_targets(root, kind.partition(".")[0])
    expected = selected & set(resource_name_fields(kind))
    expected.update(field for field in selected if naming_target_matches(field, targets.get(kind, set()), kind))
    if name_tag:
        expected.add("Name tag")
    return [f"naming rule missing: {kind}: {field}" for field in sorted(expected)
            if kind + "." + field not in NAMING_EXEMPT_PROPERTIES
            and not naming_target_matches(field, targets.get(kind, set()), kind)]


def design_naming_errors(root: Path, kind: str, mode: str = "CREATE", name_tag: bool = False) -> list[str]:
    """Preflight a selected resource type before asking for design values."""
    selected = set(selected_properties(root, kind))
    if not selected:
        raise ValueError(f"catalog resource type missing: {kind}")
    selected -= {field.removeprefix(kind + ".") for field in catalog_outputs(root, kind)}
    if name_tag and not selected.intersection({"Tags", "Tags[].Key", "HostedZoneTags", "HostedZoneTags[].Key"}):
        raise ValueError(f"Name tag is not selectable: {kind}")
    if kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}:
        selected.add("Name")
    if kind in {"EC2.VPCEndpoint", "EC2.Instance"}:
        name_tag = True
    return naming_coverage_errors(root, kind, selected, name_tag, mode)


def naming_errors(root: Path, kind: str, rows: list[list[str]], mode: str = "CREATE") -> list[str]:
    if kind in {"CodeBuild.Project", "IAM.Role"}:
        field = "RoleName" if kind == "IAM.Role" else "Name"
        names = [row[2].strip("`\"") for row in rows if row[1].removeprefix(kind + ".") == field]
        if len(names) != 1:
            return [f"{kind}.{field} must appear exactly once"]
        value = names[0]
        if not value.strip() or value.strip().lower() in {"unset", "pending", "pending_deploy", "tbd", "n/a", "none", "未確定"} or value.startswith("[") or "{{" in value:
            return [f"{kind}.{field} must be confirmed and non-empty"]
    if mode == "IMPORT":
        return []  # Confirmed actual names above and provider/schema checks remain mandatory.
    outputs = catalog_outputs(root, kind)
    selected = {row[1].removeprefix(kind + ".") for row in rows if kind + "." + row[1].removeprefix(kind + ".") not in outputs}
    tag_rows = [row for row in rows if row[1].removeprefix(kind + ".").startswith(("Tags", "HostedZoneTags"))]
    return naming_coverage_errors(root, kind, selected, resource_display_name(kind, tag_rows) is not None, mode)


@memoized
def catalog_outputs(root: Path, kind: str) -> set[str]:
    return {line.partition("=")[0] for path in design_material_files(root)
            if path.stem.replace("_", ".", 1) == kind
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.endswith("=IDENTIFIER_OUTPUT") and line.partition("=")[0] not in HIDDEN_PROPERTIES}


def resource_rows(values: dict[str, str], identity: str, kind: str, root: Path) -> list[list[str]]:
    outputs = catalog_outputs(root, kind)
    rows = []
    for row_id, row in entries(values, "desired.row."):
        if not row_id.startswith(identity + "-"):
            continue
        if set(row) - {"property", "value", "comment", "artifactSha256", "document"} or not {"property", "value", "comment"} <= row.keys():
            raise ValueError(f"invalid resource row: {row_id}")
        observed = values.get(f"observed.row.{row_id}.value")
        value = row["value"]
        if observed is not None:
            if link := LINK.fullmatch(value):
                value = observed if row["property"] in outputs else f"[{literal(observed)}]({link.group(2)}#{link.group(3)})"
            else:
                raise ValueError(f"observed value requires a desired logical reference: {row_id}")
        rows.append([row_id, row["property"], value, row["comment"]])
    return rows


def catalog_display_rows(rows: list[list[str]], kind: str, root: Path) -> list[list[str]]:
    """Sort property blocks without separating contiguous array elements."""
    if kind == "EC2.SecurityGroup" or GROUPED.get(kind, {}).get("display") == "rule-table":
        return rows  # Horizontal rule tables have their own generation and restoration.
    order = dict(catalog_property_order(root, kind) or {})
    if kind == "CodeBuild.Project":
        subnets, groups = kind + ".VpcConfig.Subnets", kind + ".VpcConfig.SecurityGroupIds"
        order[subnets], order[groups] = order[groups], order[subnets]
    if kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}:
        order[kind + ".Name"] = -1
    if kind == "S3.Bucket":
        order[kind + ".Region"] = order[kind + ".BucketName"] + 0.5
    blocks = []
    previous_array = ""
    array_order = {}
    for prop, rank in order.items():
        if "[]" in prop:
            array = prop.split("[]", 1)[0] + "[]"
            array_order.setdefault(array, rank)
    for row in rows:
        array = row[1].split("[]", 1)[0] + "[]" if "[]" in row[1] else ""
        if array and array == previous_array:
            blocks[-1].append(row)
        else:
            blocks.append([row])
        previous_array = array
    return [row for block in sorted(blocks, key=lambda block: array_order.get(
        block[0][1].split("[]", 1)[0] + "[]", order.get(block[0][1], len(order)))) for row in block]


def validate_required_properties(values: dict[str, str], root: Path) -> None:
    """Reject missing required model inputs before producing any view or artifact."""
    if entries(values, "desired.stack."):
        stack_model(values)
        return
    catalog = DesignSchemaCatalog(root)
    errors = []
    for identity, resource in entries(values, "desired.resource."):
        resource_mode(resource)
        kind = resource["resourceType"]
        rows = resource_rows(values, identity, kind, root)
        properties = {row[1] for row in rows
                      if literal(row[2]).strip().strip('"').strip().lower()
                      not in {"", "unset", "pending", "pending_deploy", "tbd", "未確定"}}
        if "parentProperty" in resource:
            properties.add(resource["parentProperty"])
        kinds = {kind} | {
            child for child in GROUPED_RESOURCE_TYPES.get(kind, set())
            if any(row[1].startswith(child + ".") for row in rows)
        }
        for schema_kind in sorted(kinds):
            present = property_paths_with_parents({prop.removeprefix(schema_kind + ".") for prop in properties
                                                  if prop.startswith(schema_kind + ".")})
            missing = catalog.required_design_properties(schema_kind) - present - IMPLICIT_GROUPED_PROPERTIES.get(schema_kind, set())
            errors.extend(f"{resource['logicalId']}: required provider schema property missing: {schema_kind}.{prop}"
                          for prop in sorted(missing))
    if errors:
        raise ValueError("\n- ".join(errors))


def design_target(path: Path, root: Path) -> dict:
    project = root / "project.json"
    if project.is_file() and path.is_relative_to(root / "docs/designs"):
        relative = path.parent.relative_to(root / "docs/designs")
        if len(relative.parts) == 2:
            environment, directory = relative.parts
            return next((item for item in json.loads(project.read_text(encoding="utf-8")).get("targets", [])
                         if item.get("environment") == environment and item.get("alias", item.get("awsAccountId")) == directory), {})
    return {}


def validate_kms_policy_accounts(values: dict[str, str], target: dict) -> None:
    """Check local KMS account principals without rewriting explicit external grants."""
    if not target:
        return
    execution = target.get("awsExecutionAccountId", target["awsAccountId"])
    keys = {identity for identity, resource in entries(values, "desired.resource.")
            if resource["resourceType"] == "KMS.Key" and resource_mode(resource) == "CREATE"}
    for identity, row in entries(values, "desired.row."):
        if not any(identity.startswith(key + "-") for key in keys) or row.get("property") != "KMS.Key.KeyPolicy" or "document" not in row:
            continue
        external = set(re.findall(r"\bcross-account:(arn:[A-Za-z0-9_+=,.@:/-]+)(?=$|[\s`])", row.get("comment", "")))
        document = json.loads(row["document"], object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(document, dict):
            raise ValueError(f"KMS.Key.KeyPolicy {identity}: document must be an object")
        statements = document.get("Statement", [])
        for number, statement in enumerate(statements if isinstance(statements, list) else [statements], 1):
            if not isinstance(statement, dict):
                raise ValueError(f"KMS.Key.KeyPolicy {identity} Statement[{number}]: must be an object")
            if statement.get("Effect") != "Allow":
                continue
            principal = statement.get("Principal", {})
            principals = principal.get("AWS", []) if isinstance(principal, dict) else []
            for arn in principals if isinstance(principals, list) else [principals]:
                match = re.fullmatch(r"arn:[^:]+:iam::([0-9]{12}):(root|role/aws-service-role/macie(?:\.[a-z0-9-]+)?\.amazonaws\.com/AWSServiceRoleForAmazonMacie)", str(arn))
                if match and match[1] != execution and arn not in external:
                    raise ValueError(f"KMS.Key.KeyPolicy {identity} Statement[{number}] Principal.AWS: {arn}: "
                                     f"must use AWS execution account {execution}; explicit cross-account grant requires "
                                     f"cross-account:{arn} in the policy row comment")


def display_rows(kind: str, rows: list[list[str]]) -> list[list[str]]:
    """Apply the existing service displays without changing formal model values."""
    aliases = {formal: display for display, formal in DISPLAY_PROPERTY_ALIASES.items()}
    result = []
    index = 0
    counts: dict[str, int] = {}
    while index < len(rows):
        identity, prop, value, comment = rows[index]
        if prop in HIDDEN_PROPERTIES:
            raise ValueError(f"hidden property must not be a display row: {prop}")
        if prop == CODEBUILD_FORMAL_VARIABLE + "Name":
            block = rows[index:index + 3]
            if [row[1] for row in block] != [CODEBUILD_FORMAL_VARIABLE + field for field in ("Name", "Type", "Value")]:
                raise ValueError("CodeBuild variables require contiguous Name/Type/Value rows")
            name, variable_type, value = [literal(row[2]) for row in block]
            prop = "CodeBuild.Project.Environment.Variables." + name
            if LINK.fullmatch(block[2][2]):
                value = block[2][2]
                comment = f"<!-- codebuild-variable-type: {variable_type} --> {comment}"
            elif variable_type == "PLAINTEXT":
                value = block[2][2]
            else:
                raise ValueError("CodeBuild non-PLAINTEXT variables require a resource link")
            index += 2
        elif prop in LINKED_LIST_PROPERTIES:
            linked = LINK.fullmatch(value)
            if prop in CODEBUILD_VPC_PROPERTIES and not linked:
                raise ValueError("CodeBuild VpcConfig value must be a resource link")
            items = [value] if linked else subnet_list_items(prop, value)
            source = ""
            if not linked:
                encoded = json.dumps(value, ensure_ascii=True)
                for char in "|<>[]":
                    encoded = encoded.replace(char, f"\\u{ord(char):04x}")
                source = "<!-- subnet-list-source: " + encoded + " --> "
            field = prop.removesuffix("[]").removeprefix(kind + ".")
            for offset, item in enumerate(items):
                counts[prop] = counts.get(prop, 0) + 1
                result.append([identity, f"{field}[{counts[prop]}]", item, (source if offset == 0 else "") + comment])
            index += 1
            continue
        elif prop == GUARDDUTY_FORMAL_FEATURE + "Name":
            if index + 1 >= len(rows) or rows[index + 1][1] != GUARDDUTY_FORMAL_FEATURE + "Status":
                raise ValueError("GuardDuty features require contiguous Name/Status rows")
            prop = "GuardDuty.Detector.Features." + literal(value)
            value = rows[index + 1][2]
            index += 1
        elif prop == CLOUDTRAIL_FORMAL_DATA_RESOURCE + "Type":
            if index + 1 >= len(rows) or rows[index + 1][1] != CLOUDTRAIL_FORMAL_DATA_RESOURCE + "Values":
                raise ValueError("CloudTrail data resources require contiguous Type/Values rows")
            types = {value: key for key, value in CLOUDTRAIL_RESOURCE_TYPES.items()}
            if literal(value) not in types:
                raise ValueError("unsupported CloudTrail data resource type")
            counts["data"] = counts.get("data", 0) + 1
            prop = f"CloudTrail.Trail.EventSelectors.DataResources[{counts['data']}].{types[literal(value)]}"
            value = rows[index + 1][2]
            if literal(value) == '["arn:aws:s3"]':
                value = "`All current and future S3 buckets`"
            index += 1
        elif prop.startswith((CODEBUILD_FORMAL_VARIABLE, GUARDDUTY_FORMAL_FEATURE, CLOUDTRAIL_FORMAL_DATA_RESOURCE)) and not prop.startswith(GUARDDUTY_FORMAL_FEATURE + "AdditionalConfiguration"):
            raise ValueError(f"incomplete compact display group: {prop}")
        prop = aliases.get(prop, prop).removeprefix(kind + ".")
        result.append([identity, prop, value, comment])
        index += 1
    if kind == "CodePipeline.Pipeline":
        return pipeline_rows(result)
    if kind in REQUIRED_NAME_TAG_TYPES:
        return ec2_display_rows(result)
    if kind == "Glue.Job":
        return glue_argument_rows(result, kind)
    return result


def pipeline_rows(rows: list[list[str]]) -> list[list[str]]:
    action_counts: list[int] = []
    seen_stage: set[str] = set()
    seen_action: set[str] = set()
    result = []
    trailing = []
    ordered = []
    name_last = False
    for row in rows:
        field = row[1]
        if not field.startswith("Stages[]."):
            (trailing if action_counts else result).append(row)
            continue
        if trailing:
            raise ValueError("CodePipeline stage rows must be contiguous")
        field = field.removeprefix("Stages[].")
        action = field.startswith("Actions[].")
        field = field.removeprefix("Actions[].")
        if not action_counts:
            # Catalog order ends each stage with Name; legacy models put it first.
            name_last = action
        if not action_counts or (name_last and "Name" in seen_stage) or (not action and field in seen_stage):
            seen_stage, seen_action = set(), set()
            action_counts.append(0)
        if action:
            if not seen_action or ("[]" not in field and field in seen_action):
                seen_action = set()
                action_counts[-1] += 1
            seen_action.add(field)
        else:
            seen_stage.add(field)
        ordered.append((len(action_counts), action_counts[-1] if action else 0, [row[0], field, *row[2:]]))
    for stage, action, (identity, field, value, comment) in ordered:
        prefix = f"Stages[{stage}]."
        if action:
            prefix += "Actions." if action_counts[stage - 1] == 1 else f"Actions[{action}]."
        if field != "Configuration":
            result.append([identity, prefix + field, value, comment])
            continue
        config = json.loads(literal(value), object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(config, dict) or not config or any(not isinstance(item, str) for item in config.values()):
            raise ValueError("CodePipeline Configuration must be a non-empty string object")
        comments = dict(part.split(": ", 1) for part in comment.split(" / ") if ": " in part)
        if set(comments) != set(config):
            raise ValueError("CodePipeline Configuration requires a comment for each key")
        for key, item in config.items():
            result.append([identity, prefix + "Configuration." + key, item if LINK.fullmatch(item) else f"`{item}`", comments[key]])
    return result + trailing


def row_table(rows: list[list[str]]) -> list[str]:
    return [HEADER, ALIGNMENT, *("| " + " | ".join([str(number), *row[1:]]) + " |" for number, row in enumerate(rows, 1))]


def sg_tables(rows: list[list[str]], children: list[tuple[dict, list[list[str]]]]) -> list[str]:
    basic, tags, rules = [], [], []
    current = None
    for row in rows:
        prop = row[1].removeprefix("EC2.SecurityGroup.")
        if match := re.fullmatch(r"SecurityGroup(Ingress|Egress)\[\]\.(.+)", prop):
            direction, field = match.groups()
            if field == "IpProtocol":
                current = {"Direction": "Inbound" if direction == "Ingress" else "Outbound"}
                rules.append(current)
            if current is None or current["Direction"] != ("Inbound" if direction == "Ingress" else "Outbound"):
                raise ValueError("SG inline rule must start with IpProtocol")
            current[field] = row[2]
        elif prop.startswith("Tags[]."):
            if prop == "Tags[].Key":
                tags.append({"Key": json.loads(row[2])})
            elif prop == "Tags[].Value" and tags and "Value" not in tags[-1]:
                tags[-1]["Value"] = json.loads(row[2])
            else:
                raise ValueError("SG tags require contiguous Key/Value pairs")
        else:
            basic.append([row[0], prop, *row[2:]])
    output = row_table(basic)
    if tags:
        if any(set(tag) != {"Key", "Value"} for tag in tags):
            raise ValueError("incomplete SG tag")
        output = ["<!-- security-group-tags: " + json.dumps(tags, ensure_ascii=False, separators=(",", ":")) + " -->", "", *output]
    for child, child_rows in children:
        values = {row[1].removeprefix(child["resourceType"] + "."): row[2] for row in child_rows}
        direction = "Inbound" if child["resourceType"].endswith("Ingress") else "Outbound"
        identifier = values.pop("Id")
        values["Direction"] = f'{direction} <a id="{child["anchor"]}"></a><!-- logical-id: {child["logicalId"]} --><!-- rule-id: {identifier} -->'
        rules.append(values)
    for rule in rules:
        first, last = rule.pop("FromPort", None), rule.pop("ToPort", None)
        if (first is None) != (last is None):
            raise ValueError("SG FromPort and ToPort must be supplied together")
        if first is not None:
            first, last = literal(first), literal(last)
            protocol = literal(rule["IpProtocol"]).lower()
            port = f"Type={first}, Code={last}" if protocol in {"icmp", "icmpv6", "1", "58"} else first if first == last else f"{first}-{last}"
            rule["Port"] = f"`{port}`"
        for peer in ("SourceSecurityGroupId", "DestinationSecurityGroupId"):
            if peer in rule:
                rule["Direction"] += f" <!-- security-group-id: {rule.pop(peer)} -->"
    if rules:
        fields = ["Direction", "IpProtocol", "Port", "CidrIp", "CidrIpv6", "SourcePrefixListId", "DestinationPrefixListId", "SourceSecurityGroupOwnerId", "Description"]
        unknown = set().union(*(rule.keys() for rule in rules)) - set(fields)
        if unknown:
            raise ValueError(f"unsupported SG rule fields: {sorted(unknown)}")
        fields = [field for field in fields if field in {"Direction", "Port"} or any(field in rule for rule in rules)]
        output += ["", *table(fields, [[rule.get(field, "—") for field in fields] for rule in rules])]
    return output


def resource_display_rows(values: dict[str, str], identity: str, resource: dict[str, str], root: Path) -> list[list[str]]:
    """Include a Key's own grouped aliases when resolving its display name."""
    rows = resource_rows(values, identity, resource["resourceType"], root)
    if resource["resourceType"] == "KMS.Key":
        for child_id, child in entries(values, "desired.resource."):
            link = LINK.fullmatch(child.get("parentReference", ""))
            if child["resourceType"] == "KMS.Alias" and link and not link.group(2) and link.group(3) == resource["anchor"]:
                rows += resource_rows(values, child_id, child["resourceType"], root)
    return rows


@input_scope
def markdown_for(path: Path, values: dict[str, str], root: Path) -> str:
    """Produce the complete base view; policy tables are rendered afterwards."""
    validate_required_properties(values, root)
    if path.stem == "cloudformation-stacks":
        limit, stacks = stack_model(values)
        for _, stack in stacks:
            if errors := naming_errors(root, "CloudFormation.Stack", [["1", "StackName", stack["name"], "名前"]]):
                raise ValueError("; ".join(errors))
        settings, artifacts = deployment_settings(values)
        delivery = []
        if artifacts:
            delivery = ["", "## S3配置", "", "### 配置ファイル", "",
                "| No. | StackName | Resource | Property | Source | Bucket | KeyPrefix |",
                "| ---: | --- | --- | --- | --- | --- | --- |"]
            delivery += ["| " + " | ".join([str(number)] + [artifact[field] for field in ARTIFACT_FIELDS]) + " |"
                         for number, (_, artifact) in enumerate(artifacts, 1)]
        if settings:
            deployment_bucket(settings["templateBucket"], path, root)
        for _, artifact in artifacts:
            deployment_bucket(artifact["bucket"], path, root)
        return "\n".join(["# CloudFormation stack 詳細設計", "",
            f"<!-- max-concurrent-stacks: {limit} -->", "",
            *[f"<!-- {field}: {value} -->" for field, value in settings.items()],
            "## Stack一覧", "", "| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |",
            "| ---: | ---: | --- | --- | --- | --- |", *[
                "| " + " | ".join([str(number), stack["deployOrder"], stack["name"], stack["template"],
                    stack["parameters"], values[f"display.stack.{identity}.comment"]]) + " |"
                for number, (identity, stack) in enumerate(stacks, 1)], *delivery]) + "\n"
    service = path.stem
    if values.get(f"desired.service.{service}.serviceId") != service:
        raise ValueError(f"service ID must equal file stem: {path.name}")
    owned = values[f"desired.service.{service}.ownedCatalogResourceTypes"].split(",")
    resources = entries(values, "desired.resource.")
    if not resources:
        raise ValueError(f"service model has no resources: {path.name}")
    relative = path.parent.relative_to(root / "docs/designs") if path.is_relative_to(root / "docs/designs") else None
    target = design_target(path, root)
    validate_kms_policy_accounts(values, target)
    stack_source = root / "model" / relative / "cloudformation-stacks.properties" if relative is not None else None
    stack_names = None
    identity_catalog = DesignSchemaCatalog(root)
    for identity, resource in resources:
        if "cfn-logicalId" not in resource:
            if target.get("iacEngine") == "cloudformation" and resource_mode(resource) == "CREATE" and f"desired.resource.{identity}.logicalId" not in values:
                try:
                    cfn_type = identity_catalog.cloudformation_type(resource["resourceType"])
                except ValueError:
                    cfn_type = None  # API-only design resources have no CFn identity.
                if cfn_type:
                    raise ValueError(f"{identity}: cfn-logicalId required for CloudFormation CREATE resource")
            continue
        if target.get("iacEngine") == "terraform":
            raise ValueError(f"{identity}: cfn-logicalId is forbidden for Terraform")
        if resource_mode(resource) != "CREATE":
            raise ValueError(f"{identity}: cfn-logicalId requires CREATE with a formal CFn type")
        identity_catalog.cloudformation_type(resource["resourceType"])
        if target.get("iacEngine") == "cloudformation" and (stack_source is None or not stack_source.is_file()):
            raise ValueError(f"{identity}: cfn-logicalId requires authoritative cloudformation-stacks.properties")
        if stack_source is not None and stack_source.is_file():
            if stack_names is None:
                from model_files import read_model
                _, stacks = stack_model(properties(read_model(stack_source)))
                stack_names = {stack["name"] for _, stack in stacks}
            if cfn_resource_identity(resource["cfn-logicalId"])[0] not in stack_names:
                raise ValueError(f"{identity}: cfn-logicalId references an undeclared stack")
    counts = Counter(resource["resourceType"] for _, resource in resources)
    by_anchor = {}
    details = []
    for identity, resource in resources:
        kind = resource["resourceType"]
        mode = resource_mode(resource)
        if kind not in owned:
            raise ValueError(f"resource is outside service ownership: {kind}")
        rows = catalog_display_rows(resource_rows(values, identity, kind, root), kind, root)
        rule_table = GROUPED.get(kind, {}).get("display") == "rule-table"
        configured_name = None if rule_table else resource_display_name(
            kind, resource_display_rows(values, identity, resource, root), values.get(f"display.resource.{identity}.label"), mode
        )
        name = (values.get(f"display.resource.{identity}.label") or resource["logicalId"]) if rule_table else configured_name or values.get(f"display.resource.{identity}.label")
        type_display = not rule_table and configured_name is None and (name is None or name == kind)
        if type_display:
            if kind in GROUPED or counts[kind] != 1 or resource_has_name_property(root, kind, mode):
                raise ValueError(f"resource type display requires a single nameless independent resource: {kind}")
            name = kind
        if not name or name in {"UNSET", "PENDING_DEPLOY"}:
            raise ValueError(f"confirmed resource display label is missing: {kind}: {identity}")
        anchor = resource["anchor"]
        if anchor != resource_anchor(service, name, kind) or anchor in by_anchor:
            raise ValueError(f"resource anchor must be unique and match its name: {kind}: {anchor}")
        errors = naming_errors(root, kind, rows, mode)
        if errors:
            raise ValueError("; ".join(errors))
        item = (identity, resource, name, rows)
        by_anchor[anchor] = item
        details.append(item)
    independent = [item for item in details if item[1]["resourceType"] not in GROUPED]
    grouped: dict[str, list] = {}
    for item in details:
        identity, resource, name, rows = item
        if resource["resourceType"] not in GROUPED:
            continue
        kind = resource["resourceType"]
        rule = GROUPED[kind]
        for field in ("parentReference", "parentProperty"):
            if not resource.get(field):
                raise ValueError(f"{kind}: {resource['logicalId']}: required metadata missing: desired.resource.{identity}.{field} ({kind}.{rule['parentProperty']})")
        link = LINK.fullmatch(resource["parentReference"])
        parent = by_anchor.get(link.group(3)) if link and not link.group(2) else None
        if not parent or parent[1]["resourceType"] != rule["parent"] or link.group(1) != parent[1]["logicalId"] or resource["parentProperty"] != kind + "." + rule["parentProperty"]:
            raise ValueError(f"{kind}: {resource['logicalId']}: invalid grouped parent: parentReference / parentProperty ({kind}.{rule['parentProperty']})")
        if kind in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
            parent_rows = [row for row_id, row in entries(values, "desired.row.")
                           if row_id.startswith(identity + "-") and row.get("property") == resource["parentProperty"]]
            if len(parent_rows) != 1 or parent_rows[0].get("value") != resource["parentReference"]:
                raise ValueError(f"{kind}: {resource['logicalId']}: {resource['parentProperty']} requires exactly one formal row matching parentReference")
            if kind + ".Id" not in HIDDEN_PROPERTIES and (not rows or rows[0][1] != kind + ".Id"):
                raise ValueError(f"{kind}: {resource['logicalId']}: required first property: {kind}.Id")
        grouped.setdefault(parent[0], []).append(item)
        maximum = rule["maxCount"]
        if maximum is not None and sum(child[1]["resourceType"] == kind for child in grouped[parent[0]]) > maximum:
            raise ValueError(f"{kind}: {resource['logicalId']}: too many grouped children for {parent[1]['logicalId']}: {resource['parentProperty']}")
    output = [values["display.service.title"], "", f"- Design service ID: `{service}`",
              "- Owned catalog resource types: " + ", ".join(f"`{kind}`" for kind in owned)]
    output += ["", "## リソース一覧"]
    for kind in dict.fromkeys(item[1]["resourceType"] for item in independent):
        items = [item for item in independent if item[1]["resourceType"] == kind]
        output += ["", "### " + kind, "", *table(["No.", "ResourceName", "Comment"], [
            [str(number), f'[{name}](#{resource["anchor"]})', values[f"display.resource.{identity}.comment"]]
            for number, (identity, resource, name, _) in enumerate(items, 1)], numbered=True)]
    output += ["", "## リソース詳細"]
    for identity, resource, name, rows in independent:
        kind = resource["resourceType"]
        heading = f"### {kind}" if name == kind and resource_display_name(kind, rows, mode=resource_mode(resource)) is None else f"### {kind}: {name}"
        output += ["", f'<!-- resource-logical-id: {resource["logicalId"]} -->', f'<a id="{resource["anchor"]}"></a>', "", heading, ""]
        children = grouped.get(identity, [])
        if kind == "EC2.SecurityGroup":
            output += sg_tables(rows, [(child, child_rows) for _, child, _, child_rows in children])
        else:
            display = display_rows(kind, rows)
            for _, child, child_name, child_rows in children:
                if child["resourceType"] == ROTATION_SCHEDULE:
                    child_rows = [[rid, prop, f'[{name}](#{resource["anchor"]})' if prop == child["parentProperty"] else value, comment]
                                  for rid, prop, value, comment in child_rows]
                child_display = display_rows(kind if child["resourceType"] == ROTATION_SCHEDULE else child["resourceType"], child_rows)
                if child["resourceType"] != ROTATION_SCHEDULE:
                    for row in child_display:
                        row[1] = child["resourceType"] + "." + row[1]
                if child["resourceType"] == LAMBDA_PERMISSION:
                    hidden = [row[1:] for row in child_rows if row[1] in {LAMBDA_PERMISSION + ".Id", LAMBDA_PERMISSION + ".FunctionName"}]
                    child_display = [row for row in child_display if row[1] not in {LAMBDA_PERMISSION + ".Id", LAMBDA_PERMISSION + ".FunctionName"}]
                    metadata = json.dumps([child_name, hidden], ensure_ascii=False, separators=(",", ":"))
                    for char in "<>|()":
                        metadata = metadata.replace(char, "\\u%04x" % ord(char))
                    for row in child_display:
                        row[1] = row[1].removeprefix("Lambda.")
                    child_display[0][3] = f"<!-- lambda-permission: {metadata} --> " + child_display[0][3]
                prefix = f'<a id="{child["anchor"]}"></a><!-- logical-id: {child["logicalId"]} --> '
                if child["resourceType"] == ROTATION_SCHEDULE:
                    prefix += child_name + "："
                comment = child_display[0][3]
                source = SUBNET_LIST_SOURCE.match(comment)
                child_display[0][3] = (source.group(0) if source else "") + prefix + (comment[source.end():] if source else comment)
                display += child_display
            display = indexed_rows(display, kind, root)
            output += row_table(display)
        if kind == "Macie.ClassificationJob":
            definitions = [row for row in rows if row[1] == kind + ".s3JobDefinition"]
            if definitions:
                match = re.fullmatch(r"\[[^\]]+\]\(([^)#]+\.json)\)", definitions[0][2])
                raw = (path.parent / match.group(1)).read_text(encoding="utf-8") if match else literal(definitions[0][2])
                document = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                if "bucketDefinitions" in document:
                    mappings = [[f'[{name}](#{resource["anchor"]})', f'`{group["accountId"]}`', f"`{bucket}`"] for group in document["bucketDefinitions"] for bucket in group["buckets"]]
                    output += ["", "#### 対象S3 bucket", "", *table(["Job", "AWS account ID", "Bucket"], mappings)]
    for _, note in entries(values, "desired.note."):
        output += ["", note["text"]]
    return "\n".join(output) + "\n"
