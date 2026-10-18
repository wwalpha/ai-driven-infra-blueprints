"""Resolve local authoritative inputs and desired/observed display rows; reads files."""
from validation_cache import input_exists, input_is_file, input_text

import json
import re
from pathlib import Path
from model_core import properties, entries, validate_bucket_reference, LINK, literal
from design_layout import HIDDEN_PROPERTIES
from validation_cache import memoized


def reference_attribute(kind: str, attribute: str) -> str:
    """Map proven Model attributes to provider attributes, never GetAtt aliases."""
    # Ref/GetAtt Id return the Secret ARN; ManagedPolicy uses PolicyArn, not Arn.
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-secretsmanager-secret.html
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-managedpolicy.html
    return {"SecretsManager.Secret": "Id", "IAM.ManagedPolicy": "PolicyArn"}.get(kind, attribute) if attribute == "Arn" else attribute


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
def catalog_outputs(root: Path, kind: str) -> set[str]:
    from utils.aws_catalogs import catalogs_for
    return set(catalogs_for(root).outputs(kind)) - HIDDEN_PROPERTIES


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
            elif '<<' in value:
                value += ' (observed: ' + observed + ')'
            else:
                raise ValueError(f"observed value requires a desired logical reference: {row_id}")
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


@memoized
def bound_stack_names(path: Path) -> dict[str, str]:
    """Validated placement names identify fixed entries, independently of desired names."""
    from model_files import load_model
    from model_templates import service_source, json_read
    registered = service_source(path)
    if registered is None:
        return {}
    model = load_model(path)
    bindings = json_read(model.files[registered[2] / 'bindings.json'])
    return {name: model.values[f'desired.stack.{identity}.name']
            for identity, name in bindings.get('stacks', {}).items()}


@memoized
def bound_resource_anchors(path: Path) -> dict[tuple[str, str], str]:
    """Only validated, explicitly internal YAML bindings may outlive a name change."""
    from model_templates import service_source, load_expansion, parse_template, source_paths
    path = path.absolute()
    if len(path.parents) >= 5 and path.parents[2].name == "designs" and path.parents[3].name == "docs":
        path = path.parents[4] / "model" / path.parents[1].name / path.parent.name / (path.stem + ".properties")
    paths = source_paths(path)
    if paths is None or not input_exists(paths[2]):
        return {}
    registered = service_source(path)
    if registered is None:
        return {}
    expansion = load_expansion(path)
    definitions = parse_template(registered[1])[0]
    anchors = {}
    for identity, resource in entries(expansion.values, "desired.resource."):
        source = expansion.provenance[f"desired.resource.{identity}.anchor"]
        definition = definitions[source["definition"]]
        raw = definition.values[source["key"]]
        if any(raw == "<<" + name + ">>" for name in source.get("internalParameters", [])):
            anchor = resource["anchor"]
            if not re.fullmatch(re.escape(path.stem) + r"-[a-z0-9_.-]+", anchor):
                raise ValueError(f"invalid bound resource anchor: {anchor}")
            anchors[resource["resourceType"], resource["logicalId"]] = anchor
    return anchors
