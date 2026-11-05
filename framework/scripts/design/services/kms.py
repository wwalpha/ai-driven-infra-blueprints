"""KMS display selection."""

import model.references as references
from contracts.model import MODEL_PENDING_DEPLOY, RESOURCE_TYPE_KEY
from utils.reference_contracts import S3_KMS_MASTER_KEY_ID

import model as _model_api


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
    if resource[RESOURCE_TYPE_KEY] not in {"KMS.Key", "KMS.Alias"}:
        return name
    if resource[RESOURCE_TYPE_KEY] == "KMS.Alias" and attribute == "AliasName":
        if isinstance(displayed, str):
            name = displayed
    if values.get(f"desired.row.{position.row_id}.property") == S3_KMS_MASTER_KEY_ID:
        return name
    if position.source_field != "value" or position.pointer:
        return name
    raw, structured = _model_api.parse_reference_field(
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
    if state == "unobserved" and displayed == MODEL_PENDING_DEPLOY:
        return MODEL_PENDING_DEPLOY
    return {
        "match": observed,
        "mismatch": observed,
        "unproven": "未確認: " + str(observed),
        "pending": MODEL_PENDING_DEPLOY,
        "unobserved": "未観測",
    }[state]
