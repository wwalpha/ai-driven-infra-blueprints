"""Model string parsing and structural/deployment contracts, without file I/O."""

import re
from pathlib import Path
from iac_values import cfn_resource_identity
from validation_cache import memo_table


LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")

def positive_integer(value: str, label: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) < 1:
        raise ValueError(f"{label} must be an integer >= 1: {value}")
    return int(value)


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




def literal(value: str) -> str:
    return value[1:-1] if value.startswith("`") and value.endswith("`") else value
