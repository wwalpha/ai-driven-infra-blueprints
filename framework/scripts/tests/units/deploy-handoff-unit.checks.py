"""Current failure/Task authority and one-shot Implement evidence checks."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from types import SimpleNamespace

import deploy_handoff
import pytest
from deploy import contracts, failures, handoff
from deploy import operation_journal as J
from deploy.recovery import cleanup_unexecuted
from support.pytest_cli import run
from task_contract_core import relative_path, safe_path, set_status, task_digest
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked
from utils.file_operations import sha
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.sealed_evidence import evidence_store, write_sealed

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize(
    "stage,code,service,operation,expected",
    [
        (
            "PREPARATION",
            "ValidationError",
            "cloudformation",
            "validate_template",
            "IAC_CANDIDATE",
        ),
        (
            "PREPARATION",
            "ValidationException",
            "cloudformation",
            "create_change_set",
            "IAC_CANDIDATE",
        ),
        (
            "PREPARATION",
            "AccessDenied",
            "cloudformation",
            "create_change_set",
            "AUTHORIZATION",
        ),
        (
            "PREPARATION",
            "ReadTimeoutError",
            "cloudformation",
            "create_change_set",
            "NEEDS_HUMAN",
        ),
        ("POLL", "ValidationError", "cloudformation", "describe_stacks", "NEEDS_HUMAN"),
        (
            "EXECUTE",
            "ReadTimeoutError",
            "cloudformation",
            "execute_change_set",
            "SUBMISSION_UNKNOWN",
        ),
    ],
)
def check_failure_classes(stage, code, service, operation, expected):
    error = ValueError("must not be persisted as diagnosis")
    error.code, error.deploy_service, error.deploy_operation = code, service, operation
    state = {"status": "RUNNING" if stage == "EXECUTE" else "BLOCKED"}
    failures.exception(state, error, stage)
    assert state["failure"]["classification"] == expected
    assert "must not be persisted" not in json.dumps(state)


def check_status_helpers_preserve_task_identity():
    text = "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n- Authorized delete/replacement: `none`\n"
    suspended = (
        set_status(text, "suspend") + "\n## Suspension reason\n\n    awaiting child\n"
    )
    assert (
        task_digest(text)
        == task_digest(suspended)
        == task_digest(set_status(suspended, "running"))
    )
    assert task_digest(text) == task_digest(text.replace("`none`", "`change-set`"))
    assert task_digest(text) != task_digest(text + "\n## Other\nchanged\n")


def _callback_check_unexecuted_shell_recovery_aws(
    calls, change, defect, stack, /, operation, **arguments
):
    calls.append((operation, arguments))
    assert arguments["StackName"] == "original"
    if operation == "describe_stacks":
        if defect == "interrupted":
            raise AwsError(
                "cloudformation", operation, "ValidationError", stack_absent=True
            )
        return {"Stacks": [stack]}
    if operation == "describe_change_set":
        return change
    if operation == "list_stack_resources":
        if defect == "read":
            raise AwsError("cloudformation", operation, "AccessDenied")
        return {"StackResourceSummaries": [{}] if defect == "resources" else []}
    assert operation == "delete_stack"


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "origin",
        "identity",
        "protected",
        "parent",
        "status",
        "change-stack",
        "executed",
        "change-status",
        "resources",
        "read",
        "interrupted",
    ],
)
def check_unexecuted_shell_recovery(defect):
    proof = {
        "stackId": "original",
        "changeSetId": "change",
        "operationType": "CREATE",
        "absentBeforeCreate": True,
    }
    state = {
        "status": "NOT_STARTED",
        "stackId": "original",
        "preExecutionRecovery": proof,
    }
    stack = {"StackId": "original", "StackStatus": "REVIEW_IN_PROGRESS"}
    change = {
        "StackId": "original",
        "ChangeSetId": "change",
        "Status": "FAILED",
        "ExecutionStatus": "UNAVAILABLE",
    }
    if defect == "origin":
        proof["absentBeforeCreate"] = False
    if defect == "identity":
        stack["StackId"] = "reused"
    if defect == "protected":
        stack["EnableTerminationProtection"] = True
    if defect == "parent":
        stack["ParentId"] = "parent"
    if defect == "status":
        stack["StackStatus"] = "CREATE_COMPLETE"
    if defect == "change-stack":
        change["StackId"] = "other"
    if defect == "executed":
        change["ExecutionStatus"] = "EXECUTE_COMPLETE"
    if defect == "change-status":
        change["Status"] = "CREATE_COMPLETE"
    if defect == "interrupted":
        state.update(cleanupStatus="DELETE_INTENT", cleanupStackId="original")
    calls, saves, waits = [], [], []
    aws = _bind_framework_callback(
        _callback_check_unexecuted_shell_recovery_aws, calls, change, defect, stack
    )
    if defect in {"none", "interrupted"}:
        cleanup_unexecuted(
            aws,
            lambda: saves.append(copy.deepcopy(state)),
            lambda s: waits.append(s["stackId"]),
            state,
        )
        assert state["status"] == "NOT_STARTED" and "stackStatus" not in state
        assert (waits == ["original"]) == (defect == "none")
    else:
        with pytest.raises(Blocked):
            cleanup_unexecuted(
                aws,
                lambda: saves.append(copy.deepcopy(state)),
                lambda s: waits.append(s["stackId"]),
                state,
            )
        assert not any(op == "delete_stack" for op, _ in calls)
        assert not waits
    assert saves or defect not in {"none", "interrupted"}


@pytest.mark.parametrize("lock_path", [".lock", ".lock/registration"])
def check_validation_snapshot_project_paths(tmp_path, lock_path):
    paths = {"README.md", "infra/new.json", "missing.md", "model/.lock", ".lockfile"}
    contracts.output(tmp_path, "init", "-q")
    for relative in paths - {"missing.md"}:
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(relative)
    for relative in (lock_path, "framework/ignored.py", "missing.md"):
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("synthetic")
    contracts.output(tmp_path, "add", "README.md", "missing.md", lock_path, "framework")
    (tmp_path / "missing.md").unlink()
    with (
        patch.object(contracts, "paths", wraps=contracts.paths) as listing,
        patch.object(contracts, "sha", wraps=sha) as hashes,
    ):
        snapshot = contracts.validation_snapshot(tmp_path)
    listing.assert_called_once_with(
        tmp_path,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        ".",
        ":(top,exclude)framework",
        ":(top,exclude).lock",
    )
    assert set(snapshot) == paths and snapshot["missing.md"] is None
    assert {call.args[0] for call in hashes.call_args_list} == {
        tmp_path / p for p in paths - {"missing.md"}
    }
    assert snapshot["README.md"] == sha(tmp_path / "README.md")
    (tmp_path / "README.md").write_text("changed")
    changed = contracts.validation_snapshot(tmp_path)
    assert changed != snapshot
    assert changed | {"README.md": snapshot["README.md"]} == snapshot
    for forbidden in (".lock", ".lock/registration", ".git/config", "../outside"):
        with pytest.raises(ValueError, match="exact repository-relative path"):
            relative_path(forbidden)
        with pytest.raises(ValueError, match="exact repository-relative path"):
            safe_path(tmp_path, forbidden)


@pytest.mark.parametrize(
    "defect", ["none", "model", "path", "failure", "other-task", "other-digest"]
)
def check_one_shot_request_requires_current_authority(tmp_path, defect):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "infra/cloudformation/templates/kms.yaml"
    model = root / "model/dev/team/kms.properties"
    for path, text in (
        (source, "Resources: {}"),
        (model, "desired.row.001-001.value=`approved`\n"),
    ):
        path.parent.mkdir(parents=True)
        path.write_text(text)
    relative, model_relative = (
        source.relative_to(root).as_posix(),
        model.relative_to(root).as_posix(),
    )
    task = SimpleNamespace(
        name="tasks/deploy.md",
        task_digest="task",
        text="- External IaC repair: `allowed`\n## Validation scope\n- `dev/team/kms`\n",
    )
    target = {"awsAccountId": "123456789012", "awsRegion": "region"}
    failure = {
        "repository": str(root),
        "taskFile": task.name,
        "taskDigest": task.task_digest,
        "target": target,
        "environment": "dev",
        "directory": "team",
        "inputs": {relative: sha(source), model_relative: sha(model)},
        "states": {
            "Kms": {
                "status": "BLOCKED",
                "failure": {
                    "classification": "IAC_CANDIDATE",
                    "executionState": "NOT_EXECUTED",
                },
            }
        },
    }
    if defect == "failure":
        failure["states"]["Kms"]["failure"]["classification"] = "SUBMISSION_UNKNOWN"
    if defect == "other-task":
        failure["taskFile"] = "tasks/previous.md"
    elif defect == "other-digest":
        failure["taskDigest"] = "previous"
    path = tmp_path / "failure.json"
    write_sealed(root, path, failure)
    diagnosis = {
        "Kms": {
            "reason": "The current template differs from the explicitly approved desired Model entry.",
            "inputRefs": [{"path": relative, "sha256": sha(source)}],
            "modelRefs": [
                {
                    "path": model_relative,
                    "sha256": sha(model),
                    "key": "desired.row.001-001.value",
                }
            ],
        }
    }
    if defect == "model":
        model.write_text("desired.row.001-001.value=`changed`\n")
    allowed = ["infra/unrelated.yaml"] if defect == "path" else [relative]
    with (
        patch.object(handoff, "task_snapshot", return_value=task),
        patch.object(handoff.operation_journal, "read", return_value=None),
    ):
        if defect == "none":
            request = handoff.issue_request(root, path, diagnosis, allowed)
            assert request["allowedPaths"] == [relative]
            assert (
                not {"workflow", "attempts", "session", "approvedChangeDigest"}
                & request.keys()
            )
            handoff.verify_inputs(root, request)
            model.write_text("desired.row.001-001.value=`changed`\n")
            with pytest.raises(Blocked, match="dependency changed"):
                handoff.verify_inputs(root, request)
        else:
            with pytest.raises(Blocked):
                handoff.issue_request(root, path, diagnosis, allowed)


def delivered_request(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    directory = evidence_store(root) / "deploy-repair-current"
    directory.mkdir(mode=0o700)
    path = directory / "request.json"
    failure = evidence_store(root) / "deploy-failure-current.json"
    identity = {
        "repository": str(root),
        "taskFile": "tasks/deploy.md",
        "taskDigest": "task",
    }
    write_sealed(root, failure, identity)
    write_sealed(
        root,
        path,
        {**identity, "requestId": "current", "failureEvidence": str(failure)},
    )
    write_sealed(
        root, directory / "result.json", {"requestId": "current", "commit": "commit"}
    )
    write_sealed(root, directory / "validation.json", {"requestId": "current"})
    for number in (1, 2):
        (directory / f"static-{number}.log").write_text("static PASS", encoding="utf-8")
    return (
        root,
        path,
        failure,
        {
            "deployRepair": str(path),
            "verified": True,
            "merged": "commit",
            "commit": "commit",
            "repairStaticRuns": 2,
        },
    )


@pytest.mark.parametrize(
    "case", ["completed", "unknown", "shared", "unknown-reference", "unverified"]
)
def check_delivered_request_evidence_is_discarded(tmp_path, case):
    root, path, failure, state = delivered_request(tmp_path)
    directory = path.parent
    with handoff.locked(path):
        with pytest.raises(Blocked, match="lock busy"):
            with handoff.locked(path):
                raise AssertionError("second repair owner acquired lock")
    assert not path.with_suffix(".lock").exists()
    assert (evidence_store(root) / "deploy-repair.lock").is_file()
    if case in {"shared", "unknown-reference"}:
        other = evidence_store(root) / "deploy-repair-other/request.json"
        other.parent.mkdir(mode=0o700)
        write_sealed(root, other, {"failureEvidence": str(failure)})
        if case == "unknown-reference":
            other.write_text("unreadable")
    if case == "unverified":
        state["verified"] = False
    if case in {"unknown-reference", "unverified"}:
        with pytest.raises((Blocked, ValueError)):
            handoff.discard_request(state)
        assert path.exists() and failure.exists()
    elif case == "unknown":
        extra = directory / "user-note.txt"
        extra.write_text("preserve user evidence")
        with pytest.raises(Blocked, match="unknown files"):
            handoff.discard_request(state)
        assert (
            extra.read_text() == "preserve user evidence"
            and path.exists()
            and failure.exists()
        )
    else:
        handoff.discard_request(state)
        assert not directory.exists()
        assert failure.exists() == (case == "shared")


def _callback_cleanup_interrupt(
    original, selected, after, exception, path, *args, **kwargs
):
    if path == selected and not after:
        raise exception("interrupted cleanup")
    result = original(path, *args, **kwargs)
    if path == selected and after:
        raise exception("interrupted cleanup")
    return result


@pytest.mark.parametrize("exception", [OSError, SystemExit])
@pytest.mark.parametrize(
    "method,name,after",
    [
        ("read_text", "validation.json", False),
        ("rename", "active", False),
        ("rename", "active", True),
        ("unlink", "static-1.log", True),
        ("unlink", "static-2.log", True),
        ("unlink", "validation.json", True),
        ("unlink", "result.json", True),
        ("unlink", "request.json", True),
        ("unlink", "failure", True),
        ("rmdir", "cleanup", False),
        ("rmdir", "cleanup", True),
        ("unlink", "receipt", False),
        ("unlink", "receipt", True),
    ],
)
def check_discard_retries_every_interruption(tmp_path, method, name, after, exception):
    root, request, failure, state = delivered_request(tmp_path)
    directory = request.parent.with_name("deploy-cleanup-current")
    receipt = directory.with_suffix(".json")
    unused = failure.with_name("deploy-failure-unconsumed.json")
    write_sealed(root, unused, {"unconsumed": True})
    original = {p: p.read_bytes() for p in request.parent.iterdir()}
    selected = {
        "active": request.parent,
        "failure": failure,
        "cleanup": directory,
        "receipt": receipt,
    }.get(name)
    if selected is None:
        selected = (request.parent if method == "read_text" else directory) / name
    with (
        patch.object(
            Path,
            method,
            _bind_framework_callback(
                _callback_cleanup_interrupt,
                getattr(Path, method),
                selected,
                after,
                exception,
            ),
        ),
        pytest.raises(exception, match="interrupted cleanup"),
    ):
        handoff.discard_request(state)
    if request.exists():
        assert failure.exists()
        assert handoff.referenced_failures(root) == {failure}
        assert all(p.read_bytes() == content for p, content in original.items())
    else:
        assert handoff.referenced_failures(root) == set()
    handoff.discard_request(state)
    assert (
        not request.parent.exists() and not directory.exists() and not receipt.exists()
    )
    assert not failure.exists() and unused.exists()
    with patch.object(Path, "unlink", side_effect=AssertionError("double deletion")):
        handoff.discard_request(state)


@pytest.mark.parametrize(
    "defect",
    [
        "receipt-signature",
        "file",
        "failure-signature",
        "unknown",
        "missing-receipt",
        "symlink",
        "ownership",
        "commit",
        "request-id",
        "result-signature",
        "validation-signature",
    ],
)
def check_discard_rejects_unknown_or_changed_evidence(tmp_path, defect):
    root, request, failure, state = delivered_request(tmp_path)
    if defect in {"result-signature", "validation-signature"}:
        request.with_name(defect.removesuffix("-signature") + ".json").write_text(
            "tampered", encoding="utf-8"
        )
    else:
        with (
            patch.object(
                Path,
                "rename",
                _bind_framework_callback(
                    _callback_cleanup_interrupt,
                    Path.rename,
                    request.parent,
                    True,
                    SystemExit,
                ),
            ),
            pytest.raises(SystemExit),
        ):
            handoff.discard_request(state)
        directory = request.parent.with_name("deploy-cleanup-current")
        receipt = directory.with_suffix(".json")
        if defect == "receipt-signature":
            receipt.write_text("tampered", encoding="utf-8")
        elif defect == "file":
            (directory / "static-1.log").write_text("changed", encoding="utf-8")
        elif defect == "failure-signature":
            failure.write_text("tampered", encoding="utf-8")
        elif defect == "unknown":
            (directory / "user-note.txt").write_text("preserve", encoding="utf-8")
        elif defect == "missing-receipt":
            receipt.unlink()
        elif defect == "symlink":
            receipt.unlink()
            receipt.symlink_to(failure)
        elif defect == "ownership":
            receipt.unlink()
            receipt.mkdir()
        elif defect == "commit":
            state.update(commit="another", merged="another")
        elif defect == "request-id":
            state["deployRepair"] = str(
                request.parent.with_name("deploy-repair-other") / "request.json"
            )
            # Even a validly signed receipt cannot move to another request's location.
            receipt.rename(receipt.with_name("deploy-cleanup-other.json"))
    with pytest.raises((Blocked, ValueError)):
        handoff.discard_request(state)
    assert failure.exists()


@pytest.mark.parametrize("when", ["before", "after"])
def check_discard_retry_preserves_shared_failure(tmp_path, when):
    root, request, failure, state = delivered_request(tmp_path)
    other = evidence_store(root) / "deploy-repair-other/request.json"
    other.parent.mkdir(mode=0o700)
    if when == "before":
        write_sealed(root, other, {"failureEvidence": str(failure)})
    with (
        patch.object(
            Path,
            "rename",
            _bind_framework_callback(
                _callback_cleanup_interrupt,
                Path.rename,
                request.parent,
                True,
                SystemExit,
            ),
        ),
        pytest.raises(SystemExit),
    ):
        handoff.discard_request(state)
    if when == "after":
        write_sealed(root, other, {"failureEvidence": str(failure)})
    before = other.read_bytes()
    handoff.discard_request(state)
    assert other.read_bytes() == before and failure.exists()
    assert handoff.referenced_failures(root) == {failure}


@pytest.mark.parametrize(
    "reference",
    [
        "unused",
        "request",
        "unknown-request",
        "other-task",
        "other-digest",
        "tampered",
        "other-repo",
        "other-target",
        "symlink",
        "writable",
    ],
)
def check_explicit_failure_discard_preserves_referenced_or_unknown_evidence(
    tmp_path, reference
):
    root = tmp_path / "repo"
    root.mkdir()
    store = evidence_store(root)
    path = store / "deploy-failure-original.json"
    failure = {
        "repository": str(root),
        "taskFile": "tasks/deploy.md",
        "taskDigest": "task",
        "target": {"awsAccountId": "123456789012", "awsRegion": "region"},
    }
    if reference == "other-task":
        failure["taskFile"] = "tasks/other.md"
    elif reference == "other-digest":
        failure["taskDigest"] = "different"
    if reference == "other-repo":
        failure["repository"] = str(tmp_path / "foreign")
    elif reference == "other-target":
        failure["target"]["awsRegion"] = "other"
    write_sealed(root, path, failure)
    if reference in {"request", "unknown-request"}:
        request = store / "deploy-repair-active/request.json"
        request.parent.mkdir(mode=0o700)
        write_sealed(root, request, {"failureEvidence": str(path)})
        if reference == "unknown-request":
            request.write_text("unreadable")
    if reference == "tampered":
        path.write_text("unreadable")
    if reference == "symlink":
        saved = path.with_suffix(".original")
        path.rename(saved)
        path.symlink_to(saved)
    elif reference == "writable":
        path.chmod(0o666)
    with patch.object(J, "location", return_value=tmp_path / "journal/journal.json"):
        if reference in {"unused", "other-task", "other-digest", "other-target"}:
            handoff.discard_failure(root, path)
            assert not path.exists()
        else:
            with pytest.raises((Blocked, ValueError, KeyError)):
                handoff.discard_failure(root, path)
            assert path.exists()


@pytest.mark.parametrize("held", ["journal", "repair"])
def check_explicit_discard_lock_contention_preserves_evidence(tmp_path, held):
    root = tmp_path / "repo"
    root.mkdir()
    path = evidence_store(root) / "deploy-failure-current.json"
    target = {"awsAccountId": "123456789012", "awsRegion": "region"}
    write_sealed(root, path, {"repository": str(root), "target": target})
    journal = tmp_path / "journal/journal.json"
    with patch.object(J, "location", return_value=journal):
        with J.locked(journal) if held == "journal" else handoff.repair_lock(root):
            with pytest.raises(Blocked, match="lock busy"):
                handoff.discard_failure(root, path)
            assert path.exists()
        handoff.discard_failure(root, path)
    assert not path.exists()


def check_failure_discard_cli_uses_explicit_mode_only(tmp_path):
    arguments = [
        "--repository-root",
        str(tmp_path),
        "--failure",
        str(tmp_path / "failure.json"),
    ]
    with (
        patch.object(handoff, "discard_failure") as discard,
        patch.object(handoff, "issue_request") as issue,
    ):
        assert deploy_handoff.main([*arguments, "--discard-failure"]) == 0
        discard.assert_called_once_with(tmp_path, tmp_path / "failure.json")
        issue.assert_not_called()
    for options in [[], ["--discard-failure", "--path", "unwanted"]]:
        with pytest.raises(SystemExit):
            deploy_handoff.main([*arguments, *options])


STACK_ID = "arn:aws:cloudformation:region:123456789012:stack/{}/token"


@pytest.mark.parametrize(
    "case",
    [
        "independent",
        "independent-many",
        "same",
        "inbound",
        "outbound",
        "transitive",
        "unknown",
        "publication",
        "disjoint-publication",
        "waiting-publication",
        "producer",
        "unknown-publication",
        "aws-error",
        "unknown-owner",
        "observed-overlap",
        "observed-disjoint",
    ],
)
def check_handoff_scopes_current_failure_and_preserves_journal(tmp_path, case):
    root = tmp_path / "repo"
    root.mkdir()
    template = root / "infra/cloudformation/templates/s3.yaml"
    parameters = root / "infra/cloudformation/parameters/dev/team/s3.json"
    model = root / "model/dev/team/s3.properties"
    for path, text in (
        (template, "Resources: {}"),
        (parameters, "[]"),
        (model, "desired.row.001-001.value=approved"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    relative = template.relative_to(root).as_posix()
    model_path = model.relative_to(root).as_posix()
    target = {"awsAccountId": "123456789012", "awsRegion": "region"}
    task = SimpleNamespace(
        name="tasks/current.md",
        task_digest="current",
        text="- External IaC repair: `allowed`\n## Validation scope\n- `dev/team/s3`\n",
    )
    diagnosis = {
        "S3": {
            "reason": "The failed template needs correction to the current approved desired Model.",
            "inputRefs": [{"path": relative, "sha256": sha(template)}],
            "modelRefs": [
                {
                    "path": model_path,
                    "sha256": sha(model),
                    "key": "desired.row.001-001.value",
                }
            ],
        }
    }
    failure = {
        "repository": str(root),
        "taskFile": task.name,
        "taskDigest": task.task_digest,
        "target": target,
        "environment": "dev",
        "directory": "team",
        "inputs": {
            p.relative_to(root).as_posix(): sha(p)
            for p in (template, parameters, model)
        },
        "states": {
            "S3": {"status": "BLOCKED", "failure": {"classification": "IAC_CANDIDATE"}}
        },
    }
    failure_path = tmp_path / "failure.json"
    write_sealed(root, failure_path, failure)
    state = {
        "status": "RUNNING",
        "externalOperation": True,
        "delivery": {"imports": {}},
    }
    if case == "inbound":
        state["delivery"]["imports"] = {
            "S3Export": {"ExportingStackId": STACK_ID.format("S3")}
        }
    elif case == "unknown":
        state.pop("delivery")
    name = "S3" if case == "same" else "KMS"
    publication = {"repository": str(root), "target": target}
    if case in {
        "publication",
        "disjoint-publication",
        "waiting-publication",
        "producer",
        "unknown-publication",
    }:
        overlap = case == "publication"
        publication["pendingGeneration"] = {
            "view": {
                "generated": {
                    "originals": {
                        (
                            model_path if overlap else "docs/designs/dev/team/kms.md"
                        ): None
                    },
                    "outputs": None if case == "waiting-publication" else {},
                },
                "waitingModelManifest": {
                    model_path if overlap else "model/dev/team/kms.properties": "hash"
                },
                "producers": [{"stack": "S3"}] if case == "producer" else [],
            }
        }
        if case == "unknown-publication":
            publication["pendingGeneration"]["view"]["generated"]["originals"] = {}
            publication["pendingGeneration"]["view"]["waitingModelManifest"] = {}
    if case == "unknown-owner":
        publication["repository"] = str(tmp_path / "missing")
        publication["pendingObserved"] = {
            "beforeManifest": {"model/unknown.properties": "hash"},
            "evidence": {"KMS": {}},
        }
    elif case in {"observed-overlap", "observed-disjoint"}:
        publication["pendingObserved"] = {
            "beforeManifest": {
                model_path
                if case == "observed-overlap"
                else "model/dev/team/kms.properties": "hash"
            },
            "evidence": {"KMS": {}},
        }
    record = {
        "target": target,
        "publication": publication,
        "operations": {
            name: {"unit": {"name": name}, "inputDigest": "old", "state": state}
        },
    }
    journal = tmp_path / "operations/journal.json"
    journal.parent.mkdir(mode=0o700)
    write_sealed(Path(publication["repository"]), journal, record)
    before = journal.read_bytes()
    unit = {"name": "S3", "template": "s3.yaml", "parameters": "s3.json"}
    exports = (
        [{"Name": "KmsExport", "ExportingStackId": STACK_ID.format("KMS")}]
        if case in {"outbound", "transitive"}
        else []
    )
    if case == "independent-many":
        exports = [
            {"Name": "KmsExport", "ExportingStackId": STACK_ID.format("KMS")},
            *[
                {
                    "Name": "Other" + str(i),
                    "ExportingStackId": STACK_ID.format("Other" + str(i)),
                }
                for i in range(199)
            ],
        ]
    if case == "outbound":
        template.write_text(
            "Resources: {X: {Type: X, Properties: {Value: {Fn::ImportValue: KmsExport}}}}"
        )
        failure["inputs"][relative] = sha(template)
        diagnosis["S3"]["inputRefs"][0]["sha256"] = sha(template)
        write_sealed(root, failure_path, failure)
    if case == "transitive":
        exports.append(
            {"Name": "MiddleExport", "ExportingStackId": STACK_ID.format("Middle")}
        )
    aws = Mock(
        side_effect=Blocked("read denied")
        if case == "aws-error"
        else _bind_framework_callback(handoff_dependency_response, exports)
    )
    with (
        patch.object(handoff, "task_snapshot", return_value=task),
        patch.object(J, "location", return_value=journal),
        patch.object(handoff.inputs, "load_units", return_value=(1, [unit])),
        patch.object(handoff, "dependency_reader", return_value=aws),
    ):
        with J.locked(journal), handoff.repair_lock(root):
            if case in {
                "independent",
                "independent-many",
                "disjoint-publication",
                "waiting-publication",
                "observed-disjoint",
            }:
                request = handoff.issue_request(
                    root, failure_path, diagnosis, [relative]
                )
                assert set(request["diagnosis"]) == {"S3"}
            else:
                with pytest.raises((Blocked, KeyError)):
                    handoff.issue_request(root, failure_path, diagnosis, [relative])
    assert journal.read_bytes() == before
    if case == "independent-many":
        assert [(call.args[0], call.kwargs) for call in aws.call_args_list] == [
            ("describe_stacks", {"StackName": "KMS"}),
            ("describe_stacks", {"StackName": "S3"}),
            ("list_imports", {"ExportName": "KmsExport"}),
            ("describe_stacks", {"StackName": "Middle"}),
        ]


def handoff_dependency_response(exports, operation, **arguments):
    if operation == "describe_stacks":
        name = arguments["StackName"].split(":stack/")[-1].split("/")[0]
        identity = STACK_ID.format(name)
        return {
            "Stacks": [
                {
                    "StackId": identity,
                    "StackStatus": "UPDATE_COMPLETE",
                    "Outputs": [
                        {
                            "OutputKey": e["Name"],
                            "OutputValue": "value",
                            "ExportName": e["Name"],
                        }
                        for e in exports
                        if e["ExportingStackId"] == identity
                    ],
                }
            ]
        }
    if operation == "list_exports":
        return {"Exports": [dict(e, Value="value") for e in exports]}
    assert operation == "list_imports"
    return {
        "Imports": ["S3" if arguments["ExportName"] == "MiddleExport" else "Middle"]
    }


@pytest.mark.parametrize("lock", ["journal", "repair"])
def check_handoff_lock_order_fails_without_waiting_or_releasing_owner(tmp_path, lock):
    root = tmp_path / "repo"
    root.mkdir()
    journal = tmp_path / "journal/journal.json"
    with J.locked(journal) if lock == "journal" else handoff.repair_lock(root):
        with pytest.raises(Blocked, match="lock busy"):
            with J.locked(journal), handoff.repair_lock(root):
                raise AssertionError("concurrent Handoff acquired controller locks")
    with J.locked(journal), handoff.repair_lock(root):
        pass


@pytest.mark.parametrize("directory", ["team", "123456789012", "changed-target"])
def check_dependency_reader_uses_current_authentication(tmp_path, directory):
    target = {
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "awsProfile": "approved",
        "iacEngine": "cloudformation",
    }
    if not directory.isdigit():
        target["alias"] = directory
    (tmp_path / "project.json").write_text(
        json.dumps({"targets": [{**target, "environment": "dev"}]}), encoding="utf-8"
    )
    request = {
        "environment": "dev",
        "directory": directory,
        "target": target
        if directory != "changed-target"
        else {**target, "awsRegion": "us-east-1"},
    }
    with (
        patch.object(
            handoff.context,
            "get_caller_identity",
            return_value={"Account": "123456789012"},
        ) as auth,
        patch.object(
            handoff.cloudformation, "list_exports", return_value={"Exports": []}
        ) as read,
    ):
        if directory == "changed-target":
            with pytest.raises(Blocked, match="target changed"):
                handoff.dependency_reader(tmp_path, request)
        else:
            aws = handoff.dependency_reader(tmp_path, request)
            assert aws("list_exports") == {"Exports": []}
            assert read.call_args.args[0][:3] == (
                "approved",
                "ap-northeast-1",
                "123456789012",
            )
            with pytest.raises(Blocked, match="only Import/Export reads"):
                aws("delete_stack", StackName="KMS")
        assert auth.call_args.args[0][:3] == (
            "approved",
            "ap-northeast-1",
            "123456789012",
        )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
