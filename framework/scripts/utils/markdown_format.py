"""Markdown prose and section selection, excluding fenced examples."""

import re


def markdown_prose(text):
    """Yield original offsets and lines outside fenced examples."""
    offset, fence = 0, None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None:
            yield offset, line
        offset += len(line)
