"""Stop unrelated work on services with unresolved target-local issues."""

import argparse
from pathlib import Path
import re
import sys

from validation_scope import active_scope
from model_files import service_model_path
from task_contract import task_path


SERVICE = r"[a-z0-9]+(?:[-_][a-z0-9]+)*"


def remediation_scope(root: Path) -> set[tuple[str, str, str]]:
    path = task_path(root)
    if not path.is_file():
        return set()
    result = set()
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line == "## Issue remediation"
        elif inside and line.strip():
            match = re.fullmatch(rf"- `({SERVICE})/({SERVICE})/({SERVICE})`", line)
            if not match:
                raise ValueError(f"invalid Issue remediation entry: {line}")
            entry = match.groups()
            if entry in result:
                raise ValueError("duplicate Issue remediation entry")
            result.add(entry)
    if result:
        scope = active_scope(root)
        if scope is None or not result <= scope:
            raise ValueError("Issue remediation must be within explicit service Validation scope")
    return result


def unresolved_services(root: Path, path: Path) -> list[tuple[str, set[str]]]:
    """Existing inventories use numbered issues and model/design evidence links."""
    environment, target = path.parent.relative_to(root / "issues").parts
    result = []
    heading = ""
    block = []
    number = ""
    fence = ""
    contents = path.read_text(encoding="utf-8")

    def flush():
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
                        source = service_model_path(linked, base_path) if base == "model" else linked
                        parts = source.relative_to(base_path).parts
                    except ValueError:
                        continue
                    if len(parts) == 3 and parts[:2] == (environment, target) and linked.suffix == suffix:
                        services.add(source.stem)
        result.append((number, services))

    for line in contents.splitlines():
        if match := re.match(r"^\s*(`{3,}|~{3,})", line):
            if not fence:
                fence = match[1][0]
            elif match[1][0] == fence:
                fence = ""
            continue
        if fence:
            continue
        if re.match(r"^#{1,3} ", line):
            flush()
            number, block = "", []
            heading = line.removeprefix("### ") if line.startswith("### ") else ""
        elif not number and re.fullmatch(rf"<!-- issue-service: {SERVICE} -->", line):
            heading += "\n" + line
        elif match := re.match(r"^ {0,3}(\d+)[.)] +", line):
            flush()
            number, block = match[1], [line]
        else:
            block.append(line)
    flush()
    if not result and contents.strip() and "未解決issueなし" not in contents:
        result.append(("unknown", set()))
    return result


def issue_errors(root: Path, scope, *, remediation=(), target=None) -> list[str]:
    errors = []
    for path in sorted((root / "issues").glob("*/*/issues.md")):
        identity = path.parent.relative_to(root / "issues").parts
        if target is not None and identity != target:
            continue
        selected = None if scope is None else {service for env, directory, service in scope if (env, directory) == identity}
        if selected == set():
            continue
        for number, services in unresolved_services(root, path):
            if not services:
                errors.append(f"unresolved issue service is ambiguous: {path.relative_to(root)}: issue {number}; stop target work")
                continue
            for service in sorted(services):
                entry = (*identity, service)
                if (selected is None or service in selected) and entry not in remediation:
                    errors.append(f"unresolved issue blocks task: {'/'.join(entry)}: {path.relative_to(root)}: issue {number}; only investigation or explicit Issue remediation is allowed")
    return errors


def require_no_issues(root: Path, scope, *, target=None) -> None:
    errors = issue_errors(root, scope, remediation=remediation_scope(root), target=target)
    if errors:
        raise ValueError("\n- ".join(errors))


def require_target_no_issues(root: Path, target: tuple[str, str]) -> None:
    if not (root / "issues" / target[0] / target[1] / "issues.md").is_file():
        return
    scope = active_scope(root) if task_path(root).is_file() else None
    if scope is not None and not any(entry[:2] == target for entry in scope):
        scope = None  # An unrelated contract cannot bypass a target's issues.
    require_no_issues(root, scope, target=target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target-directory", required=True)
    parser.add_argument("--service", action="append", required=True)
    parser.add_argument("--task", action="store_true", help="Recheck the current task, including explicit remediation scope")
    args = parser.parse_args()
    if any(not re.fullmatch(SERVICE, value) for value in [args.environment, args.target_directory, *args.service]):
        parser.error("invalid environment/target/service")
    scope = {(args.environment, args.target_directory, service) for service in args.service}
    root = args.repository_root.resolve()
    try:
        if args.task:
            contract = active_scope(root)
            if contract is not None and not scope <= contract:
                raise ValueError("requested services are outside active task validation scope")
        errors = issue_errors(root, scope, remediation=remediation_scope(root) if args.task else ())
    except (OSError, ValueError) as error:
        errors = [str(error)]
    if errors:
        print("Issue gate: FAIL\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print("Issue gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
