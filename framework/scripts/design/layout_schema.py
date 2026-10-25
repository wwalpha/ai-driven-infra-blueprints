"""Read-only display layout metadata without Model/rendering dependencies."""

import json
import re
from pathlib import Path

from utils.input_cache import input_text
from utils.reference_contracts import LINKED_LIST_PROPERTIES as LINKED_LIST_PROPERTIES
from utils.reference_contracts import SUBNET_LIST_PROPERTIES as SUBNET_LIST_PROPERTIES

from design.services.definitions.config import RESOURCE_ANCHOR_KINDS

LAYOUT_PATH = Path(__file__).resolve().parents[2] / "rules" / "resource-layout.json"

LAYOUTS = json.loads(input_text(LAYOUT_PATH, encoding="utf-8"))

RESOURCE_PROPERTY_PREFIXES = tuple(name + "." for name in LAYOUTS)

GROUPED = {name: rule for name, rule in LAYOUTS.items() if isinstance(rule, dict)}

GROUPED_RESOURCE_TYPES = {
    rule["parent"]: {
        name for name, child in GROUPED.items() if child["parent"] == rule["parent"]
    }
    for rule in GROUPED.values()
}

IMPLICIT_GROUPED_PROPERTIES = {
    name: {rule["parentProperty"]} for name, rule in GROUPED.items()
}

DETAILS_HEADING = "## リソース詳細"

RESOURCE = re.compile(
    r"^### ([A-Za-z0-9]+\.[A-Za-z0-9]+): ([^<>|`\s](?:[^<>|`]*[^<>|`\s])?)$"
)

ANCHOR = re.compile(r'<a\s+id="([^"]+)"\s*></a>')

RESOURCE_ID = re.compile(
    r"^<!-- resource-logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) -->$"
)

CHILD = re.compile(
    r'^<a id="([A-Za-z0-9_.-]+)"></a><!-- logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) -->\s*'
)


CHILD_NAME = re.compile(r"^([^<>|`\n：]+)：")

HEADER = "| No. | Property | Value | Source / Comment |"

ALIGNMENT = "| ---: | --- | --- | --- |"


SUBNET_LIST_SOURCE = re.compile(r'^<!-- subnet-list-source: ("(?:[^"\\]|\\.)*") --> ')


STACK_DESIGN = "cloudformation-stacks.md"

STACK_HEADER = "| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |"


def resource_anchor(service_id: str, name: str, resource_type: str = "") -> str:
    """Use the displayed resource name as the navigation identity."""
    kind = RESOURCE_ANCHOR_KINDS.get(resource_type)
    prefix = f"{service_id}-{kind}" if kind else service_id
    return prefix + "-" + re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-")


COMPACT_SOURCE = re.compile(r"^<!-- compact-source: (.+?) --> ")
