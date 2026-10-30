"""Artifact review, bounded summaries and page-first detail; no source reads."""

import re
from collections import Counter

from utils.comparison_contract import CATEGORIES, validate_cause
from validation.diagnostics import CAUSE_KINDS

import issues.aggregate as _imports_issues_aggregate

from .aggregate import IAC_CATEGORIES, pending_deploy_count
from .records import brief, identifier
from .review import review_names

CHANNELS = ("warnings", "information", "unverified", "processing_errors")


def has_processing_errors(artifact):
    return (
        bool(artifact.get("processing_errors"))
        or artifact["overview"]["records"]["error"] > 0
    )


def validation_status(artifact):
    if has_processing_errors(artifact):
        return "ERROR"
    if artifact.get("ordinary") or (
        not artifact.get("reviewed")
        and any(
            "message" in item and item.get("cause_kind") == "input_invalid"
            for item in artifact.get("judgments", [])
        )
    ):
        return "FAIL"
    if artifact.get("unverified"):
        return "INCOMPLETE"
    return "CHECKED"


def scan_exit_code(artifact):
    status = validation_status(artifact)
    return 2 if status == "ERROR" else 1 if status == "FAIL" else 0


def channel_summary(values, section):
    codes = Counter(
        item.get("code", "unknown") if isinstance(item, dict) else "unknown"
        for item in values
    )
    return dict(
        total=len(values),
        preview=[brief(item) for item in values[:5]],
        omitted=max(0, len(values) - 5),
        by_code=dict(codes.most_common(5)),
        omitted_codes=max(0, len(codes) - 5),
        detail="detail --section " + section,
    )


def summary(artifact, *, pending_names=None):
    if artifact.get("version") != 6:
        raise ValueError("unsupported scan artifact version; version 6 required")
    comparison_status = _imports_issues_aggregate.comparison_status
    view = artifact["overview"]
    counts = view["records"]
    if pending_names is None:
        pending_names = review_names(artifact) if "naming" in artifact else []
    return dict(
        ordinary_candidates=len(artifact.get("ordinary", [])),
        judgment_items=len(artifact.get("judgments", [])),
        naming_items=len(artifact.get("naming", {}).get("names", [])),
        naming_auto_pass=len(artifact.get("naming", {}).get("names", []))
        - len(pending_names),
        naming_review_required=len(pending_names),
        iac_differences=counts["difference"],
        iac_uncompared=counts["uncompared"],
        iac_errors=counts["error"],
        iac_matched=counts["matched"],
        iac_deferred=counts["deferred"],
        iac_excluded=counts["excluded"],
        iac_pending_deploy_excluded=view["pending_deploy_excluded"],
        iac_status=comparison_status(
            counts,
            incomplete=any(
                item["status"] == "unverified"
                for item in artifact.get("service_results", [])
            ),
        ),
        validation_status=validation_status(artifact),
        review_required=not artifact.get("reviewed", False),
        processing_stages=len(
            {
                item.get("job_id") or item.get("id") or item.get("code", "unknown")
                for item in artifact.get("processing_errors", [])
            }
        ),
        comparison_incomplete=view["comparison_incomplete"],
        checks=artifact.get("checks"),
        **{
            name: artifact.get("notice_overview", {}).get(name)
            or channel_summary(artifact.get(name, []), name)
            for name in CHANNELS
        },
    )


def review_payload(artifact, artifact_path):
    pending_names = review_names(artifact)
    return dict(
        summary=summary(artifact, pending_names=pending_names),
        scope={key: artifact[key] for key in ("environment", "target", "services")},
        publication_scope=dict(
            target_services=artifact["target_services"],
            missing_services=sorted(
                set(artifact["target_services"]) - set(artifact["services"])
            ),
            complete=artifact["services"] == artifact["target_services"],
        ),
        scan_id=artifact.get("scan_id"),
        naming_context_id=artifact.get("naming_context_id"),
        executed_at=artifact.get("executed_at"),
        artifact=str(artifact_path),
        iac_summary=artifact["overview"],
        review_required=dict(
            names=len(pending_names),
            judgments=len(artifact["judgments"]),
            policy="naming_context、AUTO_PASS以外のnaming、judgmentsの全IDと、全Human確定情報・今回の診断を確認する。AUTO_PASSは個別LLM Review不要。",
        ),
        human_confirmations=dict(
            total=len(artifact["human_confirmations"]["confirmations"]),
            items=[
                brief(line)
                for line in artifact["human_confirmations"]["confirmations"][:3]
            ],
            omitted=max(0, len(artifact["human_confirmations"]["confirmations"]) - 3),
        ),
        cfn_lint=dict(
            status=artifact.get("cfn_lint", {}).get("status", "not_run"),
            jobs=len(artifact.get("cfn_lint", {}).get("jobs", [])),
            coverage=channel_summary(
                artifact.get("cfn_lint", {}).get("coverage", []), "lint_coverage"
            ),
        ),
        detail="issues_scan.py detail --artifact <path> --section naming_context|naming|judgments|ordinary|check_results|human_confirmations|iac_issues|iac|warnings|information|unverified|processing_errors; --offset 0 --limit 50; IaC: --category <分類> / --issue-id ISSUE-<id>",
    )


def detail_payload(
    artifact,
    section,
    offset=0,
    limit=50,
    category=None,
    issue_id=None,
    record_category=None,
):
    if artifact.get("version") != 6:
        raise ValueError("unsupported scan artifact version")
    if offset < 0 or limit < 1:
        raise ValueError("invalid detail range")
    if (category or issue_id) and section not in {"iac", "iac_issues"}:
        raise ValueError("IaC filters require section iac or iac_issues")
    if record_category is not None:
        if section != "iac" or record_category not in CATEGORIES:
            raise ValueError(
                "record-category requires section iac and a comparison category"
            )
        if category or issue_id:
            raise ValueError("record-category cannot be combined with Issue filters")
    context = {}
    if section in {"iac", "iac_issues"}:
        actions = artifact.get("iac_issues")
        if not isinstance(actions, list):
            raise ValueError("missing artifact Issue index; rescan")
        selected = [
            a
            for a in actions
            if (not category or a["category"] == category)
            and (not issue_id or a["id"] == issue_id)
        ]
        if issue_id and not selected:
            raise ValueError("Issue ID not found in selected artifact/category")
        if section == "iac_issues":
            content = selected
        else:
            indices = (
                [
                    i
                    for i, item in enumerate(artifact["iac"])
                    if item["category"] == record_category
                ]
                if record_category
                else sorted({i for action in selected for i in action["members"]})
                if category or issue_id
                else range(len(artifact["iac"]))
            )
            meta = artifact["record_meta"]
            items = []
            for i in indices[offset : offset + limit]:
                item = artifact["iac"][i]
                items.append(
                    dict(
                        item,
                        record_index=i,
                        issue_id=meta[i]["issue_id"],
                        value_differences=artifact.get("iac_display", {}).get(
                            meta[i]["record_id"], []
                        ),
                    )
                )
            return dict(
                total=len(indices),
                offset=offset,
                items=items,
                omitted=max(0, len(indices) - len(items)),
            )
    elif section == "naming":
        content = artifact["naming"]["names"]
        context = {"naming_context_id": artifact.get("naming_context_id")}
    elif section == "naming_context":
        content = [artifact["naming_context"]]
    elif section == "machine_diagnostics":
        content = artifact[section].splitlines()
    elif section == "cfn_lint":
        content = artifact[section]["jobs"]
        context = {
            "status": artifact[section]["status"],
            "coverage_detail": "detail --section lint_coverage",
        }
    elif section == "lint_coverage":
        content = artifact["cfn_lint"]["coverage"]
    elif section == "check_results":
        content = artifact.get(section, [])
    elif section == "human_confirmations":
        content = artifact[section]["confirmations"]
    else:
        content = artifact[section]
    page = content[offset : offset + limit]
    return dict(
        total=len(content),
        offset=offset,
        items=page,
        omitted=max(0, len(content) - len(page)),
        **({"context": context} if context else {}),
    )


def validate_artifact(artifact, *, rule_index=None):
    """Validate the saved six-category index without reclassification or regrouping."""
    if artifact.get("version") != 6:
        raise ValueError("unsupported scan artifact version")
    causes = {}
    for channel in (
        "ordinary",
        "judgments",
        "unverified",
        "processing_errors",
        "information",
    ):
        seen_diagnostics = set()
        for item in artifact.get(channel, []):
            if "cause_kind" not in item:
                continue
            cause = item["cause_kind"]
            if cause not in CAUSE_KINDS:
                raise ValueError("invalid diagnostic cause_kind")
            if channel == "ordinary" and cause != "input_invalid":
                raise ValueError("ordinary diagnostic requires input_invalid")
            if channel == "processing_errors" and cause != "check_failure":
                raise ValueError("processing diagnostic requires check_failure")
            diagnostic = item.get("diagnostic", {})
            if "cause_kind" in diagnostic and diagnostic["cause_kind"] != cause:
                raise ValueError("inconsistent diagnostic cause_kind")
            key = item.get("diagnostic_id") or item.get("id")
            if key is not None:
                if key in causes and causes[key] != cause:
                    raise ValueError("inconsistent cause_kind for diagnostic ID")
                causes[key] = cause
                if key in seen_diagnostics:
                    raise ValueError("duplicate diagnostic ID in channel")
                seen_diagnostics.add(key)
            ownership = item.get("ownership", {})
            if (
                channel == "judgments"
                and "message" in item
                and ownership.get("status") in {"assigned", "outside"}
            ):
                raise ValueError("proven diagnostic owner cannot require assignment")
            if channel == "ordinary" and ownership.get("status") == "outside":
                raise ValueError("outside diagnostic cannot be an ordinary Issue")
    if not re.fullmatch(r"[0-9a-f]{32}", artifact.get("scan_id", "")):
        raise ValueError("invalid scan_id")
    if identifier(artifact["naming_context"]) != artifact["naming_context_id"]:
        raise ValueError("invalid naming_context_id")
    pending_names = review_names(artifact, rule_index) if "naming" in artifact else []
    records, meta = artifact["iac"], artifact["record_meta"]
    if len(records) != len(meta) or artifact["overview"]["record_count"] != len(
        records
    ):
        raise ValueError("invalid artifact record index")
    counts = dict.fromkeys(CATEGORIES, 0)
    for item in records:
        if item.get("category") not in CATEGORIES:
            raise ValueError("invalid comparison category")
        counts[item["category"]] += 1
        cause = item.get("cause", {})
        if cause.get("kind") == "desired-value-excluded":
            validate_cause(cause)
            if item["category"] != "excluded":
                raise ValueError("invalid desired PENDING_DEPLOY comparison category")
        if item["category"] == "deferred" or cause.get("kind") in {
            "import-reference-excluded",
            "import-reference-deferred",
        }:
            validate_cause(item.get("cause"))
            if item["category"] != (
                "excluded" if cause["phase"] == "pending_deploy" else "deferred"
            ):
                raise ValueError("invalid IMPORT comparison category")
    if counts != artifact["overview"]["records"] or artifact["overview"][
        "issue_count"
    ] != len(artifact["iac_issues"]):
        raise ValueError("invalid artifact comparison counts")
    if artifact["overview"]["pending_deploy_excluded"] != pending_deploy_count(records):
        raise ValueError("invalid artifact PENDING_DEPLOY count")
    seen, issue_ids = set(), set()
    for group in artifact["iac_issues"]:
        if (
            group["id"] in issue_ids
            or not group["members"]
            or len(group["members"]) != group["compact"]["records"]
        ):
            raise ValueError("invalid artifact Issue index")
        issue_ids.add(group["id"])
        for index in group["members"]:
            if (
                type(index) is not int
                or not 0 <= index < len(meta)
                or index in seen
                or meta[index]["issue_id"] != group["id"]
                or records[index]["category"] not in IAC_CATEGORIES
            ):
                raise ValueError("invalid artifact Issue membership")
            seen.add(index)
    for i, entry in enumerate(meta):
        if entry["category"] != records[i]["category"] or entry[
            "record_id"
        ] != identifier(records[i]):
            raise ValueError("invalid artifact record metadata")
        if (entry["issue_id"] is not None) != (i in seen):
            raise ValueError("invalid artifact Issue membership")
        if (records[i]["category"] in IAC_CATEGORIES) != (i in seen):
            raise ValueError("invalid artifact Issue membership")

    return pending_names
