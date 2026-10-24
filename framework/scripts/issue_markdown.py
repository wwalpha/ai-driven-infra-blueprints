"""Fence-aware classification of ordinary issues and nonblocking diagnostics."""
import re

NOTICE_MARKER = r'^(<!-- issues-notices:[^ >]+:(?:start|end) -->)[ \t]*$'
WARNING_HEADINGS = ('警告（非ブロッキング）', '参照警告（非ブロッキング）')
SERVICE_MARKER = r'^.*(<!-- issue-service: [a-z0-9_-]+ -->).*$'
ISSUE_ID = r'^.*(<!-- issue-id: [^ >]+ -->)'


def markdown_matches(text, pattern):
    result, offset, fence = [], 0, None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
        elif marker and (marker[1][0] == '~' or '`' not in marker[2]):
            fence = (marker[1][0], len(marker[1]))
        else:
            match = re.match(pattern, line.rstrip('\r\n'))
            if match:
                result.append((offset, offset + match.end(), match.group(1)))
        offset += len(line)
    return result


def without_notices(text):
    return split_notices(text)[0]


def split_notices(text):
    """Explicit scopes and heading containment win over warning list syntax.

    Only explicit issue metadata can resume ordinary issues inside a warning.
    Contradictory scope/issue metadata is rejected before any report is saved.
    """
    notices, ordinary, offset = [], [], 0
    opened = None
    for start, end, marker in markdown_matches(text, NOTICE_MARKER):
        scope, action = marker.removeprefix('<!-- issues-notices:').removesuffix(' -->').rsplit(':', 1)
        if action == 'start':
            if opened is not None:
                raise ValueError('ambiguous issues-notices: nested scope marker')
            opened = (start, scope)
        else:
            if opened is None or opened[1] != scope:
                raise ValueError('ambiguous issues-notices: unmatched scope marker')
            block = text[opened[0]:end]
            if markdown_matches(block, SERVICE_MARKER) or markdown_matches(block, ISSUE_ID):
                raise ValueError('ambiguous issues-notices: ordinary issue metadata inside explicit notice scope')
            ordinary.append(text[offset:opened[0]])
            notices.append((scope, block))
            offset, opened = end, None
    if opened is not None:
        raise ValueError('ambiguous issues-notices: unclosed scope marker')
    ordinary.append(text[offset:])
    text = ''.join(ordinary)
    headings = markdown_matches(text, r'^(#{1,3} .+)$')
    owned = set()
    for index, (start, end, heading) in enumerate(headings):
        if not heading.startswith('### '):
            continue
        body = text[end:headings[index + 1][0] if index + 1 < len(headings) else len(text)]
        items = markdown_matches(body, r'^ {0,3}(\d+)[.)] +')
        markers = markdown_matches(body, SERVICE_MARKER)
        first_item_end = items[1][0] if len(items) > 1 else len(body)
        if (markers and (not items or markers[0][0] <= items[0][0]) or
                items and markdown_matches(body[items[0][0]:first_item_end], ISSUE_ID)):
            owned.add(start)
    ordinary, offset, warning = [], 0, None
    warning_level = 0
    for start, _end, line in markdown_matches(text, r'^(.*)$'):
        heading = re.fullmatch(r'(#{1,3}) (.+)', line)
        boundary = (heading and (len(heading[1]) <= warning_level or start in owned or heading[2] in WARNING_HEADINGS)) or re.fullmatch(SERVICE_MARKER, line)
        if warning is not None and boundary:
            ordinary.append(text[offset:warning])
            notices.append((None, text[warning:start].rstrip()))
            offset, warning = start, None
        if heading and heading[2] in WARNING_HEADINGS:
            warning, warning_level = start, len(heading[1])
        elif warning is not None and re.match(ISSUE_ID, line):
            raise ValueError('ambiguous warning: issue-id requires an ordinary service section or issue-service marker')
    if warning is not None:
        ordinary.append(text[offset:warning])
        notices.append((None, text[warning:].rstrip()))
        offset = len(text)
    ordinary.append(text[offset:])
    return ''.join(ordinary), notices
