"""Secrets Manager display parsing."""

from ..contracts import DisplayExtension, NamedChildDisplay
from .design import ROTATION_SCHEDULE, ROTATION_SUBNETS


def subnet_list_items(prop: str, raw: str) -> list[str] | None:
    if prop == ROTATION_SUBNETS:
        return [item.strip() for item in raw.split(",")]
    return None


def display_child(
    name: str, rows: list[list[str]], display: list[list[str]]
) -> list[list[str]]:
    result = [row for row in display if row[1] != ROTATION_SCHEDULE + ".SecretId"]
    if not result:
        raise ValueError("RotationSchedule requires a visible property")
    return result


EXTENSION = DisplayExtension(
    parse_linked_list=subnet_list_items,
    named_child=NamedChildDisplay(
        display_child,
        render_in_parent=True,
        label_in_display=True,
    ),
)
SECRET_DISPLAY = DisplayExtension(child_property_prefixes=(ROTATION_SCHEDULE,))
