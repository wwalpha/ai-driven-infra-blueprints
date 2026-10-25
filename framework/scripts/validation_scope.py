"""Explicit active-task validation scope; never infer a repository-wide fallback."""

from pathlib import Path

import design.layout as design_layout
import model.sources as _imports_model_sources
from task_contract_core import active_scope as active_scope
from utils.input_cache import input_is_file, input_select, input_text


def scoped_files(root: Path, base: str, suffix: str, scope) -> list[Path]:
    directory = root / base
    if base == "model":
        model_paths = _imports_model_sources.model_paths
        return (
            model_paths(root)
            if scope is None
            else sorted(
                directory / env / target / (service + suffix)
                for env, target, service in scope
            )
        )
    if scope is None:
        return sorted(input_select(directory, f"*{suffix}", recursive=True))
    return sorted(
        path
        for environment, target, service in scope
        if input_is_file(
            path := directory / environment / target / f"{service}{suffix}"
        )
    )


def reference_lines(
    path: Path, fragments: set[str], *, lines: list[str] | None = None
) -> list[str]:
    """Read only referenced resource blocks, including their enclosing grouped parent."""
    ANCHOR, RESOURCE = design_layout.ANCHOR, design_layout.RESOURCE
    resource_heading_lines = design_layout.resource_heading_lines
    if lines is None:
        lines = resource_heading_lines(input_text(path, encoding="utf-8").splitlines())
    starts = []
    for index, line in enumerate(lines):
        if RESOURCE.fullmatch(line):
            start = index
            while start and (
                not lines[start - 1].strip()
                or ANCHOR.fullmatch(lines[start - 1])
                or lines[start - 1].startswith("<!-- resource-logical-id:")
            ):
                start -= 1
            starts.append(start)
    metadata = [
        line
        for line in lines[: starts[0] if starts else 0]
        if line.startswith("- Design service ID:")
    ]
    blocks = []
    groups = set()
    for start, end in zip(starts, [*starts[1:], len(lines)], strict=False):
        block = lines[start:end]
        anchors = set(ANCHOR.findall("\n".join(block)))
        if not fragments & anchors:
            continue
        heading = next(
            RESOURCE.fullmatch(line) for line in block if RESOURCE.fullmatch(line)
        )
        if heading.group(1) == "EC2.SecurityGroup":
            parent_anchor = next(
                ANCHOR.fullmatch(line).group(1)
                for line in block
                if ANCHOR.fullmatch(line)
            )
            groups.add(parent_anchor)
            if fragments & anchors <= {parent_anchor}:
                end = next(
                    (
                        index
                        for index, line in enumerate(block)
                        if line.startswith("| Direction |")
                    ),
                    len(block),
                )
                block = [
                    line
                    for line in block[:end]
                    if not line.startswith("<!-- security-group-tags:")
                ]
        blocks.extend(block)
    if groups:
        # The SG parser needs its matching overview rows; other groups and rules are irrelevant.
        metadata.extend(
            (
                "## リソース一覧",
                "### EC2.SecurityGroup",
                "| No. | ResourceName | Comment |",
                "| ---: | --- | --- |",
            )
        )
        number = 0
        for line in lines:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if (
                len(cells) == 3
                and cells[0].isdigit()
                and any(f"](#{anchor})" in cells[1] for anchor in groups)
            ):
                number += 1
                metadata.append("| " + " | ".join([str(number), *cells[1:]]) + " |")
    return [*metadata, "## リソース詳細", *blocks]
