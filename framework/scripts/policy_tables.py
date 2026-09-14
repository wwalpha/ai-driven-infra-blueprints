#!/usr/bin/env python3
"""Render service policy tables from the linked design JSON, never the reverse."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import sys

from design_layout import ANCHOR, DETAILS_HEADING, HEADER, RESOURCE

START = "<!-- policy-tables:start -->"
END = "<!-- policy-tables:end -->"
IAM_START = "<!-- iam-policy-tables:start -->"
IAM_END = "<!-- iam-policy-tables:end -->"
OVERVIEW_HEADERS = ["RoleName", "信頼ポリシー", "インラインポリシー"]
JSON_LINK = re.compile(r"\[([^\]]+)\]\(([^)#]+\.json)\)")
# Exact catalog properties: policy names, ARNs and enum settings are not documents.
POLICY_FORMATS = {
    "ApiGateway.RestApi.Policy": "statement",
    "DynamoDB.GlobalTable.Replicas[].ReplicaStreamSpecification.ResourcePolicy.PolicyDocument": "statement",
    "DynamoDB.GlobalTable.Replicas[].ResourcePolicy.PolicyDocument": "statement",
    "DynamoDB.Table.ResourcePolicy": "wrapped-statement",
    "DynamoDB.Table.StreamSpecification.ResourcePolicy.PolicyDocument": "statement",
    "EC2.VPCEndpoint.PolicyDocument": "statement",
    "ECR.Repository.RepositoryPolicyText": "statement",
    "Events.EventBus.Policy": "statement",
    "IAM.ManagedPolicy.PolicyDocument": "statement",
    "IAM.Role.AssumeRolePolicyDocument": "statement",
    "IAM.Role.Policies[].PolicyDocument": "statement",
    "IAM.User.Policies[].PolicyDocument": "statement",
    "KMS.Key.KeyPolicy": "statement",
    "Logs.LogGroup.ResourcePolicyDocument": "statement",
    "Logs.ResourcePolicy.PolicyDocument": "statement",
    "S3.BucketPolicy.PolicyDocument": "statement",
    "SNS.TopicPolicy.PolicyDocument": "statement",
    "SQS.QueuePolicy.PolicyDocument": "statement",
    "SSO.PermissionSet.InlinePolicy": "statement",
    "SecretsManager.ResourcePolicy.ResourcePolicy": "statement",
    "ECR.Repository.LifecyclePolicy": "settings",
    "Logs.LogGroup.DataProtectionPolicy": "settings",
    "SNS.Subscription.DeliveryPolicy": "settings",
    "SNS.Subscription.FilterPolicy": "settings",
    "SNS.Subscription.RedrivePolicy": "settings",
    "SNS.Subscription.ReplayPolicy": "settings",
    "SNS.Topic.ArchivePolicy": "settings",
    "SNS.Topic.DataProtectionPolicy": "settings",
    "SQS.Queue.RedriveAllowPolicy": "settings",
    "SQS.Queue.RedrivePolicy": "settings",
}
POLICY_KEYS = {"Version", "Id", "Statement"}
INLINE_POLICY_DOCUMENTS = {
    "IAM.Role.Policies[].PolicyDocument",
    "IAM.User.Policies[].PolicyDocument",
}
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
    return f"{artifact_id(role_logical_id)}-{suffix}.json"


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


def literal(value: str) -> str:
    return value[1:-1] if value.startswith("`") and value.endswith("`") else value


def code(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if text == "":
        return '`""`'
    if any(char in text for char in "`|<>&\n\r"):
        escaped = html.escape(text, quote=False).replace("|", "&#124;").replace("\n", "&#10;").replace("\r", "&#13;")
        return f"<code>{escaped}</code>"
    return f"`{text}`"


def cell(value: object) -> str:
    return "<br>".join(code(item) for item in value) if isinstance(value, list) and value else code(value)


def table(headers: list[str], rows: list[list[str]], numbered: bool = False) -> list[str]:
    alignment = ["---"] * len(headers)
    if numbered:
        alignment[0] = "---:"
    return ["| " + " | ".join(row) + " |" for row in [headers, alignment, *rows]]


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
    name: str
    policies: list[Policy]
    table_end: int


def resources_in(lines: list[str]) -> list[Resource]:
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
        resources.append(Resource(current_type, logical_id, anchor, names[0] if names else "（RoleName未指定）", policies, index))
    if len({resource.anchor for resource in resources}) != len(resources):
        raise ValueError("duplicate resource detail table or anchor")
    return resources


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate policy JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


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
    document = json.loads(artifact.read_text(encoding="utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
    if not isinstance(document, dict):
        raise ValueError(f"policy JSON must be an object: {policy.link}")
    result = [f'<a id="{policy.anchor}"></a>', "", f"#### {policy.kind}：{policy.label}", ""]
    style = POLICY_FORMATS[policy.property_name]
    if style == "settings":
        result.extend(table(["Property", "Type", "Value"], settings_rows(document)))
        if policy.property_name == "ECR.Repository.LifecyclePolicy" and "LifecyclePolicyText" in document:
            encoded = document["LifecyclePolicyText"]
            if not isinstance(encoded, str):
                raise ValueError("LifecyclePolicyText must be a JSON string")
            decoded = json.loads(encoded, object_pairs_hook=unique_object, parse_constant=invalid_constant)
            if not isinstance(decoded, dict):
                raise ValueError("LifecyclePolicyText must encode an object")
            result.extend(["", "LifecyclePolicyTextの内容：", "", *table(["Property", "Type", "Value"], settings_rows(decoded))])
        return result
    if style == "wrapped-statement":
        if set(document) != {"PolicyDocument"}:
            raise ValueError(f"unsupported resource policy wrapper: {policy.link}")
        document = document["PolicyDocument"]
    if not isinstance(document, dict) or set(document) - POLICY_KEYS:
        raise ValueError(f"unsupported policy document keys: {policy.link}")
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or not statements:
        raise ValueError(f"policy requires non-empty Statement: {policy.link}")
    flattened = []
    for statement in statements:
        if not isinstance(statement, dict) or set(statement) - set(STATEMENT_KEYS):
            raise ValueError(f"unsupported policy Statement keys: {policy.link}")
        if policy.property_name == "IAM.Role.Policies[].PolicyDocument" and "Sid" in statement:
            sid = statement["Sid"]
            if not isinstance(sid, str) or len(sid) > 16:
                raise ValueError(f"IAM inline policy Sid must be a string of at most 16 characters: {policy.link}")
        if not isinstance(statement.get("Effect"), str) or statement["Effect"] not in {"Allow", "Deny"}:
            raise ValueError(f"invalid policy Statement Effect: {policy.link}")
        flat = {}
        for key in STATEMENT_KEYS:
            if key not in statement:
                continue
            value = statement[key]
            if key in {"Principal", "NotPrincipal"} and isinstance(value, dict):
                for principal_type in sorted(value):
                    if principal_type not in {"AWS", "Service", "Federated", "CanonicalUser"}:
                        raise ValueError(f"unsupported policy Principal type: {principal_type}")
                    flat[f"{key}.{principal_type}"] = cell(value[principal_type])
                if not value:
                    raise ValueError("empty policy Principal")
            elif key == "Condition":
                if not isinstance(value, dict) or not value:
                    raise ValueError("policy Condition must be a non-empty object")
                conditions = []
                for operator, entries in sorted(value.items()):
                    if not isinstance(entries, dict) or not entries:
                        raise ValueError("policy Condition operator must contain context keys")
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


def render_policy_overviews(text: str, resources: list[Resource]) -> str:
    """Add only the derived Policies column; keep the chosen summary columns."""
    details_heading = re.search(r"^" + re.escape(DETAILS_HEADING) + r"$", text, re.MULTILINE)
    if not details_heading:
        raise ValueError("resource details are missing")
    overview, details = text[:details_heading.start()], text[details_heading.start():]
    for resource_type in sorted({resource.resource_type for resource in resources} - {"IAM.Role"}):
        owned = {resource.anchor: resource for resource in resources if resource.resource_type == resource_type}
        required = any(resource.policies for resource in owned.values())
        pattern = re.compile(r"^### " + re.escape(resource_type) + r"\n(?:\n|\|[^\n]*\n)*", re.MULTILINE)
        matches = list(pattern.finditer(overview))
        if len(matches) != 1:
            if required:
                raise ValueError(f"policy resource overview must appear exactly once: {resource_type}")
            continue
        match = matches[0]
        rows = [[part.strip() for part in line.strip("|").split("|")] for line in match.group().splitlines() if line.startswith("|")]
        if not rows or (not required and "Policies" not in rows[0]):
            continue
        if len(rows) < 3 or rows[0].count("Policies") > 1:
            raise ValueError(f"invalid policy resource overview: {resource_type}")
        headers, alignment, *entries = rows
        if not 2 <= len(headers) <= (7 if "Policies" in headers else 6) or any(len(row) != len(headers) for row in rows):
            raise ValueError(f"invalid policy resource overview width: {resource_type}")
        column = headers.index("Policies") if "Policies" in headers else None
        if column == 0:
            raise ValueError("Policies cannot replace the resource identifier column")
        seen = []
        for row in entries:
            link = re.fullmatch(r"\[([^\]]+)\]\(#([^)]+)\)", row[0])
            if not link or link.group(2) not in owned or link.group(1) != owned[link.group(2)].logical_id:
                raise ValueError(f"invalid policy overview resource link: {resource_type}")
            resource = owned[link.group(2)]
            seen.append(resource.anchor)
            if column is not None:
                row.pop(column)
            if required:
                row.append("<br>".join(f"[{policy.label}](#{policy.anchor})" for policy in resource.policies) or "—")
        if len(seen) != len(set(seen)) or set(seen) != set(owned):
            raise ValueError(f"policy overview must list every owning resource once: {resource_type}")
        if column is not None:
            headers.pop(column)
            alignment.pop(column)
        if required:
            headers.append("Policies")
            alignment.append("---")
        replacement = f"### {resource_type}\n\n" + "\n".join("| " + " | ".join(row) + " |" for row in [headers, alignment, *entries]) + "\n\n"
        overview = overview[:match.start()] + replacement + overview[match.end():]
    return overview + details


def rendered_design(path: Path) -> str:
    original = path.read_text(encoding="utf-8")
    lines = without_policy_tables(original.splitlines())
    resources = resources_in(lines)
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
    text = "\n".join(lines) + "\n"
    text = render_policy_overviews(text, resources)
    roles = [resource for resource in resources if resource.resource_type == "IAM.Role"]
    if not roles:
        return text
    overview_rows = []
    for role in roles:
        overview_rows.append([
            f"[{role.name}](#{role.anchor})",
            "<br>".join(f"[{p.label}](#{p.anchor})" for p in role.policies if p.kind == "信頼ポリシー"),
            "<br>".join(f"[{p.label}](#{p.anchor})" for p in role.policies if p.kind == "インラインポリシー") or "—",
        ])
    overview = "### IAM.Role\n\n" + "\n".join(table(OVERVIEW_HEADERS, overview_rows)) + "\n\n"
    pattern = re.compile(r"^### IAM\.Role\n(?:\n|\|[^\n]*\n)*", re.MULTILINE)
    matches = list(pattern.finditer(text))
    details_heading = re.search(r"^" + re.escape(DETAILS_HEADING) + r"$", text, re.MULTILINE)
    if len(matches) != 1 or not details_heading or matches[0].start() > details_heading.start():
        raise ValueError("IAM Role overview must appear exactly once before resource details")
    return pattern.sub(lambda _: overview, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path, help="Explicitly authorized service Markdown path")
    parser.add_argument("--write", action="store_true", help="Update only derived policy views")
    args = parser.parse_args()
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
