"""Gate unresolved target-local issues; Deploy contracts diagnose and report only."""

import argparse
import re
import sys
from pathlib import Path

import model.importing.repository as repository
import validation_scope as _dependency_validation_scope
from issue_inventory import SERVICE
from issue_inventory import unresolved_services as unresolved_services
from task_contract_core import (
    TaskSnapshot,
    issue_remediation_scope,
    model_operation,
    section,
    status,
    task_read_scope,
    task_snapshot,
    validate_contract,
)
from utils.input_cache import input_is_file, input_select


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
    validate_contract(root, snapshot.name, snapshot.text, check_paths=False)
    return set(issue_remediation_scope(snapshot.text))


def _issue_diagnostics(root, scope, *, remediation=(), target=None, tolerant=False):
    issues, failures = [], []
    paths = (
        input_select(root / "issues", "*/*/issues.md")
        if scope is None
        else (
            root / "issues" / env / directory / "issues.md"
            for env, directory in {entry[:2] for entry in scope}
        )
    )
    for path in sorted(paths):
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
        try:
            if not input_is_file(path):
                continue
            records = unresolved_services(root, path)
        except Exception as error:
            if not tolerant:
                raise
            failures.append(
                f"{path.relative_to(root)}: {type(error).__name__}: {error}"
            )
            continue
        for number, services in records:
            affected = {
                service
                for service in services
                if (selected is None or service in selected)
                and (*identity, service) not in remediation
            }
            if affected or not services:
                issues.append((path.relative_to(root), number, affected))
    return issues, failures


def issue_errors(root: Path, scope, *, remediation=(), target=None) -> list[str]:
    issues, _ = _issue_diagnostics(root, scope, remediation=remediation, target=target)
    errors = []
    for path, number, services in issues:
        if not services:
            errors.append(
                f"unresolved issue service is ambiguous: {path}: issue {number}; stop target work"
            )
        for service in sorted(services):
            entry = (*path.parent.parts[1:], service)
            errors.append(
                f"unresolved issue blocks task: {'/'.join(entry)}: {path}: issue {number}; only investigation or explicit Issue remediation is allowed"
            )
    return errors


def _deploy_policy(root, snapshot, scope, target):
    if snapshot is None:
        return False
    validate_contract(root, snapshot.name, snapshot.text, check_paths=False)
    lines = section(snapshot.text, "## Task contract")
    types = [line for line in lines if line.startswith("- Task type:")]
    phases = [line for line in lines if line.startswith("- Infrastructure phase:")]
    if not phases and types != ["- Task type: `infrastructure`"]:
        return False
    if (
        types != ["- Task type: `infrastructure`"]
        or len(phases) != 1
        or phases[0]
        not in {
            f"- Infrastructure phase: `{phase}`"
            for phase in ("implement", "deploy", "update", "destroy")
        }
    ):
        raise ValueError(
            "Issue Gate requires exactly one valid infrastructure Task type/phase"
        )
    if phases != ["- Infrastructure phase: `deploy`"]:
        return False
    declared = snapshot.scope
    if (
        not declared
        or scope is None
        or not scope
        or not scope <= declared
        or target is not None
        and not any(entry[:2] == target for entry in scope)
    ):
        raise ValueError(
            "Deploy Issue Gate requires explicit matching service Validation scope"
        )
    return True


def print_warning(message):
    print(message, file=sys.stderr)


@task_read_scope
def task_issue_errors(
    root: Path,
    scope,
    *,
    target=None,
    task_file=None,
    contract_file=None,
    snapshot: TaskSnapshot | None = None,
    warn=None,
) -> list[str]:
    """Apply validated Deploy reporting or the existing scoped Model deletion exception.

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
    if _deploy_policy(root, snapshot, scope, target):
        try:
            issues, failures = _issue_diagnostics(
                root, scope, target=target, tolerant=True
            )
        except Exception as error:
            issues, failures = [], [f"{type(error).__name__}: {error}"]
        if warn is not None and (issues or failures):
            details = [
                f"{path}: issue {number}; services: {', '.join(sorted(services)) or 'unknown'}"
                for path, number, services in issues
            ]
            warn(
                "Deploy Issue Gate: WARNING (non-blocking)\n"
                + "Scope: "
                + ", ".join("/".join(entry) for entry in sorted(scope))
                + "\n"
                + f"Unresolved issues: {len(issues)}\nIssue diagnostics failures: {len(failures)}\n"
                + "\n".join([*details, *failures, "Deploy continues."])
            )
        return []
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
    warn=None,
) -> None:
    errors = task_issue_errors(
        root,
        scope,
        target=target,
        task_file=task_file,
        contract_file=contract_file,
        snapshot=snapshot,
        warn=warn,
    )
    if errors:
        raise ValueError("\n- ".join(errors))


@task_read_scope
def require_target_no_issues(
    root: Path,
    target: tuple[str, str],
    *,
    snapshot: TaskSnapshot | None = None,
    warn=None,
) -> None:
    try:
        if not input_is_file(root / "issues" / target[0] / target[1] / "issues.md"):
            return
    except Exception:
        pass  # The common policy classifies diagnostic failures after Task validation.
    snapshot = snapshot or task_snapshot(root, required=False)
    scope = snapshot.scope if snapshot is not None else None
    if scope is not None and not any(entry[:2] == target for entry in scope):
        _deploy_policy(root, snapshot, scope, target)
        scope = None  # An unrelated contract cannot bypass a target's issues.
    require_no_issues(root, scope, target=target, snapshot=snapshot, warn=warn)


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
    warnings = []
    try:
        if args.task:
            contract = _dependency_validation_scope.active_scope(root)
            if contract is not None and not scope <= contract:
                raise ValueError(
                    "requested services are outside active task validation scope"
                )
        errors = (
            task_issue_errors(root, scope, warn=warnings.append)
            if args.task
            else issue_errors(root, scope)
        )
    except (OSError, ValueError) as error:
        errors = [str(error)]
    if errors:
        print("Issue gate: FAIL\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    if warnings:
        print_warning("\n".join(warnings))
    else:
        print("Issue gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
