#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from contextlib import nullcontext
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import import_guard
import issue_gate
import pytest
import sync_runtime
import task_contract as tasks
from issue_gate import remediation_scope
from issues.publication import save
from model.sources import load_model
from support.import_model_fixtures import dependency_fixture, operation_contract
from support.issue_gate_fixtures import (
    Path,
    issue_errors,
    json,
    mock,
    require_no_issues,
    subprocess,
    sys,
)
from support.model_sources import write_model
from support.validator import MODULE as validator
from utils.script_loader import module
from validation.findings import Findings
from validation.task import TaskValidation
from validation_scope import active_scope

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_report_commit_independence_git(tmp_path, /, *args):
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            *args,
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize("kind", ["reports", "migration", "design"])
def check_report_commit_independence(tmp_path, monkeypatch, kind):
    name = "tasks/investigation.md"
    reports = {"issues/dev/cde/issues.md", "issues/dev/cde/iac-issues.md"}
    permitted = reports | {name}
    text = (
        "## Task contract\n- Task type: `"
        + ("design" if kind == "design" else "migration")
        + "`\n- Task status: `running`\n## Validation scope\n- `dev/cde/s3`\n"
        "## Required changes\n- [R1] Save reports\n## Acceptance checks\n"
        + "".join(f"- [R1] `exists:{path}`\n" for path in sorted(reports))
        + "## Modified files\n"
        + "".join(f"- `{path}`\n" for path in sorted(permitted))
        + "## Allowed paths\n"
        + "".join(f"- `{path}`\n" for path in sorted(permitted))
    )
    if kind == "migration":
        text += "- `infra/**`\n"  # An ordinary migration must retain its Git baseline.
    git = _bind_framework_callback(
        _callback_check_report_commit_independence_git, tmp_path
    )
    git("init", "--quiet", "--initial-branch=master")
    for path in reports | {"outside.txt"}:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("")
    git("add", ".")
    git("commit", "--quiet", "-m", "initial")
    baseline = git("rev-parse", "HEAD")
    tasks.start(tmp_path, name, text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    findings = Findings(tmp_path)
    task = TaskValidation(tmp_path, findings)
    with mock.patch(
        "model.importing.repository.task_start_commit", return_value=baseline
    ) as start:
        task.fix_baseline()
        assert start.call_count == (0 if kind == "reports" else 1)
        git("commit", "--quiet", "--allow-empty", "-m", "advance HEAD")
        if kind == "reports":
            save(tmp_path, "dev", "cde", ["s3"], iac=[])
        else:
            for path in reports:
                (tmp_path / path).write_text("ordinary Task change")
        task.check_task_scope()
        assert not findings.errors, findings.errors
        (tmp_path / "committed.txt").write_text("unrelated committed input")
        git("add", "committed.txt")
        git("commit", "--quiet", "-m", "unrelated change")
        assert git("rev-parse", "HEAD") != baseline
        task.check_task_scope()
    assert active_scope(tmp_path) == {("dev", "cde", "s3")}
    assert (tmp_path / name).read_text() == text  # No suspension or replacement Task.
    for state in ("unstaged", "staged", "untracked"):
        outside = tmp_path / (
            "untracked.txt" if state == "untracked" else "outside.txt"
        )
        outside.write_text(state)
        if state == "staged":
            git("add", "outside.txt")
            outside.write_text("")
        blocked = TaskValidation(tmp_path, Findings(tmp_path))
        blocked.check_task_scope()
        if kind == "reports":
            assert not blocked.findings.errors, blocked.findings.errors
            assert blocked.changed_paths == blocked.scope_paths == set()
        else:
            assert any(
                f"outside task scope: {outside.name}" in error
                for error in blocked.findings.errors
            )
    (tmp_path / "outside.txt").write_text("")
    git("add", "outside.txt")
    (tmp_path / "untracked.txt").unlink()
    if kind != "reports":
        assert any(
            "outside task scope: committed.txt" in error for error in findings.errors
        )
        assert "committed.txt" in task.changed_paths and task.baseline == baseline
        return
    assert not findings.errors, findings.errors
    assert task.changed_paths == task.scope_paths == set()
    task.check_issue_gate()
    task.check_acceptance_checks({})
    assert not findings.errors, findings.errors
    # Preserve independent index changes, including a file restored only in the worktree.
    git("add", "issues/dev/cde/issues.md")
    (tmp_path / "issues/dev/cde/issues.md").write_text("")
    assert task.final_paths() == set()
    task.check_task_scope()
    assert not findings.errors, findings.errors
    with mock.patch(
        "model.importing.repository.task_start_commit",
        side_effect=AssertionError("report completion used a baseline"),
    ):
        tasks.complete(tmp_path, name)
    assert tasks.status((tmp_path / name).read_text()) == "completed"


@pytest.fixture
def deletion_gate(tmp_path, monkeypatch):
    name = "tasks/deletion.md"
    text = (
        operation_contract("import-delete")
        + "## Validation scope\n- `stg/cde/vpc`\n"
        + f"## Modified files\n- `{name}`\n## Allowed paths\n- `{name}`\n"
    )
    tasks.start(tmp_path, name, text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    issues = tmp_path / "issues/stg/cde/issues.md"
    issues.parent.mkdir(parents=True)
    issues.write_text("### vpc\n1. 既存のIssue\n", encoding="utf-8")
    return tmp_path / name, text, issues, {("stg", "cde", "vpc")}


def check_deletion_gate_and_task_validation(deletion_gate):
    path, text, issues, scope = deletion_gate
    root = path.parent.parent
    original = issues.read_bytes()
    for content in (original.decode("utf-8"), "### unknown service\n1. 既存のIssue\n"):
        issues.write_text(content, encoding="utf-8")
        assert issue_errors(root, scope), (
            "inventory analysis must still report unresolved issues"
        )
        require_no_issues(root, scope)
        findings = Findings(root)
        task = TaskValidation(root, findings)
        task.task_type = "design"
        task.check_issue_gate()
        assert not findings.errors
    issues.write_bytes(original)
    assert path.read_text() == text and issues.read_bytes() == original


@pytest.mark.parametrize("kind", ["merge", "update", "deploy", "completed", "missing"])
def check_ordinary_issue_gate_restored(deletion_gate, kind):
    path, text, issues, scope = deletion_gate
    if kind == "merge":
        text = text.replace("`import-delete`", "`import-merge`").replace(
            "## Model delete sources\n- `stg/cde/vpc/009`",
            "## Model merge pairs\n- "
            + json.dumps(
                {"source": "stg/cde/vpc/009", "destination": "stg/cde/vpc/001"}
            ),
        )
    elif kind in {"update", "deploy"}:
        text = text.replace("- Model operation: `import-delete`\n", "").replace(
            "## Model delete sources\n- `stg/cde/vpc/009`\n", ""
        )
        if kind == "deploy":
            text = text.replace(
                "- Task type: `design`",
                "- Task type: `infrastructure`\n- Infrastructure phase: `deploy`",
            )
    elif kind == "completed":
        text = tasks.set_status(text, "completed")
    else:
        path.unlink()
    if kind != "missing":
        path.write_text(text)
    with pytest.raises(ValueError):
        require_no_issues(path.parent.parent, scope)


@pytest.mark.parametrize(
    "old,new",
    [
        ("`design`", "`infrastructure`"),
        ("`update`", "`import`"),
        ("- `stg/cde/vpc/009`", "- `009`"),
        ("- AWS API execution: `forbidden`", "- AWS API execution: `allowed`"),
        ("- deploy/apply: `forbidden`", "- deploy/apply: `allowed`"),
        ("`import-delete`", "`unknown`"),
        ("## Modified files", "## Missing files"),
        ("- `stg/cde/vpc`", "- `stg/cde/ec2`"),
        ("- `stg/cde/vpc`", "- `all`"),
    ],
)
def check_deletion_contract_fail_closed(deletion_gate, old, new):
    path, text, issues, scope = deletion_gate
    path.write_text(text.replace(old, new))
    with pytest.raises(ValueError):
        require_no_issues(path.parent.parent, scope)


@pytest.mark.parametrize(
    "scope,target",
    [
        (None, None),
        ({("dev", "cde", "vpc")}, None),
        ({("stg", "cde", "vpc"), ("stg", "cde", "ec2")}, None),
        ({("stg", "cde", "vpc")}, ("dev", "cde")),
    ],
)
def check_deletion_scope_fail_closed(deletion_gate, scope, target):
    path, text, issues, _ = deletion_gate
    with pytest.raises(ValueError, match="matching service Validation scope"):
        require_no_issues(path.parent.parent, scope, target=target)


def check_deletion_task_selection(deletion_gate):
    path, text, issues, scope = deletion_gate
    root = path.parent.parent
    other = "tasks/ordinary.md"
    tasks.start(
        root,
        other,
        text.replace("tasks/deletion.md", other)
        .replace("- Model operation: `import-delete`\n", "")
        .replace("## Model delete sources\n- `stg/cde/vpc/009`\n", ""),
    )
    with (
        tasks.selected_task(root, other),
        pytest.raises(ValueError, match="unresolved issue"),
    ):
        require_no_issues(root, scope)


def check_remediation_still_requires_explicit_scope(deletion_gate):
    path, text, issues, scope = deletion_gate
    root = path.parent.parent
    ordinary = text.replace("- Model operation: `import-delete`\n", "").replace(
        "## Model delete sources\n- `stg/cde/vpc/009`\n", ""
    )
    path.write_text(ordinary + "## Issue remediation\n- `stg/cde/vpc`\n")
    require_no_issues(root, scope)
    assert issue_errors(root, scope)
    path.write_text(ordinary + "## Issue remediation\n- `stg/cde/ec2`\n")
    with pytest.raises(ValueError, match="within explicit service Validation scope"):
        require_no_issues(root, scope)


@pytest.mark.parametrize("use_task", [False, True])
def check_deletion_cli_requires_task_opt_in(deletion_gate, use_task):
    path, text, issues, scope = deletion_gate
    args = [
        "issue_gate.py",
        "--repository-root",
        str(path.parent.parent),
        "--environment",
        "stg",
        "--target-directory",
        "cde",
        "--service",
        "vpc",
    ] + (["--task"] if use_task else [])
    with mock.patch.object(sys, "argv", args):
        assert issue_gate.main() == (0 if use_task else 1)


@pytest.mark.parametrize("deletion", [False, True])
def check_resume_issue_gate(deletion_gate, deletion):
    path, text, issues, scope = deletion_gate
    root, name = path.parent.parent, path.relative_to(path.parent.parent).as_posix()
    if not deletion:
        text = text.replace("`import-delete`", "`import-merge`").replace(
            "## Model delete sources\n- `stg/cde/vpc/009`",
            "## Model merge pairs\n- "
            + json.dumps(
                {"source": "stg/cde/vpc/009", "destination": "stg/cde/vpc/001"}
            ),
        )
        path.write_text(text)
    tasks.suspend(root, name, "explicit test stop")
    if deletion:
        tasks.resume(root, name)
        assert tasks.status(path.read_text()) == "running"
    else:
        with pytest.raises(ValueError, match="unresolved issue"):
            tasks.resume(root, name)
        assert tasks.status(path.read_text()) == "suspend"


@pytest.fixture
def generation_model(tmp_path, monkeypatch):
    dependency_fixture(tmp_path)
    model = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(model).authoritative)
    issues = tmp_path / "issues/stg/cde/issues.md"
    issues.parent.mkdir(parents=True)
    issues.write_text("### service-b\n1. 既存のIssue\n", encoding="utf-8")
    git = _bind_framework_callback(
        _callback_check_report_commit_independence_git, tmp_path
    )
    git("init", "--quiet", "--initial-branch=master")
    git("add", ".")
    git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "initial")
    name = "tasks/generation.md"
    sources = {p.relative_to(tmp_path).as_posix() for p in load_model(model).files}
    listed = "".join(f"- `{p}`\n" for p in sorted(sources | {name}))
    text = (
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
        "- Workflow: `update`\n## Validation scope\n"
        "- `stg/cde/service-a`\n- `stg/cde/service-b`\n"
        "## Modified files\n" + listed + "## Allowed paths\n" + listed
    )
    tasks.start(tmp_path, name, text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    values["display.resource.002.comment"] = "生成対象の変更"
    write_model(model, values)
    changed = import_guard.changed_sources(tmp_path)
    assert changed and changed <= sources
    assert set(git("diff", "--name-only").splitlines()) == changed
    return tmp_path / name, model, values, issues


@pytest.mark.parametrize("entrypoint", ["cli", "runtime"])
@pytest.mark.parametrize(
    "inventory",
    [
        "### service-b\n1. 既存のIssue\n",
        "### s3\n1. 他サービスのIssue\n",
        "所有不明のIssue",
        "未解決issueなし",
    ],
)
def check_generation_ignores_issues(generation_model, entrypoint, inventory):
    path, model, values, issues = generation_model
    root = path.parent.parent
    scope = {("stg", "cde", service) for service in ("service-a", "service-b")}
    issues.write_text(inventory, encoding="utf-8")
    original = issues.read_bytes()
    runner = module("sync-model.py", "issue_gate_sync_cli")
    with (
        mock.patch.object(sync_runtime, "run_generation", return_value=0) as generate,
        mock.patch.object(runner, "run_generation", generate),
        mock.patch.object(runner, "generation_context", return_value=nullcontext()),
    ):
        if entrypoint == "cli":
            assert (
                runner.run(
                    [
                        "--write",
                        "--scope",
                        "stg/cde/service-a",
                        "--scope",
                        "stg/cde/service-b",
                    ],
                    repository_root=root,
                )[0]
                == 0
            )
        else:
            assert (
                sync_runtime._sync(root, True, "stg", "cde", ["service-a", "service-b"])
                == 0
            )
        assert generate.call_args.args[:2] == (root, scope)
        generate.side_effect = ValueError("new candidate validation error")
        if entrypoint == "cli":
            code, diagnostic = runner.run(
                [
                    "--write",
                    "--scope",
                    "stg/cde/service-a",
                    "--scope",
                    "stg/cde/service-b",
                ],
                repository_root=root,
            )
            assert code == 1 and "new candidate validation error" in diagnostic
        else:
            with pytest.raises(ValueError, match="new candidate validation error"):
                sync_runtime._sync(root, True, "stg", "cde", ["service-a", "service-b"])
    assert issues.read_bytes() == original


@pytest.mark.parametrize("failure", ["issue", "allowed", "scope", "reference"])
def check_generation_preserves_model_guards(generation_model, failure):
    path, model, values, issues = generation_model
    root = path.parent.parent
    original = issues.read_bytes()
    if failure == "allowed":
        path.write_text(
            path.read_text(encoding="utf-8").split("## Allowed paths")[0]
            + f"## Allowed paths\n- `{path.relative_to(root).as_posix()}`\n",
            encoding="utf-8",
        )
        diagnostic = "Modified file is outside Allowed paths"
    elif failure == "scope":
        path.write_text(
            path.read_text(encoding="utf-8").replace("- `stg/cde/service-b`\n", ""),
            encoding="utf-8",
        )
        diagnostic = "Model changes require all affected services in Validation scope"
    elif failure == "reference":
        values["desired.reference.origin.producerLogicalId"] = "ServiceA_Resource_999"
        write_model(model, values)
        diagnostic = "invalid candidate reference"
    else:
        diagnostic = "unresolved issue"
    with pytest.raises(ValueError, match=diagnostic):
        import_guard.require_import_changes(root, generation=failure != "issue")
    assert issues.read_bytes() == original


def check_remediation_model_save_and_real_diff(generation_model):
    path, model, values, issues = generation_model
    root = path.parent.parent
    text = (
        path.read_text(encoding="utf-8").replace(
            "- Workflow: `update`\n",
            "- Workflow: `update`\n- AWS API execution: `forbidden`\n"
            "- deploy/apply: `forbidden`\n",
        )
        + "## Issue remediation\n- `stg/cde/service-b`\n"
    )
    path.write_text(text, encoding="utf-8")
    import_guard.require_import_changes(root)
    assert issues.read_text(encoding="utf-8") == "### service-b\n1. 既存のIssue\n"
    forbidden = root / "framework/rules/example.md"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text("outside remediation authority\n", encoding="utf-8")
    task = TaskValidation(root, Findings(root))
    task.check_task_scope()
    assert any(
        "Issue remediation forbidden path: framework/rules/example.md" in error
        for error in task.findings.errors
    )
    with pytest.raises(ValueError, match="Issue remediation forbidden path"):
        tasks.complete(root, path.relative_to(root).as_posix())


def check_inventory_parser(tmp_path):
    root = tmp_path
    scope = {("dev", "cde", "ec2")}
    scope = {("dev", "cde", "ec2")}
    assert not issue_errors(root, scope)
    path = root / "issues/dev/cde/issues.md"
    path.parent.mkdir(parents=True)
    original = "# 問題一覧\n\n## dev／cde\n\n### Amazon EC2\n\n1. 不正な設定。根拠: [ec2.properties:1](../../../model/dev/cde/ec2.properties)。\n\n```text\n1. 診断のcode例\n### fake\n```\n"
    path.write_text(original)
    assert len(issue_errors(root, scope)) == 1
    assert not issue_errors(root, {("prod", "cde", "ec2")})
    assert not issue_errors(root, {("dev", "non-cde", "ec2")})
    assert not issue_errors(root, {("dev", "cde", "s3")})
    assert not issue_errors(root, set())
    assert issue_errors(root, None)
    path.write_text(
        "### Amazon EC2\n<!-- issue-service: ec2 -->\n\n1. 設定不足\n\n2. 参照不足\n"
    )
    assert len(issue_errors(root, scope)) == 2
    path.write_text(
        "### ec2\n\n1. 設定不足。参照先: [s3](../../../docs/designs/dev/cde/s3.md)。\n"
    )
    assert issue_errors(root, scope)
    assert not issue_errors(
        root, {("dev", "cde", "s3")}
    )  # Explicit ownership wins over references.
    path.write_text("### Unknown service\n\n1. 設定不足\n")
    assert "ambiguous" in issue_errors(root, {("dev", "cde", "s3")})[0]
    assert issue_errors(
        root, scope, remediation=scope
    )  # Unknown ownership cannot be waived.
    path.write_text("設定不足\n")
    assert issue_errors(root, scope)
    path.write_text("# 問題一覧\n\n未解決issueなし\n")
    assert not issue_errors(root, scope)
    path.write_text("")
    assert not issue_errors(root, scope)
    (path.parent / "diff.md").write_text("### ec2\n\n1. 環境間の差分\n")
    assert not issue_errors(
        root, scope
    )  # Differences never enter the unresolved issue inventory.
    for contents in ("### ec2\n1. 差分\n", "invalid inventory; 999 differences", ""):
        (path.parent / "iac-issues.md").write_text(contents)
        assert not issue_errors(root, scope)
    path.write_text(original)
    assert issue_errors(root, scope)

    assert not issue_errors(root, {("dev", "cde", "s3")})


def check_investigation_report_conditions(tmp_path):
    root = tmp_path
    path = root / "issues/dev/cde/issues.md"
    path.parent.mkdir(parents=True)
    original = "# 問題一覧\n\n## dev／cde\n\n### Amazon EC2\n\n1. 不正な設定。根拠: [ec2.properties:1](../../../model/dev/cde/ec2.properties)。\n\n```text\n1. 診断のcode例\n### fake\n```\n"
    path.write_text(original)

    active = root / "tasks/example.md"
    active.parent.mkdir()
    contract = "## Task contract\n\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n\n## Validation scope\n\n- `dev/cde/ec2`\n"
    for name in ("issues.md", "iac-issues.md"):
        report = f"issues/dev/cde/{name}"
        investigation = contract.replace(
            "Task type: `design`", "Task type: `migration`"
        ).split("## Modified files")[0] + (
            "## Modified files\n- `tasks/example.md`\n"
            + f"- `{report}`\n## Validation scope\n- `dev/cde/ec2`\n"
            + f"\n## Allowed paths\n\n- `tasks/example.md`\n- `{report}`\n"
        )
        active.write_text(investigation)
        instance = validator.Validator(root)
        instance.task_type = "migration"
        instance.changed_paths = {"tasks/example.md", report}
        instance.check_issue_gate()
        assert not instance.errors  # Report saving does not require issue remediation.
        path.write_text("### Unknown service\n\n1. 調査中\n")
        instance.check_issue_gate()
        assert (
            not instance.errors
        )  # Unknown ownership must not prevent recording the investigation.
        path.write_text(original)
        for task_type, allowed, changed in (
            ("design", investigation, report),
            ("infrastructure", investigation, report),
            ("migration", investigation, "model/dev/cde/ec2.properties"),
            ("migration", investigation + "- `infra/**`\n", report),
            ("migration", investigation, "infra/dev/cde/ec2.yaml"),
            ("migration", investigation, f"issues/prod/cde/{name}"),
            (
                "migration",
                investigation.replace("## Validation scope", "## Missing scope"),
                report,
            ),
            ("migration", investigation.replace("dev/cde/ec2", "all"), report),
            (
                "migration",
                investigation.replace(report, f"issues/prod/cde/{name}"),
                report,
            ),
        ):
            active.write_text(allowed)
            instance = validator.Validator(root)
            instance.task_type, instance.changed_paths = task_type, {changed}
            instance.check_issue_gate()
            assert instance.errors, (task_type, allowed, changed)


def check_remediation_scope_inputs(tmp_path):
    root = tmp_path
    active = root / "tasks/example.md"
    active.parent.mkdir()
    contract = (
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
        "## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n"
        "## Validation scope\n- `dev/cde/ec2`\n"
    )
    for invalid in ("- `dev/cde/s3`", "- `all`", "- `dev/cde/ec2`\n- `dev/cde/ec2`"):
        active.write_text(contract + "\n## Issue remediation\n\n" + invalid + "\n")
        try:
            remediation_scope(root)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid remediation scope accepted")
    active.write_text(
        contract.replace("dev/cde/ec2", "all")
        + "\n## Issue remediation\n\n- `dev/cde/ec2`\n"
    )
    try:
        remediation_scope(root)
    except ValueError:
        pass
    else:
        raise AssertionError("all-scope remediation accepted")


@pytest.fixture
def remediation_task(tmp_path, monkeypatch):
    name = "tasks/remediation.md"
    paths = {
        name,
        "model/dev/cde/ec2.properties",
        "model/dev/cde/ec2/part-001.properties",
        "model/dev/cde/s3.properties",
        "docs/designs/dev/cde/ec2.md",
        "docs/designs/dev/cde/ec2/policy.json",
        "issues/dev/cde/issues.md",
    }
    listed = "".join(f"- `{path}`\n" for path in sorted(paths))
    text = (
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
        "- Workflow: `update`\n- AWS API execution: `forbidden`\n"
        "- deploy/apply: `forbidden`\n"
        "## Validation scope\n- `dev/cde/ec2`\n- `dev/cde/s3`\n"
        "## Issue remediation\n- `dev/cde/ec2`\n"
        "## Modified files\n" + listed + "## Allowed paths\n" + listed
    )
    tasks.start(tmp_path, name, text)
    monkeypatch.setenv(tasks.SELECTOR, name)
    return tmp_path, name, text, paths


def check_service_remediation_and_iac_separation(remediation_task):
    root, name, text, paths = remediation_task
    inventory = root / "issues/dev/cde/issues.md"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("### ec2\n1. 設定不足\n2. 参照不足\n", encoding="utf-8")
    iac = inventory.with_name("iac-issues.md")
    iac.write_text("### ec2\n1. ModelとIaCの値が異なる\n", encoding="utf-8")
    assert len(issue_errors(root, {("dev", "cde", "ec2")})) == 2
    require_no_issues(root, active_scope(root))
    assert remediation_scope(root) == {("dev", "cde", "ec2")}
    task = TaskValidation(root, Findings(root))
    task.task_type, task.contract_text = "design", text
    task.check_task_boundary(root / name, paths)
    assert not task.findings.errors
    inventory.write_text("### s3\n1. 対象外Issue\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unresolved issue.*s3"):
        require_no_issues(root, active_scope(root))
    inventory.write_text("未解決issueなし\n", encoding="utf-8")
    ordinary = text.replace("## Issue remediation\n- `dev/cde/ec2`\n", "")
    (root / name).write_text(ordinary, encoding="utf-8")
    require_no_issues(root, active_scope(root))
    assert not remediation_scope(root)  # IaC differences do not start remediation.
    assert (root / name).read_text(encoding="utf-8") == ordinary
    assert iac.read_text(encoding="utf-8") == "### ec2\n1. ModelとIaCの値が異なる\n"


@pytest.mark.parametrize("heading", ["Allowed paths", "Modified files"])
@pytest.mark.parametrize(
    "path",
    [
        "infra/cloudformation/templates/ec2.yaml",
        "infra/cloudformation/parameters/dev/cde/ec2.json",
        "infra/cde/terraform/dev/main.tf",
        "framework/scripts/issue_gate.py",
        "framework/rules/issue-gate.md",
        "framework/materials/schema.json",
        ".agents/skills/update/SKILL.md",
        "AGENTS.md",
        "README.md",
        "pyproject.toml",
        ".github/workflows/framework-it.yml",
        "project.json",
        "issues/dev/cde/iac-issues.md",
        "model/prod/cde/ec2.properties",
        "model/dev/cde/iam.properties",
        "model/dev/cde/ec2/main.tf",
        "docs/designs/dev/cde/ec2/template.yaml",
        "**",
        "*/*",
        "[fi]*/*",
        "framework/**",
        "model/**",
    ],
)
def check_remediation_forbidden_declarations(remediation_task, heading, path):
    root, name, text, _ = remediation_task
    text = text.replace(f"## {heading}\n", f"## {heading}\n- `{path}`\n")
    other = name.replace("remediation", "rejected")
    with pytest.raises(ValueError):
        tasks.start(root, other, text.replace(name, other))
    assert not (root / other).exists()
    (root / name).write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        tasks.refresh(root, name)
    with pytest.raises(ValueError):
        require_no_issues(root, {("dev", "cde", "ec2")})
    assert tasks.status((root / name).read_text(encoding="utf-8")) == "running"


@pytest.mark.parametrize(
    "old,new",
    [
        ("- AWS API execution: `forbidden`", "- AWS API execution: `allowed`"),
        ("- AWS API execution: `forbidden`", "- AWS API execution: `read-only`"),
        ("- AWS API execution: `forbidden`\n", ""),
        ("- deploy/apply: `forbidden`", "- deploy/apply: `allowed`"),
        ("- deploy/apply: `forbidden`\n", ""),
        ("- Workflow: `update`", "- Workflow: `import`"),
        ("- Task type: `design`", "- Task type: `infrastructure`"),
        ("- Task type: `design`", "- Task type: `governance`"),
        ("## Task contract", "## Task contract\n- AWS mutation: `allowed`"),
        ("## Task contract", "## Task contract\n- Infrastructure phase: `deploy`"),
        ("## Task contract", "## Task contract\n- AWS API execution: `forbidden`"),
        ("## Issue remediation\n- `dev/cde/ec2`", "## Issue remediation"),
        (
            "## Issue remediation\n- `dev/cde/ec2`",
            "## Issue remediation\n- `dev/cde/ec2`\n## Issue remediation\n- `dev/cde/ec2`",
        ),
    ],
)
def check_remediation_forbidden_operations(remediation_task, old, new):
    root, name, text, _ = remediation_task
    with pytest.raises(ValueError):
        tasks.validate_contract(root, name, text.replace(old, new))


@pytest.mark.parametrize(
    "path",
    [
        "framework/scripts/issue_gate.py",
        ".agents/skills/update/SKILL.md",
        "AGENTS.md",
        "infra/cde/terraform/dev/main.tf",
        "issues/dev/cde/iac-issues.md",
    ],
)
def check_remediation_actual_changes_and_completion(remediation_task, path):
    root, name, text, _ = remediation_task
    task = TaskValidation(root, Findings(root))
    task.task_type, task.contract_text = "design", text
    task.check_task_boundary(root / name, {path})
    assert any("Issue remediation forbidden path" in e for e in task.findings.errors)
    # Completion must reject real changes even if its earlier validator was bypassed.
    with (
        mock.patch("model.importing.repository.changed_paths", return_value={path}),
        pytest.raises(ValueError, match="Issue remediation forbidden path"),
    ):
        tasks.complete(root, name)
    assert tasks.status((root / name).read_text(encoding="utf-8")) == "running"


def check_remediation_completion_and_resume(remediation_task):
    root, name, text, paths = remediation_task
    tasks.suspend(root, name, "test stop")
    tasks.resume(root, name)
    assert tasks.status((root / name).read_text(encoding="utf-8")) == "running"
    with (
        mock.patch("model.importing.repository.changed_paths", return_value=paths),
        mock.patch.object(import_guard, "require_import_changes"),
    ):
        tasks.complete(root, name)
    assert tasks.status((root / name).read_text(encoding="utf-8")) == "completed"


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
