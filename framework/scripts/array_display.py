"""Shared one-based array display and lossless verification of source rows."""

from __future__ import annotations

import json
from pathlib import Path
import re

from design_catalog import DesignSchemaCatalog
from validation_cache import memoized


ROOT = Path(__file__).resolve().parents[2]
SOURCE = re.compile(r"^<!-- array-source: (.+?) --> ")
ARRAY = re.compile(r"\[\]")


@memoized
def display_catalog(root):
    catalog = DesignSchemaCatalog(root)
    aliases = json.loads((root / "framework/rules/display-property-aliases.json").read_text(encoding="utf-8"))
    types = {name.removeprefix("AWS::").replace("::", ".", 1) for name in catalog.resource_types}
    types.update(catalog.api_schemas)
    return catalog, aliases, tuple(kind + "." for kind in sorted(types))


def array_template(prop, kind, root):
    catalog, aliases, prefixes = display_catalog(root)
    qualified = prop if prop.startswith(prefixes) else kind + "." + prop
    owner = ".".join(qualified.split(".")[:2])
    formal = aliases.get(qualified, qualified)
    template = prop
    # Retain a displayed ancestor when an alias hides an array component.
    if formal != qualified and "[]" in formal and "[]" not in template:
        ancestors = []
        for part in formal.removeprefix(owner + ".").split("."):
            ancestors.append(part.removesuffix("[]"))
            if part.endswith("[]"):
                for ancestor in reversed(ancestors):
                    if re.search(r"(?:^|\.)" + re.escape(ancestor) + r"(?:\.|$)", template):
                        template = re.sub(r"(^|\.)" + re.escape(ancestor) + r"(?=\.|$)", r"\g<0>[]", template, count=1)
                        break
    if owner == "CodePipeline.Pipeline":
        template = re.sub(r"(Stages\[[1-9]\d*\]\.Actions)(?=\.)", r"\1[]", template)
    if owner == "CloudTrail.Trail" and re.search(r"EventSelectors\.DataResources\[[1-9]\d*\]\.(S3|Lambda)$", template):
        template = re.sub(r"EventSelectors\.DataResources\[[1-9]\d*\]", "EventSelectors[].DataResources[]", template)
    for compact_owner, field in (("GuardDuty.Detector", "Features"), ("CodeBuild.Project", "Environment.Variables")):
        if owner == compact_owner:
            template = re.sub(r"(^|\.)" + re.escape(field) + r"(?=\.[^.]+$)", r"\g<0>[]", template)
    if "[]" in template:
        parent, remainder = template.split("[]", 1)
        template = parent + "[]" + re.sub(r"\[[1-9]\d*\]", "[]", remainder)
    # Existing indexed lists and compact, name-based rows already have a display.
    if re.search(r"\[\d+\]", formal) or formal.endswith("[]"):
        return template
    try:
        if catalog.property_schema(owner, formal.removeprefix(owner + ".")).get("type") == "array":
            template += "[]"
    except KeyError:
        pass  # Design-only fields and compact names are not schema properties.
    return template


def numbered_property(prop, states, compact=False):
    """Repeat a direct field to start a new object; count nested arrays separately."""
    while match := ARRAY.search(prop):
        prefix, field = prop[:match.start()], prop[match.end():]
        number, seen = states.get(prefix, (0, set()))
        nested = bool(re.search(r"\[(?:\d*)\]", field))
        if not number or not field or (compact and not nested) or (not nested and field in seen):
            number, seen = number + 1, set()
        if not nested:
            seen.add(field)
        states[prefix] = number, seen
        prop = prop[:match.start()] + f"[{number}]" + field
    return prop


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
        compact = bool(re.search(r"(?:Features|Environment\.Variables)\[\]\.[^.]+$|DataResources\[\]\.(?:S3|Lambda)$", template))
        if "[]" not in template:
            result.append([identity, prop, value, comment])
            continue
        items = [value]
        if template.endswith("[]"):
            raw = value[1:-1] if value.startswith("`") and value.endswith("`") else value
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = None  # A resource link remains one selected element.
                if isinstance(parsed, list):
                    items = ["`" + (item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, separators=(",", ":"))) + "`" for item in parsed]
                    if any(any(char in item[1:-1] for char in "|`\n\r") for item in items):
                        raise ValueError("array display elements cannot contain Markdown table delimiters")
        metadata = json.dumps([prop, value, max(1, len(items))], ensure_ascii=True)
        for char in "|<>":
            metadata = metadata.replace(char, f"\\u{ord(char):04x}")
        for offset, item in enumerate(items or [value]):
            field = numbered_property(template, states, compact) if items else template.removesuffix("[]")
            result.append([identity, field, item, (f"<!-- array-source: {metadata} --> " if offset == 0 else "") + comment])
    return result


def restored_rows(rows, kind, root=ROOT):
    """Restore sources, then regenerate to reject wrong indexes, values or comments."""
    result = []
    index = 0
    marked = False
    while index < len(rows):
        identity, prop, value, comment = rows[index]
        marker = SOURCE.match(comment)
        if "<!-- array-source:" in comment and not marker:
            raise ValueError("invalid array source marker")
        if not marker:
            result.append(rows[index])
            index += 1
            continue
        source = json.loads(marker[1])
        if (not isinstance(source, list) or len(source) != 3 or
                not all(isinstance(item, str) for item in source[:2]) or
                type(source[2]) is not int or not 1 <= source[2] <= len(rows) - index):
            raise ValueError("invalid array source row or element count")
        marked = True
        result.append([identity, *source[:2], comment[marker.end():]])
        index += source[2]
    if marked:
        expected = indexed_rows(result, kind, root)
        if [row[1:] for row in expected] != [row[1:] for row in rows]:
            raise ValueError("array indexes, elements or comments differ from their source rows")
    return result
