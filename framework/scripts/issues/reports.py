"""Deterministic reports from the current reviewed snapshot only."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from task_contract_core import relative_path

from .aggregate import MAX_EXAMPLES, comparison_status, iac_summary
from .records import brief, identifier, safe_text


def evidence(root, report, source):
    if not source:
        return ""
    path = root / relative_path(source["path"])
    number = source.get("line")
    if number is not None and (type(number) is not int or number < 1):
        raise ValueError("invalid evidence line")
    label = source["path"] + (f":{number}" if number else "")
    relative = Path(os.path.relpath(path, report.parent)).as_posix()
    target = "<" + relative + ">" if " " in relative else relative
    return f"[{label}]({target})"


def issue_key(root, record):
    message = safe_text(record["message"]).replace(str(root) + "/", "")
    return identifier([record["service"], record.get("key", message)])


def issue_content(root, path, record):
    message = safe_text(record["message"]).replace(str(root) + "/", "")
    message = escape(message, quote=False)
    link = evidence(root, path, record.get("source"))
    return (
        message
        + (f" 根拠: {link}。" if link else "")
        + f" <!-- issue-id: {issue_key(root, record)} -->"
    )


def ordinary_report(root, artifact):
    environment, directory, services = (
        artifact[key] for key in ("environment", "target", "services")
    )
    path = root / "issues" / environment / directory / "issues.md"
    stamp = (
        datetime.fromisoformat(artifact["executed_at"].replace("Z", "+00:00"))
        .astimezone(timezone(timedelta(hours=9)))
        .strftime("%Y-%m-%d %H:%M:%S Asia/Tokyo")
    )
    incomplete = bool(artifact["unverified"] or artifact["processing_errors"])
    lines = [
        "# 問題一覧",
        "",
        f"Scan実行日時: {stamp}",
        f"今回確認した範囲: {environment}／{directory}／{', '.join(services)}",
        "今回の検証: 未完了（未検証・処理エラーあり）"
        if incomplete
        else "今回の検証: ローカルScanとLLM Review済み（AWS未検証）",
        "",
        f"## {environment}／{directory}",
        "",
    ]
    for service in services:
        records = {
            issue_key(root, item): item
            for item in artifact["ordinary"]
            if item["service"] == service
        }
        if records:
            lines.extend(
                [f"### {service}", "", f"<!-- issue-service: {service} -->", ""]
            )
            lines.extend(
                f"{number}. {issue_content(root, path, item)}\n"
                for number, (_, item) in enumerate(sorted(records.items()), 1)
            )
    if not artifact["ordinary"]:
        lines.extend(
            ["未解決issueなし（検証未完了）" if incomplete else "未解決issueなし", ""]
        )
    scope_id = identifier([environment, directory, services])
    lines.append(f"<!-- issues-notices:{scope_id}:start -->")
    for channel, heading in (
        ("information", "情報"),
        ("unverified", "未検証範囲"),
        ("processing_errors", "処理エラー（未検証範囲あり）"),
        ("warnings", "警告（非ブロッキング）"),
    ):
        if artifact[channel]:
            lines.extend(["## " + heading, ""])
            lines.extend(
                "- "
                + escape(safe_text(json.dumps(value, ensure_ascii=False)), quote=False)
                for value in artifact[channel]
            )
    lines.append(f"<!-- issues-notices:{scope_id}:end -->")
    return "\n".join(lines) + "\n"


def repair_target(group):
    direction = group.get("repair_direction", "未確定")
    label = {
        "IaC修正": "IaC",
        "Model修正": "Model",
        "入力修正": "不足入力",
        "修正先要確認": "Model／IaC（修正先要確認）",
        "未確定": "未特定（修正方向は未確定）",
    }[direction]
    return label + (": " + brief(group["target"]) if group["target"] else "")


def iac_report(
    environment,
    directory,
    services,
    records,
    display=None,
    *,
    stamp=None,
    artifact=None,
):
    summary = (
        dict(
            artifact["overview"],
            index=sorted(
                (group["compact"] for group in artifact["iac_issues"]),
                key=lambda item: item["report_order"],
            ),
        )
        if artifact is not None
        else iac_summary(
            records, environment, directory, services, display, include_index=True
        )
    )
    counts = summary["records"]
    unverified_services = (
        [
            item["service"]
            for item in artifact.get("service_results", [])
            if item["status"] == "unverified"
        ]
        if artifact
        else []
    )
    status = comparison_status(counts, incomplete=bool(unverified_services))
    if stamp and stamp.endswith("Z"):
        stamp = (
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            .astimezone(timezone(timedelta(hours=9)))
            .strftime("%Y-%m-%d %H:%M:%S Asia/Tokyo")
        )
    stamp = stamp or datetime.now(timezone(timedelta(hours=9))).strftime(
        "%Y-%m-%d %H:%M:%S Asia/Tokyo"
    )
    lines = [
        "# model → IaC比較の非阻害結果",
        "",
        f"実行日時: {stamp}",
        f"今回指定した範囲: {environment}／{directory}／{', '.join(sorted(set(services)))}",
        f"今回の判定: {status}",
        "未検証Service: "
        + (
            ", ".join(unverified_services)
            if unverified_services
            else "なし（IaC比較の未比較・保留・処理エラーは別集計）"
        ),
        "今回のTarget全Serviceの結果。未実施・失敗は未検証。通常issue gateの停止対象外。",
        f"問題: {summary['issue_count']}件（原因・必要対応単位）",
        f"影響: 差分 {counts['difference']}件 / 未比較 {counts['uncompared']}項目 / 処理エラー {counts['error']}項目",
        f"元レコード数: {summary['record_count']}（一致 {counts['matched']} / 想定内保留 {counts['deferred']} / 除外 {counts['excluded']}）",
        "分類: "
        + " / ".join(
            f"{category} {count}件" for category, count in summary["categories"].items()
        )
        + f" / PENDING_DEPLOY（比較対象外） {summary['pending_deploy_excluded']}件",
        f"表示{len(summary['groups'])}／全{summary['issue_count']}対応単位、未表示{summary['omitted_issues']}",
        "未表示の分類: "
        + " / ".join(
            f"{category} {count}件"
            for category, count in summary["omitted_categories"].items()
        ),
        "未表示の影響: "
        + " / ".join(
            f"{kind} {count}件"
            for kind, count in summary["omitted_record_categories"].items()
        ),
        "",
    ]
    if summary["comparison_incomplete"]:
        lines.extend(
            [
                "比較途中終了: 収集済みレコードを保持。未実施範囲は未検証であり、一致・修正完了とは扱わない。",
                "",
            ]
        )
    lines.extend(
        [
            "## 全Issueの簡易一覧",
            "",
            "| Issue ID | 分類 | 原因・問題 | 修正対象 | 必要な操作 | 影響レコード数 | 影響Service |",
            "| --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for item in summary["index"]:
        lines.append(
            "| "
            + " | ".join(
                brief(value).replace("\n", " ").replace("\r", " ")
                for value in (
                    item["id"],
                    item["category"],
                    item["problem"] + "：" + item["cause"],
                    repair_target(item),
                    item["remedy"],
                    item["records"],
                    ", ".join(item["services"]),
                )
            )
            + " |"
        )
    lines.extend(["", "## 詳細（最大16グループ）", ""])
    for group in summary["groups"]:
        lines.extend(
            [
                f"### {group['id']} / {group['category']}: {group['problem']}",
                f"- 原因: {group['cause']}",
                f"- 必要な対応: {group['remedy']}",
                f"- 修正対象: {repair_target(group)}",
                f"- 影響範囲: {', '.join(group['services'])}。{group['records']}レコード / 直接差分 {group['direct_resources']}リソース / 未比較 {group['uncompared']}項目 / 処理エラー {group['errors']}項目",
            ]
        )
        if group.get("repair_direction") == "IaC修正":
            lines.append("- 確認事項: Modelの要求設定が設計意図と一致すること。")
        if group["cascading"]:
            lines.append(
                f"- 探索中断: {group['cascading']}項目。直接Import依存は未確定。"
            )
        for example in group["examples"]:
            lines.append(
                f"対象: {example['service']} / {example['resource']} / {example['property']}: {example['reason']}"
            )
            for child in example.get("deferred_children", []):
                lines.append(
                    f"保留原因の子項目: {child['property']} / {child['category']}: {child['reason']}"
                )
            if example.get("omitted_deferred_children"):
                lines.append(
                    f"省略保留原因: {example['omitted_deferred_children']}件（全文はartifact）"
                )
            for field in example.get("reference_diagnostics", []):
                lines.extend(
                    [
                        "参照field: " + field["path"],
                        "- Model参照: " + field["model"],
                        "- IaC参照: " + field["iac"],
                        "- 参照同一性: " + field["identity"],
                        "- 許容形式: " + field["allowed_forms"],
                        "- 静的形式適合性: " + field["format"],
                        "- ローカル具体値比較: "
                        + field.get("local_comparison", "未実施"),
                        "- 証明／比較理由: " + field["reason"],
                    ]
                )
            if example.get("omitted_reference_fields"):
                lines.append(
                    f"省略参照フィールド: {example['omitted_reference_fields']}件"
                )
            if "condition" in example:
                condition = example["condition"]
                lines.extend(
                    [
                        f"Condition: {condition['condition']} = false",
                        f"Stack／論理ID: {condition['stack']}／{condition['logical']}",
                        "テンプレート位置: " + condition["template"],
                    ]
                )
                for value in condition["inputs"]:
                    lines.append(
                        f"原因入力: {value['name']} = {value['value']} / 取得元: {value['source']}"
                    )
                if condition["omitted_inputs"]:
                    lines.append(
                        f"省略原因入力: {condition['omitted_inputs']}件（全文はartifact）"
                    )
            if "fields" in example:
                if example["field_status"]:
                    lines.append("相違項目: " + example["field_status"])
                for field in example["fields"]:
                    lines.extend(
                        [
                            "相違項目: " + field["path"],
                            "- Model: " + field["model"],
                            "- IaC: " + field["iac"],
                        ]
                    )
                    if field["model"] == field["iac"]:
                        lines.append(
                            "不一致の検出結果を保持（短縮・マスキングまたはキー重複）。"
                        )
                if example["omitted_fields"]:
                    lines.append(f"省略相違フィールド: {example['omitted_fields']}件")
        if group["omitted_examples"]:
            lines.append(f"省略代表例: {group['omitted_examples']}レコード")
        lines.append("")
    waits = [item for item in records if item["category"] == "deferred"]
    if waits:
        lines.extend(
            [
                "## 想定内保留（Issue対象外）",
                "",
                f"想定内保留件数: {counts['deferred']}件。比較状態: {status}。保留は一致・比較完了には含めない。",
                "",
            ]
        )
        reasons = {
            "unobserved": "識別子が未観測",
            "awaiting_handoff": "識別子の形式は検証済み、承認済みhandoff待ち",
        }
        for item in waits[:MAX_EXAMPLES]:
            cause = item["cause"]
            producer = cause["producer"]
            lines.extend(
                [
                    f"- Service: {brief(item['service'])} / Resource: {brief(item['resource'])} / Property: {brief(item['property'])}",
                    f"  - Producer Resource: {brief(producer['service'])}/{brief(producer['resource'])} ({brief(producer['resourceType'])}) / 参照属性: {brief(producer['attribute'])}",
                    "  - 保留理由: " + reasons[cause["phase"]],
                    "  - 保留解除条件: 識別子の観測・形式検証と既存契約による承認済みhandoffの確認後に再比較する。",
                    "  - 比較状態: deferred（比較保留）",
                ]
            )
        if len(waits) > MAX_EXAMPLES:
            lines.append(
                f"保留表示省略: {len(waits) - MAX_EXAMPLES}件（全レコードはArtifactに保存）"
            )
        lines.extend(
            [
                "",
                "保留の全レコード取得（offsetを50ずつ進める）:",
                "```console",
                "python3 framework/scripts/issues_scan.py detail --artifact <path> --section iac --record-category deferred --offset 0 --limit 50",
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## 全メンバー取得",
            "",
            "代表例は修正対象の上限ではない。同じscanの一時artifactから一覧のIssue IDで全メンバーを取得する。",
            "```console",
            "python3 framework/scripts/issues_scan.py detail --artifact <path> --section iac --issue-id ISSUE-<id> --offset 0 --limit 50",
            "```",
            "offsetを50ずつ進め、total件すべてを確認する。後続の修正タスクは全メンバーを調査・再比較し、未比較を修正完了と扱わない。",
            "",
        ]
    )
    return "\n".join(lines)
