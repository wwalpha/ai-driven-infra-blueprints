import json

from design.catalog import selected_properties
from design.layout import (
    resource_has_name_property,
    resource_mode,
    resource_name_fields,
)
from design.policy_tables import literal
from design.services.definitions.registry import REQUIRED_NAME_TAG_TYPES
from model.validations.naming import (
    NAMING_EXEMPT_PROPERTIES,
    naming_rule_files,
    naming_target_matches,
    naming_targets,
)
from utils.aws_catalogs import catalog_outputs
from utils.aws_mappings import definition_root

from .records import identifier, safe_text


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


def naming_materials(comparison, *, service=None):
    rules, names, judgments = {}, [], []
    services = comparison.services if service is None else [service]
    for service in services:
        if service not in comparison.models:
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
                    provider_errors = []
                    shown = comparison.redacted(value, field)
                    raw = literal(value) if isinstance(value, str) else None
                    available = (
                        isinstance(raw, str)
                        and bool(raw.strip())
                        and raw.lower()
                        not in {
                            "unresolved",
                            "unset",
                            "tbd",
                            "todo",
                            "pending_deploy",
                            "未確定",
                        }
                        and not any(token in raw for token in ("${", "{{", "<masked"))
                        and not raw.startswith(("[", "{"))
                        and shown == value
                    )
                    if field != "Name tag" and available:
                        try:
                            provider_errors = comparison.catalog.literal_errors(
                                kind, field, literal(value)
                            )
                        except KeyError:
                            pass  # Design-only names do not have provider properties.
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
                        "value": shown,
                        "value_available": available,
                        "required_missing": field in required and value is None,
                        "provider_errors": comparison.redacted(provider_errors, field),
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
        "review_policy": "全名称を確認し、Patternに含まれるcomponentだけを対象に正本で確定した値を比較する。未確認componentを名前から推測せず、その不足だけでIssueや未検証にしない。独立して確認できる固定要素、構造、形式、確定値の違反は報告する。検査実行不能は未検証に残す。coverage除外をconvention/値検証除外へ拡大しない。applied_ruleは対象のPattern、rule_missingは共通規則のpath、provider_constraintは対象のprovider_errorsを指定する。confirmed_mismatchの期待値は対象設定または対象に対応するHuman confirmationのcomponent=valueから確認する。",
    }, judgments
