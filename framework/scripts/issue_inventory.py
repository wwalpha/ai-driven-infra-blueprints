"""Read ordinary Issue service ownership without Task or Model loading dependencies."""

import re
from pathlib import Path

from issue_markdown import markdown_matches, split_notices
from utils.input_cache import input_text

SERVICE = r"[a-z0-9]+(?:[-_][a-z0-9]+)*"


def _callback_unresolved_services_flush(
    block, environment, heading, number, path, result, root, target, /
):
    if not number:
        return
    text = "\n".join(block)
    markers = re.findall(rf"<!-- issue-service: ({SERVICE}) -->", heading + "\n" + text)
    services = set(markers)
    if not services and re.fullmatch(SERVICE, heading):
        services.add(heading)
    if not services:
        for link in re.findall(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]*)?\)", text):
            link = re.sub(r":\d+$", "", link)
            linked = (path.parent / link).resolve()
            for base, suffix in (("model", ".properties"), ("docs/designs", ".md")):
                try:
                    base_path = (root / base).resolve()
                    source = linked
                    parts = linked.relative_to(base_path).parts
                    if (
                        base == "model"
                        and len(parts) == 4
                        and re.fullmatch(r"part-[0-9]{3,}\.properties", linked.name)
                    ):
                        source = linked.parent.with_name(
                            linked.parent.name + ".properties"
                        )
                        parts = source.relative_to(base_path).parts
                except ValueError:
                    continue
                if (
                    len(parts) == 3
                    and parts[:2] == (environment, target)
                    and linked.suffix == suffix
                ):
                    services.add(source.stem)
    result.append((number, services))


def unresolved_services(root: Path, path: Path) -> list[tuple[str, set[str]]]:
    """Existing inventories use numbered issues and model/design evidence links."""
    environment, target = path.parent.relative_to(root / "issues").parts
    result = []
    heading = ""
    block = []
    number = ""
    contents, notices = split_notices(input_text(path, encoding="utf-8"))

    lines = markdown_matches(contents, r"^(.*)$")
    for _, _, line in lines:
        if re.match(r"^#{1,3} ", line):
            _callback_unresolved_services_flush(
                block, environment, heading, number, path, result, root, target
            )
            number, block = "", []
            heading = line.removeprefix("### ") if line.startswith("### ") else ""
        elif not number and re.fullmatch(rf"<!-- issue-service: {SERVICE} -->", line):
            heading += "\n" + line
        elif match := re.match(r"^ {0,3}(\d+)[.)] +", line):
            _callback_unresolved_services_flush(
                block, environment, heading, number, path, result, root, target
            )
            number, block = match[1], [line]
        else:
            block.append(line)
    _callback_unresolved_services_flush(
        block, environment, heading, number, path, result, root, target
    )
    substantive = [
        line for _, _, line in lines if line.strip() and not re.match(r"^#{1,3} ", line)
    ]
    if (
        not result
        and contents.strip()
        and "未解決issueなし" not in contents
        and (substantive or not notices)
    ):
        result.append(("unknown", set()))
    return result
