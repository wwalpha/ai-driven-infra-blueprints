"""Issue identities and report text; comparison evidence is produced by comparison."""

from comparison.result import identifier, safe_text


def iac_key(item):
    return identifier(
        [item["service"], item["resource"], item["property"], item.get("stack")]
    )


def condition_disabled(item):
    cause = item.get("cause", {})
    return (
        item["category"] == "difference"
        and cause.get("kind") == "condition-disabled"
        and cause.get("result") is False
    )


def brief(value, limit=160):
    value = (
        safe_text(str(value))
        .replace("|", "／")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return value if len(value) <= limit else value[:limit] + "…（全文はartifact）"
