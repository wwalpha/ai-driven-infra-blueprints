#!/usr/bin/env python3
"""Render IAM Role policy tables from the linked design JSON, never the reverse."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import sys

from design_layout import ANCHOR, HEADER, RESOURCE

START = "<!-- iam-policy-tables:start -->"
END = "<!-- iam-policy-tables:end -->"
OVERVIEW_HEADERS = ["RoleName", "信頼ポリシー", "インラインポリシー"]
JSON_LINK = re.compile(r"\[([^\]]+)\]\(([^)#]+\.json)\)")
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
    return f"{artifact_id(role_logical_id)}-{suffix}.json"


def without_policy_tables(lines: list[str]) -> list[str]:
    """Remove only explicitly marked derived blocks; reject malformed markers."""
    result = []
    inside = False
    for line in lines:
        if line == START:
            if inside:
                raise ValueError("nested IAM policy table marker")
            inside = True
            if result and result[-1] == "":
                result.pop()
        elif line == END:
            if not inside:
                raise ValueError("unmatched IAM policy table end marker")
            inside = False
        elif not inside:
            if "<!-- iam-policy-tables:" in line:
                raise ValueError("invalid IAM policy table marker")
            if re.match(r"^#{2,6} (信頼ポリシー|インラインポリシー)[：:]", line):
                raise ValueError("IAM policy tables must be inside generated markers")
            result.append(line)
    if inside:
        raise ValueError("unclosed IAM policy table marker")
    return result


def literal(value: str) -> str:
    return value[1:-1] if value.startswith("`") and value.endswith("`") else value


def code(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
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
    trust: bool


@dataclass
class Role:
    logical_id: str
    anchor: str
    name: str
    policies: list[Policy]
    table_end: int


def roles_in(lines: list[str]) -> list[Role]:
    roles = []
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
        if line != HEADER or current_type != "IAM.Role":
            index += 1
            continue
        if not anchor:
            raise ValueError(f"IAM Role lacks an anchor: {logical_id}")
        index += 2
        rows = []
        while index < len(lines) and lines[index].startswith("|"):
            cells = [part.strip() for part in lines[index].strip("|").split("|")]
            if len(cells) != 4:
                raise ValueError(f"invalid IAM Role property row: {logical_id}")
            rows.append(cells)
            index += 1
        names = [literal(row[2]) for row in rows if row[1] == "IAM.Role.RoleName"]
        if len(names) > 1:
            raise ValueError(f"duplicate IAM RoleName: {logical_id}")
        policies = []
        for number, row in enumerate(rows):
            trust = row[1] == "IAM.Role.AssumeRolePolicyDocument"
            if not trust and row[1] != "IAM.Role.Policies[].PolicyDocument":
                continue
            match = JSON_LINK.fullmatch(row[2])
            if not match:
                raise ValueError(f"IAM policy requires a JSON artifact link: {logical_id}")
            label, link = match.groups()
            if not trust:
                if number == 0 or rows[number - 1][1] != "IAM.Role.Policies[].PolicyName":
                    raise ValueError(f"IAM inline policy requires a preceding PolicyName: {logical_id}")
                label = literal(rows[number - 1][2])
                if label in {"", "UNSET", "PENDING_DEPLOY"}:
                    raise ValueError(f"IAM inline PolicyName is unresolved: {logical_id}")
            if any(char in label for char in "[]|\n\r"):
                raise ValueError(f"invalid IAM policy display label: {logical_id}")
            suffix = "trust" if trust else f"inline-{artifact_id(label)}"
            policies.append(Policy(label, link, f"{anchor}-{suffix}", trust))
        if sum(policy.trust for policy in policies) != 1:
            raise ValueError(f"IAM Role must have exactly one trust policy: {logical_id}")
        if len({policy.anchor for policy in policies}) != len(policies):
            raise ValueError(f"duplicate IAM policy anchor: {logical_id}")
        roles.append(Role(logical_id, anchor, names[0] if names else "（RoleName未指定）", policies, index))
    if len({role.anchor for role in roles}) != len(roles):
        raise ValueError("duplicate IAM Role detail table or anchor")
    return roles


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate IAM JSON key: {key}")
        result[key] = value
    return result


def policy_lines(path: Path, policy: Policy) -> list[str]:
    artifact = (path.parent / policy.link).resolve()
    if artifact.parent != (path.parent / path.stem).resolve():
        raise ValueError(f"IAM policy artifact must belong to the owning service: {policy.link}")
    document = json.loads(artifact.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(document, dict) or set(document) - POLICY_KEYS:
        raise ValueError(f"unsupported IAM policy document keys: {policy.link}")
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or not statements:
        raise ValueError(f"IAM policy requires non-empty Statement: {policy.link}")
    flattened = []
    for statement in statements:
        if not isinstance(statement, dict) or set(statement) - set(STATEMENT_KEYS):
            raise ValueError(f"unsupported IAM Statement keys: {policy.link}")
        if not isinstance(statement.get("Effect"), str) or statement["Effect"] not in {"Allow", "Deny"}:
            raise ValueError(f"invalid IAM Statement Effect: {policy.link}")
        flat = {}
        for key in STATEMENT_KEYS:
            if key not in statement:
                continue
            value = statement[key]
            if key in {"Principal", "NotPrincipal"} and isinstance(value, dict):
                for principal_type in sorted(value):
                    if principal_type not in {"AWS", "Service", "Federated", "CanonicalUser"}:
                        raise ValueError(f"unsupported IAM Principal type: {principal_type}")
                    flat[f"{key}.{principal_type}"] = cell(value[principal_type])
                if not value:
                    raise ValueError("empty IAM Principal")
            elif key == "Condition":
                if not isinstance(value, dict) or not value:
                    raise ValueError("IAM Condition must be a non-empty object")
                conditions = []
                for operator, entries in sorted(value.items()):
                    if not isinstance(entries, dict) or not entries:
                        raise ValueError("IAM Condition operator must contain context keys")
                    for context_key, expected in sorted(entries.items()):
                        conditions.append(f"{code(operator)}：{code(context_key)} = {code(expected)}")
                flat[key] = "<br>".join(conditions)
            else:
                flat[key] = str(value) if key == "Effect" else cell(value)
        flattened.append(flat)
    columns = []
    for key in STATEMENT_KEYS:
        columns.extend(sorted({column for flat in flattened for column in flat if column == key or column.startswith(key + ".")}))
    kind = "信頼ポリシー" if policy.trust else "インラインポリシー"
    result = [f'<a id="{policy.anchor}"></a>', "", f"### {kind}：{policy.label}", ""]
    for key in ("Version", "Id"):
        if key in document:
            result.extend([f"{key}：{code(document[key])}", ""])
    result.extend(table(["Statement", *columns], [
        [str(number), *(flat.get(column, "—") for column in columns)]
        for number, flat in enumerate(flattened, 1)
    ], numbered=True))
    return result


def rendered_design(path: Path) -> str:
    original = path.read_text(encoding="utf-8")
    lines = without_policy_tables(original.splitlines())
    roles = roles_in(lines)
    if not roles:
        if START in original:
            raise ValueError("IAM policy tables have no owning Role")
        return original
    for role in reversed(roles):
        generated = ["", START]
        for policy in role.policies:
            generated.extend(["", *policy_lines(path, policy)])
        generated.extend(["", END])
        lines[role.table_end:role.table_end] = generated
    overview_rows = []
    for role in roles:
        overview_rows.append([
            f"[{role.name}](#{role.anchor})",
            "<br>".join(f"[{p.label}](#{p.anchor})" for p in role.policies if p.trust),
            "<br>".join(f"[{p.label}](#{p.anchor})" for p in role.policies if not p.trust) or "—",
        ])
    overview = "### IAM.Role\n\n" + "\n".join(table(OVERVIEW_HEADERS, overview_rows)) + "\n\n"
    text = "\n".join(lines) + "\n"
    pattern = re.compile(r"^### IAM\.Role\n(?:\n|\|[^\n]*\n)*", re.MULTILINE)
    matches = list(pattern.finditer(text))
    first_resource = re.search(r"^## [A-Za-z0-9]+\.[A-Za-z0-9]+: ", text, re.MULTILINE)
    if len(matches) != 1 or not first_resource or matches[0].start() > first_resource.start():
        raise ValueError("IAM Role overview must appear exactly once before resource details")
    return pattern.sub(lambda _: overview, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path, help="Explicitly authorized service Markdown path")
    parser.add_argument("--write", action="store_true", help="Update only derived IAM views")
    args = parser.parse_args()
    try:
        rendered = rendered_design(args.design)
        if rendered != args.design.read_text(encoding="utf-8"):
            if not args.write:
                raise ValueError("IAM policy tables are stale; regenerate with --write")
            args.design.write_text(rendered, encoding="utf-8")
        print("IAM policy tables: PASS")
        return 0
    except (OSError, ValueError) as error:
        print(f"IAM policy tables: FAIL ({error})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
