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



def scalar_reference(row):
    """Decode the existing JSON scalar only at explicitly enabled properties."""
    from reference_contracts import SCALAR_REFERENCE_PROPERTIES
    from model.references import _json
    from model.identity import resource_link
    prop = re.sub(r'\[\d+\]', '[]', row['property'])
    if prop not in SCALAR_REFERENCE_PROPERTIES or 'document' in row:
        return None
    value, structured = _json('desired.row.scalar.value', row['value'])
    if not structured:
        return None
    if (not isinstance(value, dict) or set(value) != {'$resource', '$attribute'} or
            not resource_link(value['$resource']) or value['$attribute'] != SCALAR_REFERENCE_PROPERTIES[prop][1]):
        raise ValueError('scalar Resource reference requires a Resource link and explicit Arn: ' + prop)
    return value


def scalar_reference_operand(row, root, scope, *, resolver=None):
    """Resolve scalar intent without acquiring or deriving any physical value."""
    from reference_contracts import SCALAR_REFERENCE_PROPERTIES
    from model.identity import Resolver
    selector = scalar_reference(row)
    if selector is None:
        return None
    operand = (resolver or Resolver(root)).operand(selector['$resource'], scope,
        attribute=selector['$attribute'], field=row['property'])
    snapshot, _, resource, attribute = operand
    expected = SCALAR_REFERENCE_PROPERTIES[re.sub(r'\[\d+\]', '[]', row['property'])]
    if ((resource['resourceType'], attribute) != expected or
            (snapshot.scope.environment, snapshot.scope.target) != (scope.environment, scope.target)):
        raise ReferenceResolutionError('scalar Arn reference requires a same-target KMS.Key', reference=selector['$resource'])
    return operand


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
    for row_id, row in entries(values, 'desired.row.'):
        operand = scalar_reference_operand(row, root, scope, resolver=resolver)
        if operand is not None:
            snapshot, number, resource, _ = operand
            from model.render import resource_presentation
            from model.identity import address
            name, _, _ = resource_presentation(snapshot.values, number, resource,
                definitions_root or root, scope=snapshot.scope)
            result[f'desired.row.{row_id}.value'] = address(snapshot.scope, resource, consumer_scope=scope, label=name)
    return result


def document_references(document, root, *, property_name=None, resolver=None, scope=None, resolve=None):
    """One JSON reference walk for semantic validation and execution projection."""
    from model.identity import Resolver, resource_link, reference_tokens
    resolver = resolver or Resolver(root)

    def reference(uri, attribute, field, original):
        operand = resolver.operand(uri, scope, attribute=attribute, field=field)
        return resolve(*operand, uri) if resolve else original

    def visit(value, field):
        if isinstance(value, str):
            if field and field.rsplit('.', 1)[-1] in {'Description', 'description'}:
                return value
            if value.startswith('resource://'):
                raise ReferenceResolutionError('unsupported saved Resource reference syntax')
            if resource_link(value):
                return reference(value, None, field, value)
            if any(reference_tokens(value)):
                raise ReferenceResolutionError('embedded Resource reference requires an explicit JSON operand')
            return value
        if isinstance(value, list):
            return [visit(item, field + '[]' if field else None) for item in value]
        if isinstance(value, dict):
            if '$resource' in value:
                if (set(value) - {'$resource', '$attribute'} or not resource_link(value['$resource']) or
                        '$attribute' in value and (not isinstance(value['$attribute'], str) or not value['$attribute'])):
                    raise ValueError('invalid structured Resource reference')
                return reference(value['$resource'], value.get('$attribute'), field, value)
            if '$attribute' in value:
                raise ValueError('Resource attribute requires $resource')
            return {key: visit(child, field + '.' + key if field else key) for key, child in value.items()}
        return value
    return visit(document, property_name)


def confirmed_property(snapshot, number, kind, attribute, uri, resolver):
    """Select one authoritative Row before evaluating its desired/observed value."""
    from model.importing.references import known
    from model.identity import resource_link
    rows = [(rid, row) for rid, row in entries(snapshot.authoritative, 'desired.row.')
            if rid.rpartition('-')[0] == number and row['property'] == kind + '.' + attribute]
    if len(rows) == 1:
        rid, row = rows[0]
        observed = snapshot.authoritative.get(f'observed.row.{rid}.value')
        if observed is not None:
            if not resource_link(row['value']):
                raise ReferenceResolutionError('JSON observed output requires a logical Resource reference', reference=uri)
            resolver.resolve(row['value'], snapshot.scope)
        value = literal(observed if observed is not None else row.get('value', ''))
        if known(value):
            return value
    raise ReferenceResolutionError('JSON Resource reference requires one confirmed output: ' + kind + '.' + attribute, reference=uri)


def execution_document(document, root, *, property_name=None, resolver=None, scope=None):
    """Resolve confirmed JSON operands; unresolved values cannot become AWS artifacts."""
    from reference_contracts import ARN_SHAPES, ARN_FORMS
    from model.sources import target_for
    from model.identity import Resolver
    resolver = resolver or Resolver(root)

    def reference(snapshot, number, resource, attribute, uri):
        kind = resource['resourceType']
        if attribute == 'Arn' or (kind, attribute) in ARN_FORMS:
            if attribute != 'Arn' or kind not in ARN_SHAPES:
                raise ReferenceResolutionError('JSON Resource ARN form cannot be derived: ' + kind + '.' + attribute, reference=uri)
            identity, template, patterns = ARN_SHAPES[kind]
            fields = identity if isinstance(identity, dict) else {identity: 'id'}
            parts = {group: confirmed_property(snapshot, number, kind, prop, uri, resolver) for prop, group in fields.items()}
            from design_catalog import DesignSchemaCatalog
            catalog = DesignSchemaCatalog(root)
            if any(catalog.literal_errors(kind, prop, parts[group]) for prop, group in fields.items()):
                raise ReferenceResolutionError('invalid JSON Resource ARN identifier: ' + kind, reference=uri)
            if any(re.fullmatch(patterns[group], value) is None for group, value in parts.items()):
                raise ReferenceResolutionError('invalid JSON Resource ARN identifier: ' + kind, reference=uri)
            if kind == 'S3.Bucket':
                name = parts['id']
                if ('..' in name or re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', name) or
                        name.startswith(('xn--', 'sthree-', 'amzn-s3-demo-')) or
                        name.endswith(('-s3alias', '--ol-s3', '.mrap', '--x-s3', '--table-s3'))):
                    raise ReferenceResolutionError('invalid JSON Resource BucketName', reference=uri)
                for rid, row in entries(snapshot.authoritative, 'desired.row.'):
                    if rid.rpartition('-')[0] != number and row['property'] == 'S3.Bucket.BucketName':
                        value = snapshot.authoritative.get(f'observed.row.{rid}.value', row['value'])
                        if literal(value) == name:
                            raise ReferenceResolutionError('JSON Resource ARN requires a unique BucketName', reference=uri)
            target, _ = target_for(snapshot.scope, resolver.reads)
            from botocore.session import get_session
            from botocore.exceptions import UnknownRegionError
            session = get_session()
            try:
                partition = session.get_partition_for_region(target['awsRegion'])
            except UnknownRegionError as error:
                raise ReferenceResolutionError('unknown JSON Resource AWS partition', reference=uri) from error
            # SDK regex fallbacks also accept invented regions; require a recorded region.
            if not any(item['partition'] == partition and target['awsRegion'] in item['regions']
                       for item in session.get_data('endpoints')['partitions']):
                raise ReferenceResolutionError('JSON Resource ARN requires a confirmed Region', reference=uri)
            return template.format(partition=partition, region=target['awsRegion'],
                                   account=target.get('awsExecutionAccountId', target['awsAccountId']), **parts)
        return confirmed_property(snapshot, number, kind, attribute, uri, resolver)

    return document_references(document, root, property_name=property_name, resolver=resolver, scope=scope, resolve=reference)
