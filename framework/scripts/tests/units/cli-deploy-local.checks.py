"""CLI Deploy local completion and Model projection never invoke the SDK."""

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import task_contract_runtime as runtime
import worktree_task as wt
from deploy import completion
from deploy import progress as deploy_progress
from model.format import FORMAT
from model.identity import Resolver
from model.reference_nodes import parse
from model.reference_values import reference_value
from model.render import generate_files
from model.sources import load_model
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    project_configuration,
    reference,
    resource,
    save,
)
from support.pytest_cli import run
from support.repository_fixtures import transition_contract
from utils import cli_deploy as cli
from utils.aws_mappings import mapping_alias

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

NAME = "tasks/cli-example.md"
CONTEXT = (
    "- Infrastructure phase: `deploy`\n"
    "- Deploy execution method: `cli`\n"
    "- CLI AWS account: `123456789012`\n"
    "- CLI AWS region: `ap-northeast-1`\n"
    "- CLI AWS partition: `aws`\n"
)


def contract():
    return transition_contract(
        NAME, ["file.txt"], kind="infrastructure", scope="qa/team/iam"
    ).replace(
        "- Task type: `infrastructure`\n", "- Task type: `infrastructure`\n" + CONTEXT
    )


@pytest.mark.parametrize(
    "method", ["", "sdk", "cli", "invalid", "cli`\n- Deploy execution method: `cli"]
)
def check_explicit_method(method):
    text = contract()
    text = (
        text.replace("- Deploy execution method: `cli`\n", "")
        if not method
        else text.replace("method: `cli`", f"method: `{method}`")
    )
    if method in {"invalid", "cli`\n- Deploy execution method: `cli"}:
        with pytest.raises(ValueError):
            cli.is_cli(text)
    else:
        assert cli.is_cli(text) == (method == "cli")
    with pytest.raises(ValueError, match="infrastructure/deploy"):
        cli.is_cli(contract().replace("phase: `deploy`", "phase: `implement`"))


@pytest.mark.parametrize("sdk_bound", [False, True])
@pytest.mark.parametrize("validation_failure", [False, True])
def check_completion_uses_local_validator(tmp_path, sdk_bound, validation_failure):
    project_configuration(tmp_path)
    text = contract()
    path = tmp_path / NAME
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    snapshot = SimpleNamespace(
        name=NAME, text=text, status="running", scope=frozenset({("qa", "team", "iam")})
    )
    validator = Mock()
    validator.report.return_value = int(validation_failure)
    validator.findings.failures.return_value = [
        {"reason": "synthetic validation failure"}
    ]
    with (
        patch.object(runtime, "task_snapshot", return_value=snapshot),
        patch.object(runtime, "task_reads", return_value=nullcontext()),
        patch.object(runtime, "verify_snapshot"),
        patch.object(runtime, "Validator", return_value=validator),
        patch.object(wt, "paths", return_value=set()),
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(runtime._imports_import_guard, "require_import_changes"),
        patch.object(completion, "verify_observation_delta"),
    ):
        if sdk_bound:
            progress_path = deploy_progress.progress_path(tmp_path, NAME, create=True)
            progress_path.touch()
        if sdk_bound or validation_failure:
            with pytest.raises(ValueError):
                runtime.complete(tmp_path, NAME)
            assert path.read_text(encoding="utf-8") == text
        else:
            runtime.complete(tmp_path, NAME)
            assert "- Task status: `completed`" in path.read_text(encoding="utf-8")
            validator.run.assert_called_once()


def check_sdk_completion_route_is_unchanged(tmp_path):
    snapshot = SimpleNamespace(
        name=NAME, text=contract().replace("method: `cli`", "method: `sdk`")
    )
    with (
        patch.object(runtime, "task_snapshot", return_value=snapshot),
        patch.object(completion, "require_local") as require,
        patch.object(completion, "validate_local", return_value="validated"),
        patch.object(completion, "finish_local") as finish,
    ):
        runtime.complete(tmp_path, NAME)
        require.assert_called_once_with(tmp_path, snapshot)
        finish.assert_called_once_with(tmp_path, snapshot, "validated")


@pytest.mark.parametrize("publication", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [
        ("account", None),
        ("account", "999999999999"),
        ("region", None),
        ("region", "us-east-1"),
        ("partition", None),
        ("partition", "AWS!"),
    ],
)
def check_context_required_without_model_references(
    tmp_path, publication, field, value
):
    project_configuration(tmp_path)
    original = {
        "account": "123456789012",
        "region": "ap-northeast-1",
        "partition": "aws",
    }[field]
    line = f"- CLI AWS {field}: `{original}`\n"
    text = contract().replace(line, f"- CLI AWS {field}: `{value}`\n" if value else "")
    if publication:
        text = text.replace("status: `running`", "status: `completed`")
    path = tmp_path / NAME
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    snapshot = SimpleNamespace(
        name=NAME,
        text=text,
        status="completed" if publication else "running",
        scope=frozenset({("qa", "team", "iam")}),
    )
    with (
        patch.object(runtime, "task_snapshot", return_value=snapshot),
        patch("task_contract_core.task_snapshot", return_value=snapshot),
        patch.object(runtime, "task_reads", return_value=nullcontext()),
        patch.object(wt, "paths", return_value=set()),
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(
            runtime,
            "Validator",
            side_effect=AssertionError("validation should not run"),
        ),
        patch(
            "validation.runner.Validator",
            side_effect=AssertionError("publication should not run"),
        ),
    ):
        with pytest.raises(ValueError, match="CLI AWS"):
            if publication:
                cli.validate_candidate(tmp_path, NAME, "latest-base")
            else:
                runtime.complete(tmp_path, NAME)
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("wrong_context", [None, "account", "region", "partition"])
def check_reference_projection_without_sdk(tmp_path, wrong_context):
    with mapping_alias(FRAMEWORK, tmp_path):
        _, _, consumer, policy = project(tmp_path)
        producer, values = resource(tmp_path, "s3", "S3.Bucket", attribute="BucketName")
        values["desired.row.001-001.value"] = "`fixture-materials`"
        save(producer, values)
        text = contract()
        if wrong_context:
            text = text.replace(
                {
                    "account": "`123456789012`",
                    "region": "`ap-northeast-1`",
                    "partition": "`aws`",
                }[wrong_context],
                "`invalid`",
            )
        path = tmp_path / NAME
        path.parent.mkdir()
        path.write_text(text, encoding="utf-8")
        with patch(
            "model.reference_values.aws_runtime",
            side_effect=AssertionError("SDK metadata forbidden"),
        ):
            if wrong_context:
                with pytest.raises(ValueError):
                    reference_value(
                        Resolver(tmp_path),
                        consumer,
                        parse(reference("S3_Bucket_001", "Arn")),
                    )
            else:
                result = reference_value(
                    Resolver(tmp_path),
                    consumer,
                    parse(reference("S3_Bucket_001", "Arn")),
                )
                assert (
                    result.status == "resolved"
                    and result.value == "arn:aws:s3:::fixture-materials"
                )
                document = json.loads(policy["desired.row.001-002.document"])
                document["Statement"][0]["Resource"] = reference("S3_Bucket_001", "Arn")
                policy["desired.row.001-002.document"] = json.dumps(document)
                save(consumer, policy)
                before = consumer.path.read_bytes()
                view = tmp_path / "docs/designs/qa/team/iam.md"
                files = generate_files(view, load_model(consumer).values, tmp_path)
                assert (
                    json.loads(files[view.with_suffix("") / "policy.json"])[
                        "Statement"
                    ][0]["Resource"]
                    == result.value
                )
                assert consumer.path.read_bytes() == before


@pytest.mark.parametrize("failure", [False, True])
def check_publication_validates_actual_latest_base(tmp_path, failure):
    project_configuration(tmp_path)
    source = tmp_path / "model/qa/team/iam.properties"
    source.parent.mkdir(parents=True)
    source.write_text(
        FORMAT + "\ndesired.row.001-001.value=fixture\n", encoding="utf-8"
    )
    snapshot = SimpleNamespace(
        name=NAME,
        text=contract(),
        status="completed",
        scope=frozenset({("qa", "team", "iam")}),
    )
    validator = Mock()
    validator.report.return_value = int(failure)
    with (
        patch("task_contract_core.task_snapshot", return_value=snapshot),
        patch.object(wt, "output", return_value="candidate-head"),
        patch.object(wt, "paths", return_value={"model/qa/team/iam.properties"}),
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(wt, "subprocess_bytes", return_value=source.read_bytes()),
        patch("utils.aws_mappings.definition_root", return_value=tmp_path),
        patch("validation.runner.Validator", return_value=validator) as factory,
    ):
        if failure:
            with pytest.raises(ValueError, match="latest-base"):
                cli.validate_candidate(tmp_path, NAME, "latest-base")
        else:
            cli.validate_candidate(tmp_path, NAME, "latest-base")
        candidate = factory.call_args.kwargs["final_candidate"]
        assert candidate.base_commit == "latest-base"
        assert candidate.candidate_head == "candidate-head"
        assert candidate.task_text == snapshot.text
        assert candidate.scope == snapshot.scope


@pytest.mark.parametrize("change", ["observed", "desired", "new", "project"])
def check_cli_completion_preserves_authority(tmp_path, change):
    project_configuration(tmp_path)
    path = tmp_path / "model/qa/team/iam.properties"
    path.parent.mkdir(parents=True)
    before = (
        FORMAT + "\ndesired.row.001-001.value=fixed\nobserved.row.001-001.value=old\n"
    )
    path.write_text(
        before.replace("old", "current")
        if change == "observed"
        else before.replace("fixed", "changed"),
        encoding="utf-8",
    )
    paths = (
        {"project.json"} if change == "project" else {"model/qa/team/iam.properties"}
    )
    snapshot = SimpleNamespace(
        text=contract(), name=NAME, scope=frozenset({("qa", "team", "iam")})
    )
    with (
        patch.object(completion, "collect_working_paths", return_value=SimpleNamespace(all_paths=paths)),
        patch.object(completion.contracts, "subprocess_bytes", return_value=None if change == "new" else before.encode("utf-8")),
    ):
        if change == "observed":
            cli.require_local_completion(tmp_path, snapshot)
        else:
            with pytest.raises(ValueError):
                cli.require_local_completion(tmp_path, snapshot)


@pytest.mark.parametrize("failure", [False, True])
def check_cli_finalize_checks_even_zero_delta(tmp_path, failure):
    text = contract().replace("status: `running`", "status: `completed`")
    snapshot = SimpleNamespace(text=text, raw=text.encode("utf-8"))
    state = {
        "task_file": NAME,
        "task_id": "cli-example",
        "worktree": str(tmp_path),
        "python_setup": {"status": "ready"},
        "merged": None,
        "branch": "task",
        "base": "main",
    }
    base = tmp_path / "base"
    with (
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(wt.tasks, "read_task_snapshot", return_value=snapshot),
        patch.object(wt, "integration_task"),
        patch.object(wt, "_prepare_commit", return_value="latest-base"),
        patch.object(wt, "base_worktree", return_value=base),
        patch.object(wt, "paths", return_value=set()),
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(
            wt,
            "output",
            side_effect=[
                "candidate-head",
                "candidate-head",
                "latest-base",
                "candidate-head",
            ],
        ),
        patch.object(wt, "ancestor", return_value=True),
        patch.object(
            wt,
            "_run_model_guard",
            side_effect=wt.Blocked("validation failed") if failure else None,
        ) as guard,
        patch.object(wt, "git") as git,
        patch.object(wt, "save"),
        patch.object(wt, "cleanup_state", return_value=state),
    ):
        if failure:
            with pytest.raises(wt.Blocked, match="validation failed"):
                wt._finalize(tmp_path, "cli-example")
            git.assert_not_called()
        else:
            wt._finalize(tmp_path, "cli-example")
            git.assert_called_once_with(
                base, "merge", "--ff-only", "--no-autostash", "task"
            )
        assert guard.call_args.kwargs["validation_base"] == "latest-base"


def check_cli_pr_refused_before_publication(tmp_path):
    state = {"worktree": str(tmp_path), "task_file": NAME, "merged": None}
    with (
        patch.object(wt, "load", return_value=(tmp_path, None, None, state)),
        patch.object(
            wt.tasks,
            "read_task_snapshot",
            return_value=SimpleNamespace(text=contract()),
        ),
        patch.object(
            wt, "module", side_effect=AssertionError("PR publication forbidden")
        ),
    ):
        with pytest.raises(wt.Blocked, match="PR publication"):
            wt.finalize(tmp_path, "cli-example", create_pr=True)


if __name__ == "__main__":
    raise SystemExit(run(__file__, message="CLI Deploy local checks: PASS"))
