"""Shared display relationships and identified children in resource tables."""

from __future__ import annotations

import json
import re
from pathlib import Path

from design_catalog import design_material_files
from security_group_tables import security_group_table_lines


LAYOUT_PATH = Path(__file__).resolve().parents[1] / "rules" / "resource-layout.json"
LAYOUTS = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
GROUPED = {name: rule for name, rule in LAYOUTS.items() if isinstance(rule, dict)}
GROUPED_RESOURCE_TYPES = {
    rule["parent"]: {name for name, child in GROUPED.items() if child["parent"] == rule["parent"]}
    for rule in GROUPED.values()
}
IMPLICIT_GROUPED_PROPERTIES = {
    name: {rule["parentProperty"]} for name, rule in GROUPED.items()
}
DISPLAY_ALIAS_PATH = Path(__file__).resolve().parents[1] / "rules" / "display-property-aliases.json"
DISPLAY_PROPERTY_ALIASES = json.loads(DISPLAY_ALIAS_PATH.read_text(encoding="utf-8"))
DETAILS_HEADING = "## リソース詳細"
RESOURCE = re.compile(r"^### ([A-Za-z0-9]+\.[A-Za-z0-9]+): ([A-Za-z0-9][A-Za-z0-9_.-]*)$")
ANCHOR = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
CHILD = re.compile(
    r'^<a id="([a-z0-9_.-]+)"></a><!-- logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) -->\s*'
)
HEADER = "| No. | Property | Value | Source / Comment |"
ALIGNMENT = "| ---: | --- | --- | --- |"


def layout_errors(root: Path) -> list[str]:
    """Require an explicit display decision for every catalog resource."""
    errors = []
    try:
        layouts = json.loads((root / "framework" / "rules" / "resource-layout.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"cannot read resource layout decisions: {error}"]
    if not isinstance(layouts, dict):
        return ["resource layout decisions must be an object"]
    catalog = {
        path.stem.replace("_", ".", 1): {
            line.partition("=")[0] for line in path.read_text(encoding="utf-8").splitlines()
        }
        for path in design_material_files(root)
    }
    try:
        aliases = json.loads((root / "framework" / "rules" / "display-property-aliases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        errors.append(f"cannot read display property aliases: {error}")
        aliases = {}
    selected = set().union(*catalog.values())
    if not isinstance(aliases, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in aliases.items()) or len(set(aliases.values())) != len(aliases):
        errors.append("display property aliases must be a one-to-one object")
    else:
        for display, formal in aliases.items():
            if not isinstance(display, str) or not isinstance(formal, str) or display in selected or formal not in selected or display.split(".")[0] != formal.split(".")[0]:
                errors.append(f"invalid display property alias: {display}: {formal}")
    if set(layouts) != set(catalog):
        errors.append(
            f"resource layout coverage mismatch: unclassified={sorted(set(catalog) - set(layouts))}, "
            f"stale={sorted(set(layouts) - set(catalog))}"
        )
    for name, rule in layouts.items():
        if rule == "independent":
            continue
        required = {"parent", "parentProperty", "maxCount", "identityProperty"}
        if not isinstance(rule, dict) or set(rule) not in (required, required | {"display"}):
            errors.append(f"invalid resource layout decision: {name}")
            continue
        if "display" in rule and (
            rule["display"] != "rule-table"
            or name not in {"EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}
            or rule != {"parent": "EC2.SecurityGroup", "parentProperty": "GroupId", "maxCount": None, "identityProperty": "Id", "display": "rule-table"}
        ):
            errors.append(f"invalid Security Group rule table layout: {name}")
        parent = rule["parent"]
        if not isinstance(parent, str) or parent not in catalog or layouts.get(parent) != "independent":
            errors.append(f"grouped parent must be an independent catalog resource: {name}: {parent}")
        if f'{name}.{rule["parentProperty"]}' not in catalog.get(name, set()):
            errors.append(f"grouped parent property is absent from catalog: {name}")
        identity = rule["identityProperty"]
        if identity is not None and f"{name}.{identity}" not in catalog.get(name, set()):
            errors.append(f"grouped identity property is absent from catalog: {name}")
        if rule["maxCount"] != 1 and not (rule["maxCount"] is None and identity):
            errors.append(f"multiple grouped children require an identity property: {name}")
    return errors


def catalog_order_errors(resource_type: str, rows: list[list[str]], root: Path | None = None) -> list[str]:
    """Compare visible rows with the selection-list order, within each resource."""
    root = root or Path(__file__).resolve().parents[2]
    material = next((path for path in design_material_files(root) if path.stem.replace("_", ".", 1) == resource_type), None)
    if material is None:
        return [f"display order catalog is missing: {resource_type}"]
    order = {line.partition("=")[0]: number for number, line in enumerate(material.read_text(encoding="utf-8").splitlines())}
    previous = -1
    seen: set[str] = set()
    previous_property = ""
    for row in rows:
        prop = row[1] if row[1].startswith(resource_type + ".") else resource_type + "." + row[1]
        if prop not in order:
            continue  # Design-only fields and other grouped resources are separate.
        rank = order[prop]
        if rank < previous:
            array = prop.split("[]", 1)[0] + "[]" if "[]" in prop else ""
            if not array or prop not in seen or not previous_property.startswith(array + "."):
                return [f"resource rows must follow catalog file order: {resource_type}: {prop}"]
            # A repeated field starts the next array element, not a global sort.
            seen = {item for item in seen if not item.startswith(array + ".")}
        seen.add(prop)
        previous = rank
        previous_property = prop
    return []


def expanded_design(lines: list[str], *, normalized: bool = False) -> tuple[list[str], dict[str, dict]]:
    """Expand identified children for model/link resolution; keep S3's flat model.

    Child anchors and logical IDs live in the first row's comment. Visible tables
    stay grouped; this in-memory expansion never rewrites the source Markdown.
    """
    if not normalized:
        lines = security_group_table_lines(lines)
    result: list[str] = []
    children: dict[str, dict] = {}
    parent_type = parent_id = parent_anchor = pending_anchor = service_id = ""
    child_names: set[tuple[str, str]] = set()
    logical_ids: set[str] = set()
    grouped_tables: set[str] = set()
    anchors = ANCHOR.findall("\n".join(lines))
    if len(anchors) != len(set(anchors)):
        raise ValueError("duplicate resource anchor")
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("- Design service ID: "):
            service_id = line.split("`")[1]
        if anchor := ANCHOR.fullmatch(line):
            pending_anchor = anchor.group(1)
        if heading := RESOURCE.fullmatch(line):
            parent_type, parent_id = heading.groups()
            parent_anchor = pending_anchor
            pending_anchor = ""
            if parent_id in logical_ids:
                raise ValueError(f"duplicate resource logical ID: {parent_id}")
            logical_ids.add(parent_id)
        elif line.startswith("#"):
            parent_type = ""
        if line != HEADER:
            if "<!-- logical-id:" in line:
                raise ValueError("child identity marker must be in a resource table row")
            result.append(line)
            index += 1
            continue
        if index + 1 >= len(lines) or lines[index + 1] != ALIGNMENT:
            raise ValueError("invalid resource table alignment")
        if parent_type in GROUPED_RESOURCE_TYPES:
            if parent_anchor in grouped_tables:
                raise ValueError("grouped parent must have exactly one detail table")
            grouped_tables.add(parent_anchor)
        result.extend((HEADER, ALIGNMENT))
        index += 2
        parent_rows = []
        table_children: list[dict] = []
        counts: dict[str, int] = {}
        single_properties: set[str] = set()
        active_child = None
        grouped_started = False
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
            if len(cells) != 4:
                raise ValueError("resource table row must have four cells")
            cells[1] = prop = DISPLAY_PROPERTY_ALIASES.get(cells[1], cells[1])
            resource_type = ".".join(prop.split(".")[:2])
            rule = GROUPED.get(resource_type)
            marker = CHILD.match(cells[3])
            if rule and resource_type != parent_type:
                if parent_type != rule["parent"]:
                    raise ValueError(f"grouped resource has wrong parent: {resource_type}: {parent_type}")
                grouped_started = True
                if prop == f'{resource_type}.{rule["parentProperty"]}':
                    raise ValueError(f"{prop} must be omitted from its enclosing {parent_type} table")
                identity = rule["identityProperty"]
                if identity:
                    if prop == f"{resource_type}.{identity}":
                        if not marker:
                            raise ValueError(f"grouped identity row requires anchor and logical ID: {prop}")
                        anchor, logical_id = marker.groups()
                        if anchor != f"{service_id}-{logical_id.lower()}" or logical_id in logical_ids:
                            raise ValueError(f"invalid or duplicate grouped logical ID/anchor: {logical_id}")
                        logical_ids.add(logical_id)
                        name = cells[2].strip("`")
                        pending_rule = rule.get("display") == "rule-table" and name == "PENDING_DEPLOY"
                        if not pending_rule and (resource_type, name) in child_names:
                            raise ValueError(f"duplicate grouped identity value: {resource_type}: {name}")
                        if not pending_rule:
                            child_names.add((resource_type, name))
                        active_child = {
                            "resourceType": resource_type, "logicalId": logical_id, "anchor": anchor,
                            "parentLogicalId": parent_id, "parentAnchor": parent_anchor,
                            "parentProperty": f'{resource_type}.{rule["parentProperty"]}', "rows": [],
                        }
                        children[anchor] = active_child
                        table_children.append(active_child)
                        counts[resource_type] = counts.get(resource_type, 0) + 1
                    elif marker or not active_child or active_child["resourceType"] != resource_type:
                        raise ValueError(f"grouped child rows must start with {resource_type}.{identity}")
                    if marker:
                        cells[3] = cells[3][marker.end():]
                    active_child["rows"].append(cells)
                else:
                    if marker or "<!-- logical-id:" in cells[3]:
                        raise ValueError("unidentified grouped child must not have an identity marker")
                    if prop in single_properties:
                        raise ValueError(f"duplicate property in single grouped child: {prop}")
                    single_properties.add(prop)
                    counts[resource_type] = 1
                    parent_rows.append(cells)
            else:
                if marker or "<!-- logical-id:" in cells[3]:
                    raise ValueError("child identity marker is only allowed on a grouped identity row")
                if grouped_started:
                    raise ValueError(f"grouped rows must follow {parent_type} rows")
                parent_rows.append(cells)
                active_child = None
            index += 1
        for resource_type, count in counts.items():
            maximum = GROUPED[resource_type]["maxCount"]
            if maximum is not None and count > maximum:
                raise ValueError(f"too many grouped children: {resource_type}")
        for number, cells in enumerate(parent_rows, 1):
            result.append("| " + " | ".join([str(number), *cells[1:]]) + " |")
        for child in table_children:
            result.extend(("", f'<a id="{child["anchor"]}"></a>',
                           f'### {child["resourceType"]}: {child["logicalId"]}', "", HEADER, ALIGNMENT))
            for number, cells in enumerate(child["rows"], 1):
                result.append("| " + " | ".join([str(number), *cells[1:]]) + " |")
    return result, children
