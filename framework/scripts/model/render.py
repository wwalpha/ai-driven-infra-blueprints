"""Render detailed designs from authoritative service properties."""

from __future__ import annotations

import json
from collections import Counter
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

import array_display as _dependency_array_display
import aws_mapping_display as _dependency_aws_mapping_display
import aws_mapping_display as _imports_aws_mapping_display
import design_layout as _dependency_design_layout
import policy_tables as _dependency_policy_tables
import policy_tables as _imports_policy_tables
from design_catalog import (
    DesignSchemaCatalog as DesignSchemaCatalog,
)
from sync_files import changed_files
from utils.aws_catalogs import catalog_outputs as catalog_outputs
from utils.input_cache import (
    input_bytes,
    input_is_file,
    input_recorder,
    input_scope,
    input_select,
    recording_inputs,
)
from utils.json_format import policy_json
from utils.layout_schema import (
    GROUPED,
    HIDDEN_PROPERTIES,
    LAMBDA_PERMISSION,
    ROTATION_SCHEDULE,
    SUBNET_LIST_SOURCE,
)
from utils.layout_schema import resource_anchor as resource_anchor

import model.display as _dependency_model_display
import model.files as _imports_model_files
import model.identity as _imports_model_identity
import model.projection as _dependency_model_projection
import model.projection as _imports_model_projection
import model.sources as _dependency_model_sources
import model.sources as _imports_model_sources
import model.validation as _dependency_model_validation
import model.validation as _imports_model_validation
from model.core import (
    ARTIFACT_FIELDS,
    LINK,
    ReferenceResolutionError,
    deployment_settings,
    entries,
    stack_model,
)
from model.core import (
    properties as properties,
)
from model.format import JSON_LINK


def stack_markdown(path, values, root, *, definitions_root=None):
    reference_display = _imports_model_projection.reference_display
    limit, stacks = stack_model(values)
    settings, artifacts = deployment_settings(values)
    displayed = reference_display(values, path, root, definitions_root=definitions_root)
    display_artifacts = dict(entries(displayed, 'desired.artifact.'))
    delivery = []
    if artifacts:
        delivery = ["", "## S3配置", "", "### 配置ファイル", "",
            "| No. | StackName | Resource | Property | Source | Bucket | KeyPrefix |",
            "| ---: | --- | --- | --- | --- | --- | --- |"]
        delivery += ["| " + " | ".join([str(number)] + [display_artifacts[identity][field] for field in ARTIFACT_FIELDS]) + " |"
                     for number, (identity, artifact) in enumerate(artifacts, 1)]
    if settings:
        _dependency_model_projection.deployment_bucket(settings["templateBucket"], path, root)
    for _, artifact in artifacts:
        _dependency_model_projection.deployment_bucket(artifact["bucket"], path, root)
    return "\n".join(["# CloudFormation stack 詳細設計", "",
        f"<!-- max-concurrent-stacks: {limit} -->", "",
        *[f"<!-- {field}: {value} -->" for field, value in settings.items()],
        "## Stack一覧", "", "| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |",
        "| ---: | ---: | --- | --- | --- | --- |", *[
            "| " + " | ".join([str(number), stack["deployOrder"], stack["name"], stack["template"],
                stack["parameters"], values[f"display.stack.{identity}.comment"]]) + " |"
            for number, (identity, stack) in enumerate(stacks, 1)], *delivery]) + "\n"


def display_name(values, identity, resource, rows, root):
    """Pure final display selection, shared by rendering and reference diagnostics."""
    kind = resource['resourceType']
    label = values.get(f'display.resource.{identity}.label')
    if GROUPED.get(kind, {}).get('display') == 'rule-table':
        return label or resource['logicalId'], None
    mode = _dependency_design_layout.resource_mode(resource)
    if mode == 'IMPORT' and kind not in {'IAM.Role', 'CodeBuild.Project'}:
        # Resolve a saved self-reference from its observation, never from its link label.
        local = {''} | {value + '.md' for key, value in values.items()
                        if key.startswith('desired.service.') and key.endswith('.serviceId')}
        rows = [list(row) for row in rows]
        for row in rows:
            field = row[1].removeprefix(kind + '.')
            link = LINK.fullmatch(row[2])
            if field in _dependency_design_layout.resource_name_fields(kind) and link and link[2] in local and link[3] == resource['anchor']:
                matches = [rid for rid, item in entries(values, 'desired.row.') if rid.startswith(identity + '-')
                           and item.get('property') == kind + '.' + field
                           and (source_link := LINK.fullmatch(item.get('value', '')))
                           and source_link.groups()[1:] == link.groups()[1:]]
                if len(matches) == 1:
                    row[2] = values.get(f'observed.row.{matches[0]}.value', row[2])
    count = sum(item['resourceType'] == kind for _, item in entries(values, 'desired.resource.'))
    return _dependency_design_layout.resource_display_selection(root, kind, rows, label, mode, count)


def resource_presentation(values, identity, resource, root, *, scope=None):
    kind = resource['resourceType']
    rows = _dependency_model_display.catalog_display_rows(_dependency_model_projection.resource_rows(values, identity, kind, root), kind, root)
    name, configured = display_name(values, identity, resource,
                                    _dependency_model_projection.resource_display_rows(values, identity, resource, root, scope=scope), root)
    return name, configured, rows


def _callback_resource_details_inspect(_state_resource_details_122, by_anchor, details, names, owned, root, scope, values, /):
    display_anchor = _imports_model_identity.display_anchor
    pass
    kind = _state_resource_details_122.resource["resourceType"]
    if kind not in owned:
        raise ValueError(f"resource is outside service ownership: {kind}")
    name, configured_name, rows = resource_presentation(values, _state_resource_details_122.identity, _state_resource_details_122.resource, root, scope=scope)
    if configured_name is None and name is None:
        raise ValueError(f"resource type display requires a single nameless independent resource: {kind}")
    if not name or name in {"UNSET", "PENDING_DEPLOY"}:
        raise ValueError(f"confirmed resource display label is missing: {kind}: {_state_resource_details_122.identity}")
    anchor = display_anchor(_state_resource_details_122.resource)
    _state_resource_details_122.resource = {**_state_resource_details_122.resource, 'anchor': anchor}
    derived = anchor
    if anchor in by_anchor:
        raise ReferenceResolutionError('duplicate Resource display anchor: ' + anchor)
    names.add(derived)
    item = (_state_resource_details_122.identity, _state_resource_details_122.resource, name, rows)
    by_anchor[anchor] = item
    details.append(item)


def resource_details(values, root, service, owned, resources, bound_anchors, *, findings=None, scope=None):
    _state_resource_details_122 = _CallbackState()
    by_anchor = {}
    names = set()
    details = []
    for _state_resource_details_122.identity, _state_resource_details_122.resource in resources:
        inspect = _bind_framework_callback(_callback_resource_details_inspect, _state_resource_details_122, by_anchor, details, names, owned, root, scope, values)
        if findings is None:
            inspect()
        else:
            findings.evaluate('model.resource.' + _state_resource_details_122.identity, None, inspect)
    return details, by_anchor


def grouped_resources(values, details, by_anchor, *, scope=None):
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
        parse_reference = _imports_model_identity.parse_reference
        local = link and (not link[2] or scope is not None and parse_reference(link[0], scope)[:3] == (scope.environment, scope.target, scope.service))
        parent = by_anchor.get(link[3]) if local else None
        if resource['parentProperty'] != kind + '.' + rule['parentProperty']:
            raise ValueError('invalid grouped parentProperty: ' + identity)
        if not parent or parent[1]['resourceType'] != rule['parent']:
            raise ReferenceResolutionError(f"{kind}: {resource['logicalId']}: invalid grouped parent: parentReference / parentProperty ({kind}.{rule['parentProperty']})")
        if kind in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
            parent_rows = [row for row_id, row in entries(values, "desired.row.")
                           if row_id.startswith(identity + "-") and row.get("property") == resource["parentProperty"]]
            if len(parent_rows) != 1:
                raise ValueError(f"{kind}: {resource['logicalId']}: {resource['parentProperty']} requires exactly one formal row matching parentReference")
            row_link = LINK.fullmatch(parent_rows[0].get('value', ''))
            same = (parse_reference(row_link[0], scope) == parse_reference(link[0], scope) if scope is not None and row_link else
                    bool(row_link and row_link[3] == link[3] and not row_link[2] and not link[2]))
            if not same:
                raise ReferenceResolutionError('grouped formal row does not match parentReference', resource=identity, property=resource['parentProperty'])
            if kind + ".Id" not in HIDDEN_PROPERTIES and (not rows or rows[0][1] != kind + ".Id"):
                raise ValueError(f"{kind}: {resource['logicalId']}: required first property: {kind}.Id")
        grouped.setdefault(parent[0], []).append(item)
        maximum = rule["maxCount"]
        if maximum is not None and sum(child[1]["resourceType"] == kind for child in grouped[parent[0]]) > maximum:
            raise ValueError(f"{kind}: {resource['logicalId']}: too many grouped children for {parent[1]['logicalId']}: {resource['parentProperty']}")
    return grouped


def resource_table_lines(resource, name, rows, children, root):
    expected = Counter(row[0] for row in _dependency_aws_mapping_display.selected_rows(rows, root))
    for _, _, _, child_rows in children:
        expected.update(row[0] for row in _dependency_aws_mapping_display.selected_rows(child_rows, root))
    if any(count != 1 for count in expected.values()):
        raise ValueError("duplicate selected Model row IDs")
    consumed = []
    output = []
    kind = resource["resourceType"]
    if kind == "EC2.SecurityGroup":
        rules = [(child, _dependency_aws_mapping_display.selected_rows(child_rows, root)) for _, child, _, child_rows in children]
        output += _dependency_model_display.sg_tables(_dependency_aws_mapping_display.selected_rows(rows, root), [(child, rows) for child, rows in rules if rows], root, consumed=consumed)
    else:
        display = display_rows(kind, rows, root, mode=_dependency_design_layout.resource_mode(resource), consumed=consumed)
        for _, child, child_name, child_rows in children:
            child_rows = _dependency_aws_mapping_display.selected_rows(child_rows, root)
            if not child_rows:
                continue
            if child["resourceType"] == ROTATION_SCHEDULE:
                child_rows = [[rid, prop, f'[{name}](#{resource["anchor"]})' if prop == child["parentProperty"] else value, comment]
                              for rid, prop, value, comment in child_rows]
            child_display = display_rows(kind if child["resourceType"] == ROTATION_SCHEDULE else child["resourceType"], child_rows, root, mode=_dependency_design_layout.resource_mode(child), consumed=consumed)
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
        display = _dependency_array_display.indexed_rows(display, kind, root)
        output += _dependency_model_display.row_table(display)
    if Counter(consumed) != expected:
        raise ValueError("selected display rows were omitted or consumed more than once")
    return output


@input_scope
def markdown_for(path: Path, values: dict[str, str], root: Path, *, definitions_root: Path | None = None) -> str:
    """Validated generation used by ordinary design and explicit validation."""
    validate_mappings = _imports_aws_mapping_display.validate_mappings
    validate_mappings(values, definitions_root or root)
    _dependency_model_validation.validate_required_properties(values, definitions_root or root)
    return render_validated_model(path, values, root, definitions_root=definitions_root)


def render_validated_model(path: Path, values: dict[str, str], root: Path, *, definitions_root: Path | None = None) -> str:
    """Internal renderer after mapping/required-property preflight, before artifacts."""
    reference_display = _imports_model_projection.reference_display
    scope_for = _imports_model_sources.scope_for
    validate_json_settings = _imports_model_validation.validate_json_settings
    model_path = (root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties')
    validate_json_settings(values, model_path)
    if path.stem == "cloudformation-stacks":
        return stack_markdown(path, values, root, definitions_root=definitions_root)
    values = reference_display(values, path, root, definitions_root=definitions_root)
    service = path.stem
    if values.get(f"desired.service.{service}.serviceId") != service:
        raise ValueError(f"service ID must equal file stem: {path.name}")
    owned = values[f"desired.service.{service}.ownedCatalogResourceTypes"].split(",")
    resources = entries(values, "desired.resource.")
    if not resources:
        raise ValueError(f"service model has no resources: {path.name}")
    _dependency_model_validation.validate_resource_identities(path, values, root, resources, definitions_root=definitions_root)
    scope = scope_for((root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties'))
    details, by_anchor = resource_details(values, definitions_root or root, service, owned, resources, _dependency_model_projection.bound_resource_anchors(path), scope=scope)
    return render_markdown(path, values, definitions_root or root, owned, details, grouped_resources(values, details, by_anchor, scope=scope))


@input_scope
def generate_markdown(path: Path, values: dict[str, str], root: Path) -> str:
    """Render the selected service without deciding whether its design is correct."""
    reference_display = _imports_model_projection.reference_display
    scope_for = _imports_model_sources.scope_for
    validate_json_settings = _imports_model_validation.validate_json_settings
    validate_json_settings(values, (path.parents[4] / 'model' / path.relative_to(path.parents[4] / 'docs/designs')).with_suffix('.properties'))
    values = reference_display(values, path, path.parents[4], definitions_root=root)
    service = path.stem
    owned = values.get(f"desired.service.{service}.ownedCatalogResourceTypes", "").split(",")
    details = []
    for identity, resource in entries(values, "desired.resource."):
        kind = resource["resourceType"]
        Scope = _imports_model_sources.Scope
        scope = Scope(path.parents[4], path.parent.parent.name, path.parent.name, path.stem)
        name, _, rows = resource_presentation(values, identity, resource, root, scope=scope)
        name = name or kind
        display_anchor = _imports_model_identity.display_anchor
        resource = {**resource, 'anchor': display_anchor(resource)}
        details.append((identity, resource, name, rows))
    by_anchor = {item[1]["anchor"]: item for item in details}
    scope = scope_for((path.parents[4] / 'model' / path.relative_to(path.parents[4] / 'docs/designs')).with_suffix('.properties'))
    grouped = grouped_resources(values, details, by_anchor, scope=scope)
    return render_markdown(path, values, root, owned, details, grouped, model_policy_views(values))


def render_markdown(path, values, root, owned, details, grouped, policy_views=None):
    service = path.stem
    children = {item[0] for items in grouped.values() for item in items}
    independent = [item for item in details if item[0] not in children]
    output = [values["display.service.title"], "", f"- Design service ID: `{service}`",
              "- Owned catalog resource types: " + ", ".join(f"`{kind}`" for kind in owned)]
    output += ["", "## リソース一覧"]
    for kind in dict.fromkeys(item[1]["resourceType"] for item in independent):
        items = [item for item in independent if item[1]["resourceType"] == kind]
        output += ["", "### " + kind, "", *_dependency_policy_tables.table(["No.", "ResourceName", "Comment"], [
            [str(number), f'[{name}](#{resource["anchor"]})', values[f"display.resource.{identity}.comment"]]
            for number, (identity, resource, name, _) in enumerate(items, 1)], numbered=True)]
    output += ["", "## リソース詳細"]
    for identity, resource, name, rows in independent:
        kind = resource["resourceType"]
        heading = f"### {kind}" if name == kind and _dependency_design_layout.resource_display_name(kind, rows, mode=_dependency_design_layout.resource_mode(resource), root=root) is None else f"### {kind}: {name}"
        output += ["", f'<!-- resource-logical-id: {resource["logicalId"]} -->', f'<a id="{resource["anchor"]}"></a>', "", heading, ""]
        children = grouped.get(identity, [])
        output += resource_table_lines(resource, name, rows, children, root)
        output += (policy_views or {}).get(identity, [])
        if kind == "Macie.ClassificationJob":
            definitions = [row for row in rows if row[1] == kind + ".s3JobDefinition"]
            if definitions:
                row_id = definitions[0][0]
                raw = (values[f"desired.row.{row_id}.document"] if JSON_LINK.fullmatch(definitions[0][2])
                       else _dependency_policy_tables.literal(values[f"desired.row.{row_id}.value"]))
                document = policy_json(raw)
                if "bucketDefinitions" in document:
                    mappings = [[f'[{name}](#{resource["anchor"]})', f'`{group["accountId"]}`', f"`{bucket}`"] for group in document["bucketDefinitions"] for bucket in group["buckets"]]
                    output += ["", "#### 対象S3 bucket", "", *_dependency_policy_tables.table(["Job", "AWS account ID", "Bucket"], mappings)]
    for _, note in entries(values, "desired.note."):
        output += ["", note["text"]]
    return "\n".join(output) + "\n"


def model_policy_views(values):
    END = _imports_policy_tables.END
    IAM_END = _imports_policy_tables.IAM_END
    IAM_START = _imports_policy_tables.IAM_START
    INLINE_POLICY_DOCUMENTS = _imports_policy_tables.INLINE_POLICY_DOCUMENTS
    JSON_LINK = _imports_policy_tables.JSON_LINK
    POLICY_FORMATS = _imports_policy_tables.POLICY_FORMATS
    START = _imports_policy_tables.START
    Policy = _imports_policy_tables.Policy
    artifact_id = _imports_policy_tables.artifact_id
    policy_document_lines = _imports_policy_tables.policy_document_lines

    resource_row_index = _imports_model_files.resource_row_index

    result = {}
    rows_by_resource = resource_row_index(values)
    for identity, resource in entries(values, 'desired.resource.'):
        policies = []
        rows = rows_by_resource[identity]
        for position, (_, row) in enumerate(rows):
            prop = row['property']
            link = JSON_LINK.fullmatch(row.get('value', ''))
            if prop not in POLICY_FORMATS or not link or 'document' not in row:
                continue
            label, target = link.groups()
            trust = prop == 'IAM.Role.AssumeRolePolicyDocument'
            inline = prop in INLINE_POLICY_DOCUMENTS
            if inline and position and rows[position - 1][1]['property'] == prop.removesuffix('PolicyDocument') + 'PolicyName':
                label = _dependency_policy_tables.literal(rows[position - 1][1]['value'])
            suffix = 'trust' if trust else 'inline-' + artifact_id(label) if inline else 'policy-' + artifact_id(Path(target).stem)
            kind = '信頼ポリシー' if trust else 'インラインポリシー' if inline else 'ポリシー設定' if POLICY_FORMATS[prop] == 'settings' else 'ポリシー'
            policy = Policy(label, target, resource['anchor'] + '-' + suffix, kind, prop)
            policies.extend(['', *policy_document_lines(json.loads(row['document']), policy)])
        if policies:
            start, end = (IAM_START, IAM_END) if resource['resourceType'] == 'IAM.Role' else (START, END)
            result[identity] = ['', start, *policies, '', end]
    return result




def generate_files(path, values, root, *, warnings=None):
    """Generate one service in memory, without validation or dependency publication."""
    Resolver = _imports_model_identity.Resolver
    safe = _imports_model_sources.safe
    scope_for = _imports_model_sources.scope_for
    validate_json_settings = _imports_model_validation.validate_json_settings
    validate_json_settings(values, (root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties'), warnings=warnings)
    resolver = Resolver(root)
    artifacts = {}
    for identity, row in entries(values, 'desired.row.'):
        if 'document' not in row:
            continue
        match = JSON_LINK.fullmatch(row.get('value', ''))
        if not match:
            raise ValueError('JSON document requires an artifact link: ' + identity)
        safe(root, path.parent / match[1])
        artifact = (path.parent / match[1]).resolve()
        safe(root, artifact)
        if artifact.parent != path.with_suffix('').resolve():
            raise ValueError('JSON artifact must belong to owning service')
        execution_document = _imports_model_projection.execution_document
        document = execution_document(policy_json(row['document']), root, property_name=row['property'], resolver=resolver,
            scope=scope_for((root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties')),
            logical_id=values.get(f'desired.resource.{identity.rpartition("-")[0]}.logicalId'), warnings=warnings)
        content = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
        if artifact in artifacts and artifacts[artifact] != content:
            raise ValueError('conflicting authoritative JSON documents')
        artifacts[artifact] = content
    artifacts[path] = stack_markdown(path, values, root) if entries(values, 'desired.stack.') else generate_markdown(path, values, root)
    return artifacts



def render_model(snapshot, context):
    root = snapshot.scope.root
    if context is not None and context.root != root:
        raise ValueError('render context belongs to another Model root')
    context = context if context is not None else input_recorder(root)
    document = root / 'docs/designs' / snapshot.scope.environment / snapshot.scope.target / (snapshot.scope.service + '.md')
    with recording_inputs(context):
        return generate_files(document, snapshot.values, root)




def owned_artifacts(path, values):
    return {(path.parent / link[1]).resolve() for _, row in entries(values, 'desired.row.')
            if 'document' in row and (link := JSON_LINK.fullmatch(row.get('value', '')))
            and (path.parent / link[1]).resolve().parent == path.with_suffix('').resolve()}


def view_plan(path, values, root, managed):
    """Plan one display transaction without taking ownership of unrelated JSON."""
    inputs = {p: input_bytes(p) for p in input_select(path.with_suffix(''), '*.json', recursive=True, kinds=('file', 'symlink'))}
    inputs[path] = input_bytes(path) if input_is_file(path) else None
    for file in inputs.keys() | managed:
        _dependency_model_sources.safe(root, file)
        if file != path and file.parent != path.with_suffix('').resolve():
            raise ValueError('JSON artifact must belong to owning service')
    files = generate_files(path, values, root)
    if any(file in inputs and file != path and file not in managed and inputs[file] != text.encode('utf-8')
           for file, text in files.items()):
        raise ValueError('unowned JSON output collision')
    inputs.update({file: input_bytes(file) if input_is_file(file) else None for file in files if file not in inputs})
    return {**changed_files(files), **{file: None for file in managed - files.keys() if file.is_file()}}, inputs



_COMPAT_ROOT = Path(__file__).resolve().parents[3]


def display_rows(kind: str, rows: list[list[str]], root: Path=_COMPAT_ROOT, *, mode='CREATE', _counts=None, consumed: list[str] | None=None):
    return _dependency_model_display.display_rows(kind, rows, root, mode=mode, _counts=_counts, consumed=consumed)
