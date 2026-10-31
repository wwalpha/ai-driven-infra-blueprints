"""KMS display selection."""

import model.references as references


def alias_display_name(rows, selected_label):
    aliases = [row[2].strip('`"') for row in rows if row[1] == "KMS.Alias.AliasName"]
    if aliases:
        if any(
            not alias.startswith("alias/") or not alias.removeprefix("alias/").strip()
            for alias in aliases
        ):
            raise ValueError(
                "KMS Key display requires a confirmed AliasName beginning with alias/"
            )
        names = {alias.removeprefix("alias/") for alias in aliases}
        if len(names) == 1:
            return next(iter(names))
        if selected_label in names:
            return selected_label
        raise ValueError(
            "KMS Key has multiple aliases; select an alias without alias/ in display label"
        )
    return None


def reference_label(
    values, position, node, scope, resolver, resource, attribute, name, displayed
):
    if resource["resourceType"] not in {"KMS.Key", "KMS.Alias"}:
        return name
    if resource["resourceType"] == "KMS.Alias" and attribute == "AliasName":
        if isinstance(displayed, str):
            name = displayed
    if position.source_field != "value" or position.pointer:
        return name
    raw, structured = references._json(
        f"desired.row.{position.row_id}.value",
        values[f"desired.row.{position.row_id}.value"],
    )
    if not structured or not references.is_reference(raw):
        return name
    observation = references.kms_observation(
        values, position.row_id, node, scope, resolver
    )
    if observation is None:
        return name
    state, observed = observation
    return {
        "match": observed,
        "mismatch": observed,
        "unproven": "未確認: " + str(observed),
        "pending": "PENDING_DEPLOY",
        "unobserved": "未観測",
    }[state]
