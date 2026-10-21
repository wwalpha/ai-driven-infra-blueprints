"""Derived execution/display fields; never serialize these into Model authority."""
import hashlib
import json
import re
from pathlib import Path
from validation_cache import input_is_file, input_text, memoized
from model.core import LINK, entries, literal, ReferenceResolutionError, validate_bucket_reference
from design_document import DesignIndex
from design_catalog import design_material_files
from design_layout import HIDDEN_PROPERTIES, RESOURCE

ANCHOR = re.compile(r'^<a\s+id="([^"]+)"\s*></a>$')
JSON_LINK = re.compile(r"^\[[^\]]+\]\(([^)#]+\.json)\)$")
RESOURCE_LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")
REFERENCE_NAME_SUFFIXES = ('.Name', '.RoleName', '.LogGroupName', '.BucketName', '.AliasName',
                         '.GroupName', '.InstanceProfileName', '.FunctionName', '.TrailName',
                         '.QueueName', '.UserName', '.RepositoryName')

def json_sha256(path: Path) -> str:
    content = json.loads(input_text(path, encoding="utf-8"))
    return document_sha256(content)


def document_sha256(content) -> str:
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@memoized
def identifier_outputs(root: Path) -> dict[str, set[str]]:
    outputs: dict[str, set[str]] = {}
    for path in design_material_files(root):
        resource_type = path.stem.replace("_", ".", 1)
        outputs[resource_type] = {
            line.partition("=")[0]
            for line in input_text(path, encoding="utf-8").splitlines()
            if line.endswith("=IDENTIFIER_OUTPUT") and line.partition("=")[0] not in HIDDEN_PROPERTIES
        }
    return outputs


def bound_stack_names(path):
    from model.sources import load_model
    return {stack['placementName']: stack['name']
            for _, stack in entries(load_model(path).authoritative, 'desired.stack.')}


def bound_resource_anchors(path):
    from model.sources import load_model
    path = Path(path).absolute()
    if len(path.parents) >= 5 and path.parents[2].name == 'designs' and path.parents[3].name == 'docs':
        path = path.parents[4] / 'model' / path.parents[1].name / path.parent.name / (path.stem + '.properties')
    if path.suffix != '.properties' or not input_is_file(path):
        return {}
    return {(resource['resourceType'], resource['logicalId']): resource['anchor']
            for _, resource in entries(load_model(path).authoritative, 'desired.resource.')}


def linked_resource(path: Path, value: str, *, design_index: DesignIndex | None = None) -> tuple[str, str] | None:
    match = RESOURCE_LINK.fullmatch(value)
    if not match:
        return None
    _, target_text, fragment = match.groups()
    target = path if not target_text else path.parent / target_text
    if not input_is_file(target):
        return None
    pending_anchor = ""
    view = (design_index or DesignIndex()).get(target).view(frozenset({fragment}))
    identities = view.logical_ids
    lines, _ = view.expanded
    for line in lines:
        if anchor := ANCHOR.fullmatch(line):
            pending_anchor = anchor.group(1)
        elif resource := RESOURCE.fullmatch(line):
            if pending_anchor == fragment:
                return resource.group(1), identities.get(resource.groups(), resource.group(2))
            pending_anchor = ""
    return None


def is_import_expression(prop: str, raw_value: str, design: Path) -> bool:
    """Validate the narrow Model ImportValue notation, not arbitrary CFn/YAML."""
    value = literal(raw_value)
    link = re.fullmatch(r"\[([^\]]+)\]\(([^)]*)\)", value)
    expression = link[1] if link else value
    hosted_zone = prop == 'Route53.RecordSet.AliasTarget.HostedZoneId'
    if not (expression.startswith(('Fn::', 'Ref:')) or
            hosted_zone and ('Fn::' in value or '${' in value or expression.startswith('!')) or
            hosted_zone and value.startswith('[') and LINK.fullmatch(value) is None):
        return False
    if (not hosted_zone or
            re.fullmatch(r'Fn::ImportValue: [A-Z][A-Za-z0-9]*\$\{Suffix\}', expression) is None):
        raise ValueError('invalid or unsupported Model ImportValue expression: ' + prop)
    if link:
        if raw_value != value or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*\.md', link[2]) is None:
            raise ValueError('ImportValue link requires a same-target service Markdown filename')
        target = (design.parent / link[2]).resolve()
        if target.parent != design.parent.resolve() or not input_is_file(target):
            raise ValueError('ImportValue link requires an existing same-target service design: ' + link[2])
    return True


def reference_attribute(kind: str, attribute: str) -> str:
    """Map proven Model attributes to provider attributes, never GetAtt aliases."""
    # Ref/GetAtt Id return the Secret ARN; ManagedPolicy uses PolicyArn, not Arn.
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-secretsmanager-secret.html
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-managedpolicy.html
    return {"SecretsManager.Secret": "Id", "IAM.ManagedPolicy": "PolicyArn"}.get(kind, attribute) if attribute == "Arn" else attribute


def deployment_bucket(reference: str, path: Path, root: Path) -> str:
    """Resolve the confirmed name from the referenced authoritative S3 model."""
    from model.sources import load_model
    validate_bucket_reference(reference)
    link = LINK.fullmatch(reference)
    target_path = path.parent.relative_to(root / "docs/designs")
    source = root / "model" / target_path / "s3.properties"
    if not input_is_file(source):
        raise ReferenceResolutionError("deployment bucket requires an existing authoritative S3 model",
                                       source=str(source), reference=reference)
    values = load_model(source).authoritative
    resources = [(identity, resource) for identity, resource in entries(values, "desired.resource.")
                 if resource.get("resourceType") == "S3.Bucket" and resource.get("anchor") == link.group(3)]
    if len(resources) != 1:
        raise ReferenceResolutionError("deployment bucket reference must identify one S3.Bucket")
    rows = entries(values, "desired.row.")
    names = [literal(row.get("value", "")) for identity, row in rows
             if identity.startswith(resources[0][0] + "-") and row.get("property") == "S3.Bucket.BucketName"]
    if len(names) != 1 or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", names[0]) or link.group(1) != names[0]:
        raise ReferenceResolutionError("deployment bucket requires the matching confirmed BucketName")
    return names[0]


@memoized
def catalog_outputs(root: Path, kind: str) -> set[str]:
    from utils.aws_catalogs import catalogs_for
    return set(catalogs_for(root).outputs(kind)) - HIDDEN_PROPERTIES


def observed_value(row_id, row, observed, outputs):
    from model.importing.sources import has_reference
    value = row['value']
    if observed is not None:
        if link := LINK.fullmatch(value):
            value = observed if row['property'] in outputs else f"[{literal(observed)}]({link.group(2)}#{link.group(3)})"
        elif has_reference(value):
            pass  # Structured link labels retain their native string/list shape.
        else:
            raise ValueError(f"observed value requires a desired logical reference: {row_id}")
    return value


def resource_rows(values: dict[str, str], identity: str, kind: str, root: Path) -> list[list[str]]:
    outputs = catalog_outputs(root, kind)
    rows = []
    for row_id, row in entries(values, "desired.row."):
        if not row_id.startswith(identity + "-"):
            continue
        if set(row) - {"property", "value", "comment", "artifactSha256", "document"} or not {"property", "value", "comment"} <= row.keys():
            raise ValueError(f"invalid resource row: {row_id}")
        observed = values.get(f"observed.row.{row_id}.value")
        value = observed_value(row_id, row, observed, outputs)
        rows.append([row_id, row["property"], value, row["comment"]])
    return rows


def design_target(path: Path, root: Path) -> dict:
    project = root / "project.json"
    if input_is_file(project) and path.is_relative_to(root / "docs/designs"):
        relative = path.parent.relative_to(root / "docs/designs")
        if len(relative.parts) == 2:
            environment, directory = relative.parts
            return next((item for item in json.loads(input_text(project, encoding="utf-8")).get("targets", [])
                         if item.get("environment") == environment and item.get("alias", item.get("awsAccountId")) == directory), {})
    return {}


def resource_display_rows(values: dict[str, str], identity: str, resource: dict[str, str], root: Path) -> list[list[str]]:
    """Include a Key's own grouped aliases when resolving its display name."""
    rows = resource_rows(values, identity, resource["resourceType"], root)
    if resource["resourceType"] == "KMS.Key":
        for child_id, child in entries(values, "desired.resource."):
            link = LINK.fullmatch(child.get("parentReference", ""))
            if child["resourceType"] == "KMS.Alias" and link and not link.group(2) and link.group(3) == resource["anchor"]:
                rows += resource_rows(values, child_id, child["resourceType"], root)
    return rows

