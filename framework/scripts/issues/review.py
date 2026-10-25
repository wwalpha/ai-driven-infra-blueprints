"""Evidence-backed decisions for scoped existing ordinary Issues; no input reads."""

from task_contract_core import relative_path

from .records import identifier, safe_text
from .reports import issue_key, issue_marker


def existing_issues(artifact):
    judgments = [
        item
        for item in artifact.get("judgments", [])
        if item.get("kind") == "existing-issue-correspondence"
    ]
    items = [item["materials"] for item in judgments]
    ids = [item["id"] for item in items]
    if (
        len(ids) != len(set(ids))
        or any(
            item["service"] is not None and item["service"] not in artifact["services"]
            for item in items
        )
        or any(
            item["id"] != item["materials"]["id"]
            or item["service"] != item["materials"]["service"]
            for item in judgments
        )
    ):
        raise ValueError("duplicate or out-of-scope existing Issue materials")
    return {item["id"]: item for item in items}


def required_text(item, key):
    value = item.get(key) if isinstance(item, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"existing Issue decision needs {key}")
    return value


def corresponding_target(artifact, decision, previous, target):
    return (
        isinstance(target, dict)
        and all(
            isinstance(target.get(key), str) and target[key].strip()
            for key in ("service", "check_id", "rule", "resource", "property", "scope")
        )
        and target["service"] == decision["service"]
        and target["scope"]
        == f"{artifact['environment']}/{artifact['target']}/{decision['service']}"
        and target in previous.get("verification_targets", [])
    )


def decision_evidence(artifact, decision, evidence, previous):
    if not isinstance(evidence, dict):
        raise ValueError("existing Issue evidence must be structured")
    kind = evidence.get("kind")
    if kind == "scan":
        section = evidence.get("section")
        if section not in {
            "ordinary",
            "check_results",
            "unverified",
            "processing_errors",
        }:
            raise ValueError("unsupported scan evidence section")
        matches = [
            item
            for item in artifact.get(section, [])
            if evidence.get("id") == item.get("id", identifier(item))
        ]
        if len(matches) != 1:
            raise ValueError("unknown or ambiguous current scan evidence")
        record = matches[0]
        service = decision["service"]
        scopes = record.get("scope", [])
        if record.get("service") != service and (
            not isinstance(scopes, list)
            or f"{artifact['environment']}/{artifact['target']}/{service}" not in scopes
        ):
            raise ValueError("scan evidence does not cover the Issue service")
        if decision["verification"] != "local":
            raise ValueError("local scan is not AWS revalidation evidence")
        if section == "check_results":
            required_text(evidence, "subject")
            required_text(evidence, "details")
        outcome = (
            "present"
            if section == "ordinary"
            else "absent"
            if section == "check_results"
            and record["status"] == "PASS"
            and record.get("complete") is True
            and any(
                corresponding_target(artifact, decision, previous, target)
                and target["check_id"] == record.get("check_id")
                and target["scope"] in scopes
                for target in record.get("verification_targets", [])
            )
            else "unverified"
        )
        description = record.get("message") or record.get("check_id") or str(record)
        return outcome, (
            f"Scan {artifact['scan_id']} / {section} / {evidence['id']}: {description} "
            + evidence.get("subject", "")
            + " "
            + evidence.get("details", "")
        )
    if kind == "not_run":
        required_text(evidence, "check")
        return "unverified", required_text(evidence, "details")
    if (
        kind != "revalidation"
        or evidence.get("verification") != decision["verification"]
    ):
        raise ValueError("revalidation must identify the local/AWS verification scope")
    for key in ("check", "subject", "details", "rule"):
        required_text(evidence, key)
    source = evidence.get("source", {})
    relative_path(required_text(source, "path"))
    if type(source.get("line")) is not int or source["line"] < 1:
        raise ValueError("revalidation requires a positive source line")
    outcome = evidence.get("outcome")
    if outcome not in {"present", "absent", "unverified"}:
        raise ValueError("invalid revalidation outcome")
    if evidence.get("completed") is not True and outcome != "unverified":
        outcome = "unverified"
    target = evidence.get("target")
    if outcome == "absent" and not (
        corresponding_target(artifact, decision, previous, target)
        and target["check_id"] == evidence["check"]
        and target["rule"] == evidence["rule"]
        and target.get("path") == source["path"]
    ):
        outcome = "unverified"
    return outcome, (
        f"{evidence['check']} / {evidence['subject']} / {source['path']}:{source['line']} / "
        f"{evidence['rule']}: {evidence['details']}"
    )


def existing_decisions(artifact, review):
    """State decisions are canonical; resolved is only a checked compatibility projection."""
    existing = existing_issues(artifact)
    decisions = review.get("existing_issue_judgments", [])
    if not isinstance(decisions, list):
        raise ValueError("existing_issue_judgments must be a list")
    seen, updates, resolutions, consumed = set(), [], [], set()
    detected = {
        issue_key(artifact["root"], item)
        for item in [*artifact["ordinary"], *review["issues"]]
    }
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("malformed existing Issue decision")
        issue_id = required_text(decision, "id")
        if issue_id in seen or issue_id not in existing:
            raise ValueError(
                "duplicate, unknown or out-of-scope existing Issue decision"
            )
        seen.add(issue_id)
        previous = existing[issue_id]
        if decision.get("service") != previous["service"]:
            raise ValueError("existing Issue decision service mismatch")
        status = decision.get("status")
        if status not in {"continuing", "resolved", "unverified"}:
            raise ValueError("invalid existing Issue status")
        reason = required_text(decision, "reason")
        if previous["service"] is None and status != "unverified":
            raise ValueError("unknown Service ownership requires unverified retention")
        if decision.get("verification") not in {"local", "aws"}:
            raise ValueError("existing Issue decision needs local/AWS verification")
        evidence = decision.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(
                "existing Issue decision needs current revalidation evidence"
            )
        results = [
            decision_evidence(artifact, decision, item, previous) for item in evidence
        ]
        outcomes = {result for result, _ in results}
        valid = (
            outcomes == {"absent"}
            if status == "resolved"
            else "present" in outcomes and "absent" not in outcomes
            if status == "continuing"
            else "unverified" in outcomes and "present" not in outcomes
        )
        if not valid:
            raise ValueError(
                "Issue state contradicts failed/incomplete revalidation evidence"
            )
        marker = previous.get("marker") or issue_marker(previous["message"])
        if status != "continuing" and (
            previous.get("current_diagnostic_ids") or marker in detected
        ):
            raise ValueError("current diagnostic still confirms this existing Issue")
        description = safe_text("; ".join(text for _, text in results))
        if status == "resolved":
            resolutions.append(dict(id=issue_id, reason=reason, evidence=description))
            continue
        record = decision.get("issue")
        if status == "continuing":
            diagnostic_id = decision.get("diagnostic_id")
            if diagnostic_id is not None:
                matches = [
                    item
                    for item in artifact["ordinary"]
                    if item["id"] == diagnostic_id
                    and item["service"] == decision["service"]
                ]
                if len(matches) != 1 or not any(
                    item.get("kind") == "scan"
                    and item.get("section") == "ordinary"
                    and item.get("id") == diagnostic_id
                    for item in evidence
                ):
                    raise ValueError(
                        "continuing Issue needs its current diagnostic evidence"
                    )
                if diagnostic_id in consumed:
                    raise ValueError(
                        "current diagnostic assigned to multiple existing Issues"
                    )
                record = matches[0]
                consumed.add(diagnostic_id)
            if not isinstance(record, dict):
                raise ValueError(
                    "continuing Issue needs a current issue or diagnostic_id"
                )
            required_text(record, "message")
            if record.get("service", decision["service"]) != decision["service"]:
                raise ValueError("continuing Issue ownership mismatch")
        else:
            required_text(decision, "not_checked_reason")
        if previous["service"] is None:
            continue  # Review unknown ownership without changing its scope or original bytes.
        updates.append(
            dict(
                id=issue_id,
                service=decision["service"],
                status=status,
                reason=safe_text(reason),
                evidence=description,
                issue=record if status == "continuing" else None,
                not_checked_reason=safe_text(decision.get("not_checked_reason", "")),
            )
        )
    if seen != existing.keys():
        raise ValueError("all scoped existing Issues require a current state decision")
    legacy = review["resolved"]
    if legacy:
        expected = {item["id"] for item in resolutions}
        ids = [item["id"] for item in legacy]
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise ValueError("resolved contradicts canonical existing Issue decisions")
        by_id = {item["id"]: item for item in resolutions}
        if any(item != by_id[item["id"]] for item in legacy):
            raise ValueError("resolved must be empty or the exact derived projection")
    return updates, resolutions, consumed
