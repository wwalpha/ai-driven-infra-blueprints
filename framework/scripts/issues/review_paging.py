"""Deterministic, lossless pages of the complete Review batch JSON."""

import json

from utils.json_format import fingerprint

PAGE_TARGET = 8192
PAGE_LIMIT = 32768


def pages(material):
    """Return JSON text fragments; concatenation and JSON decoding restore material."""
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False)
    chunks = []
    current = ""
    size = 0
    for token in encoder.iterencode(material):
        if (
            current
            and len(token.encode("utf-8")) <= PAGE_TARGET
            and size + len(token.encode("utf-8")) > PAGE_TARGET
        ):
            chunks.append(current)
            current, size = "", 0
        while token:
            room = PAGE_TARGET - size
            # Bound actual UTF-8 bytes, while preserving character boundaries.
            part = token.encode("utf-8")[:room].decode("utf-8", errors="ignore")
            if not part:
                chunks.append(current)
                current, size = "", 0
                continue
            current += part
            size += len(part.encode("utf-8"))
            token = token[len(part) :]
            if token or size >= PAGE_TARGET:
                chunks.append(current)
                current, size = "", 0
    if current:
        chunks.append(current)
    digest = fingerprint(material)
    offset = 0
    result = []
    for index, content in enumerate(chunks):
        end = offset + len(content)
        page = dict(
            page_index=index,
            page_count=len(chunks),
            material_digest=digest,
            position=dict(unit="json-character", start=offset, end=end),
            content=content,
            has_next=index + 1 < len(chunks),
        )
        page["page_digest"] = fingerprint(page)
        if (
            len(
                (json.dumps(page, ensure_ascii=False, allow_nan=False) + "\n").encode(
                    "utf-8"
                )
            )
            > PAGE_LIMIT
        ):
            raise ValueError("Review page exceeds 32768 bytes")
        result.append(page)
        offset = end
    return result
