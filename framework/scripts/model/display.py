"""Catalog ordering and common display tables, separate from document assembly."""

import json
import re
from collections import Counter
from pathlib import Path

import aws_mapping_display as _display_aws_mapping_display
import design.common as _display_common
import design.compact_rows
import design.layout_schema as _display_design_layout
import design.services.codebuild
import design.services.codepipeline
import design.services.config as _imports_design_layout
import design.services.definitions.registry as _display_definitions
import design.services.glue
from design.common import row_table as row_table
from design.services.cloudtrail import display_row as cloudtrail_display_row
from design.services.definitions.cloudtrail import (
    CLOUDTRAIL_FORMAL_DATA_RESOURCE,
)
from design.services.definitions.codebuild import (
    CODEBUILD_FORMAL_VARIABLE,
    CODEBUILD_VPC_PROPERTIES,
)
from design.services.definitions.guardduty import GUARDDUTY_FORMAL_FEATURE
from design.services.ec2.display import ec2_display_rows
from design.services.guardduty import display_row as guardduty_display_row
from utils.input_cache import input_scope

from model.core import LINK, ReferenceResolutionError, literal
from model.reference_nodes import (
    display_source,
    nodes,
    project_text,
    read_display_source,
)

ROOT = Path(__file__).resolve().parents[3]
REFERENCE_ROWS = re.compile(r'^<!-- reference-rows: ([A-Za-z0-9+/=]+) --> ')


def restored_reference_rows(rows, kind, root, *, mode):
    marker = REFERENCE_ROWS.match(rows[0][3])
    source = read_display_source(marker[1])
    if not isinstance(source, list) or len(source) != 3:
        raise ValueError('invalid reference display source')
    original, projected, count = source
    if (not isinstance(original, list) or not original or not isinstance(projected, list) or
            len(original) != len(projected) or type(count) is not int or not 1 <= count <= len(rows) or
            any(not isinstance(row, list) or len(row) != 4 or any(not isinstance(cell, str) for cell in row)
                for row in original + projected)):
        raise ValueError('invalid reference source rows or count')
    references = set()
    for before, after in zip(original, projected, strict=True):
        if before[:2] != after[:2] or before[3] != after[3]:
            raise ValueError('reference source identity/property/comment differs')
        if any(nodes(literal(before[2]))):
            project_text(before[2])
            references.add(before[0])
            if any(nodes(literal(after[2]))):
                raise ValueError('reference display contains internal nodes')
        elif before != after:
            raise ValueError('non-reference source row differs')
    if not references:
        raise ValueError('reference source requires typed references')
    expected = _display_rows(kind, projected, root, mode=mode, _counts=None, consumed=None, references=references)
    actual = [list(row) for row in rows[:count]]
    actual[0][3] = actual[0][3][marker.end():]
    if len(expected) != count or [row[1:] for row in actual] != [row[1:] for row in expected]:
        raise ValueError('reference display differs from source rows')
    return original, count


def catalog_display_rows(rows: list[list[str]], kind: str, root: Path) -> list[list[str]]:
    """Sort property blocks without separating contiguous array elements."""
    if kind == "EC2.SecurityGroup" or _display_design_layout.GROUPED.get(kind, {}).get("display") == "rule-table":
        return rows  # Horizontal rule tables have their own generation and restoration.
    order = dict(_display_common.catalog_property_order(root, kind) or {})
    design.services.codebuild.adjust_display_order(kind, order)
    if kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}:
        order[kind + ".Name"] = -1
    if kind == "S3.Bucket":
        order[kind + ".Region"] = order[kind + ".BucketName"] + 0.5
    blocks = []
    previous_array = ""
    array_order = {}
    for prop, rank in order.items():
        if "[]" in prop:
            array = prop.split("[]", 1)[0] + "[]"
            array_order.setdefault(array, rank)
    for row in rows:
        array = row[1].split("[]", 1)[0] + "[]" if "[]" in row[1] else ""
        if array and array == previous_array:
            blocks[-1].append(row)
        else:
            blocks.append([row])
        previous_array = array
    return [row for block in sorted(blocks, key=lambda block: array_order.get(
        block[0][1].split("[]", 1)[0] + "[]", order.get(block[0][1], len(order)))) for row in block]


@input_scope
def display_rows(kind: str, rows: list[list[str]], root: Path = ROOT, *, mode="CREATE", _counts=None, consumed: list[str] | None = None) -> list[list[str]]:
    rows = _display_aws_mapping_display.selected_rows(rows, root)
    originals, projected, references = [], [], set()
    for row in rows:
        original, shown = list(row), list(row)
        marker = re.match(r'^<!-- reference-value: ([A-Za-z0-9+/=]+) --> ', row[3])
        if marker:
            original[2] = read_display_source(marker[1])
            original[3] = shown[3] = row[3][marker.end():]
        if any(nodes(literal(original[2]))):
            references.add(row[0])
            if not marker:
                shown[2] = project_text(row[2])
        originals.append(original)
        projected.append(shown)
    result = _display_rows(kind, projected, root, mode=mode, _counts=_counts, consumed=consumed, references=references)
    if references and result:
        source = display_source([originals, projected, len(result)])
        result[0][3] = '<!-- reference-rows: ' + source + ' --> ' + result[0][3]
    return result


def _display_rows(kind, rows, root, *, mode, _counts, consumed, references):
    """Apply the existing service displays without changing formal model values."""
    rows = _display_aws_mapping_display.selected_rows(rows, root)
    processed = []
    formal_properties = {row[1] for row in rows}
    result = []
    index = 0
    counts = {} if _counts is None else _counts
    while index < len(rows):
        start = index
        identity, prop, value, comment = rows[index]
        packed = design.compact_rows.packed_compact_rows(rows, index) if mode == 'IMPORT' else None
        if packed is not None:
            block, expanded = packed
            rendered = display_rows(kind, expanded, root, mode=mode, _counts=counts)
            source = json.dumps([[row[1:] for row in block], len(rendered)], ensure_ascii=True)
            for char in '|<>':
                source = source.replace(char, f'\\u{ord(char):04x}')
            rendered[0][3] = '<!-- compact-source: ' + source + ' --> ' + rendered[0][3]
            result.extend(rendered)
            processed.extend(row[0] for row in block)
            index += len(block)
            continue
        if prop == CODEBUILD_FORMAL_VARIABLE + "Name":
            _, prop, value, comment = design.services.codebuild.codebuild_display_row(rows, index, comment, mode=mode,
                                                                                   typed=rows[index + 2][0] in references)
            index += 2
        elif prop in _display_design_layout.LINKED_LIST_PROPERTIES:
            linked = LINK.fullmatch(value)
            if prop in CODEBUILD_VPC_PROPERTIES and not linked and mode != "IMPORT" and identity not in references:
                if literal(value).lstrip().startswith(('[', '{')):
                    _display_common.subnet_list_items(prop, value)
                raise ReferenceResolutionError("CodeBuild VpcConfig value must be a resource link", property=prop, reference=value)
            items = [value] if linked else _display_common.subnet_list_items(prop, value)
            source = ""
            if not linked:
                encoded = json.dumps(value, ensure_ascii=True)
                for char in "|<>[]":
                    encoded = encoded.replace(char, f"\\u{ord(char):04x}")
                source = "<!-- subnet-list-source: " + encoded + " --> "
            field = prop.removesuffix("[]").removeprefix(kind + ".")
            for offset, item in enumerate(items):
                counts[prop] = counts.get(prop, 0) + 1
                result.append([identity, f"{field}[{counts[prop]}]", item, (source if offset == 0 else "") + comment])
            processed.extend(row[0] for row in rows[start:index + 1])
            index += 1
            continue
        elif prop == GUARDDUTY_FORMAL_FEATURE + "Name":
            prop, value = guardduty_display_row(rows, index)
            index += 1
        elif prop == CLOUDTRAIL_FORMAL_DATA_RESOURCE + "Type":
            prop, value = cloudtrail_display_row(rows, index, counts, mode)
            index += 1
        elif prop.startswith((CODEBUILD_FORMAL_VARIABLE, GUARDDUTY_FORMAL_FEATURE, CLOUDTRAIL_FORMAL_DATA_RESOURCE)) and not prop.startswith(GUARDDUTY_FORMAL_FEATURE + "AdditionalConfiguration"):
            raise ValueError(f"incomplete compact display group: {prop}")
        # Compact producers own their dynamic names; ordinary rows use Mapping names.
        item = _display_aws_mapping_display.rule(prop, root) if not _display_aws_mapping_display.compact_group(prop) and prop in formal_properties else None
        is_import_role_arn = _imports_design_layout.is_import_role_arn
        prop = "RoleARN" if is_import_role_arn(prop, value, mode) else _display_aws_mapping_display.display_name(prop, kind, root) if item else prop.removeprefix(kind + ".")
        result.append([identity, prop, value, comment])
        processed.extend(row[0] for row in rows[start:index + 1])
        index += 1
    if Counter(processed) != Counter(row[0] for row in rows):
        raise ValueError("selected display rows were omitted or consumed more than once")
    if kind == "CodePipeline.Pipeline":
        result = design.services.codepipeline.pipeline_rows(result)
    elif kind in _display_definitions.REQUIRED_NAME_TAG_TYPES:
        result = ec2_display_rows(result)
    elif kind == "Glue.Job":
        result = design.services.glue.glue_argument_rows(result, kind)
    if consumed is not None:
        consumed.extend(processed)
    return result
