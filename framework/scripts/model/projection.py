"""Derived execution/display fields; never serialize these into Model authority."""
from utils.json_format import document_sha256
from contextlib import contextmanager
from contextvars import ContextVar
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
    from model.identity import display_anchor
    return {(resource['resourceType'], resource['logicalId']): display_anchor(resource)
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
                return resource.group(1), identities.get(pending_anchor, resource.group(2))
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
    from model.identity import Resolver, parse_reference
    validate_bucket_reference(reference)
    from model.sources import scope_for
    snapshot, identity, resource = Resolver(root).resolve(reference, scope_for((root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties') if path.is_relative_to(root / 'docs/designs') else path))
    if resource['resourceType'] != 'S3.Bucket':
        raise ReferenceResolutionError('deployment bucket must identify one S3.Bucket')
    rows = entries(snapshot.authoritative, 'desired.row.')
    names = [literal(row.get('value', '')) for rid, row in rows
             if rid.rpartition('-')[0] == identity and row.get('property') == 'S3.Bucket.BucketName']
    if len(names) != 1 or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', names[0]):
        raise ReferenceResolutionError('deployment bucket requires one confirmed BucketName')
    return names[0]


@memoized
def catalog_outputs(root: Path, kind: str) -> set[str]:
    from utils.aws_catalogs import catalogs_for
    return set(catalogs_for(root).outputs(kind)) - HIDDEN_PROPERTIES


def observed_value(row_id, row, observed, outputs):
    from model.importing.sources import has_reference
    from model.references import LINKS
    value = row['value']
    if observed is not None:
        if link := LINK.fullmatch(value):
            value = observed if row['property'] in outputs else f"[{literal(observed)}]({link.group(2)}#{link.group(3)})"
        elif has_reference(value) or LINKS.search(value):
            pass  # Structured link labels retain their native string/list shape.
        else:
            raise ValueError(f"observed value requires a desired logical reference: {row_id}")
    return value


_resource_row_cache = ContextVar("resource_row_cache", default=None)


@contextmanager
def resource_row_scope():
    """Reuse parsed rows only within one generation, including nested invocations."""
    token = _resource_row_cache.set({})
    try:
        yield
    finally:
        _resource_row_cache.reset(token)


def _resource_row_entries(values):
    cache = _resource_row_cache.get()
    if cache is None:
        return entries(values, "desired.row.")
    key = id(values)
    signature = tuple(values.items())
    previous = cache.get(key)
    if previous is None or previous[1] != signature:
        # Parse a fresh snapshot so the shared immutable-input memo cannot hide edits.
        parsed = entries(dict(signature), "desired.row.")
        cache[key] = (values, signature, parsed)
    return cache[key][2]


def resource_rows(values: dict[str, str], identity: str, kind: str, root: Path) -> list[list[str]]:
    outputs = catalog_outputs(root, kind)
    rows = []
    for row_id, row in _resource_row_entries(values):
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


def resource_display_rows(values: dict[str, str], identity: str, resource: dict[str, str], root: Path, *, scope=None) -> list[list[str]]:
    """Include a Key's own grouped aliases when resolving its display name."""
    rows = resource_rows(values, identity, resource["resourceType"], root)
    if resource["resourceType"] == "KMS.Key":
        for child_id, child in entries(values, "desired.resource."):
            from model.identity import parse_reference
            parent = child.get('parentReference', '')
            link = LINK.fullmatch(parent)
            same = (link is not None and link[3] == resource['anchor'] and
                    (not link[2] or scope is not None and parse_reference(parent, scope)[:3] ==
                     (scope.environment, scope.target, scope.service)))
            if child['resourceType'] == 'KMS.Alias' and same:
                rows += resource_rows(values, child_id, child["resourceType"], root)
    return rows



def reference_display(values, path, root, *, definitions_root=None):
    """Preserve saved links/anchors and project only execution documents for display."""
    from model.identity import Resolver
    from model.sources import scope_for
    model_path = (root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties') if path.is_relative_to(root / 'docs/designs') else path
    scope = scope_for(model_path)
    resolver = Resolver(root)
    result = dict(values)
    for key, value in values.items():
        if key.startswith('desired.row.') and key.endswith('.document'):
            projected = execution_document(json.loads(value), root,
                property_name=values[key.removesuffix('document') + 'property'], resolver=resolver, scope=scope)
            result[key] = json.dumps(projected, ensure_ascii=False)
            result[key.removesuffix('document') + 'artifactSha256'] = document_sha256(projected)
    return result


def execution_document(document, root, *, property_name=None, resolver=None, scope=None):
    """Resolve confirmed JSON operands; unresolved values cannot become AWS artifacts."""
    from model.identity import Resolver, resource_link, reference_tokens
    resolver = resolver or Resolver(root)

    def reference(uri, attribute=None, field=None):
        snapshot, number, resource = resolver.resolve(uri, scope)
        if attribute is None:
            from reference_contracts import contract
            forms = contract(field).get(resource['resourceType'], ()) if field else ()
            if len(forms) != 1:
                raise ReferenceResolutionError('JSON Resource reference requires an explicit attribute', reference=uri)
            attribute, = forms
        matches = []
        for rid, row in entries(snapshot.authoritative, 'desired.row.'):
            if rid.rpartition('-')[0] != number:
                continue
            if row['property'] != resource['resourceType'] + '.' + attribute:
                continue
            value = snapshot.authoritative.get(f'observed.row.{rid}.value', row.get('value'))
            if value is not None and not resource_link(value) and literal(value) not in {'', 'UNSET', 'PENDING_DEPLOY'}:
                matches.append(literal(value))
        if len(matches) != 1:
            raise ReferenceResolutionError('JSON Resource reference requires one confirmed output', reference=uri)
        return matches[0]

    def visit(value, field):
        if isinstance(value, str):
            if field and field.rsplit('.', 1)[-1] in {'Description', 'description'}:
                return value
            if value.startswith('resource://'):
                raise ReferenceResolutionError('unsupported saved Resource reference syntax')
            if resource_link(value):
                return reference(value, field=field)
            if any(reference_tokens(value)):
                raise ReferenceResolutionError('embedded Resource reference requires an explicit JSON operand')
            return value
        if isinstance(value, list):
            return [visit(item, field + '[]' if field else None) for item in value]
        if isinstance(value, dict):
            if '$resource' in value:
                if set(value) - {'$resource', '$attribute'}:
                    raise ValueError('invalid structured Resource reference')
                return reference(value['$resource'], value.get('$attribute'))
            return {key: visit(child, field + '.' + key if field else key) for key, child in value.items()}
        return value
    return visit(document, property_name)
