import json

from design.catalog import selected_properties
from design.layout import (
    resource_has_name_property,
    resource_mode,
    resource_name_fields,
)
from design.policy_tables import literal
from design.services.definitions.registry import REQUIRED_NAME_TAG_TYPES
from issue_markdown import without_notices
from model.validation import (
    NAMING_EXEMPT_PROPERTIES,
    naming_rule_files,
    naming_target_matches,
    naming_targets,
)
from utils.aws_catalogs import catalog_outputs
from utils.aws_mappings import definition_root

from .records import identifier, safe_text
from .reports import inventories, issue_marker, issue_targets, numbered, owned_blocks


def rule_section(text, heading):
    lines = text.splitlines()
    result, active = [], False
    for line in lines:
        if line == heading:
            active = True
        elif active and line.startswith("## "):
            break
        if active:
            result.append(line)
    return "\n".join(result)


def naming_materials(comparison):
    rules, names, judgments = {}, [], []
    for service in comparison.services:
        if service not in comparison.models:
            if service in comparison.reference_unavailable:
                continue
            judgments.append(
                {
                    "id": identifier([service, "load-error"]),
                    "service": service,
                    "kind": "input-load-error",
                    "materials": "model unavailable; validators retain actual diagnostics",
                }
            )
            continue
        loaded = comparison.model(service)
        notes = [
            dict(
                key=key, value=safe_text(value), source=comparison.source(service, key)
            )
            for key, value in loaded.values.items()
            if key.startswith("desired.note.")
        ]
        if notes:
            judgments.append(
                {
                    "id": identifier([service, "notes"]),
                    "service": service,
                    "kind": "human-components/exceptions",
                    "materials": notes,
                }
            )
        for identity, resource in comparison.resources[service].items():
            try:
                mode = resource_mode(resource)
            except ValueError as error:
                judgments.append(
                    {
                        "id": identifier([service, identity, "mode-error"]),
                        "service": service,
                        "resource": identity,
                        "kind": "invalid-resource-mode",
                        "materials": str(error),
                        "source": comparison.source(
                            service, f"desired.resource.{identity}.resourceMode"
                        ),
                    }
                )
                continue
            kind = resource.get("resourceType")
            try:
                comparison.catalog.schema(kind)
            except (ValueError, KeyError, TypeError, AttributeError):
                judgments.append(
                    {
                        "id": identifier([service, identity, "type-error"]),
                        "service": service,
                        "resource": identity,
                        "kind": "invalid-resource-type",
                        "materials": "resource type unavailable; retain mechanical diagnostics",
                    }
                )
                continue
            owned = {}
            for rid, row in comparison.rows[service][identity]:
                kind = ".".join(row.get("property", "").split(".")[:2])
                owned.setdefault(kind, []).append((rid, row))
            owned.setdefault(resource["resourceType"], [])
            for kind, rows in owned.items():
                try:
                    comparison.catalog.schema(kind)
                except (ValueError, KeyError, TypeError, AttributeError):
                    judgments.append(
                        {
                            "id": identifier(
                                [service, identity, kind, "row-type-error"]
                            ),
                            "service": service,
                            "kind": "invalid-row-type",
                            "materials": "row type unavailable; retain mechanical diagnostics",
                        }
                    )
                    continue
                namespace = kind.partition(".")[0]
                if namespace not in rules:
                    shared = []
                    for file in naming_rule_files(comparison.root, namespace):
                        if file.is_relative_to(comparison.root):
                            comparison.inputs.add(file)
                        text = file.read_text(encoding="utf-8")
                        if file.name == "aws-resource-naming.md":
                            text = "\n\n".join(
                                rule_section(text, heading)
                                for heading in (
                                    "## Scope",
                                    "## General rules",
                                    "## Name tag policy",
                                )
                            )
                        if file.name == "aws-resource-naming.md":
                            rules.setdefault(
                                "common",
                                [
                                    {
                                        "path": file.relative_to(
                                            definition_root(comparison.root)
                                        ).as_posix(),
                                        "text": text,
                                    }
                                ],
                            )
                        else:
                            shared.append(
                                {
                                    "path": file.relative_to(
                                        definition_root(comparison.root)
                                    ).as_posix(),
                                    "text": text,
                                }
                            )
                    rules[namespace] = shared
                targets = naming_targets(comparison.root, namespace).get(kind, set())
                outputs = catalog_outputs(comparison.root, kind)
                fields = set(resource_name_fields(kind)) | targets
                selected = []
                for pos, (rid, row) in enumerate(rows):
                    prop = row["property"].removeprefix(kind + ".")
                    if row["property"] in outputs:
                        continue
                    if prop in fields or naming_target_matches(prop, targets, kind):
                        selected.append((rid, row, prop, row["value"]))
                    if (
                        prop in {"Tags[].Key", "HostedZoneTags[].Key"}
                        and literal(row["value"]) == "Name"
                    ):
                        valuefield = prop.replace(".Key", ".Value")
                        pair = (
                            rows[pos + 1]
                            if pos + 1 < len(rows)
                            and rows[pos + 1][1]["property"] == kind + "." + valuefield
                            else None
                        )
                        selected.append(
                            (
                                pair[0] if pair else rid,
                                pair[1] if pair else row,
                                "Name tag",
                                pair[1]["value"] if pair else None,
                            )
                        )
                    if prop in {"Tags", "HostedZoneTags"}:
                        try:
                            value = json.loads(literal(row["value"]))
                        except ValueError:
                            value = None
                        if isinstance(value, dict) and "Name" in value:
                            selected.append((rid, row, "Name tag", value["Name"]))
                        elif isinstance(value, list):
                            for tag in value:
                                if isinstance(tag, dict) and tag.get("Key") == "Name":
                                    selected.append(
                                        (rid, row, "Name tag", tag.get("Value"))
                                    )
                required = (
                    {"Name"}
                    if kind
                    in {
                        "EC2.VPC",
                        "EC2.Subnet",
                        "EC2.RouteTable",
                        "EC2.FlowLog",
                        "CodeBuild.Project",
                    }
                    else {"RoleName"}
                    if kind == "IAM.Role"
                    else {"Name tag"}
                    if kind in REQUIRED_NAME_TAG_TYPES
                    else set()
                )
                if (
                    resource_has_name_property(comparison.root, kind, mode)
                    and kind not in REQUIRED_NAME_TAG_TYPES
                ):
                    required.update(
                        set(resource_name_fields(kind))
                        & selected_properties(comparison.root, kind)
                        - {
                            field.removeprefix(kind + ".")
                            for field in catalog_outputs(comparison.root, kind)
                        }
                    )
                # IMPORT removes framework mandatory Name policy, not confirmed IAM/CodeBuild names.
                if mode == "IMPORT" and kind not in {"IAM.Role", "CodeBuild.Project"}:
                    required = set()
                for field in sorted(required - {item[2] for item in selected}):
                    selected.append((None, None, field, None))
                if not selected:
                    selected.append((None, None, "(no selected naming property)", None))
                for rid, row, field, value in selected:
                    key = (
                        f"desired.row.{rid}.value"
                        if rid
                        else f"desired.resource.{identity}.resourceType"
                    )
                    entry = {
                        "id": identifier([service, identity, kind, field, rid]),
                        "service": service,
                        "resource": identity,
                        "resourceType": kind,
                        "resourceMode": mode,
                        "property": field,
                        "value": comparison.redacted(value, field),
                        "required_missing": field in required and value is None,
                        "rule": namespace,
                        "rule_targets": sorted(targets),
                        "scope": "IMPORT framework convention excluded"
                        if mode == "IMPORT"
                        else "coverage exemption; apply exact convention/value scope from common rule"
                        if kind + "." + field in NAMING_EXEMPT_PROPERTIES
                        else "CREATE selected naming target",
                        "source": comparison.source(service, key),
                        "comment": safe_text(row["comment"]) if row else None,
                        "pattern_review": "not applicable"
                        if field == "(no selected naming property)"
                        else "exact exemption scope applies"
                        if kind + "." + field in NAMING_EXEMPT_PROPERTIES
                        else "required"
                        if mode == "CREATE"
                        else "framework convention excluded",
                        "human_context_id": identifier([service, "notes"])
                        if notes
                        else None,
                        "identity": {
                            key: resource[key]
                            for key in ("logicalId", "cfn-logicalId", "anchor")
                            if key in resource
                        },
                    }
                    names.append(entry)
    return {
        "target_context": comparison.target,
        "rules": rules,
        "names": names,
        "review_policy": "全名称のpattern/正本component/例外scopeを確認する。human_context_idの注記とrow commentを根拠にし、不足componentを値から推測しない。coverage除外をconvention/値検証除外へ拡大しない。",
    }, judgments


def existing_materials(root, environment, directory, services):
    path = root / "issues" / environment / directory / "issues.md"
    inventories(root, path)
    if not path.is_file():
        return [], []
    preamble, sections = owned_blocks(
        root, path, without_notices(path.read_text(encoding="utf-8"))
    )
    items = []
    preamble = without_notices(preamble)
    human_prefix, unowned = numbered(preamble)
    groups = [(None, unowned)] + [
        (service, numbered(body)[1]) for service, body in sections
    ]
    for service, issues in groups:
        if service not in services and service is not None:
            continue
        for text in issues:
            items.append(
                {
                    "id": identifier([service, text]),
                    "service": service,
                    "message": safe_text(text),
                    "kind": "existing-unresolved; current state decision required",
                    "marker": issue_marker(text),
                    "verification_targets": issue_targets(text),
                    "ownership_reason": "Service ownership cannot be established from the existing heading, markers or evidence links"
                    if service is None
                    else None,
                }
            )
    human = [
        line
        for line in human_prefix.splitlines()
        if line.strip() and not line.startswith(("#", "更新日時:", "今回確認した範囲:"))
    ]
    return items, human
