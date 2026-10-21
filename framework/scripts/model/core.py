"""Model string parsing and structural/deployment contracts, without file I/O."""

import re
from pathlib import Path
from iac_values import cfn_resource_identity
from validation_cache import memo_table


class ReferenceResolutionError(ValueError):
    """A semantic reference failure, distinct from invalid source data or I/O."""
    def __init__(self, message, *, code='reference.unresolved', **details):
        super().__init__(message)
        self.diagnostic = {'code': code, 'message': message, 'status': 'unresolved', **details}


def reference_warning(error, **details):
    return {**error.diagnostic, **details}


def report_reference_warnings(warnings):
    import json
    import sys
    for warning in warnings:
        print('WARNING [' + warning['code'] + '] ' + json.dumps(warning, ensure_ascii=False), file=sys.stderr)


LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")

def positive_integer(value: str, label: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) < 1:
        raise ValueError(f"{label} must be an integer >= 1: {value}")
    return int(value)


def properties(text: str) -> dict[str, str]:
    from model.format import parse
    return parse(text, require_header=False).values


def validate_runtime_keys(values):
    """Validate a projection while keeping derived fields out of canonical schema."""
    import re
    derived = {}
    authority = {}
    for key, value in values.items():
        match = re.fullmatch(r'(?:observed\.row\.([A-Za-z0-9_-]+)\.(property|comment)|desired\.row\.([A-Za-z0-9_-]+)\.artifactSha256)', key)
        if re.fullmatch(r'desired\.resource\.[A-Za-z0-9_-]+\.anchor', key):
            if value != 'resource-' + values.get(key.removesuffix('anchor') + 'logicalId', ''):
                raise ValueError('invalid derived Resource anchor: ' + key)
            continue
        (derived if match else authority)[key] = value
    validate_model_keys(authority)
    for key, value in derived.items():
        if key.endswith('.artifactSha256'):
            from utils.json_format import document_sha256
            from utils.json_format import strict_json
            document = authority.get(key.removesuffix('artifactSha256') + 'document')
            if document is None or document_sha256(strict_json(document)) != value:
                raise ValueError('invalid derived artifactSha256: ' + key)
        else:
            desired = key.replace('observed.', 'desired.', 1)
            if authority.get(desired) != value or key.rsplit('.', 1)[0] + '.value' not in authority:
                raise ValueError('invalid derived observed metadata: ' + key)


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


def validate_model_keys(values: dict[str, str]) -> None:
    """Expanded Model fields; visibility never determines whether a field is legal."""
    fields = {
        ('desired', 'service'): {'serviceId', 'ownedCatalogResourceTypes', 'lastAllocated'},
        ('desired', 'resource'): {'resourceType', 'logicalId', 'resourceMode',
                                'cfn-logicalId', 'parentProperty', 'parentReference', 'deploymentEncryption'},
        ('desired', 'row'): {'property', 'value', 'comment', 'document'},
        ('observed', 'row'): {'value'},
        ('desired', 'note'): {'text'},
        ('display', 'resource'): {'comment', 'label'},
        ('desired', 'stack'): {'name', 'template', 'parameters', 'deployOrder', 'placementName'},
        ('display', 'stack'): {'comment'},
        ('desired', 'reference'): {'consumerKey', 'pointer', 'text', 'occurrence', 'producerKind', 'producerScope', 'producerId', 'producerLogicalId', 'resourceType', 'format', 'property', 'labelPolicy', 'contextProperty'},
        ('desired', 'artifact'): set(ARTIFACT_FIELDS),
    }
    singles = {'display.service.title', 'desired.deployment.maxConcurrentStacks',
               'desired.deployment.templateBucket', 'desired.deployment.templateKeyPrefix'}
    for key in values:
        parts = key.split('.')
        if key not in singles and not (len(parts) == 4 and parts[2] and
                                      parts[3] in fields.get(tuple(parts[:2]), set())):
            raise ValueError('unknown Model field: ' + key)


def stack_model(values: dict[str, str]) -> tuple[int, list[tuple[str, dict[str, str]]]]:
    """Validate deployment inputs once for rendering, projection and execution."""
    limit = positive_integer(values.get("desired.deployment.maxConcurrentStacks", "1"), "MaxConcurrentStacks")
    stacks = entries(values, "desired.stack.")
    if not stacks:
        raise ValueError("stack model is empty")
    names, parameters = set(), set()
    allowed = {"name", "template", "parameters", "deployOrder"}
    for identity, stack in stacks:
        if set(stack) not in (allowed, allowed | {'placementName'}):
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
               not key.startswith(("desired.stack.", "desired.artifact.", "desired.reference.", "desired.service.", "desired.note.")) and
               key not in {"desired.deployment." + field for field in
                           ("maxConcurrentStacks", "templateBucket", "templateKeyPrefix")}]
    if unknown:
        raise ValueError(f"unknown stack design fields: {unknown}")
    return limit, sorted([(identity, {k: v for k, v in stack.items() if k != 'placementName'}) for identity, stack in stacks], key=lambda entry: (int(entry[1]["deployOrder"]), entry[1]["name"]))


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
    from model.identity import parse_reference
    _, _, service, logical = parse_reference(value)
    if service != 's3' or not logical.startswith('S3_Bucket_'):
        raise ValueError('deployment bucket must reference an S3.Bucket URI')


def validate_key_prefix(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/", value) or len(value) > 800:
        raise ValueError("deployment keyPrefix must be an explicit relative prefix ending in /")




def literal(value: str) -> str:
    return value[1:-1] if value.startswith("`") and value.endswith("`") else value


def validate_stack_metadata(values):
    """Canonical placement identities are checked separately from execution fields."""
    stacks = entries(values, 'desired.stack.')
    placements = set()
    for identity, stack in stacks:
        placement = stack.get('placementName')
        if not isinstance(placement, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,127}', placement) or placement in placements:
            raise ValueError('invalid, missing or duplicate fixed Stack placementName: ' + identity)
        if any(other_id != identity and other.get('name') == placement for other_id, other in stacks):
            raise ValueError('fixed Stack placementName conflicts with another Stack name: ' + identity)
        placements.add(placement)


def validate_authority(values):
    """Validate the saved schema before adding any runtime-only metadata."""
    validate_model_keys(values)
    for identity, resource in entries(values, 'desired.resource.'):
        if not re.fullmatch(r'[A-Za-z0-9_]+\.[A-Za-z0-9_]+', resource.get('resourceType', '')):
            raise ValueError('Resource requires a valid resourceType: ' + identity)
        if resource.get('resourceMode', 'CREATE') not in {'CREATE', 'IMPORT'}:
            raise ValueError('resourceMode must be CREATE or IMPORT: ' + identity)
    from model.identity import resource_index
    resource_index(values)
    for identity, row in entries(values, 'desired.row.'):
        if not {'property', 'value', 'comment'} <= row.keys():
            raise ValueError('Row requires property, value and comment: ' + identity)
    if entries(values, 'desired.stack.'):
        validate_stack_metadata(values)
        stack_model(values)


def resource_row_index(values: dict[str, str]) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Index legacy IDs as well as numbered resources using the existing prefix rule.

    Ambiguous overlapping legacy identities are rejected, never split at first '-'.
    """
    from model.core import entries
    resources = dict(entries(values, "desired.resource."))
    index = {identity: [] for identity in resources}
    # A row's final segment is its row number; legacy resource IDs may contain '-'.
    for rid, row in entries(values, "desired.row."):
        owner = rid.rpartition("-")[0]
        if owner not in resources:
            raise ValueError(f"orphan desired row: {rid}")
        prefix, overlapping = owner, []
        while "-" in prefix:
            prefix = prefix.rpartition("-")[0]
            if prefix in resources:
                overlapping.append(prefix)
        if overlapping:
            raise ValueError(f"ambiguous legacy row ownership: {rid}: {overlapping + [owner]}")
        index[owner].append((rid, row))
    return index

