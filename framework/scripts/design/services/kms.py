"""KMS display selection."""

from contracts.model import RESOURCE_TYPE_KEY
from utils.reference_contracts import S3_KMS_MASTER_KEY_ID


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
        if resource[RESOURCE_TYPE_KEY] == "KMS.Alias" and attribute == "Arn":
            return displayed.rsplit(":", 1)[-1] if isinstance(displayed, str) else name
    return name
