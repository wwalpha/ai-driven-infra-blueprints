"""Stop unrelated work on services with unresolved target-local issues."""

import argparse
import re
import sys
from pathlib import Path

import model.files as _dependency_model_files
import model.importing.repository as repository
import validation_scope as _dependency_validation_scope
from issue_markdown import markdown_matches, split_notices
from task_contract_core import (
    TaskSnapshot,
    model_operation,
    status,
    task_read_scope,
    task_snapshot,
    validate_contract,
)
from utils.input_cache import input_is_file, input_select, input_text

SERVICE = r"[a-z0-9]+(?:[-_][a-z0-9]+)*"


@task_read_scope
def remediation_scope(
    root: Path,
    *,
    task_file=None,
    contract_file=None,
    snapshot: TaskSnapshot | None = None,
) -> set[tuple[str, str, str]]:
    snapshot = snapshot or task_snapshot(
        root,
        contract_file or task_file,
        required=False,
        executable=contract_file is None,
    )
    if snapshot is None:
        return set()
    result = set()
    inside = False
    for line in snapshot.text.splitlines():
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
        scope = snapshot.scope
        if scope is None or not result <= scope:
            raise ValueError(
                "Issue remediation must be within explicit service Validation scope"
            )
    return result


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
                    source = (
                        _dependency_model_files.service_model_path(linked, base_path)
                        if base == "model"
                        else linked
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


def issue_errors(root: Path, scope, *, remediation=(), target=None) -> list[str]:
    errors = []
    paths = (
        input_select(root / "issues", "*/*/issues.md")
        if scope is None
        else (
            root / "issues" / env / directory / "issues.md"
            for env, directory in {entry[:2] for entry in scope}
        )
    )
    for path in sorted(paths):
        if not input_is_file(path):
            continue
        identity = path.parent.relative_to(root / "issues").parts
        if target is not None and identity != target:
            continue
        selected = (
            None
            if scope is None
            else {
                service
                for env, directory, service in scope
                if (env, directory) == identity
            }
        )
        if selected == set():
            continue
        for number, services in unresolved_services(root, path):
            if not services:
                errors.append(
                    f"unresolved issue service is ambiguous: {path.relative_to(root)}: issue {number}; stop target work"
                )
                continue
            for service in sorted(services):
                entry = (*identity, service)
                if (
                    selected is None or service in selected
                ) and entry not in remediation:
                    errors.append(
                        f"unresolved issue blocks task: {'/'.join(entry)}: {path.relative_to(root)}: issue {number}; only investigation or explicit Issue remediation is allowed"
                    )
    return errors


@task_read_scope
def task_issue_errors(
    root: Path,
    scope,
    *,
    target=None,
    task_file=None,
    contract_file=None,
    snapshot: TaskSnapshot | None = None,
) -> list[str]:
    """Waive existing issues only for explicit scoped deletion/identity rewrite contracts.

    contract_file permits the read-only issue check before a suspended task resumes.
    Model/reference validation and write authorization remain at their own boundaries.
    """
    if task_file is not None and contract_file is not None:
        raise ValueError("select either an executing task or a read-only contract")
    snapshot = snapshot or task_snapshot(
        root,
        contract_file or task_file,
        required=False,
        executable=contract_file is None,
    )
    if snapshot is not None and snapshot.root != root:
        raise ValueError("task snapshot belongs to another repository")
    if snapshot is not None:
        text = snapshot.text
        operation = model_operation(text)
        if operation is not None and operation.action == "import-delete":
            name = snapshot.name
            validate_contract(root, name, text)
            declared = snapshot.scope
            if (
                scope is None
                or declared is None
                or not operation.scopes <= declared
                or not scope <= declared
                or target is not None
                and not any(entry[:2] == target for entry in scope)
            ):
                raise ValueError(
                    "IMPORT deletion issue exception requires explicit matching service Validation scope"
                )
            if (root / ".git").exists():
                task_start_commit = repository.task_start_commit
                task_start_commit(root, name)
            if status(text) != "completed":
                remaining = scope - operation.source_scopes
                if not remaining:
                    return []
                return issue_errors(
                    root,
                    remaining,
                    remediation=remediation_scope(
                        root,
                        task_file=task_file,
                        contract_file=contract_file,
                        snapshot=snapshot,
                    ),
                    target=target,
                )
    return issue_errors(
        root,
        scope,
        remediation=remediation_scope(
            root, task_file=task_file, contract_file=contract_file, snapshot=snapshot
        ),
        target=target,
    )


@task_read_scope
def require_no_issues(
    root: Path,
    scope,
    *,
    target=None,
    task_file=None,
    contract_file=None,
    snapshot: TaskSnapshot | None = None,
) -> None:
    errors = task_issue_errors(
        root,
        scope,
        target=target,
        task_file=task_file,
        contract_file=contract_file,
        snapshot=snapshot,
    )
    if errors:
        raise ValueError("\n- ".join(errors))


@task_read_scope
def require_target_no_issues(
    root: Path, target: tuple[str, str], *, snapshot: TaskSnapshot | None = None
) -> None:
    if not input_is_file(root / "issues" / target[0] / target[1] / "issues.md"):
        return
    snapshot = snapshot or task_snapshot(root, required=False)
    scope = snapshot.scope if snapshot is not None else None
    if scope is not None and not any(entry[:2] == target for entry in scope):
        scope = None  # An unrelated contract cannot bypass a target's issues.
    require_no_issues(root, scope, target=target, snapshot=snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().resolve())
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target-directory", required=True)
    parser.add_argument("--service", action="append", required=True)
    parser.add_argument(
        "--task",
        action="store_true",
        help="Recheck the selected task, including remediation and validated Model deletion exceptions",
    )
    args = parser.parse_args()
    if any(
        not re.fullmatch(SERVICE, value)
        for value in [args.environment, args.target_directory, *args.service]
    ):
        parser.error("invalid environment/target/service")
    scope = {
        (args.environment, args.target_directory, service) for service in args.service
    }
    root = args.repository_root.resolve()
    try:
        if args.task:
            contract = _dependency_validation_scope.active_scope(root)
            if contract is not None and not scope <= contract:
                raise ValueError(
                    "requested services are outside active task validation scope"
                )
        errors = (
            task_issue_errors(root, scope) if args.task else issue_errors(root, scope)
        )
    except (OSError, ValueError) as error:
        errors = [str(error)]
    if errors:
        print("Issue gate: FAIL\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print("Issue gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
