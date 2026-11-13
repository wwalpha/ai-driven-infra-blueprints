"""Shared one-based array display and verification against explicit source rows."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import aws_mapping_display as _imports_aws_mapping_display
from model.core import LINK, literal
from utils.input_cache import input_scope, memoized

from design.catalog import DesignSchemaCatalog
from design.common import code
from design.services import cloudtrail, codebuild, codepipeline, guardduty

ROOT = Path(__file__).resolve().parents[3]
ARRAY = re.compile(r"\[\]")
TAG_PROPERTY = re.compile(
    r"(?:^|\.)(?:[A-Za-z0-9]*Tags|tags)(?:\[\])?(?:\.(Key|Value))?$"
)
METADATA_PROPERTY = re.compile(
    r"(?:^|\.)ExternalSecretRotationMetadata\[\]\.(Key|Value)$"
)
TAG_CELL = re.compile(r"(`[^`]*`|<code>.*?</code>|\[[^\]]+\]\([^)]*\)) = (.+)")
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


def _tag_collection(value):
    raw = literal(value).lstrip()
    if raw.startswith(("[", "{")):
        try:
            return json.loads(raw)
        except ValueError:
            pass  # A literal tag value can start with a bracket.


def _display_tag_key(key):
    if re.fullmatch(r"[A-Za-z0-9.:/@+=-]+", key) or LINK.fullmatch(key):
        return key
    escaped = html.escape(key, quote=False).translate(
        str.maketrans(
            {"|": "&#124;", "[": "&#91;", "]": "&#93;", "\n": "&#10;", "\r": "&#13;"}
        )
    )
    return f"<code>{escaped}</code>"


def compact_tag_rows(rows):
    """Show one row per tag without replacing the formal source rows."""
    result = []
    index = 0
    metadata_number = 0
    while index < len(rows):
        identity, prop, value, comment = row = rows[index]
        index += 1
        metadata = METADATA_PROPERTY.search(prop)
        match = metadata or TAG_PROPERTY.search(prop)
        if not match:
            result.append(row)
            continue
        if match[1]:
            tag_prop = prop.removesuffix(".Key")
            if (
                not tag_prop.endswith("[]")
                or index == len(rows)
                or rows[index][1] != f"{tag_prop}.Value"
            ):
                result.append(row)
                continue
            _, _, val, value_comment = rows[index]
            key = value
            keys, values = _tag_collection(key), _tag_collection(val)
            if isinstance(keys, list) and isinstance(values, list):
                if not keys or len(keys) != len(values) or not all(
                    isinstance(item, str) for item in keys + values
                ):
                    result.append(row)
                    continue
                items = zip(keys, values, strict=True)
            else:
                items = [(literal(key), literal(val))]
            comment = "<br>".join(dict.fromkeys(filter(None, (comment, value_comment))))
            index += 1
        else:
            collection = _tag_collection(value)
            if isinstance(collection, dict):
                pairs = list(collection.items())
            elif isinstance(collection, list) and all(
                isinstance(tag, dict) and tag.keys() == {"Key", "Value"}
                for tag in collection
            ):
                pairs = [(tag["Key"], tag["Value"]) for tag in collection]
            else:
                pairs = []
            if not pairs or not all(
                isinstance(key, str) and isinstance(val, str) for key, val in pairs
            ):
                result.append(row)
                continue
            items = pairs
            tag_prop = prop
        for key, val in items:
            if metadata:
                metadata_number += 1
                prefix = tag_prop.removesuffix("[]") + f"[{metadata_number}]"
            else:
                prefix = tag_prop.removesuffix("[]")
            result.append(
                [identity, f"{prefix}.{_display_tag_key(key)}", code(val), comment]
            )
    return result


def expand_saved_tag_rows(rows, kind):
    """Read tag cells for the independent saved resource-name check."""
    result = []
    for number, prop, value, comment in rows:
        field = prop.removeprefix(kind + ".")
        if re.fullmatch(r"(?:Tags|HostedZoneTags)\[[^]]*\]", field):
            pair = TAG_CELL.fullmatch(value)
            if not pair:
                raise ValueError("tag display requires a key and value")
            result.extend(
                [
                    [number, prop + ".Key", pair[1], comment],
                    [number, prop + ".Value", pair[2], comment],
                ]
            )
        elif re.match(r"(?:Tags|HostedZoneTags)\.", field):
            tag_field, _, key = field.partition(".")
            if key.startswith("<code>") and key.endswith("</code>"):
                key = html.unescape(key[6:-7])
            if not key or not value:
                raise ValueError("tag display requires a key and value")
            tags = prop.removesuffix(field) + tag_field + "[]"
            result.extend(
                [
                    [number, tags + ".Key", code(key), comment],
                    [number, tags + ".Value", value, comment],
                ]
            )
        else:
            result.append([number, prop, value, comment])
    return result


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
