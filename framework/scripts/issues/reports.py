"""Deterministic reports from the current reviewed snapshot only."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from task_contract_core import relative_path
from validation.diagnostics import Diagnostic

from .aggregate import aggregate, comparison_status
from .ownership import resolve
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


def report_message(value):
    if isinstance(value, str):
        try:
            structured = json.loads(value)
        except ValueError:
            return value
        if not isinstance(structured, (dict, list)):
            return value
        value = structured
    if isinstance(value, dict):
        return report_message(
            value.get("message")
            or value.get("Message")
            or value.get("reason")
            or value.get("code")
            or "詳細はartifact"
        )
    return "詳細はartifact" if isinstance(value, list) else str(value)


def report_source(root, record):
    if isinstance(record.get("source"), dict):
        return record["source"]
    diagnostic = record.get("diagnostic", {})
    source = (
        record.get("source")
        or record.get("source_path")
        or diagnostic.get("source_path")
        or diagnostic.get("Filename")
        or record.get("model")
        or diagnostic.get("model")
    )
    if record.get("code") in {"mechanical.view_read", "mechanical.view_unverified"}:
        source = record.get("path")
    if not isinstance(source, str):
        return None
    path = Path(source)
    if path.is_absolute():
        if not path.is_relative_to(root):
            return None
        source = path.relative_to(root).as_posix()
    line = diagnostic.get("Location", {}).get("Start", {}).get("LineNumber")
    return dict(path=source, **({"line": line} if line else {}))


def issue_content(root, path, record):
    message = safe_text(report_message(record["message"])).replace(str(root) + "/", "")
    target = " / ".join(
        str(value)
        for key in ("resource", "property")
        if (value := record.get(key)) and str(value) not in message
    )
    message = escape((target + ": " if target else "") + message, quote=False)
    source = report_source(root, record)
    diagnostic = record.get("diagnostic", {})
    if diagnostic.get("fixModels"):
        owner = record.get("ownership", {}).get("owner")
        owner = tuple(owner) if isinstance(owner, (list, tuple)) else None
        matches = []
        for model in diagnostic["fixModels"]:
            if not isinstance(model, str):
                continue
            result = resolve(
                root,
                Diagnostic.create(
                    root,
                    code="reference",
                    check_id="model.references",
                    service=None,
                    source_path=model,
                    message="",
                    cause_kind="input_invalid",
                ),
                {owner},
            )
            if owner is not None and result["status"] == "assigned":
                matches.append(model)
        source = (
            report_source(
                root,
                record
                if matches[0] == diagnostic.get("model")
                else {"source_path": matches[0]},
            )
            if len(matches) == 1
            else None
        )
    link = evidence(root, path, source)
    return (
        message
        + (f" 根拠: {link}。" if link else "")
        + f" <!-- issue-id: {record['id']} -->"
    )


def notice_key(item):
    if item.get("code") == "mechanical.view_unverified" and "path" in item:
        item = dict(item, code="mechanical.view_read")
    diagnostic = item.get("diagnostic", {})
    return (
        item.get("diagnostic_id")
        or diagnostic.get("diagnosticId")
        or item.get("id")
        or identifier({key: value for key, value in item.items() if key != "complete"})
    )


def notice_content(root, path, item):
    diagnostic = item.get("diagnostic", {})
    details = item.get("details", {})
    if not isinstance(details, dict):
        details = {}
    target = item.get("service") or item.get("scope") or diagnostic.get("service")
    if isinstance(target, (list, tuple)):
        target = ", ".join(str(value) for value in target)
    fields = [target]
    for key in ("resource", "property", "function", "pointer"):
        fields.append(item.get(key) or diagnostic.get(key))
    check = (
        item.get("check")
        or item.get("check_id")
        or item.get("phase")
        or diagnostic.get("check_id")
        or item.get("code")
        or item.get("rule")
        or item.get("checks")
    )
    if isinstance(check, (list, tuple)):
        check = ", ".join(check)
    reason = (
        item.get("message")
        or diagnostic.get("message")
        or details.get("message")
        or item.get("reason")
        or diagnostic.get("reason")
        or details.get("reason")
        or item.get("exception")
        or item.get("status")
        or "未実施"
    )
    location = diagnostic.get("Location", {}).get("Path", [])
    if location:
        fields.append("/".join(str(value) for value in location))
    text = " / ".join(brief(value) for value in fields if value)
    if check:
        text += (" / " if text else "") + brief(check)
    text += (
        ": " + brief(report_message(reason).replace(str(root) + "/", ""))
        if reason
        else ""
    )
    link = evidence(root, path, report_source(root, item))
    return " ".join(text.splitlines()) + (f" 根拠: {link}。" if link else "")


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
        f"対象Service: {', '.join(services)}",
        "今回の検証: 未完了（AWS未検証）"
        if incomplete
        else "今回の検証: ローカルScanとLLM Review済み（AWS未検証）",
        "",
        f"## {environment}／{directory}",
        "",
    ]
    for service in services:
        records = [item for item in artifact["ordinary"] if item["service"] == service]
        if records:
            lines.extend([f"### {service}", ""])
            lines.extend(
                f"{number}. {issue_content(root, path, item)}\n"
                for number, item in enumerate(
                    sorted(records, key=lambda item: item["id"]), 1
                )
            )
    if not artifact["ordinary"]:
        lines.extend(
            ["未解決issueなし（検証未完了）" if incomplete else "未解決issueなし", ""]
        )
    processing = {notice_key(item) for item in artifact["processing_errors"]}
    for channel, heading in (
        ("unverified", "未検証範囲"),
        ("processing_errors", "処理エラー（未検証範囲あり）"),
        ("warnings", "警告（非ブロッキング）"),
    ):
        notices = {}
        for item in artifact[channel]:
            key = notice_key(item)
            if channel != "unverified" or key not in processing:
                notices.setdefault(key, item)
        if notices:
            lines.extend(["## " + heading, ""])
            lines.extend(
                "- " + notice_content(root, path, item) for item in notices.values()
            )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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
    data = (
        artifact
        if artifact is not None
        else aggregate(records, environment, directory, services, display)
    )
    summary = dict(
        data["overview"],
        index=sorted(
            (group["compact"] for group in data["iac_issues"]),
            key=lambda item: item["report_order"],
        ),
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
        f"Scan実行日時: {stamp}",
        f"対象: {environment}／{directory}／{', '.join(sorted(set(services)))}",
        f"今回の判定: {status}",
        f"問題: {summary['issue_count']}件",
        "比較: "
        + " / ".join(f"{kind} {count}件" for kind, count in counts.items() if count)
        if any(counts.values())
        else "比較: 0件",
        f"PENDING_DEPLOY（比較対象外） {summary['pending_deploy_excluded']}件",
    ]
    if unverified_services:
        lines.append("未検証Service: " + ", ".join(unverified_services))
    if summary["comparison_incomplete"]:
        lines.append("比較途中終了（未実施範囲あり）")
    categories = [
        f"{category} {count}件"
        for category, count in summary["categories"].items()
        if count
    ]
    if categories:
        lines.append("分類: " + " / ".join(categories))
    if summary["index"]:
        visible = summary["index"][:20]
        lines.extend(["", "## Issue一覧", ""])
        if summary["issue_count"] > len(visible):
            lines.extend(
                [
                    f"表示{len(visible)}件／全{summary['issue_count']}件／省略{summary['issue_count'] - len(visible)}件",
                    "",
                ]
            )
        lines.extend(
            [
                "| Issue ID | 分類 | 対象 | 問題 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in visible:
            lines.append(
                "| "
                + " | ".join(
                    brief(value).replace("\n", " ").replace("\r", " ")
                    for value in (
                        item["id"],
                        item["category"],
                        ", ".join(item["services"])
                        + (" / " + item["target"] if item["target"] else ""),
                        item["problem"] + "：" + item["cause"],
                    )
                )
                + " |"
            )
    return "\n".join(lines) + "\n"
