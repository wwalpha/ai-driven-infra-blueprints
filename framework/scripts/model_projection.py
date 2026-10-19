"""Local resource links, identifier outputs and canonical JSON hashes."""
from validation_cache import input_is_file, input_text

import hashlib
import json
import re
from pathlib import Path
from design_document import DesignIndex
from design_catalog import design_material_files
from design_layout import HIDDEN_PROPERTIES, RESOURCE
from validation_cache import memoized


ANCHOR = re.compile(r'^<a\s+id="([^"]+)"\s*></a>$')
JSON_LINK = re.compile(r"^\[[^\]]+\]\(([^)#]+\.json)\)$")
RESOURCE_LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")


def json_sha256(path: Path) -> str:
    content = json.loads(input_text(path, encoding="utf-8"))
    return document_sha256(content)


def document_sha256(content) -> str:
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
            for line in input_text(path, encoding="utf-8").splitlines()
            if line.endswith("=IDENTIFIER_OUTPUT") and line.partition("=")[0] not in HIDDEN_PROPERTIES
        }
    return outputs


def linked_resource(path: Path, value: str, *, design_index: DesignIndex | None = None) -> tuple[str, str] | None:
    match = RESOURCE_LINK.fullmatch(value)
    if not match:
        return None
    _, target_text, fragment = match.groups()
    target = path if not target_text else path.parent / target_text
    if not input_is_file(target):
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
