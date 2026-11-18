"""KMS display selection."""

from utils.type_contracts import JsonValue

from ..contracts import DisplayExtension


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
    property_path: str | None,
    producer_type: str,
    attribute: str,
    name: str,
    displayed: JsonValue,
    /,
) -> str:
    if (
        producer_type == "KMS.Alias"
        and attribute == "AliasName"
        and isinstance(displayed, str)
    ):
        return displayed
    return name


ALIAS_DISPLAY = DisplayExtension(reference_label=reference_label)
KEY_DISPLAY = DisplayExtension(selected_name=alias_display_name)
