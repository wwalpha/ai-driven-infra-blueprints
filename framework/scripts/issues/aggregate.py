"""One current-run classification and bounded IaC overview."""

import json
from pathlib import Path

from utils.comparison_contract import CATEGORIES
from utils.iac_values import safe_value

from .records import brief, condition_disabled, iac_key, identifier, safe_text

IAC_CATEGORIES = {"difference", "uncompared", "error"}
IAC_CLASSES = (
    "要修正",
    "要対応",
    "要判断",
    "比較未完了",
    "CFn非対応・比較対象外",
    "処理エラー",
    "原因未確定",
)
MAX_GROUPS = 16
MAX_EXAMPLES = 10
MAX_FIELDS = 10


def pending_deploy_count(records):
    # Parent/child propagation of one property cause is one exclusion.
    return len(
        {
            (item["service"], item["resource"], identifier(item["cause"]))
            for item in records
            if item["category"] == "excluded"
            and item.get("cause", {}).get("kind")
            in {"import-reference-excluded", "desired-value-excluded"}
            and item["cause"]["phase"] == "pending_deploy"
        }
    )


def diagnostic_description(item):
    details = []
    reasons = set()
    for diagnostic in item.get("reference_diagnostics", []):
        reason = diagnostic.get("reason")
        if not reason:
            continue
        parts = []
        correspondences = diagnostic.get("correspondence_path") or [
            {"correspondence": diagnostic.get("correspondence")}
        ]
        for entry in correspondences:
            correspondence = entry.get("correspondence")
            if isinstance(correspondence, dict) and correspondence.get("value"):
                parts.append(str(correspondence["value"]))
            elif correspondence == "unproven":
                parts.append("対応未確定")
        for side in ("model", "iac"):
            value = diagnostic.get(side)
            resource = value.get("$resource") if isinstance(value, dict) else None
            if isinstance(resource, list) and len(resource) == 2:
                label = "_".join(str(part) for part in resource)
                if value.get("$attribute"):
                    label += "." + str(value["$attribute"])
                parts.append(label)
        if not any(
            isinstance(diagnostic.get(side), dict)
            and diagnostic[side].get("$attribute")
            for side in ("model", "iac")
        ):
            parts.append(diagnostic.get("path", item["property"]).rsplit(".", 1)[-1])
        details.append(" / ".join(dict.fromkeys(parts)) + ": " + reason)
        reasons.add(reason)
    for child in item.get("deferred_children", []):
        reason = child.get("reason")
        if reason and reason not in reasons:
            details.append(f"{child['property'].rsplit('.', 1)[-1]}: {reason}")
            reasons.add(reason)
    return (
        " / ".join(dict.fromkeys(details))
        or item.get("reason")
        or "原因または対応先を確定できない。"
    )


def iac_actions(entries, environment, directory):
    """O(N) grouping by proven cause/repair target/action; unknowns remain separate."""
    groups = {}
    for index, entry in enumerate(entries):
        item = entry["record"]
        if item["category"] not in IAC_CATEGORIES:
            continue
        cause = item.get("cause", {})
        path = cause.get("path")
        repair_direction = "未確定"
        # Keep the unknown-cause identity even when its response becomes actionable.
        key = [
            environment,
            directory,
            "unresolved",
            entry["id"],
            item["category"],
            item["reason"],
            item.get("iac"),
            None,
        ]
        known_missing = (
            cause.get("kind") in {"template-missing", "parameters-missing"}
            and path
            and cause.get("relationship")
            in {"direct", "stack-input", "export-search-incomplete"}
        )
        if known_missing:
            repair_direction = "入力修正"
            action = (
                "confirm-create-template"
                if cause["kind"] == "template-missing"
                else "confirm-stack-parameters"
            )
            key = [environment, directory, cause["kind"], path, action]
            title = Path(path).name + (
                " のテンプレート未作成"
                if cause["kind"] == "template-missing"
                else " の入力ファイル欠落"
            )
            classification = (
                "IaC未実装" if cause["kind"] == "template-missing" else "設定不一致"
            )
            description = f"{path} が存在しない。"
            remedy = (
                "CREATE対象と実装要否を確認し、未実装ならModelに従ってテンプレートを作成する。意図的な未実装なら状態を明示して管理する。"
                if cause["kind"] == "template-missing"
                else "Stack設計のparameters指定と配置先を確認し、必要な入力ファイルを作成・配置する。"
            )
            target, status = path, "要対応"
            if item["category"] in {"uncompared", "error"}:
                classification, status = "比較未完了", "要調査"
                description = (
                    f"{path} の欠落により参照探索を完了できない。設定差分は未確定。"
                )
                remedy = "参照先とExport宣言・探索範囲を確認して再比較する。Model/IaCの修正要否は未確定。"
        elif condition_disabled(item):
            target = path
            key = [
                environment,
                directory,
                "condition-disabled",
                path,
                item["stack"],
                cause["logical"],
                cause["condition"],
            ]
            title = f"Condition {cause['condition']} によるCREATE無効化"
            classification, status = "ConditionによるCREATE無効化", "要判断"
            description = f"確認済み入力でCondition {cause['condition']} = falseとなり、CREATE対象が無効になる。"
            remedy = "意図的な無効化か設計との不整合かを、Conditionと原因入力・取得元に基づいて確認する。修正要否・修正先は未確定。"
        elif (
            item["category"] == "uncompared"
            and cause.get("kind") == "cloudformation-unsupported"
        ):
            target = None
            key = [
                environment,
                directory,
                "cloudformation-unsupported",
                cause["resource_type"],
                "confirm-api-implementation-scope",
            ]
            title = f"{cause['resource_type']} はCloudFormation非対応"
            classification, status = "CFn非対応・比較対象外", "要確認"
            description = (
                "既知のAPI専用リソースのためCFn比較対象外。API側の実装状態は未確認。"
            )
            remedy = "実装scopeとAPI側の実装状態を確認する。実装scopeに含まれる場合は未実装として扱い、実装完了にしない。CFn一致の根拠には含めない。"
        elif (
            item["category"] == "uncompared"
            and cause.get("kind") == "import-unresolved"
        ):
            target = None
            key = [environment, directory, "import-unresolved", cause["export"]]
            title = f"Export {cause['export']} の参照解決が未完了"
            classification, status = "比較未完了", "要調査"
            description = (
                "参照先Exportの一意性または値を確認できない。設定差分は未確定。"
            )
            remedy = "Export/Importの宣言・有効条件・参照先を確認して再比較する。Model/IaCの修正要否は未確定。"
        elif item["category"] == "difference" and item["reason"].startswith(
            "KMS format"
        ):
            target = None
            key = [environment, directory, "kms-format", entry["id"]]
            proven = item["reason"].startswith(
                ("KMS format outside allowed forms:", "KMS format mismatch:")
            )
            title = (
                f"{item['service']} / {item['resource']} / {item['property']} のKMS指定形式が"
                + ("不適合" if proven else "未確定")
            )
            classification, status = (
                ("KMS指定形式違反", "要修正") if proven else ("原因未確定", "要調査")
            )
            repair_direction = "修正先要確認" if proven else "未確定"
            formats = (
                [
                    field.get("format", {})
                    for field in item.get("reference_diagnostics", [])
                ]
                if proven
                else []
            )
            for side, other, direction in (
                ("iac", "model", "IaC修正"),
                ("model", "iac", "Model修正"),
            ):
                if (
                    formats
                    and all(field.get(other) == "allowed" for field in formats)
                    and any(
                        field.get(side) == "outside allowed forms" for field in formats
                    )
                ):
                    repair_direction = direction
                    target = (item.get(side) or {}).get("path")
            diagnostic = next(iter(item.get("reference_diagnostics", [])), {})
            description = f"{diagnostic.get('path', item['property']).rsplit('.', 1)[-1]}: {item['reason']}"
            remedy = (
                "許可形式と両側の形式を確認し、形式不適合のModel/IaCを修正する。参照先が同じでも形式差は一致扱いしない。"
                if proven
                else "許可形式と両側の形式を確認し、形式違反の有無と修正先を特定する。"
            )
        elif cause.get("kind") == "input-invalid":
            target = (item.get("iac") or {}).get("path")
            if cause.get("rule") == "unique-key":
                key = [
                    environment,
                    directory,
                    target,
                    item.get("stack"),
                    item["service"],
                    item["resource"],
                    item["property"].removesuffix("[]." + cause["key"]),
                    cause,
                ]
            repair_direction = "入力修正"
            prop = item["property"].removesuffix("[]." + cause.get("key", ""))
            title = f"{item['service']} / {item['resource']} / {prop} の入力不正"
            classification, status = "IaC入力不正", "要修正"
            description = (
                "duplicate input key: " + cause["key"]
                if cause.get("rule") == "unique-key"
                else item["reason"]
            )
            remedy = "対象ResourceとIaC Pointerの証跡を確認し、重複したキーを修正する。"
        elif item["category"] == "difference" and item["reason"] in {
            "value mismatch",
            "property missing",
            "resource missing",
            "inline CREATE child missing",
            "property omitted by AWS::NoValue",
        }:
            target = (item.get("iac") or {}).get("path")
            if target and item.get("stack"):
                key = [
                    environment,
                    directory,
                    target,
                    item["stack"],
                    item["service"],
                    item["resource"],
                    item["property"],
                    item["reason"],
                    "sync-model-iac",
                ]
            repair_direction = (
                "IaC修正" if target and item.get("stack") else "修正先要確認"
            )
            title = (
                f"{item['service']} / {item['resource']} / {item['property']} の"
                + (
                    "値の不一致"
                    if item["reason"] == "value mismatch"
                    else "未実装・設定欠落"
                )
            )
            classification, status = "Model/IaC差分", "要修正"
            description = {
                "value mismatch": "ModelとIaCの設定値が一致しない。",
                "property missing": "Modelにある設定がIaCに存在しない。",
                "resource missing": "Modelに対応するCREATEリソースがIaCに存在しない。",
                "inline CREATE child missing": "Modelに対応する子リソースがIaCに存在しない。",
                "property omitted by AWS::NoValue": "設定がAWS::NoValueにより省略される。",
            }[item["reason"]]
            remedy = (
                "Modelの要求設定をIaCに反映する。"
                if repair_direction == "IaC修正"
                else "確定した設定差分を解消する。修正先要確認: Modelの設計意図とIaCの対応箇所を確認する。"
            )
        else:
            target = None
            title = f"{item['service']} / {item['resource']} / {item['property']} の確認が必要"
            classification, status = (
                (
                    "処理エラー"
                    if item["category"] == "error"
                    else "比較未完了"
                    if item["category"] == "uncompared"
                    else "原因未確定"
                ),
                "要調査",
            )
            description = diagnostic_description(item)
            remedy = (
                "Export/Importの参照関係・宣言・有効条件と探索の完了を確認する。直接依存は未確定。"
                if "ImportValue" in item["reason"]
                else "記載した検出理由とModel/IaCの対応・検証ルールを確認し、原因と修正先を特定する。"
            )
        if item.get("deferred_children") and description != diagnostic_description(
            item
        ):
            description += " / " + diagnostic_description(item)
        group_id = "ISSUE-" + identifier(key)
        group = groups.setdefault(
            group_id,
            {
                "id": group_id,
                "title": title,
                "classification": classification,
                "description": description,
                "remedy": remedy,
                "target": target,
                "status": status,
                "repair_direction": repair_direction,
                "members": [],
            },
        )
        group["members"].append(index)
        # A direct confirmed omission remains actionable when its dependent
        # unresolved references share the cause, regardless of input ordering.
        if known_missing and item["category"] == "difference":
            group.update(
                classification=classification,
                description=description,
                remedy=remedy,
                status=status,
            )
    return sorted(
        groups.values(),
        key=lambda group: (
            group["status"] != "要修正",
            group["status"] != "要対応",
            group["classification"],
            group["id"],
        ),
    )


def iac_dataset(
    records, environment, directory, services, display=None, *, redact=safe_value
):
    """Current-run data only; causal Issue identities are independent of display grouping."""
    scoped = set(services)
    if any(item["service"] not in scoped for item in records):
        raise ValueError("IaC record outside selected services")
    if any(item.get("category") not in CATEGORIES for item in records):
        raise ValueError("invalid comparison category")
    entries = []
    for index, item in enumerate(records):
        record = dict(
            redact(item),
            reason=safe_text(redact(item["reason"])),
            **{
                key: redact(item[key], item.get("property", ""))
                for key in ("desired", "actual")
                if key in item
            },
        )
        record_id = identifier(record)
        entries.append(
            dict(
                id=iac_key(item),
                record=record,
                record_index=index,
                record_id=record_id,
                display_key=record_id if record == item else identifier(item),
            )
        )
    entries.sort(
        key=lambda entry: (entry["record"]["service"], entry["id"], entry["record_id"])
    )
    shown = {}
    for entry in entries:
        key = entry["record_id"]
        fields = (display or {}).get(entry["display_key"])
        if fields is None:
            continue
        if not isinstance(fields, list) or any(
            not isinstance(field, dict)
            or any(
                not isinstance(field.get(name), str)
                for name in ("path", "model", "iac")
            )
            for field in fields
        ):
            raise ValueError("malformed IaC value difference display")
        shown[key] = []
        for field in fields:
            safe = {"path": safe_text(field["path"])}
            for side in ("model", "iac"):
                value = field[side]
                masked = redact(
                    value, entry["record"]["property"] + "." + field["path"]
                )
                safe[side] = safe_text(json.dumps(masked) if masked != value else value)
            shown[key].append(safe)
    actions = iac_actions(entries, environment, directory)
    for group in actions:
        group["category"] = (
            group["status"]
            if group["status"] in IAC_CLASSES
            else group["classification"]
        )
    return entries, actions, shown


def iac_summary(
    records,
    environment,
    directory,
    services,
    display=None,
    *,
    include_index=False,
    dataset=None,
):
    entries, actions, shown = (
        dataset
        if dataset is not None
        else iac_dataset(records, environment, directory, services, display)
    )
    groups = {}
    counts = {category: 0 for category in IAC_CLASSES}
    for action in actions:
        category = action["category"]
        counts[category] += 1
        members = [entries[i]["record"] for i in action["members"]]
        # One display unit per proven action; prose similarity never merges unknown causes.
        group = groups.setdefault(
            action["id"],
            dict(
                id=action["id"],
                category=category,
                problem=brief(action["title"]),
                cause=brief(action["description"]),
                remedy=action["remedy"],
                target=action["target"],
                repair_direction=action["repair_direction"],
                services=sorted({item["service"] for item in members}),
                stacks=set(),
                issues=0,
                records=0,
                direct=set(),
                uncompared=0,
                errors=0,
                cascading=0,
                examples=[],
            ),
        )
        group["issues"] += 1
        group["records"] += len(members)
        group["direct"].update(
            (item["service"], item["resource"], item.get("stack"))
            for item in members
            if item["category"] == "difference"
        )
        group["stacks"].update(
            stack
            for item in members
            for stack in (
                item.get("stack"),
                item.get("cause", {}).get("consumer_stack"),
                item.get("cause", {}).get("stack"),
            )
            if stack
        )
        if not group["stacks"]:
            group["stacks"].add("未確定")
        group["uncompared"] += sum(item["category"] == "uncompared" for item in members)
        group["errors"] += sum(item["category"] == "error" for item in members)
        group["cascading"] += sum(
            item.get("cause", {}).get("relationship") in {"export-search-incomplete"}
            for item in members
        )
        for i in sorted(
            action["members"],
            key=lambda i: (
                entries[i]["record"].get("cause", {}).get("relationship") != "direct",
                entries[i]["id"],
                entries[i]["record_id"],
            ),
        ):
            if len(group["examples"]) >= MAX_EXAMPLES:
                break
            item = entries[i]["record"]
            example = {
                name: brief(item[name])
                for name in ("service", "resource", "property", "reason")
            }
            example.update(issue_id=action["id"], record_id=entries[i]["id"])
            if condition_disabled(item):
                cause = item["cause"]
                example["condition"] = {
                    name: brief(cause[name])
                    for name in ("condition", "result", "stack", "logical")
                }
                example["condition"]["template"] = brief(
                    json.dumps(item["iac"], ensure_ascii=False)
                )
                example["condition"]["inputs"] = [
                    {
                        name: brief(json.dumps(value[name], ensure_ascii=False))
                        for name in ("name", "value", "source")
                    }
                    for value in cause["inputs"][:MAX_EXAMPLES]
                ]
                example["condition"]["omitted_inputs"] = max(
                    0, len(cause["inputs"]) - MAX_EXAMPLES
                )
            children = item.get("deferred_children", [])
            if children:
                example["deferred_children"] = [
                    {
                        name: brief(child[name])
                        for name in ("property", "reason", "category")
                    }
                    for child in children[:MAX_FIELDS]
                ]
                example["omitted_deferred_children"] = max(
                    0, len(children) - MAX_FIELDS
                )
            diagnostics = item.get("reference_diagnostics", [])
            if diagnostics:
                example["reference_diagnostics"] = [
                    {
                        name: brief(field[name])
                        for name in (
                            "path",
                            "model",
                            "iac",
                            "identity",
                            "allowed_forms",
                            "format",
                            "reason",
                        )
                    }
                    | (
                        {"local_comparison": brief(field["local_comparison"])}
                        if "local_comparison" in field
                        else {}
                    )
                    for field in diagnostics[:MAX_FIELDS]
                ]
                example["omitted_reference_fields"] = max(
                    0, len(diagnostics) - MAX_FIELDS
                )
            fields = shown.get(entries[i]["record_id"])
            if (
                item["category"] == "difference"
                and item["reason"]
                in {
                    "value mismatch",
                    "property missing",
                    "property omitted by AWS::NoValue",
                }
            ) or (item["category"] == "uncompared" and fields):
                example["fields"] = [
                    {name: brief(field[name]) for name in ("path", "model", "iac")}
                    for field in (fields or [])[:MAX_FIELDS]
                ]
                example["omitted_fields"] = max(0, len(fields or []) - MAX_FIELDS)
                example["field_status"] = (
                    "検出は不一致。マスク済み値から相違項目を復元できない。"
                    if not fields
                    else ""
                )
            group["examples"].append(example)
    ordered = sorted(
        groups.values(),
        key=lambda group: (
            IAC_CLASSES.index(group["category"]),
            group["services"],
            group["problem"],
            group["target"] or "",
            group["examples"][0]["issue_id"],
        ),
    )
    for group in ordered:
        group["direct_resources"] = len(group.pop("direct"))
        stacks = sorted(group["stacks"])
        group["stacks"] = [brief(stack) for stack in stacks[:5]]
        group["omitted_stacks"] = max(0, len(stacks) - 5)
        group["omitted_examples"] = group["records"] - len(group["examples"])
    # Give every present category a representative before filling the bounded list.
    visible = [
        next(group for group in ordered if group["category"] == category)
        for category in IAC_CLASSES
        if any(group["category"] == category for group in ordered)
    ]
    visible += [group for group in ordered if group not in visible][
        : MAX_GROUPS - len(visible)
    ]
    visible.sort(
        key=lambda group: (
            IAC_CLASSES.index(group["category"]),
            group["services"],
            group["problem"],
            group["examples"][0]["issue_id"],
        )
    )
    visible_ids = {group["examples"][0]["issue_id"] for group in visible}
    raw = {
        kind: sum(item["category"] == kind for item in records) for kind in CATEGORIES
    }
    return dict(
        issue_count=len(actions),
        categories=counts,
        record_count=len(records),
        records=raw,
        pending_deploy_excluded=pending_deploy_count(records),
        comparison_incomplete=any(
            item.get("comparison_incomplete") for item in records
        ),
        **(
            {
                "index": [
                    {
                        key: group[key]
                        for key in (
                            "id",
                            "category",
                            "problem",
                            "cause",
                            "remedy",
                            "target",
                            "repair_direction",
                            "records",
                            "services",
                        )
                    }
                    for group in ordered
                ]
            }
            if include_index
            else {}
        ),
        proven_causes=sum(
            any(
                (
                    entries[i]["record"].get("cause", {}).get("kind")
                    in {"template-missing", "parameters-missing"}
                    and entries[i]["record"].get("cause", {}).get("path")
                    and entries[i]["record"].get("cause", {}).get("relationship")
                    in {"direct", "stack-input", "export-search-incomplete"}
                )
                or entries[i]["record"].get("cause", {}).get("kind")
                in {"import-unresolved", "cloudformation-unsupported"}
                or condition_disabled(entries[i]["record"])
                for i in action["members"]
            )
            for action in actions
        ),
        direct_resources=len(
            {
                (item["service"], item["resource"], item.get("stack"))
                for item in records
                if item["category"] == "difference"
            }
        ),
        group_count=len(ordered),
        omitted_groups=max(0, len(ordered) - MAX_GROUPS),
        omitted_issues=len(actions) - sum(group["issues"] for group in visible),
        omitted_records=sum(group["records"] for group in ordered)
        - sum(group["records"] for group in visible),
        omitted_categories={
            category: sum(
                group["issues"]
                for group in ordered
                if group not in visible and group["category"] == category
            )
            for category in IAC_CLASSES
        },
        omitted_record_categories={
            kind: sum(
                entries[i]["record"]["category"] == kind
                for action in actions
                if action["id"] not in visible_ids
                for i in action["members"]
            )
            for kind in ("difference", "uncompared", "error")
        },
        groups=visible,
    )


def comparison_status(counts, *, incomplete=False):
    return (
        "error"
        if counts["error"]
        else "partial"
        if incomplete or counts["uncompared"] or counts["deferred"]
        else "differences"
        if counts["difference"]
        else "complete match"
        if counts["matched"]
        else "no compared records"
    )


def aggregate(
    records, environment, directory, services, display=None, *, redact=safe_value
):
    dataset = iac_dataset(
        records, environment, directory, services, display, redact=redact
    )
    entries, actions, shown = dataset
    overview = iac_summary(
        records, environment, directory, services, include_index=True, dataset=dataset
    )
    compact = {
        item["id"]: dict(item, report_order=i)
        for i, item in enumerate(overview.pop("index"))
    }
    membership = {
        entries[i]["record_index"]: group["id"]
        for group in actions
        for i in group["members"]
    }
    meta = [None] * len(entries)
    normalized = [None] * len(entries)
    for entry in entries:
        i = entry["record_index"]
        normalized[i] = entry["record"]
        meta[i] = dict(
            record_id=entry["record_id"],
            issue_id=membership.get(i),
            category=entry["record"]["category"],
        )
    issues = [
        dict(
            group,
            members=[entries[i]["record_index"] for i in group["members"]],
            compact=compact[group["id"]],
        )
        for group in actions
    ]
    return dict(
        iac=normalized,
        iac_display=shown,
        iac_issues=issues,
        record_meta=meta,
        overview=overview,
    )
