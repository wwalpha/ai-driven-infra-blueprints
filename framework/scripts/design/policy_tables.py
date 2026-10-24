#!/usr/bin/env python3
"""Render service policy tables from the linked design JSON, never the reverse."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from functools import partial as _bind_framework_callback
from pathlib import Path

import json_intrinsics as _imports_json_intrinsics
import utils.aws_mappings as _imports_utils_aws_mappings
from model.core import literal
from utils.input_cache import input_scope
from utils.json_format import (
    AwsDocumentError,
    policy_json,
    validate_aws_document,
)
from utils.json_format import (
    invalid_constant as invalid_constant,
)
from utils.json_format import (
    unique_object as unique_object,
)

import design.array_display as _dependency_array_display
import design.layout as _module_design_layout
from design.common import cell as cell
from design.common import code as code
from design.common import resource_heading_lines
from design.common import table as table
from design.layout_schema import ANCHOR, HEADER, RESOURCE
from design.services.definitions.iam import IAM_END as IAM_END
from design.services.definitions.iam import IAM_START as IAM_START
from design.services.definitions.iam import INLINE_POLICY_DOCUMENTS
from design.services.definitions.registry import POLICY_FORMATS as POLICY_FORMATS

START = "<!-- policy-tables:start -->"
END = "<!-- policy-tables:end -->"
JSON_LINK = re.compile(r"\[([^\]]+)\]\(([^)#]+\.json)\)")
# Exact catalog properties: policy names, ARNs and enum settings are not documents.
POLICY_KEYS = {"Version", "Id", "Statement"}
STATEMENT_KEYS = (
    "Sid", "Effect", "Principal", "NotPrincipal", "Action", "NotAction",
    "Resource", "NotResource", "Condition",
)


def artifact_id(value: str) -> str:
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).lower()
    return re.sub(r"-+", "-", value).strip("-")


def iam_role_policy_artifact_filename(role_logical_id: str, policy_name: str | None = None) -> str:
    suffix = "trust-policy" if policy_name is None else artifact_id(policy_name)
    role_id = artifact_id(role_logical_id).removeprefix("cde").removeprefix("-")
    return f"{role_id}-{suffix}.json"


def without_policy_tables(lines: list[str]) -> list[str]:
    """Remove only explicitly marked derived blocks; reject malformed markers."""
    result = []
    closing = ""
    markers = {START: END, IAM_START: IAM_END}
    for line in lines:
        if line in markers:
            if closing:
                raise ValueError("nested policy table marker")
            closing = markers[line]
            if result and result[-1] == "":
                result.pop()
        elif line in markers.values():
            if line != closing:
                raise ValueError("unmatched policy table end marker")
            closing = ""
        elif "<!-- policy-tables:" in line or "<!-- iam-policy-tables:" in line:
            raise ValueError("invalid policy table marker")
        elif not closing:
            if re.match(r"^#{2,6} (信頼ポリシー|インラインポリシー|ポリシー|ポリシー設定)[：:]", line):
                raise ValueError("policy tables must be inside generated markers")
            result.append(line)
    if closing:
        raise ValueError("unclosed policy table marker")
    return result


@dataclass
class Policy:
    label: str
    link: str
    anchor: str
    kind: str
    property_name: str


@dataclass
class Resource:
    resource_type: str
    logical_id: str
    anchor: str
    policies: list[Policy]
    table_end: int


@input_scope
def resources_in(lines: list[str], root: Path | None = None) -> list[Resource]:
    lines = resource_heading_lines(lines)
    resources = []
    current_type = logical_id = anchor = pending_anchor = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if match := ANCHOR.fullmatch(line):
            pending_anchor = match.group(1)
        if match := RESOURCE.fullmatch(line):
            current_type, logical_id = match.groups()
            anchor, pending_anchor = pending_anchor, ""
        elif line.startswith("#"):
            current_type = ""
        if line != HEADER or not current_type:
            index += 1
            continue
        if not anchor:
            raise ValueError(f"resource lacks an anchor: {logical_id}")
        index += 2
        rows = []
        while index < len(lines) and lines[index].startswith("|"):
            cells = [part.strip() for part in lines[index].strip("|").split("|")]
            if len(cells) != 4:
                raise ValueError(f"invalid resource property row: {logical_id}")
            rows.append(cells)
            index += 1
        rows = _dependency_array_display.restored_rows(rows, current_type, root) if root else _dependency_array_display.restored_rows(rows, current_type)
        for row in rows:
            row[1] = _module_design_layout.formal_property(row[1], current_type, root)
        names = [literal(row[2]) for row in rows if row[1] == "IAM.Role.RoleName"]
        if len(names) > 1:
            raise ValueError(f"duplicate IAM RoleName: {logical_id}")
        policies = []
        for number, row in enumerate(rows):
            trust = row[1] == "IAM.Role.AssumeRolePolicyDocument"
            if row[1] not in POLICY_FORMATS:
                continue
            match = JSON_LINK.fullmatch(row[2])
            if not match:
                raise ValueError(f"policy requires a JSON artifact link: {logical_id}: {row[1]}")
            label, link = match.groups()
            inline = row[1] in INLINE_POLICY_DOCUMENTS
            if inline:
                policy_name_property = row[1].removesuffix("PolicyDocument") + "PolicyName"
                if number == 0 or rows[number - 1][1] != policy_name_property:
                    raise ValueError(f"IAM inline policy requires a preceding PolicyName: {logical_id}")
                label = literal(rows[number - 1][2])
                if label in {"", "UNSET", "PENDING_DEPLOY"}:
                    raise ValueError(f"IAM inline PolicyName is unresolved: {logical_id}")
            if not label.strip() or any(char in label for char in "[]|<>\n\r"):
                raise ValueError(f"invalid policy display label: {logical_id}")
            suffix = "trust" if trust else f"inline-{artifact_id(label)}" if inline else f"policy-{artifact_id(Path(link).stem)}"
            kind = "信頼ポリシー" if trust else "インラインポリシー" if inline else "ポリシー設定" if POLICY_FORMATS[row[1]] == "settings" else "ポリシー"
            policies.append(Policy(label, link, f"{anchor}-{suffix}", kind, row[1]))
        if current_type == "IAM.Role" and sum(policy.kind == "信頼ポリシー" for policy in policies) != 1:
            raise ValueError(f"IAM Role must have exactly one trust policy: {logical_id}")
        if len({policy.anchor for policy in policies}) != len(policies):
            raise ValueError(f"duplicate policy anchor; use distinct artifacts for policies in one resource: {logical_id}")
        resources.append(Resource(current_type, logical_id, anchor, policies, index))
    if len({resource.anchor for resource in resources}) != len(resources):
        raise ValueError("duplicate resource detail table or anchor")
    return resources


def settings_rows(value: object, pointer: str = "") -> list[list[str]]:
    """Keep nesting, array order and empty containers using JSON Pointer paths."""
    if isinstance(value, (dict, list)):
        rows = [[code(pointer), "object" if isinstance(value, dict) else "array", "—" if value else code(value)]]
        entries = sorted(value.items()) if isinstance(value, dict) else enumerate(value)
        for key, child in entries:
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            rows.extend(settings_rows(child, f"{pointer}/{escaped}"))
        return rows
    kind = "null" if value is None else "boolean" if isinstance(value, bool) else "string" if isinstance(value, str) else "number"
    return [[code(pointer), kind, code(value)]]


def policy_lines(path: Path, policy: Policy) -> list[str]:
    artifact = (path.parent / policy.link).resolve()
    if artifact.parent != (path.parent / path.stem).resolve():
        raise ValueError(f"policy artifact must belong to the owning service: {policy.link}")
    document = policy_json(artifact.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"policy JSON must be an object: {policy.link}")
    validate_policy_document(document, policy, design=True)
    return policy_document_lines(document, policy)


def _lambda_validate_policy_document_pending_259(design, intrinsic, /, value):
    return design and intrinsic(value)


def validate_policy_document(document, policy, *, design=False):
    intrinsic = _imports_json_intrinsics.intrinsic
    project_document = _imports_json_intrinsics.project_document
    if design:
        document = project_document(document, property_name=policy.property_name)
    else:
        validate_aws_document(document)
    pending = _bind_framework_callback(_lambda_validate_policy_document_pending_259, design, intrinsic)
    if pending(document):
        return
    style = POLICY_FORMATS[policy.property_name]
    if style == 'settings':
        if policy.property_name == 'ECR.Repository.LifecyclePolicy' and 'LifecyclePolicyText' in document:
            raw = document['LifecyclePolicyText']
            if pending(raw):
                return
            if not isinstance(raw, str):
                raise ValueError('LifecyclePolicyText must be a JSON string')
            if not isinstance(policy_json(raw), dict):
                raise ValueError('LifecyclePolicyText must encode an object')
        return
    if style == 'wrapped-statement':
        if set(document) != {'PolicyDocument'}:
            raise ValueError(f'unsupported resource policy wrapper: {policy.link}')
        document = document['PolicyDocument']
        if pending(document):
            return
    if not isinstance(document, dict) or set(document) - POLICY_KEYS:
        raise ValueError(f'unsupported policy document keys: {policy.link}')
    statements = document.get('Statement')
    if pending(statements):
        return
    statements = [statements] if isinstance(statements, dict) else statements
    if not isinstance(statements, list) or not statements:
        raise ValueError(f'policy requires non-empty Statement: {policy.link}')
    for index, statement in enumerate(statements):
        if pending(statement):
            continue
        if not isinstance(statement, dict) or set(statement) - set(STATEMENT_KEYS):
            raise ValueError(f'unsupported policy Statement keys: {policy.link}')
        if policy.property_name == 'IAM.Role.Policies[].PolicyDocument' and 'Sid' in statement and not pending(statement['Sid']):
            if not isinstance(statement['Sid'], str) or len(statement['Sid']) > 16:
                raise ValueError(f'IAM inline policy Sid must be a string of at most 16 characters: {policy.link}')
        if not pending(statement.get('Effect')) and statement.get('Effect') not in ('Allow', 'Deny'):
            raise ValueError(f'invalid policy Statement Effect: {policy.link}')
        for key in ('Resource', 'NotResource'):
            if key in statement:
                value = statement[key]
                if not (isinstance(value, str) or pending(value) or isinstance(value, list) and all(isinstance(item, str) or pending(item) for item in value)):
                    prefix = '/PolicyDocument' if style == 'wrapped-statement' else ''
                    pointer = prefix + '/Statement' + (f'/{index}' if isinstance(document['Statement'], list) else '') + '/' + key
                    raise AwsDocumentError(pointer, value, f'{key} must be a string or string array')
        for key in ('Principal', 'NotPrincipal'):
            principal = statement.get(key)
            if pending(principal):
                continue
            if isinstance(principal, dict):
                if not principal:
                    raise ValueError('empty policy Principal')
                for kind in principal:
                    if kind not in {'AWS', 'Service', 'Federated', 'CanonicalUser'}:
                        raise ValueError(f'unsupported policy Principal type: {kind}')
        if 'Condition' in statement:
            condition = statement['Condition']
            if pending(condition):
                continue
            if not isinstance(condition, dict) or not condition:
                raise ValueError('policy Condition must be a non-empty object')
            if any(not isinstance(entry, dict) or not entry for entry in condition.values()):
                raise ValueError('policy Condition operator must contain context keys')


def raw_policy_lines(document, policy):
    return [f'<a id="{policy.anchor}"></a>', '', f'#### {policy.kind}：{policy.label}', '',
            '```json', json.dumps(document, ensure_ascii=False, indent=2), '```']


def policy_document_lines(document, policy):
    """Lossless display conversion; unsupported table shapes retain the entire JSON."""
    original = document
    if not isinstance(document, dict):
        return raw_policy_lines(original, policy)
    result = [f'<a id="{policy.anchor}"></a>', "", f"#### {policy.kind}：{policy.label}", ""]
    style = POLICY_FORMATS[policy.property_name]
    if style == "settings":
        result.extend(table(["Property", "Type", "Value"], settings_rows(document)))
        if policy.property_name == "ECR.Repository.LifecyclePolicy" and "LifecyclePolicyText" in document:
            encoded = document["LifecyclePolicyText"]
            if not isinstance(encoded, str):
                return raw_policy_lines(original, policy)
            try:
                decoded = policy_json(encoded)
            except ValueError:
                return raw_policy_lines(original, policy)
            if not isinstance(decoded, dict):
                return raw_policy_lines(original, policy)
            result.extend(["", "LifecyclePolicyTextの内容：", "", *table(["Property", "Type", "Value"], settings_rows(decoded))])
        return result
    if style == "wrapped-statement":
        if set(document) != {"PolicyDocument"}:
            return raw_policy_lines(original, policy)
        document = document["PolicyDocument"]
    if not isinstance(document, dict) or set(document) - POLICY_KEYS:
        return raw_policy_lines(original, policy)
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or not statements:
        return raw_policy_lines(original, policy)
    flattened = []
    for statement in statements:
        if not isinstance(statement, dict) or set(statement) - set(STATEMENT_KEYS):
            return raw_policy_lines(original, policy)
        flat = {}
        for key in STATEMENT_KEYS:
            if key not in statement:
                continue
            value = statement[key]
            if key in {"Principal", "NotPrincipal"} and isinstance(value, dict):
                for principal_type in sorted(value):
                    flat[f"{key}.{principal_type}"] = cell(value[principal_type])
                if not value:
                    return raw_policy_lines(original, policy)
            elif key == "Condition":
                if not isinstance(value, dict) or not value:
                    return raw_policy_lines(original, policy)
                conditions = []
                for operator, entries in sorted(value.items()):
                    if not isinstance(entries, dict) or not entries:
                        return raw_policy_lines(original, policy)
                    for context_key, expected in sorted(entries.items()):
                        conditions.append(f"{code(operator)}：{code(context_key)} = {code(expected)}")
                flat[key] = "<br>".join(conditions)
            else:
                flat[key] = str(value) if key == "Effect" else cell(value)
        flattened.append(flat)
    columns = []
    for key in STATEMENT_KEYS:
        columns.extend(sorted({column for flat in flattened for column in flat if column == key or column.startswith(key + ".")}))
    if policy.property_name == "IAM.Role.AssumeRolePolicyDocument" and "Version" in document:
        result.extend([*table(["Version"], [[code(document["Version"])]]), ""])
    result.extend(table(["No.", *columns], [
        [str(number), *(flat.get(column, "—") for column in columns)]
        for number, flat in enumerate(flattened, 1)
    ], numbered=True))
    return result


@input_scope
def rendered_design(path: Path, *, definitions_root: Path | None = None) -> str:
    definition_root = _imports_utils_aws_mappings.definition_root
    original = path.read_text(encoding="utf-8")
    lines = without_policy_tables(original.splitlines())
    root = definitions_root or definition_root(path.resolve().parent)
    resources = resources_in(lines, root)
    if not resources:
        if START in original or IAM_START in original:
            raise ValueError("policy tables have no owning resource")
        return original
    for resource in reversed(resources):
        if not resource.policies:
            continue
        start, end = (IAM_START, IAM_END) if resource.resource_type == "IAM.Role" else (START, END)
        generated = ["", start]
        for policy in resource.policies:
            generated.extend(["", *policy_lines(path, policy)])
        generated.extend(["", end])
        lines[resource.table_end:resource.table_end] = generated
    return "\n".join(lines) + "\n"

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path, help="Explicitly authorized service Markdown path")
    parser.add_argument("--write", action="store_true", help="Update only derived policy views")
    args = parser.parse_args(argv)
    try:
        rendered = rendered_design(args.design)
        if rendered != args.design.read_text(encoding="utf-8"):
            if not args.write:
                raise ValueError("policy tables are stale; regenerate with --write")
            args.design.write_text(rendered, encoding="utf-8")
        print("Policy tables: PASS")
        return 0
    except (OSError, ValueError) as error:
        print(f"Policy tables: FAIL ({error})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
