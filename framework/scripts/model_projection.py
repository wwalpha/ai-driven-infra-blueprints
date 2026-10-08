"""Read-only Markdown projection and explicit migration inputs; never publishes files."""

from collections import defaultdict, deque
import hashlib
import json
import re
from pathlib import Path
from design_document import DesignIndex
from design_catalog import DesignSchemaCatalog, design_material_files
from design_layout import (HIDDEN_PROPERTIES, ROTATION_SCHEDULE, RESOURCE, STACK_DESIGN, GROUPED, expanded_design,
    resource_display_name, stack_design, stack_deployment_policy, resource_mode, resource_modes, design_model_values)
from policy_tables import without_policy_tables, resources_in, unique_object, invalid_constant
from service_rows import CODEBUILD_FORMAL_VARIABLE
from model_core import properties, entries
from model_references import resource_display_rows, design_target
from validation_cache import memoized


SERVICE_ID = re.compile(r"^- Design service ID: `([^`]+)`$")
OWNED_TYPES = re.compile(r"^- Owned catalog resource types: (`[^`]+`(?:, `[^`]+`)*)$")
ANCHOR = re.compile(r'^<a\s+id="([^"]+)"\s*></a>$')
TABLE_HEADER = "| No. | Property | Value | Source / Comment |"
TABLE_ALIGNMENT = "| ---: | --- | --- | --- |"
JSON_LINK = re.compile(r"^\[[^\]]+\]\(([^)#]+\.json)\)$")
RESOURCE_LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")


def json_sha256(path: Path) -> str:
    content = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@memoized
def identifier_outputs(root: Path) -> dict[str, set[str]]:
    outputs: dict[str, set[str]] = {}
    for path in design_material_files(root):
        resource_type = path.stem.replace("_", ".", 1)
        outputs[resource_type] = {
            line.partition("=")[0]
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.endswith("=IDENTIFIER_OUTPUT") and line.partition("=")[0] not in HIDDEN_PROPERTIES
        }
    return outputs


def linked_resource(path: Path, value: str, *, design_index: DesignIndex | None = None) -> tuple[str, str] | None:
    match = RESOURCE_LINK.fullmatch(value)
    if not match:
        return None
    _, target_text, fragment = match.groups()
    target = path if not target_text else path.parent / target_text
    if not target.is_file():
        return None
    pending_anchor = ""
    view = (design_index or DesignIndex()).get(target).view(frozenset({fragment}))
    identities = view.logical_ids
    lines, _ = view.expanded
    for line in lines:
        if anchor := ANCHOR.fullmatch(line):
            pending_anchor = anchor.group(1)
        elif resource := RESOURCE.fullmatch(line):
            if pending_anchor == fragment:
                return resource.group(1), identities.get(resource.groups(), resource.group(2))
            pending_anchor = ""
    return None


def logical_link(value: str, logical_id: str) -> str:
    match = RESOURCE_LINK.fullmatch(value)
    if not match:
        return value
    return f"[{logical_id}]({match.group(2)}#{match.group(3)})"


def one_match(pattern: re.Pattern[str], lines: list[str], label: str, path: Path) -> re.Match[str]:
    matches = [match for line in lines if (match := pattern.fullmatch(line))]
    if len(matches) != 1:
        raise ValueError(f"{label} must appear exactly once: {path}")
    return matches[0]


def model_for(path: Path, root: Path | None = None, *, source: dict[str, str] | None = None, import_cfn_ids: bool = False,
              design_index: DesignIndex | None = None) -> str:
    """Read-only projection for verification and explicit migration; never save it by default."""
    if path.name == STACK_DESIGN:
        from design_layout import stack_delivery
        stacks = stack_design(path)
        output = ["# Stack design projection", f"desired.deployment.maxConcurrentStacks={stack_deployment_policy(path)}"]
        output += [f"{key}={value}" for key, value in stack_delivery(path).items()]
        for number, stack in enumerate(stacks, 1):
            key = f"desired.stack.{number:03d}"
            output.extend((
                f'{key}.name={stack["name"]}',
                f'{key}.template={stack["template"]}',
                f'{key}.parameters={stack["parameters"]}',
                f'{key}.deployOrder={stack["deployOrder"]}',
            ))
        return "\n".join(output) + "\n"
    catalog_outputs = identifier_outputs(root or Path(__file__).resolve().parents[2])
    design_index = design_index or DesignIndex()
    document = design_index.get(path)
    lines = document.lines
    if source is None and root is not None and not import_cfn_ids:
        source = design_model_values(path, root)
    modes = resource_modes(lines, source)
    from design_layout import resource_identity_metadata
    resource_numbers, cfn_ids = resource_identity_metadata(lines, values=source, import_cfn_ids=import_cfn_ids)
    model_numbers = {resource["anchor"]: identity for identity, resource in entries(source, "desired.resource.")} if source is not None else {}
    row_numbers = defaultdict(deque)
    if source is not None:
        for identity, row in entries(source, "desired.row."):
            row_numbers[(identity.split("-", 1)[0], row["property"])].append(identity)
    identities = document.projection_source.logical_ids
    view = document.view(projection=True)
    lines, children = view.expanded
    service_id = one_match(SERVICE_ID, lines, "Design service ID", path).group(1)
    owned = ",".join(
        re.findall(
            r"`([^`]+)`",
            one_match(OWNED_TYPES, lines, "Owned catalog resource types", path).group(1),
        )
    )
    output = [
        "# Generated by framework/scripts/sync-model.py; do not edit.",
        f"desired.service.{service_id}.serviceId={service_id}",
        f"desired.service.{service_id}.ownedCatalogResourceTypes={owned}",
    ]
    pending_anchor = ""
    resource_anchors = set()
    current_type = ""
    current_logical_id = ""
    current_anchor = ""
    resource_number = 0
    note_number = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if match := ANCHOR.fullmatch(line):
            pending_anchor = match.group(1)
            index += 1
            continue
        if match := RESOURCE.fullmatch(line):
            resource_number += 1
            current_type, current_logical_id = match.groups()
            current_logical_id = identities.get(match.groups(), current_logical_id)
            current_anchor = pending_anchor
            resource_anchors.add(current_anchor)
            if source is not None and current_anchor not in model_numbers:
                raise ValueError(f"resource anchor is absent from authoritative model: {current_anchor}")
            if import_cfn_ids and current_anchor not in resource_numbers and re.fullmatch(r"[0-9]{3}", identities.get(match.groups(), "")):
                raise ValueError("resource entry/resourceMode unavailable in Markdown; preserve the authoritative model instead of importing")
            key = model_numbers.get(current_anchor, resource_numbers.get(current_anchor, f"{resource_number:03d}"))
            current_resource_number = key
            output.extend(
                (
                    f"desired.resource.{key}.resourceType={current_type}",
                    f"desired.resource.{key}.anchor={pending_anchor}",
                )
            )
            if current_anchor not in resource_numbers:
                output.append(f"desired.resource.{key}.logicalId={current_logical_id}")
            if source is not None and (approval := source.get(f'desired.resource.{key}.deploymentEncryption')) is not None:
                output.append(f'desired.resource.{key}.deploymentEncryption={approval}')
            if current_anchor in cfn_ids:
                output.append(f"desired.resource.{key}.cfn-logicalId={cfn_ids.pop(current_anchor)}")
            if child := children.get(current_anchor):
                output.extend((
                    f'desired.resource.{key}.parentProperty={child["parentProperty"]}',
                    f'desired.resource.{key}.parentReference=[{child["parentLogicalId"]}](#{child["parentAnchor"]})',
                ))
            if current_anchor in modes:
                output.append(f"desired.resource.{key}.resourceMode={modes.pop(current_anchor)}")
            pending_anchor = ""
            index += 1
            continue
        if line == TABLE_HEADER:
            if not current_type:
                raise ValueError(f"resource table has no resource heading: {path}")
            if index + 1 >= len(lines) or lines[index + 1] != TABLE_ALIGNMENT:
                raise ValueError(f"invalid resource table alignment: {path}")
            index += 2
            row_number = 0
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
                if len(cells) != 4:
                    raise ValueError(f"resource table row must have four cells: {path}")
                row_number += 1
                key = f"{current_resource_number}-{row_number:03d}"
                if source is not None:
                    candidates = row_numbers[(current_resource_number, cells[1])]
                    if not candidates:
                        raise ValueError(f"resource row is absent from authoritative model: {current_anchor}: {cells[1]}")
                    key = candidates.popleft()
                linked = linked_resource(path, cells[2], design_index=design_index)
                is_identifier_output = cells[1] in catalog_outputs.get(current_type, set())
                is_identifier_reference = bool(
                    linked and catalog_outputs.get(linked[0])
                    and cells[1] != CODEBUILD_FORMAL_VARIABLE + "Value"
                )
                desired_value = cells[2]
                if is_identifier_output:
                    desired_value = f"[{current_logical_id}](#{current_anchor})"
                elif linked and (is_identifier_reference or cells[1] == ROTATION_SCHEDULE + ".SecretId"):
                    desired_value = logical_link(cells[2], linked[1])
                output.extend(
                    (
                        f"desired.row.{key}.property={cells[1]}",
                        f"desired.row.{key}.value={desired_value}",
                        f"desired.row.{key}.comment={cells[3]}",
                    )
                )
                if is_identifier_output or is_identifier_reference:
                    observed_value = RESOURCE_LINK.fullmatch(cells[2]).group(1) if is_identifier_reference else cells[2]
                    output.extend(
                        (
                            f"observed.row.{key}.property={cells[1]}",
                            f"observed.row.{key}.value={observed_value}",
                            f"observed.row.{key}.comment={cells[3]}",
                        )
                    )
                if match := JSON_LINK.fullmatch(cells[2]):
                    artifact = path.parent / match.group(1)
                    if not artifact.is_file():
                        raise ValueError(f"linked JSON artifact is missing: {artifact}")
                    digest = json_sha256(artifact)
                    output.append(f"desired.row.{key}.artifactSha256={digest}")
                index += 1
            continue
        if line.startswith("|"):
            while index < len(lines) and lines[index].startswith("|"):
                index += 1
            continue
        if line and not (
            line.startswith("#")
            or line.startswith("- Design service ID:")
            or line.startswith("- Owned catalog resource types:")
            or line.startswith("```")
        ):
            note_number += 1
            output.append(f"desired.note.{note_number:03d}.text={line}")
        index += 1
    if set(resource_numbers) - resource_anchors:
        raise ValueError("resource entry metadata must identify a resource anchor")
    if cfn_ids:
        raise ValueError(f"cfn-logicalId metadata must identify a resource anchor: {sorted(cfn_ids)}")
    if modes:
        raise ValueError(f"resource mode metadata must identify a resource anchor: {sorted(modes)}")
    return "\n".join(output) + "\n"


def imported_model(path: Path, root: Path) -> str:
    """Preserve display inputs when explicitly migrating an existing design."""
    model = model_for(path, root, import_cfn_ids=True)
    source = path.read_text(encoding="utf-8").splitlines()
    output = []
    if path.name == STACK_DESIGN:
        for number, stack in enumerate(stack_design(path), 1):
            output.append(f'display.stack.{number:03d}.comment={stack["comment"]}')
    else:
        output.append("display.service.title=" + next(line for line in source if line.startswith("# ")))
        values = properties(model)
        overview = {}
        for line in source:
            if line.startswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) == 3 and (match := RESOURCE_LINK.fullmatch(cells[1])):
                    overview[match.group(3)] = cells[2]
        headings = {anchor: name for anchor, kind, name in (
            (resource.anchor, resource.resource_type, resource.logical_id)
            for resource in resources_in(without_policy_tables(source))
        )}
        _, children = expanded_design(without_policy_tables(source))
        headings.update({anchor: child["displayName"] for anchor, child in children.items() if "displayName" in child})
        for identity, resource in entries(values, "desired.resource."):
            if design_target(path, root).get("iacEngine") == "cloudformation" and resource_mode(resource) == "CREATE" and \
                    f"desired.resource.{identity}.logicalId" not in values and "cfn-logicalId" not in resource:
                try:
                    DesignSchemaCatalog(root).cloudformation_type(resource["resourceType"])
                except ValueError:
                    pass  # API-only resources do not have a CFn identity.
                else:
                    raise ValueError(f"{identity}: cfn-logicalId unavailable in Markdown; preserve the authoritative model instead of importing")
            rows = resource_display_rows(values, identity, resource, root)
            label = headings.get(resource["anchor"])
            configured_name = resource_display_name(resource["resourceType"], rows, label, resource_mode(resource))
            multiple_aliases = resource["resourceType"] == "KMS.Key" and len({row[2] for row in rows if row[1] == "KMS.Alias.AliasName"}) > 1
            if (configured_name is None or multiple_aliases) and GROUPED.get(resource["resourceType"], {}).get("display") != "rule-table":
                if label is None:
                    raise ValueError(f"confirmed display label required for grouped resource: {resource['logicalId']}")
                if label != resource["resourceType"]:
                    output.append(f"display.resource.{identity}.label={label}")
            if resource["resourceType"] not in GROUPED:
                if resource["anchor"] not in overview:
                    raise ValueError(f"resource overview comment is missing: {resource['anchor']}")
                output.append(f"display.resource.{identity}.comment={overview[resource['anchor']]}")
        for identity, row in entries(values, "desired.row."):
            if match := JSON_LINK.fullmatch(row["value"]):
                document = json.loads((path.parent / match.group(1)).read_text(encoding="utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
                output.append(f"desired.row.{identity}.document=" + json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    return model.replace("# Generated by framework/scripts/sync-model.py; do not edit.", "# Authoritative design values; Markdown is generated by framework/scripts/sync-model.py.") + "\n".join(output) + "\n"


