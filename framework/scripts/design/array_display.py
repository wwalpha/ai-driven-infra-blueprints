"""Shared one-based array display and verification against explicit source rows."""

from __future__ import annotations

import json
import re
from pathlib import Path

import aws_mapping_display as _imports_aws_mapping_display
from model.core import LINK
from utils.input_cache import input_scope, memoized

from design.catalog import DesignSchemaCatalog
from design.services import cloudtrail, codebuild, codepipeline, guardduty

ROOT = Path(__file__).resolve().parents[3]
ARRAY = re.compile(r"\[\]")
ARRAY_TEMPLATES = {
    "CodePipeline.Pipeline": codepipeline.array_template,
    "CloudTrail.Trail": cloudtrail.array_template,
    "GuardDuty.Detector": guardduty.array_template,
    "CodeBuild.Project": codebuild.array_template,
}
COMPACT_ARRAYS = (
    cloudtrail.compact_array,
    guardduty.compact_array,
    codebuild.compact_array,
)


@memoized
def display_catalog(root):
    catalog = DesignSchemaCatalog(root)
    types = {
        name.removeprefix("AWS::").replace("::", ".", 1)
        for name in catalog.resource_types
    }
    types.update(catalog.api_schemas)
    return catalog, tuple(kind + "." for kind in sorted(types))


def array_template(prop, kind, root):
    formal_name = _imports_aws_mapping_display.formal_name
    catalog, prefixes = display_catalog(root)
    qualified = prop if prop.startswith(prefixes) else kind + "." + prop
    owner = ".".join(qualified.split(".")[:2])
    formal = (
        formal_name(prop, kind, root) if kind + "." in prefixes else None
    ) or qualified
    template = prop
    # Retain a displayed ancestor when an alias hides an array component.
    if formal != qualified and "[]" in formal and "[]" not in template:
        ancestors = []
        for part in formal.removeprefix(owner + ".").split("."):
            ancestors.append(part.removesuffix("[]"))
            if part.endswith("[]"):
                for ancestor in reversed(ancestors):
                    if re.search(
                        r"(?:^|\.)" + re.escape(ancestor) + r"(?:\.|$)", template
                    ):
                        template = re.sub(
                            r"(^|\.)" + re.escape(ancestor) + r"(?=\.|$)",
                            r"\g<0>[]",
                            template,
                            count=1,
                        )
                        break
    if owner in ARRAY_TEMPLATES:
        template = ARRAY_TEMPLATES[owner](template)
    if "[]" in template:
        parent, remainder = template.split("[]", 1)
        template = parent + "[]" + re.sub(r"\[[1-9]\d*\]", "[]", remainder)
    # Existing indexed lists and compact, name-based rows already have a display.
    if re.search(r"\[\d+\]", formal) or formal.endswith("[]"):
        return template
    try:
        if (
            catalog.property_schema(owner, formal.removeprefix(owner + ".")).get("type")
            == "array"
        ):
            template += "[]"
    except KeyError:
        pass  # Design-only fields and compact names are not schema properties.
    return template


def numbered_property(prop, states, compact=False):
    """Repeat a direct field to start a new object; count nested arrays separately."""
    while match := ARRAY.search(prop):
        prefix, field = prop[: match.start()], prop[match.end() :]
        number, seen = states.get(prefix, (0, set()))
        nested = bool(re.search(r"\[(?:\d*)\]", field))
        if (
            not number
            or not field
            or (compact and not nested)
            or (not nested and field in seen)
        ):
            number, seen = number + 1, set()
        if not nested:
            seen.add(field)
        states[prefix] = number, seen
        prop = prop[: match.start()] + f"[{number}]" + field
    return prop


@input_scope
def indexed_rows(rows, kind, root=ROOT):
    """Index all remaining catalog arrays after existing compact service displays."""
    result, states = [], {}
    for identity, prop, value, comment in rows:
        if "<!-- logical-id:" in comment:
            states = {}  # A grouped child owns its own arrays.
        if "<!-- ec2-name-tag:" in comment:
            numbered_property("Tags[].Key", states)
            numbered_property("Tags[].Value", states)
        template = array_template(prop, kind, root)
        compact = any(matches(template) for matches in COMPACT_ARRAYS)
        if "[]" not in template:
            result.append([identity, prop, value, comment])
            continue
        items = [value]
        if template.endswith("[]"):
            raw = (
                value[1:-1] if value.startswith("`") and value.endswith("`") else value
            )
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = None  # A resource link remains one selected element.
                if isinstance(parsed, list):
                    items = [
                        item
                        if isinstance(item, str) and LINK.fullmatch(item)
                        else "`"
                        + (
                            item
                            if isinstance(item, str)
                            else json.dumps(
                                item, ensure_ascii=False, separators=(",", ":")
                            )
                        )
                        + "`"
                        for item in parsed
                    ]
                    if any(
                        any(char in item[1:-1] for char in "|`\n\r") for item in items
                    ):
                        raise ValueError(
                            "array display elements cannot contain Markdown table delimiters"
                        )
                    # A complete source array is one parent field, regardless of its element count.
                    template = (
                        numbered_property(template.removesuffix("[]"), states) + "[]"
                    )
        for item in items or [value]:
            field = (
                numbered_property(template, states, compact)
                if items
                else template.removesuffix("[]")
            )
            result.append([identity, field, item, comment])
    return result


@input_scope
def verified_rows(rows, source, kind, root=ROOT):
    """Verify the display, then return the exact supplied source, never inferred JSON."""
    expected = indexed_rows(source, kind, root)
    if [row[1:] for row in expected] != [row[1:] for row in rows]:
        raise ValueError("array display differs from Model source rows")
    return [list(row) for row in source]
