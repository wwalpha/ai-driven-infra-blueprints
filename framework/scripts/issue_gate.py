"""Stop unrelated work on services with unresolved target-local issues."""
from validation_cache import input_is_file, input_select, input_text

import argparse
from pathlib import Path
import re
import sys

from validation_scope import active_scope
from model.files import service_model_path
from task_contract import task_path, contract_path, model_operation, validate_contract, status


SERVICE = r"[a-z0-9]+(?:[-_][a-z0-9]+)*"


def remediation_scope(root: Path, *, task_file=None, contract_file=None) -> set[tuple[str, str, str]]:
    path = contract_path(root, selected=contract_file) if contract_file is not None else task_path(root, selected=task_file)
    if not input_is_file(path):
        return set()
    result = set()
    inside = False
    for line in input_text(path, encoding="utf-8").splitlines():
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
        scope = active_scope(root, task_file=task_file, contract_file=contract_file)
        if scope is None or not result <= scope:
            raise ValueError("Issue remediation must be within explicit service Validation scope")
    return result


def reference_issue_parts(text):
    """Separate only recognized machine diagnostics, keeping mixed real errors blocking."""
    import json
    text = re.sub(r'<!-- issue-(?:id|service): [^>]+ -->', '', text).strip()
    text = re.sub(r'^\d+[.)] +', '', text)
    text = re.sub(r' 根拠: \[[^\]]+\]\([^)]+\)。$', '', text).strip()
    messages = [line.strip().removeprefix('- ') for line in text.splitlines() if line.strip()]
    references, errors = [], []
    exact = {'broken local parentReference', 'cyclic parentReference', 'broken same-service reference',
             'duplicate resource anchor', 'unknown external instance reference', 'unknown instance reference',
             'multiple matching candidates', 'reference producer requires exactly one name',
             'reference producer requires exactly one matching observed identifier',
             'reference producer requires a nonempty non-ARN string identifier', 'invalid reference label',
             'raw name reference cannot override label', 'raw identifier reference cannot override label',
             'reference producer requires a valid stack name',
             'ambiguous/type-mismatched fixed reference target',
             'IMPORT removed resource still has an incoming reference'}
    patterns = (
        r'(?:unknown external instance reference|unknown instance reference|ambiguous/type-mismatched fixed reference target|ambiguous/type-mismatched reference|IMPORT removed resource still has an incoming reference): [^;\n]+',
        r'broken design link: [^\s;]+: (?:[^\s;]*\.md(?:#[^\s;]+)?|#[^\s;]+)',
        r'missing design anchor: [^\s;]+: [^\s;]+',
        r'unresolved internal Model link: [^\s;]+',
        r'ambiguous Resource anchor: [^\s;]+',
        r'cyclic attribute reference: [^;\n]+',
        r'IMPORT (?:ambiguous physical reference|ambiguous producer physical identifier|explicit link differs from acquired physical reference|explicit link has no unique design target|matching Model requires a reference link|explicit reference has no physical identification contract): [^;\n]+',
        r'identifier reference does not match observed target: [^;\n]+',
        r'(?:IAM Role link must display RoleName|design link must not display internal logical ID|nameless resource link must display resource type or observed identifier): [^;\n]+',
    )
    for original in messages:
        message = re.sub(r'^(?:invalid service model|invalid reference observations|invalid IMPORT physical reference): [^\s:]+: ', '', original)
        recognized = message in exact or any(re.fullmatch(pattern, message) for pattern in patterns)
        if message.startswith('unresolved reference target: '):
            try:
                details = json.loads(message.removeprefix('unresolved reference target: '))
            except ValueError:
                details = None
            recognized = isinstance(details, dict) and details.get('reason') in {
                'unknown external instance reference', 'unknown instance reference', 'multiple matching candidates',
                'ambiguous resource/stack reference', 'zero matching candidates: resourceType mismatch',
                'zero candidates: fixed Resource ID absent or Instance has no active Resources'}
        (references if recognized else errors).append(original)
    return references, errors


def reference_issue(text):
    references, errors = reference_issue_parts(text)
    return bool(references) and not errors


def unresolved_services(root: Path, path: Path, *, with_text=False) -> list[tuple[str, set[str]]]:
    """Existing inventories use numbered issues and model/design evidence links."""
    environment, target = path.parent.relative_to(root / "issues").parts
    result = []
    heading = ""
    block = []
    number = ""
    fence = ""
    contents = input_text(path, encoding="utf-8")

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
        result.append((number, services, text) if with_text else (number, services))

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
        result.append(("unknown", set(), contents) if with_text else ("unknown", set()))
    return result


def issue_errors(root: Path, scope, *, remediation=(), target=None, warnings=None) -> list[str]:
    errors = []
    paths = (input_select(root / "issues", "*/*/issues.md") if scope is None else
             (root / "issues" / env / directory / "issues.md" for env, directory in {entry[:2] for entry in scope}))
    for path in sorted(paths):
        if not input_is_file(path):
            continue
        identity = path.parent.relative_to(root / "issues").parts
        if target is not None and identity != target:
            continue
        selected = None if scope is None else {service for env, directory, service in scope if (env, directory) == identity}
        if selected == set():
            continue
        for number, services, text in unresolved_services(root, path, with_text=True):
            reference_messages, blocking = reference_issue_parts(text)
            if warnings is not None:
                warnings.extend({'code': 'reference.legacy_issue', 'message': message,
                                 'source': str(path.relative_to(root)), 'issue': number,
                                 'scope': '/'.join(identity), 'services': sorted(services)} for message in reference_messages)
            if reference_messages and not blocking:
                continue
            if not services:
                errors.append(f"unresolved issue service is ambiguous: {path.relative_to(root)}: issue {number}; stop target work")
                continue
            for service in sorted(services):
                entry = (*identity, service)
                if (selected is None or service in selected) and entry not in remediation:
                    errors.append(f"unresolved issue blocks task: {'/'.join(entry)}: {path.relative_to(root)}: issue {number}; only investigation or explicit Issue remediation is allowed")
    return errors


def task_issue_errors(root: Path, scope, *, target=None, task_file=None, contract_file=None, warnings=None) -> list[str]:
    """Waive only existing issues for a valid, explicitly scoped deletion contract.

    contract_file permits the read-only issue check before a suspended task resumes.
    Model/reference validation and write authorization remain at their own boundaries.
    """
    if task_file is not None and contract_file is not None:
        raise ValueError('select either an executing task or a read-only contract')
    path = contract_path(root, selected=contract_file) if contract_file is not None else task_path(root, selected=task_file)
    if input_is_file(path):
        text = input_text(path, encoding='utf-8')
        from model.migration.contract import migration_contract, require_preserved_inputs
        migration = migration_contract(text)
        if migration is not None:
            declared = {tuple(service.split('/')) for service in migration.services}
            if scope != declared or target is not None:
                raise ValueError('format migration issue preservation requires its exact service scope')
            require_preserved_inputs(root, migration)
            return []  # Existing issues remain unchanged; this proves only a format transition.
        operation = model_operation(text)
        if operation is not None and operation.action == 'import-delete':
            name = path.relative_to(root).as_posix()
            validate_contract(root, name, text)
            declared = active_scope(root, task_file=task_file, contract_file=contract_file)
            if (scope is None or declared is None or not operation.scopes <= declared or
                    not scope <= declared or target is not None and not any(entry[:2] == target for entry in scope)):
                raise ValueError('IMPORT deletion issue exception requires explicit matching service Validation scope')
            if (root / '.git').exists():
                from worktree_task import task_start_commit
                task_start_commit(root, name)
            if status(text) != 'completed':
                remaining = scope - operation.source_scopes
                if not remaining:
                    return []
                return issue_errors(root, remaining, remediation=remediation_scope(root, task_file=task_file, contract_file=contract_file), target=target, warnings=warnings)
    return issue_errors(root, scope, remediation=remediation_scope(root, task_file=task_file, contract_file=contract_file), target=target, warnings=warnings)


def require_no_issues(root: Path, scope, *, target=None, task_file=None, contract_file=None, warnings=None) -> None:
    diagnostics = [] if warnings is None else warnings
    errors = task_issue_errors(root, scope, target=target, task_file=task_file, contract_file=contract_file, warnings=diagnostics)
    if warnings is None:
        from model.core import report_reference_warnings
        report_reference_warnings(diagnostics)
    if errors:
        raise ValueError("\n- ".join(errors))


def require_target_no_issues(root: Path, target: tuple[str, str]) -> None:
    if not input_is_file(root / "issues" / target[0] / target[1] / "issues.md"):
        return
    scope = active_scope(root) if input_is_file(task_path(root)) else None
    if scope is not None and not any(entry[:2] == target for entry in scope):
        scope = None  # An unrelated contract cannot bypass a target's issues.
    require_no_issues(root, scope, target=target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target-directory", required=True)
    parser.add_argument("--service", action="append", required=True)
    parser.add_argument("--task", action="store_true", help="Recheck the selected task, including remediation and validated Model deletion exceptions")
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
        warnings = []
        errors = task_issue_errors(root, scope, warnings=warnings) if args.task else issue_errors(root, scope, warnings=warnings)
        from model.core import report_reference_warnings
        report_reference_warnings(warnings)
    except (OSError, ValueError) as error:
        errors = [str(error)]
    if errors:
        print("Issue gate: FAIL\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print("Issue gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
