"""Explicit active-task validation scope; never infer a repository-wide fallback."""

from pathlib import Path
import re


def active_scope(root: Path, full: bool = False) -> set[tuple[str, str, str]] | None:
    if full:
        return None
    path = root / "tasks/active.md"
    if not path.is_file():
        raise ValueError("validation scope missing: tasks/active.md; specify scope or --all")
    lines = path.read_text(encoding="utf-8").splitlines()
    selected = []
    inside = False
    found = False
    for line in lines:
        if line == "## Validation scope":
            if found:
                raise ValueError("duplicate Validation scope section")
            inside = True
            found = True
        elif line.startswith("## "):
            inside = False
        elif inside and line.strip():
            match = re.fullmatch(r"- `([^`]+)`", line)
            if not match:
                raise ValueError(f"invalid validation scope: {line}")
            selected.append(match.group(1))
    if not selected:
        raise ValueError("validation scope missing: specify environment/target-directory/service; no automatic full validation")
    if selected == ["all"]:
        return None
    if selected == ["framework"]:
        if not any(line in {"- Task type: `governance`", "- Task type: `catalog-maintenance`", "- Task type: `migration`"} for line in lines):
            raise ValueError("framework scope requires a framework task")
        return set()
    scope = set()
    for value in selected:
        parts = value.split("/")
        if len(parts) != 3 or any(not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", part) for part in parts):
            raise ValueError(f"invalid validation scope: {value}; expected environment/target-directory/service")
        scope.add(tuple(parts))
    if len(scope) != len(selected):
        raise ValueError("duplicate validation scope entry")
    return scope


def scoped_files(root: Path, base: str, suffix: str, scope) -> list[Path]:
    directory = root / base
    if scope is None:
        return sorted(directory.rglob(f"*{suffix}"))
    return sorted(path for environment, target, service in scope
                  if (path := directory / environment / target / f"{service}{suffix}").is_file())


def reference_lines(path: Path, fragments: set[str]) -> list[str]:
    """Read only referenced resource blocks, including their enclosing grouped parent."""
    from design_layout import RESOURCE, ANCHOR, resource_heading_lines
    lines = resource_heading_lines(path.read_text(encoding="utf-8").splitlines())
    starts = []
    for index, line in enumerate(lines):
        if RESOURCE.fullmatch(line):
            start = index
            while start and (not lines[start - 1].strip() or ANCHOR.fullmatch(lines[start - 1])
                             or lines[start - 1].startswith("<!-- resource-logical-id:")):
                start -= 1
            starts.append(start)
    metadata = [line for line in lines[:starts[0] if starts else 0] if line.startswith("- Design service ID:")]
    blocks = []
    groups = set()
    for start, end in zip(starts, [*starts[1:], len(lines)]):
        block = lines[start:end]
        anchors = set(ANCHOR.findall("\n".join(block)))
        if not fragments & anchors:
            continue
        heading = next(RESOURCE.fullmatch(line) for line in block if RESOURCE.fullmatch(line))
        if heading.group(1) == "EC2.SecurityGroup":
            parent_anchor = next(ANCHOR.fullmatch(line).group(1) for line in block if ANCHOR.fullmatch(line))
            groups.add(parent_anchor)
            if fragments & anchors <= {parent_anchor}:
                end = next((index for index, line in enumerate(block) if line.startswith("| Direction |")), len(block))
                block = [line for line in block[:end] if not line.startswith("<!-- security-group-tags:")]
        blocks.extend(block)
    if groups:
        # The SG parser needs its matching overview rows; other groups and rules are irrelevant.
        metadata.extend(("## リソース一覧", "### EC2.SecurityGroup", "| No. | ResourceName | Comment |", "| ---: | --- | --- |"))
        number = 0
        for line in lines:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) == 3 and cells[0].isdigit() and any(f"](#{anchor})" in cells[1] for anchor in groups):
                number += 1
                metadata.append("| " + " | ".join([str(number), *cells[1:]]) + " |")
    return [*metadata, "## リソース詳細", *blocks]
