"""EventBridge rule display-table validation."""

from contracts.model import MODEL_PENDING_DEPLOY, MODEL_UNSET


def check_rule_rows(path, logical_id, rows, *, findings):
    for property_name in ("Events.Rule.Name", "Events.Rule.State"):
        selected = [row for row in rows if row[1] == property_name]
        findings.check(
            len(selected) == 1,
            f"{property_name} must appear exactly once: {findings.relative(path)}: {logical_id}",
            source_path=path,
            cause_kind="input_invalid",
        )
        if len(selected) == 1:
            value = selected[0][2].strip()
            if len(value) >= 2 and value[0] == value[-1] == "`":
                value = value[1:-1].strip()
            findings.check(
                value not in {"", MODEL_UNSET, MODEL_PENDING_DEPLOY},
                f"{property_name} must have a confirmed value: {findings.relative(path)}: {logical_id}",
                source_path=path,
                cause_kind="input_invalid",
            )
