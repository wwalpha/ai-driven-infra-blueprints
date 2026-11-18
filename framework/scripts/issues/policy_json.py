"""Validate the saved JSON payload of Model-backed IAM and S3 policy sections."""

import json
import re
from collections import Counter

from design.layout_schema import ANCHOR
from design.policy_tables import END, IAM_END, IAM_START, START
from model.render import document_view_labels
from services.registry import REGISTRY
from utils.json_format import strict_json
from utils.markdown_format import markdown_prose
from validation.diagnostics import Diagnostic

from model import ModelView

CHECK_ID = "design.saved-policy-json"
POLICY_SERVICES = {"iam", "s3"}
POLICY_PROPERTIES = REGISTRY.design_tables.get("REVIEW_POLICY_JSON", ())
MARKERS = {START: END, IAM_START: IAM_END}
FOLDED_JSON = re.compile(
    r'^<a id="(?P<anchor>[^"\n]+)"></a>\n\n'
    r"#### [^\n]+\n\n<details>\n<summary>[^\n]*</summary>\n\n"
    r"^```json\n(?P<body>(?:(?!^ {0,3}`{3,})[^\n]*\n)*)^```\n\n</details>$",
    re.MULTILINE,
)


def marked_sections(prose):
    """Yield only complete, unnested generated sections outside fenced examples."""
    opened = []
    start = None
    for offset, line in prose:
        marker = line.rstrip("\n")
        if marker in MARKERS:
            start = None if opened else offset + len(line)
            opened.append(MARKERS[marker])
        elif marker in MARKERS.values() and opened:
            if opened.pop() != marker:
                start = None
            if not opened and start is not None:
                yield start, offset


def check_saved_policy_json(text, values, path, scope, findings):
    """Return the same View with only verified policy bodies removed."""
    policy_ids = {
        rid
        for rid, row in ModelView(values).all_rows()
        if row.get("property") in POLICY_PROPERTIES and "document" in row
    }
    if not policy_ids:
        return text
    model_anchors = Counter(
        labels[0] for labels in document_view_labels(values, policy_ids).values()
    )
    normalized = text.replace("\r\n", "\n")
    prose = list(markdown_prose(normalized))
    anchors = {
        offset: match[1]
        for offset, line in prose
        if (match := ANCHOR.fullmatch(line.rstrip("\n")))
    }
    saved_anchors = Counter(anchors.values())
    chunks = []
    cursor = 0
    for start, end in marked_sections(prose):
        for block in FOLDED_JSON.finditer(normalized, start, end):
            anchor = block["anchor"]
            if (
                anchors.get(block.start()) != anchor
                or model_anchors[anchor] != 1
                or saved_anchors[anchor] != 1
            ):
                continue
            body_start, body_end = block.span("body")
            try:
                strict_json(block["body"])
            except (ValueError, RecursionError) as error:
                line = normalized.count("\n", 0, body_start) + 1
                if isinstance(error, json.JSONDecodeError):
                    line += error.lineno - 1
                    reason = f"{error.msg} (column {error.colno})"
                else:
                    reason = "strict JSON parser rejected the payload"
                findings.add_diagnostic(
                    Diagnostic.create(
                        findings.canonical_root,
                        code="design.policy-json.invalid",
                        check_id=CHECK_ID,
                        cause_kind="input_invalid",
                        service=scope,
                        source_path=path,
                        location=f"#{anchor}",
                        message=f"{findings.relative(path)}:{line}: invalid saved policy JSON (#{anchor}): {reason}",
                    )
                )
            else:
                findings.checks += 1
                chunks.append(normalized[cursor:body_start])
                cursor = body_end
    return "".join([*chunks, normalized[cursor:]]) if chunks else text
