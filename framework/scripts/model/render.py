"""Render detailed designs from authoritative service properties."""

from __future__ import annotations
from utils.json_format import policy_json

from model.core import ReferenceResolutionError

import json
import re
from collections import Counter
from pathlib import Path
import iac_values
from array_display import indexed_rows
from model.projection import bound_resource_anchors, deployment_bucket, catalog_outputs, resource_rows, design_target, resource_display_rows, is_import_expression
from model.display import display_rows, catalog_display_rows, row_table, sg_tables
from aws_mapping_display import selected_rows
from validation_cache import input_is_file, input_bytes, input_select
from model.core import properties, entries, stack_model, deployment_settings, LINK, ARTIFACT_FIELDS

from design_layout import (
    GROUPED,
    HIDDEN_PROPERTIES,
    resource_display_name,
    resource_name_fields,
    resource_anchor,
    resource_has_name_property,
    resource_mode,
    is_import_pending_reference,
    GROUPED_RESOURCE_TYPES,
    IMPLICIT_GROUPED_PROPERTIES,
    ROTATION_SCHEDULE,
    LAMBDA_PERMISSION,
    SUBNET_LIST_SOURCE,
)
from policy_tables import literal, table
from design_catalog import DesignSchemaCatalog, property_paths_with_parents, selected_properties
from validation_cache import input_scope, memoized


from model.validation import naming_errors, validate_required_properties, validate_resource_identities

def stack_markdown(path, values, root, *, definitions_root=None):
    limit, stacks = stack_model(values)
    settings, artifacts = deployment_settings(values)
    from model.projection import reference_display
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


def display_name(values, identity, resource, rows, root):
    """Pure final display selection, shared by rendering and reference diagnostics."""
    kind = resource['resourceType']
    label = values.get(f'display.resource.{identity}.label')
    if GROUPED.get(kind, {}).get('display') == 'rule-table':
        return label or resource['logicalId'], None
    configured = resource_display_name(kind, rows, label, resource_mode(resource))
    name = configured or label
    if configured is None and (name is None or name == kind):
        count = sum(item['resourceType'] == kind for _, item in entries(values, 'desired.resource.'))
        if kind in GROUPED or count != 1 or resource_has_name_property(root, kind, resource_mode(resource)):
            return None, configured
        name = kind
    return name, configured


def resource_presentation(values, identity, resource, root):
    kind = resource['resourceType']
    rows = catalog_display_rows(resource_rows(values, identity, kind, root), kind, root)
    name, configured = display_name(values, identity, resource,
                                    resource_display_rows(values, identity, resource, root), root)
    return name, configured, rows


def resource_details(values, root, service, owned, resources, bound_anchors, *, findings=None):
    by_anchor = {}
    names = set()
    details = []
    for identity, resource in resources:
        def inspect():
            nonlocal resource
            kind = resource["resourceType"]
            mode = resource_mode(resource)
            if kind not in owned:
                raise ValueError(f"resource is outside service ownership: {kind}")
            name, configured_name, rows = resource_presentation(values, identity, resource, root)
            if configured_name is None and name is None:
                raise ValueError(f"resource type display requires a single nameless independent resource: {kind}")
            if not name or name in {"UNSET", "PENDING_DEPLOY"}:
                raise ValueError(f"confirmed resource display label is missing: {kind}: {identity}")
            from model.identity import display_anchor
            anchor = display_anchor(resource['logicalId'])
            resource = {**resource, 'anchor': anchor}
            derived = anchor
            if anchor in by_anchor:
                raise ValueError('duplicate Resource display anchor: ' + anchor)
            errors = naming_errors(root, kind, rows, mode)
            if errors:
                raise ValueError("; ".join(errors))
            names.add(derived)
            item = (identity, resource, name, rows)
            by_anchor[anchor] = item
            details.append(item)
        if findings is None:
            inspect()
        else:
            findings.evaluate('model.resource.' + identity, None, inspect)
    return details, by_anchor


def grouped_resources(values, details, by_anchor):
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
        if resource['parentProperty'] != kind + '.' + rule['parentProperty']:
            raise ValueError('invalid grouped parentProperty: ' + identity)
        if not parent or parent[1]['resourceType'] != rule['parent']:
            raise ReferenceResolutionError(f"{kind}: {resource['logicalId']}: invalid grouped parent: parentReference / parentProperty ({kind}.{rule['parentProperty']})")
        if kind in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
            parent_rows = [row for row_id, row in entries(values, "desired.row.")
                           if row_id.startswith(identity + "-") and row.get("property") == resource["parentProperty"]]
            if len(parent_rows) != 1:
                raise ValueError(f"{kind}: {resource['logicalId']}: {resource['parentProperty']} requires exactly one formal row matching parentReference")
            if parent_rows[0].get('value') != resource['parentReference']:
                raise ReferenceResolutionError('grouped formal row does not match parentReference', resource=identity, property=resource['parentProperty'])
            if kind + ".Id" not in HIDDEN_PROPERTIES and (not rows or rows[0][1] != kind + ".Id"):
                raise ValueError(f"{kind}: {resource['logicalId']}: required first property: {kind}.Id")
        grouped.setdefault(parent[0], []).append(item)
        maximum = rule["maxCount"]
        if maximum is not None and sum(child[1]["resourceType"] == kind for child in grouped[parent[0]]) > maximum:
            raise ValueError(f"{kind}: {resource['logicalId']}: too many grouped children for {parent[1]['logicalId']}: {resource['parentProperty']}")
    return grouped


def resource_table_lines(resource, name, rows, children, root):
    expected = Counter(row[0] for row in selected_rows(rows, root))
    for _, _, _, child_rows in children:
        expected.update(row[0] for row in selected_rows(child_rows, root))
    if any(count != 1 for count in expected.values()):
        raise ValueError("duplicate selected Model row IDs")
    consumed = []
    output = []
    kind = resource["resourceType"]
    if kind == "EC2.SecurityGroup":
        rules = [(child, selected_rows(child_rows, root)) for _, child, _, child_rows in children]
        output += sg_tables(selected_rows(rows, root), [(child, rows) for child, rows in rules if rows], root, consumed=consumed)
    else:
        display = display_rows(kind, rows, root, mode=resource_mode(resource), consumed=consumed)
        for _, child, child_name, child_rows in children:
            child_rows = selected_rows(child_rows, root)
            if not child_rows:
                continue
            if child["resourceType"] == ROTATION_SCHEDULE:
                child_rows = [[rid, prop, f'[{name}](#{resource["anchor"]})' if prop == child["parentProperty"] else value, comment]
                              for rid, prop, value, comment in child_rows]
            child_display = display_rows(kind if child["resourceType"] == ROTATION_SCHEDULE else child["resourceType"], child_rows, root, mode=resource_mode(child), consumed=consumed)
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
    if Counter(consumed) != expected:
        raise ValueError("selected display rows were omitted or consumed more than once")
    return output


@input_scope
def markdown_for(path: Path, values: dict[str, str], root: Path, *, definitions_root: Path | None = None) -> str:
    """Validated generation used by ordinary design and explicit validation."""
    from aws_mapping_display import validate_mappings
    validate_mappings(values, definitions_root or root)
    validate_required_properties(values, definitions_root or root)
    return render_validated_model(path, values, root, definitions_root=definitions_root)


def render_validated_model(path: Path, values: dict[str, str], root: Path, *, definitions_root: Path | None = None) -> str:
    """Internal renderer after mapping/required-property preflight, before artifacts."""
    if path.stem == "cloudformation-stacks":
        return stack_markdown(path, values, root, definitions_root=definitions_root)
    from model.projection import reference_display
    values = reference_display(values, path, root, definitions_root=definitions_root)
    service = path.stem
    if values.get(f"desired.service.{service}.serviceId") != service:
        raise ValueError(f"service ID must equal file stem: {path.name}")
    owned = values[f"desired.service.{service}.ownedCatalogResourceTypes"].split(",")
    resources = entries(values, "desired.resource.")
    if not resources:
        raise ValueError(f"service model has no resources: {path.name}")
    validate_resource_identities(path, values, root, resources, definitions_root=definitions_root)
    details, by_anchor = resource_details(values, definitions_root or root, service, owned, resources, bound_resource_anchors(path))
    return render_markdown(path, values, definitions_root or root, owned, details, grouped_resources(values, details, by_anchor))


@input_scope
def generate_markdown(path: Path, values: dict[str, str], root: Path) -> str:
    """Render the selected service without deciding whether its design is correct."""
    from model.projection import reference_display
    values = reference_display(values, path, path.parents[4], definitions_root=root)
    service = path.stem
    owned = values.get(f"desired.service.{service}.ownedCatalogResourceTypes", "").split(",")
    details = []
    for identity, resource in entries(values, "desired.resource."):
        kind = resource["resourceType"]
        name, _, rows = resource_presentation(values, identity, resource, root)
        name = name or kind
        details.append((identity, resource, name, rows))
    by_anchor = {item[1]["anchor"]: item for item in details}
    grouped = {}
    for item in details:
        link = LINK.fullmatch(item[1].get('parentReference', ''))
        parent = by_anchor.get(link[3]) if link and not link[2] else None
        if item[1]['resourceType'] in GROUPED and parent:
            grouped.setdefault(parent[0], []).append(item)
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
        output += ["", "### " + kind, "", *table(["No.", "ResourceName", "Comment"], [
            [str(number), f'[{name}](#{resource["anchor"]})', values[f"display.resource.{identity}.comment"]]
            for number, (identity, resource, name, _) in enumerate(items, 1)], numbered=True)]
    output += ["", "## リソース詳細"]
    for identity, resource, name, rows in independent:
        kind = resource["resourceType"]
        heading = f"### {kind}" if name == kind and resource_display_name(kind, rows, mode=resource_mode(resource)) is None else f"### {kind}: {name}"
        output += ["", f'<!-- resource-logical-id: {resource["logicalId"]} -->', f'<a id="{resource["anchor"]}"></a>', "", heading, ""]
        children = grouped.get(identity, [])
        output += resource_table_lines(resource, name, rows, children, root)
        output += (policy_views or {}).get(identity, [])
        if kind == "Macie.ClassificationJob":
            definitions = [row for row in rows if row[1] == kind + ".s3JobDefinition"]
            if definitions:
                row_id = definitions[0][0]
                raw = (values[f"desired.row.{row_id}.document"] if JSON_LINK.fullmatch(definitions[0][2])
                       else literal(values[f"desired.row.{row_id}.value"]))
                document = policy_json(raw)
                if "bucketDefinitions" in document:
                    mappings = [[f'[{name}](#{resource["anchor"]})', f'`{group["accountId"]}`', f"`{bucket}`"] for group in document["bucketDefinitions"] for bucket in group["buckets"]]
                    output += ["", "#### 対象S3 bucket", "", *table(["Job", "AWS account ID", "Bucket"], mappings)]
    for _, note in entries(values, "desired.note."):
        output += ["", note["text"]]
    return "\n".join(output) + "\n"


def model_policy_views(values):
    from policy_tables import (Policy, POLICY_FORMATS, INLINE_POLICY_DOCUMENTS, JSON_LINK,
                               artifact_id, policy_document_lines, START, END, IAM_START, IAM_END)
    from model.files import resource_row_index
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
                label = literal(rows[position - 1][1]['value'])
            suffix = 'trust' if trust else 'inline-' + artifact_id(label) if inline else 'policy-' + artifact_id(Path(target).stem)
            kind = '信頼ポリシー' if trust else 'インラインポリシー' if inline else 'ポリシー設定' if POLICY_FORMATS[prop] == 'settings' else 'ポリシー'
            policy = Policy(label, target, resource['anchor'] + '-' + suffix, kind, prop)
            policies.extend(['', *policy_document_lines(json.loads(row['document']), policy)])
        if policies:
            start, end = (IAM_START, IAM_END) if resource['resourceType'] == 'IAM.Role' else (START, END)
            result[identity] = ['', start, *policies, '', end]
    return result


from model.projection import JSON_LINK

def generate_files(path, values, root):
    """Generate one service in memory, without validation or dependency publication."""
    from model.sources import safe
    from model.identity import Resolver
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
        from model.projection import execution_document
        document = execution_document(policy_json(row['document']), root, property_name=row['property'], resolver=resolver)
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
    from validation_cache import recording_inputs, input_recorder
    context = context if context is not None else input_recorder(root)
    document = root / 'docs/designs' / snapshot.scope.environment / snapshot.scope.target / (snapshot.scope.service + '.md')
    with recording_inputs(context):
        return generate_files(document, snapshot.values, root)

from model.sources import safe
from sync_files import changed_files

def owned_artifacts(path, values):
    return {(path.parent / link[1]).resolve() for _, row in entries(values, 'desired.row.')
            if 'document' in row and (link := JSON_LINK.fullmatch(row.get('value', '')))
            and (path.parent / link[1]).resolve().parent == path.with_suffix('').resolve()}


def view_plan(path, values, root, managed):
    """Plan one display transaction without taking ownership of unrelated JSON."""
    inputs = {p: input_bytes(p) for p in input_select(path.with_suffix(''), '*.json', recursive=True, kinds=('file', 'symlink'))}
    inputs[path] = input_bytes(path) if input_is_file(path) else None
    for file in inputs.keys() | managed:
        safe(root, file)
        if file != path and file.parent != path.with_suffix('').resolve():
            raise ValueError('JSON artifact must belong to owning service')
    files = generate_files(path, values, root)
    if any(file in inputs and file != path and file not in managed and inputs[file] != text.encode('utf-8')
           for file, text in files.items()):
        raise ValueError('unowned JSON output collision')
    inputs.update({file: input_bytes(file) if input_is_file(file) else None for file in files if file not in inputs})
    return {**changed_files(files), **{file: None for file in managed - files.keys() if file.is_file()}}, inputs

