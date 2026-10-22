"""Markdown prose and section selection, excluding fenced examples."""
import re
from pathlib import Path

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


def markdown_sections(text):
    """Index real headings and their explicit anchors, ignoring fenced examples."""
    headings, aliases = [], []
    for offset, line in markdown_prose(text):
        if match := re.fullmatch(r'<a id="([^"<>]+)"></a>\s*', line):
            aliases.append(match[1])
        elif match := re.match(r"^(#{1,6}) (.+?)\s*#*\s*$", line):
            anchor = re.sub(r"[^\w -]", "", match[2].lower()).replace(" ", "-")
            headings.append((offset, len(match[1]), [anchor, *aliases]))
            aliases = []
    result = {}
    for index, (start, level, anchors) in enumerate(headings):
        end = next((pos for pos, depth, _ in headings[index + 1:] if depth <= level), len(text))
        for anchor in dict.fromkeys(anchors):
            if anchor in result:
                raise ValueError(f"ambiguous rule section: {anchor}")
            result[anchor] = text[start:end]
    return result



def rule_readings(root, source, text, engine=None):
    """Use the document's rule links as the single source of reading scope."""
    from task_contract import safe_path
    from utils.aws_mappings import definition_root
    root, source = definition_root(root).resolve(), source.resolve()
    readings, contents = {}, {}
    prose = "".join(re.sub(r"(`+).*?\1", "", line) for _, line in markdown_prose(text))
    for raw in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", prose):
        if ":" in raw or raw.startswith("#"):
            continue
        target, _, anchor = raw.partition("#")
        if Path(target).suffix != ".md":
            continue
        path = (source.parent / target).resolve()
        if not any(path.is_relative_to(root / directory) for directory in ("framework/rules", ".agents/skills")):
            continue
        relative = path.relative_to(root).as_posix()
        safe_path(root, relative)
        if path not in contents:
            contents[path] = path.read_bytes().decode("utf-8")
        content = contents[path]
        sections = markdown_sections(content)
        if anchor and anchor not in sections:
            raise ValueError(f"missing rule section: {source.relative_to(root)} -> {relative}#{anchor}")
        if engine and path.name in {"cloudformation.md", "terraform.md"} and path.stem != engine:
            continue
        readings.setdefault(path, set()).add(anchor)
    return {path: {"sections": sorted(anchors), "sourceText": contents[path],
                   "text": contents[path] if "" in anchors
                   else "\n".join(markdown_sections(contents[path])[anchor] for anchor in sorted(anchors))}
            for path, anchors in readings.items()}




def read_declaration(text):
    matches = re.findall(r'<!-- deploy-read-plan -->\s*```json\s*\n(.*?)\n```', text, re.S)
    if len(matches) != 1:
        raise ValueError('exactly one deploy Read declaration is required')
    from utils.json_format import policy_json
    result = policy_json(matches[0])
    if not isinstance(result, dict) or not result:
        raise ValueError('invalid Read declaration')
    for stage, entry in result.items():
        if (not isinstance(stage, str) or not isinstance(entry, dict) or set(entry) != {'when', 'documents'}
                or not isinstance(entry['when'], str) or not isinstance(entry['documents'], list)
                or not entry['documents'] or not all(isinstance(v, str) and v for v in entry['documents'])):
            raise ValueError('invalid Read stage: ' + str(stage))
    return result


def declared_readings(root, source, stages, engine='cloudformation'):
    """Read exact declared ranges, not explanatory links or inferred natural language."""
    from task_contract import safe_path
    from utils.aws_mappings import definition_root
    base = definition_root(root).resolve()
    text = source.read_text(encoding='utf-8')
    declaration = read_declaration(text)
    readings = {}
    for stage in stages:
        if stage not in declaration:
            raise ValueError('undeclared reading stage: ' + stage)
        for reference in declaration[stage]['documents']:
            relative, _, anchor = reference.partition('#')
            path = (source.parent / relative).resolve() if relative else source.resolve()
            # AGENTS belongs to the consumer root; all framework authority belongs to definition_root.
            if path == base / 'AGENTS.md':
                path = root.resolve() / 'AGENTS.md'
            owner = base if path.is_relative_to(base) else root.resolve()
            if not path.is_relative_to(owner) or path.suffix != '.md':
                raise ValueError('invalid declared document: ' + reference)
            safe_path(owner, path.relative_to(owner).as_posix())
            if engine == 'terraform' and path.name == 'cloudformation.md':
                continue
            content = path.read_text(encoding='utf-8')
            sections = markdown_sections(content)
            if anchor and anchor not in sections:
                raise ValueError('missing declared section: ' + reference)
            entry = readings.setdefault(path, {'sections': [], 'sourceText': content})
            if anchor not in entry['sections']:
                entry['sections'].append(anchor)
    for entry in readings.values():
        anchors = entry['sections']
        entry['text'] = entry['sourceText'] if '' in anchors else '\n'.join(
            markdown_sections(entry['sourceText'])[anchor] for anchor in anchors)
    return readings
