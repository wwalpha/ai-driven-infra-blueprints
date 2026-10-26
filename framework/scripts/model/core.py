"""Model string parsing and structural/deployment contracts, without file I/O."""

import json
import re
import sys
from pathlib import Path

from utils.iac_values import cfn_resource_identity
from utils.input_cache import memo_table
from validation.diagnostics import InputValidationError

from model.format import input_json, parse
from model.literal_values import value_shape


class ReferenceDiagnosticError(ValueError):
    """A classified reference cause, with context retained across callers."""

    category = "FRAMEWORK_UNSUPPORTED"
    default_code = None
    action = "Review the Framework reference contract and implementation."

    def __init__(self, message, *, code=None, diagnostics=None, **details):
        super().__init__(message)
        self.diagnostic = {
            "category": self.category,
            "code": code or self.default_code or self.category,
            "message": message,
            "status": "NOT_RUN"
            if isinstance(self, ReferenceResolutionError)
            else "FAIL",
            "action": self.action,
            **details,
        }
        self.diagnostics = diagnostics if diagnostics is not None else [self.diagnostic]

    def __str__(self):
        return (
            super().__str__() + "; " + json.dumps(self.diagnostics, ensure_ascii=False)
        )


class ModelNeedsFixError(ReferenceDiagnosticError):
    category = "MODEL_NEEDS_FIX"
    action = "Correct the Model reference or the invalid producer field."


class FrameworkUnsupportedError(ReferenceDiagnosticError):
    pass


class ReferenceResolutionError(ReferenceDiagnosticError):
    """A proven reference wait, independent of invalid Model data."""

    default_code = "reference.unresolved"
    category = "REFERENCE_UNRESOLVED"
    action = "Confirm the missing reference value, then regenerate."


def require_reference_diagnostics(diagnostics):
    """Retain individual causes while giving errors precedence over waits."""
    if not diagnostics:
        return
    if any(
        d["category"]
        not in {
            "MODEL_NEEDS_FIX",
            "FRAMEWORK_UNSUPPORTED",
            "REFERENCE_PENDING_DEPLOY",
            "REFERENCE_UNRESOLVED",
        }
        for d in diagnostics
    ):
        raise FrameworkUnsupportedError(
            "Unrecognized reference diagnostic category",
            originalDiagnostics=diagnostics,
        )
    for category, error in (
        ("MODEL_NEEDS_FIX", ModelNeedsFixError),
        ("FRAMEWORK_UNSUPPORTED", FrameworkUnsupportedError),
        ("REFERENCE_PENDING_DEPLOY", ReferenceResolutionError),
        ("REFERENCE_UNRESOLVED", ReferenceResolutionError),
    ):
        primary = next((d for d in diagnostics if d["category"] == category), None)
        if primary is not None:
            raise error(**primary, diagnostics=diagnostics)
    raise FrameworkUnsupportedError("Unrecognized reference diagnostic category")


def reference_warning(error, **details):
    return {**error.diagnostic, **details}


def report_reference_warnings(warnings):
    for warning in warnings:
        print(
            ("ERROR [" if warning.get("status") == "FAIL" else "WARNING [")
            + warning["code"]
            + "] "
            + json.dumps(warning, ensure_ascii=False),
            file=sys.stderr,
        )


LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")


def positive_integer(value: str, label: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) < 1:
        raise InputValidationError(f"{label} must be an integer >= 1: {value}")
    return int(value)


def properties(text: str) -> dict[str, str]:
    return parse(text, require_header=False).values


class SnapshotValues(dict):
    """Owned immutable strings; identity is valid only for this fixed projection."""

    __slots__ = ()

    def __new__(cls, values):
        result = dict.__new__(cls)
        dict.__init__(result, values)
        return result

    def __init__(self, values):
        # Initialize only in __new__; reinitialization must not change cached input.
        pass

    def _immutable(self, *args, **kwargs):
        raise TypeError("Snapshot values are immutable")

    __setitem__ = __delitem__ = __ior__ = _immutable
    clear = pop = popitem = setdefault = update = _immutable

    def __deepcopy__(self, memo):
        return self


def validate_runtime_keys(values):
    """Validate a projection while keeping derived fields out of canonical schema."""
    derived, authority = {}, {}
    for key, value in values.items():
        if re.fullmatch(r"observed\.row\.[A-Za-z0-9_-]+\.(property|comment)", key):
            derived[key] = value
        else:
            authority[key] = value
    validate_model_keys(authority)
    for key, value in derived.items():
        desired = key.replace("observed.", "desired.", 1)
        if (
            authority.get(desired) != value
            or key.rsplit(".", 1)[0] + ".value" not in authority
        ):
            raise ValueError("invalid derived observed metadata: " + key)


def entries(values: dict[str, str], prefix: str) -> list[tuple[str, dict[str, str]]]:
    result = structural_entries(values, prefix)
    if prefix == "desired.resource.":
        for _identity, fields in result:
            if "deploymentEncryption" in fields and (
                fields.get("resourceType") != "S3.Bucket"
                or fields["deploymentEncryption"] != "default"
            ):
                raise InputValidationError(
                    "deploymentEncryption is only default on an S3.Bucket"
                )
            if "cfn-logicalId" in fields:
                cfn_resource_identity(fields["cfn-logicalId"])
    return result


def structural_entries(
    values: dict[str, str], prefix: str
) -> list[tuple[str, dict[str, str]]]:
    memo = None
    if isinstance(values, SnapshotValues):
        memo = memo_table()
    cache_key = (structural_entries, id(values), prefix)
    if memo is not None and cache_key in memo:
        return [(identity, dict(fields)) for identity, fields in memo[cache_key][1]]
    groups: dict[str, dict[str, str]] = {}
    for key, value in values.items():
        if key.startswith(prefix):
            identity, separator, field = key[len(prefix) :].partition(".")
            if not separator:
                raise InputValidationError(f"invalid model entry: {key}")
            groups.setdefault(identity, {})[field] = value
    result = sorted(groups.items())
    if memo is not None:
        # Hold the immutable invocation input so object IDs cannot be recycled.
        memo[cache_key] = (values, result)
        return [(identity, dict(fields)) for identity, fields in result]
    return result


def resource_groups(values):
    """Retain missing and duplicate identities for scoped comparison/resolution."""
    result = {}
    for number, resource in structural_entries(values, "desired.resource."):
        result.setdefault(resource.get("logicalId"), []).append((number, resource))
    return result


def validate_model_keys(values: dict[str, str]) -> None:
    """Expanded Model fields; visibility never determines whether a field is legal."""
    fields = {
        ("desired", "service"): {
            "serviceId",
            "ownedCatalogResourceTypes",
            "lastAllocated",
        },
        ("desired", "resource"): {
            "resourceType",
            "logicalId",
            "anchor",
            "resourceMode",
            "cfn-logicalId",
            "parentProperty",
            "parentReference",
            "deploymentEncryption",
        },
        ("desired", "row"): {"property", "value", "comment", "document", "valueShape"},
        ("observed", "row"): {"value"},
        ("desired", "note"): {"text"},
        ("display", "resource"): {"comment", "label"},
        ("desired", "stack"): {
            "name",
            "template",
            "parameters",
            "deployOrder",
            "placementName",
        },
        ("display", "stack"): {"comment"},
        ("desired", "reference"): {
            "consumerKey",
            "pointer",
            "text",
            "occurrence",
            "producerKind",
            "producerScope",
            "producerId",
            "producerLogicalId",
            "resourceType",
            "format",
            "property",
            "labelPolicy",
            "contextProperty",
            "valueSelector",
        },
        ("desired", "artifact"): set(ARTIFACT_FIELDS),
    }
    singles = {
        "display.service.title",
        "desired.deployment.maxConcurrentStacks",
        "desired.deployment.templateBucket",
        "desired.deployment.templateKeyPrefix",
    }
    for key in values:
        parts = key.split(".")
        if key not in singles and not (
            len(parts) == 4
            and parts[2]
            and parts[3] in fields.get(tuple(parts[:2]), set())
        ):
            raise InputValidationError("unknown Model field: " + key)
        if key.startswith("desired.row.") and key.endswith(".valueShape"):
            value_shape({"valueShape": values[key]})


def validate_stack_field(field, value):
    if field == "deployOrder":
        positive_integer(value, "DeployOrder")
    elif field == "name" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", value):
        raise InputValidationError(f"invalid stack name: {value}")
    elif field in {"template", "parameters"}:
        path = Path(value)
        suffixes = {".yaml", ".yml"} if field == "template" else {".json"}
        if path.name != value or "\\" in value or path.suffix not in suffixes:
            raise InputValidationError(f"invalid stack {field} filename: {value}")


def stack_model(values: dict[str, str]) -> tuple[int, list[tuple[str, dict[str, str]]]]:
    """Validate deployment inputs once for rendering, projection and execution."""
    limit = positive_integer(
        values.get("desired.deployment.maxConcurrentStacks", "1"), "MaxConcurrentStacks"
    )
    stacks = entries(values, "desired.stack.")
    if not stacks:
        raise InputValidationError("stack model is empty")
    names, parameters = set(), set()
    allowed = {"name", "template", "parameters", "deployOrder"}
    for identity, stack in stacks:
        if set(stack) not in (allowed, allowed | {"placementName"}):
            raise InputValidationError(
                f"stack {identity} requires only {sorted(allowed)}"
            )
        for field in allowed:
            validate_stack_field(field, stack[field])
        if stack["name"] in names:
            raise InputValidationError(f"duplicate stack name: {stack['name']}")
        if stack["parameters"] in parameters:
            raise InputValidationError(
                f"parameter file belongs to multiple stacks: {stack['parameters']}"
            )
        names.add(stack["name"])
        parameters.add(stack["parameters"])
    deployment_settings(values)
    unknown = [
        key
        for key in values
        if key.startswith("desired.")
        and not key.startswith(
            (
                "desired.stack.",
                "desired.artifact.",
                "desired.reference.",
                "desired.service.",
                "desired.note.",
            )
        )
        and key
        not in {
            "desired.deployment." + field
            for field in ("maxConcurrentStacks", "templateBucket", "templateKeyPrefix")
        }
    ]
    if unknown:
        raise InputValidationError(f"unknown stack design fields: {unknown}")
    return limit, sorted(
        [
            (identity, {k: v for k, v in stack.items() if k != "placementName"})
            for identity, stack in stacks
        ],
        key=lambda entry: (int(entry[1]["deployOrder"]), entry[1]["name"]),
    )


ARTIFACT_FIELDS = ("stack", "resource", "property", "source", "bucket", "keyPrefix")
ARTIFACT_PROPERTIES = {
    ("AWS::Lambda::Function", "Code"): ("S3Bucket", "S3Key", "S3ObjectVersion"),
    ("AWS::Lambda::LayerVersion", "Content"): ("S3Bucket", "S3Key", "S3ObjectVersion"),
    ("AWS::StepFunctions::StateMachine", "DefinitionS3Location"): (
        "Bucket",
        "Key",
        "Version",
    ),
    ("AWS::ApiGateway::RestApi", "BodyS3Location"): ("Bucket", "Key", "Version"),
    ("AWS::Glue::Job", "Command.ScriptLocation"): None,
}


def deployment_settings(
    values: dict[str, str],
) -> tuple[dict[str, str], list[tuple[str, dict[str, str]]]]:
    settings = {
        field: values["desired.deployment." + field]
        for field in ("templateBucket", "templateKeyPrefix")
        if "desired.deployment." + field in values
    }
    if settings and set(settings) != {"templateBucket", "templateKeyPrefix"}:
        raise InputValidationError(
            "TemplateBucket and TemplateKeyPrefix must be specified together"
        )
    artifacts = entries(values, "desired.artifact.")
    names = {stack.get("name") for _, stack in entries(values, "desired.stack.")}
    destinations = set()
    for identity, artifact in artifacts:
        if set(artifact) != set(ARTIFACT_FIELDS) or not all(artifact.values()):
            raise InputValidationError(
                f"artifact {identity} requires only {list(ARTIFACT_FIELDS)}"
            )
        if artifact["stack"] not in names or not re.fullmatch(
            r"[A-Z][A-Za-z0-9]*", artifact["resource"]
        ):
            raise InputValidationError(f"invalid artifact stack/resource: {identity}")
        if artifact["property"] not in {prop for _, prop in ARTIFACT_PROPERTIES}:
            raise InputValidationError(
                f"unsupported artifact property: {artifact['property']}"
            )
        source = Path(artifact["source"])
        if (
            source.is_absolute()
            or ".." in source.parts
            or "\\" in artifact["source"]
            or not artifact["source"].startswith("infra/cloudformation/artifacts/")
        ):
            raise InputValidationError(
                "artifact source must be a file under infra/cloudformation/artifacts/"
            )
        destination = tuple(
            artifact[field] for field in ("stack", "resource", "property")
        )
        if destination in destinations:
            raise InputValidationError(f"duplicate artifact destination: {destination}")
        destinations.add(destination)
    if settings:
        validate_bucket_reference(settings["templateBucket"])
        validate_key_prefix(settings["templateKeyPrefix"])
    for _, artifact in artifacts:
        validate_bucket_reference(artifact["bucket"])
        validate_key_prefix(artifact["keyPrefix"])
        if any(
            "|" in value or "\n" in value or "\r" in value
            for value in artifact.values()
        ):
            raise InputValidationError("artifact fields must be single table cells")
    return settings, artifacts


def validate_bucket_reference(value: str) -> None:
    if not resource_link(value):
        raise InputValidationError(
            "deployment bucket requires a Markdown Resource reference"
        )


def validate_key_prefix(value: str) -> None:
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/", value)
        or len(value) > 800
    ):
        raise InputValidationError(
            "deployment keyPrefix must be an explicit relative prefix ending in /"
        )


def literal(value: str) -> str:
    return value[1:-1] if value.startswith("`") and value.endswith("`") else value


def validate_stack_metadata(values):
    """Canonical placement identities are checked separately from execution fields."""
    stacks = entries(values, "desired.stack.")
    placements = set()
    for identity, stack in stacks:
        placement = stack.get("placementName")
        if (
            not isinstance(placement, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", placement)
            or placement in placements
        ):
            raise InputValidationError(
                "invalid, missing or duplicate fixed Stack placementName: " + identity
            )
        if any(
            other_id != identity and other.get("name") == placement
            for other_id, other in stacks
        ):
            raise InputValidationError(
                "fixed Stack placementName conflicts with another Stack name: "
                + identity
            )
        placements.add(placement)


def validate_authority(values):
    """Validate the saved schema before adding any runtime-only metadata."""
    validate_model_keys(values)
    for identity, resource in entries(values, "desired.resource."):
        if not re.fullmatch(
            r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+", resource.get("resourceType", "")
        ):
            raise InputValidationError(
                "Resource requires a valid resourceType: " + identity
            )
        if resource.get("resourceMode", "CREATE") not in {"CREATE", "IMPORT"}:
            raise InputValidationError(
                "resourceMode must be CREATE or IMPORT: " + identity
            )
    resource_index(values)
    for identity, row in entries(values, "desired.row."):
        if not {"property", "value", "comment"} <= row.keys():
            raise InputValidationError(
                "Row requires property, value and comment: " + identity
            )
        if "document" in row:
            input_json(row["document"])
    if entries(values, "desired.stack."):
        validate_stack_metadata(values)
        stack_model(values)


def resource_row_index(
    values: dict[str, str],
) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Group rows by their fixed Resource number; reject orphan rows."""
    resources = dict(entries(values, "desired.resource."))
    index = {identity: [] for identity in resources}
    for rid, row in entries(values, "desired.row."):
        owner = rid.rpartition("-")[0]
        if owner not in resources:
            raise InputValidationError(f"orphan desired row: {rid}")
        index[owner].append((rid, row))
    return index


COUNTERS = "desired.service.identity.lastAllocated"


def prefix(kind):
    if (
        not isinstance(kind, str)
        or re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+", kind) is None
    ):
        raise InputValidationError("invalid ResourceType for logicalId: " + str(kind))
    return kind.replace(".", "_")


def sequence(kind, logical):
    head = prefix(kind) + "_"
    suffix = logical.removeprefix(head) if isinstance(logical, str) else ""
    if (
        not isinstance(logical, str)
        or not logical.startswith(head)
        or not re.fullmatch(r"[0-9]{3,}", suffix)
        or int(suffix) < 1
        or suffix != f"{int(suffix):03d}"
    ):
        raise InputValidationError(
            "logicalId requires ResourceType prefix and fixed sequence: " + str(logical)
        )
    return int(suffix)


def counters(values):
    state = input_json(values.get(COUNTERS, "{}"))
    if not isinstance(state, dict):
        raise InputValidationError(
            "lastAllocated must be a ResourceType to integer object"
        )
    prefixes = {}
    for kind, number in state.items():
        if type(number) is not int or number < 0:
            raise InputValidationError(
                "lastAllocated must contain nonnegative integers"
            )
        head = prefix(kind)
        if head in prefixes and prefixes[head] != kind:
            raise InputValidationError(
                "ResourceType logicalId prefix collision: " + head
            )
        prefixes[head] = kind
    return state


def resource_index(values):
    state, result = counters(values), {}
    prefixes = {prefix(kind): kind for kind in state}
    for number, resource in entries(values, "desired.resource."):
        kind, logical = resource["resourceType"], resource.get("logicalId")
        head = prefix(kind)
        if head in prefixes and prefixes[head] != kind:
            raise InputValidationError(
                "ResourceType logicalId prefix collision: " + head
            )
        prefixes[head] = kind
        serial = sequence(kind, logical)
        if logical in result:
            raise ModelNeedsFixError(
                "duplicate logicalId: " + logical,
                code="MODEL_REF_TARGET_AMBIGUOUS",
                targetLogicalId=logical,
                resourceLogicalId=logical,
                modelKey=f"desired.resource.{number}.logicalId",
                resourceIds=[
                    candidate
                    for candidate, fields in entries(values, "desired.resource.")
                    if fields.get("logicalId") == logical
                ],
            )
        if state.get(kind, -1) < serial:
            raise InputValidationError(
                "lastAllocated is missing or behind logicalId: " + logical
            )
        result[logical] = (number, resource)
    return result


def resource_link(value):
    match = LINK.fullmatch(value) if isinstance(value, str) else None
    if match and ":" not in match[2] and (not match[2] or match[2].endswith(".md")):
        return match
    return None
