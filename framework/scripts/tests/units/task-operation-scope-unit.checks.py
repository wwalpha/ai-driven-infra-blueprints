"""Public operation Task I/O budgets, Project ownership and snapshot lifetime."""

import shutil
import sys
from contextlib import contextmanager, nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import task_contract_core as tasks
from comparison import Comparison
from deploy import preparation
from design.document import (
    DisplayMismatchError,
    model_reference_tables,
    model_resource_reference_tables,
)
from issues import runner as issues
from model.adapters import aws, observed
from model.importing import scope as permissions
from support import issues_scan_fixtures as fixtures
from support.cloudformation_destroy_fixtures import M as destroy
from support.deploy_preparation_fixtures import fixture as preparation_fixture
from support.pytest_cli import run
from utils.input_cache import input_context, memoized

from model import change_scope, render, sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")
ENV, TARGET = "dev", "123456789012"


def make_tasks(root, *, service="s3", workflow="update"):
    directory = root / "tasks"
    directory.mkdir(exist_ok=True)
    for name, status in (
        ("one", "running"),
        ("two", "completed"),
        ("three", "completed"),
    ):
        (directory / (name + ".md")).write_text(
            "## Task contract\n- Task type: `migration`\n"
            f"- Task status: `{status}`\n- Workflow: `{workflow}`\n"
            f"## Validation scope\n- `{ENV}/{TARGET}/{service}`\n"
            f"## Modified files\n- `tasks/{name}.md`\n"
            f"## Allowed paths\n- `tasks/{name}.md`\n",
            encoding="utf-8",
        )


@pytest.fixture(autouse=True)
def no_selector(monkeypatch):
    monkeypatch.delenv(tasks.SELECTOR, raising=False)


@pytest.fixture
def project(tmp_path):
    values, _ = fixtures.fixture(tmp_path, stacks=3)
    make_tasks(tmp_path)
    return tmp_path, values


@contextmanager
def task_io():
    with (
        patch.object(tasks, "_catalog", wraps=tasks._catalog) as catalog,
        patch.object(tasks, "_read_task", wraps=tasks._read_task) as read,
    ):
        yield SimpleNamespace(catalog=catalog, read=read)


def once(io, root):
    assert io.catalog.call_count == 1, io.catalog.call_args_list
    assert io.read.call_count == 3, io.read.call_args_list
    assert all(call.args[0] == root for call in io.catalog.call_args_list)
    assert all(call.args[0] == root for call in io.read.call_args_list)


@tasks.task_read_scope
def selections(root):
    return [permissions.selected(root) for _ in range(20)]


def check_nested_and_outer_reuse(tmp_path):
    make_tasks(tmp_path)
    with task_io() as io, tasks.task_reads(tmp_path) as outer:
        assert selections(root=tmp_path) == [None] * 20
        with tasks.task_reads(tmp_path) as nested:
            assert nested is outer
            assert selections(tmp_path) == [None] * 20
        once(io, tmp_path)
    assert tasks._read_contracts.get() is None


def check_independent_operations_and_exception_cleanup(tmp_path):
    make_tasks(tmp_path)
    with task_io() as io:
        assert selections(tmp_path) == [None] * 20
        once(io, tmp_path)
        make_tasks(tmp_path, workflow="import")
        assert selections(tmp_path) == [(ENV, TARGET, "s3")] * 20
        assert io.catalog.call_count == 2 and io.read.call_count == 6
    (tmp_path / "tasks/two.md").write_text(
        (tmp_path / "tasks/one.md").read_text(), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="multiple running"):
        selections(tmp_path)
    assert tasks._read_contracts.get() is None
    make_tasks(tmp_path)
    assert selections(tmp_path) == [None] * 20


def check_project_isolation_restores_parent(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    make_tasks(first)
    make_tasks(second, service="sqs", workflow="import")
    with task_io() as io, tasks.task_reads(first) as parent:
        assert selections(first)[0] is None
        assert selections(second)[0] == (ENV, TARGET, "sqs")
        assert tasks._read_contracts.get() is parent
        assert selections(first)[0] is None
        assert io.catalog.call_count == 2 and io.read.call_count == 6


@tasks.task_read_scope
@memoized
def memoized_selection(root):
    return selections(root)


def check_scope_precedes_memoized_lookup(tmp_path):
    make_tasks(tmp_path)
    with (
        input_context(),
        patch.object(tasks, "task_reads", wraps=tasks.task_reads) as scopes,
    ):
        first = memoized_selection(tmp_path)
        count = scopes.call_count
        assert tasks._read_contracts.get() is None
        assert memoized_selection(tmp_path) is first
        assert scopes.call_count == count + 1
        assert tasks._read_contracts.get() is None


def check_text_only_view_needs_no_project_snapshot(tmp_path):
    with patch.object(tasks, "task_reads", side_effect=AssertionError("no Project")):
        assert model_reference_tables(Path("view.md"), "# Text", (), tmp_path) == ()


def check_live_authority_is_fresh_and_restores_parent(tmp_path):
    make_tasks(tmp_path)
    with tasks.task_reads(tmp_path) as parent:
        captured = tasks.task_snapshot(tmp_path)
        make_tasks(tmp_path, service="sqs")
        assert tasks.task_snapshot(tmp_path).scope == {(ENV, TARGET, "s3")}
        assert tasks.task_snapshot(tmp_path, live=True).scope == {(ENV, TARGET, "sqs")}
        assert tasks._read_contracts.get() is parent
        with pytest.raises(ValueError, match="changed during validation"):
            tasks.verify_snapshot(captured)
    assert tasks.task_snapshot(tmp_path).scope == {(ENV, TARGET, "sqs")}


@pytest.mark.parametrize(
    "api",
    [
        "load",
        "raw",
        "stacks",
        "generate",
        "validated",
        "files",
        "tables",
        "resource-tables",
    ],
)
def check_standalone_public_api_budget(project, api):
    root, models = project
    model = root / f"model/{ENV}/{TARGET}/s3.properties"
    path = root / f"docs/designs/{ENV}/{TARGET}/s3.md"
    with task_io() as io:
        if api == "load":
            result = sources.load_model(scope=model)
        elif api == "raw":
            result = sources.raw_model(scope=model)
        elif api == "stacks":
            result = sources.stack_snapshot(
                path=model.with_name("cloudformation-stacks.properties")
            )
        elif api == "generate":
            result = render.generate_markdown(path=path, values=models["s3"], root=root)
        elif api == "validated":
            result = render.render_validated_model(path, models["s3"], root)
        elif api == "files":
            result = render.generate_files(path, models["s3"], root)
        elif api == "resource-tables":
            result = model_resource_reference_tables(
                path, path.read_text(), models["s3"], root
            )
        else:
            result = model_reference_tables(
                path=path,
                text=path.read_text(),
                values=tuple(models["s3"].items()),
                root=root,
            )
        assert result is not None
        once(io, root)
    assert tasks._read_contracts.get() is None


def outcome(operation):
    try:
        return operation()
    except ValueError as error:
        return type(error), str(error)


def check_display_and_authorization_results(project):
    root, models = project
    path = root / f"docs/designs/{ENV}/{TARGET}/s3.md"
    values = models["s3"]
    generated = render.generate_markdown(path, values, root)
    assert generated == path.read_text()
    for check in (False, True):
        compare = partial(
            model_reference_tables,
            path,
            generated.replace("`owner`", "`changed`"),
            tuple(values.items()),
            root,
            check_document=check,
        )

        actual = outcome(compare)
        with tasks.task_reads(root):
            assert actual == outcome(compare)
        if check:
            assert actual[0] is DisplayMismatchError
    make_tasks(root, workflow="import")
    other = root / f"model/{ENV}/{TARGET}/sqs.properties"
    actual = outcome(lambda: sources.load_model(other))
    with tasks.task_reads(root):
        assert actual == outcome(lambda: sources.load_model(other))
    assert actual == (
        ValueError,
        "IMPORT reference is outside selected environment/target/service",
    )


def check_stage_uses_project_contract_and_not_definitions(project, tmp_path_factory):
    root, models = project
    stage = tmp_path_factory.mktemp("stage")
    definitions = tmp_path_factory.mktemp("definitions")
    make_tasks(root, workflow="import")
    make_tasks(stage, service="sqs", workflow="import")
    make_tasks(definitions, service="cloudwatch-logs", workflow="import")
    shutil.copytree(root / "model", stage / "model")
    shutil.copy(root / "project.json", stage / "project.json")
    path = stage / f"docs/designs/{ENV}/{TARGET}/s3.md"
    with change_scope.index_stage(root, stage), task_io() as io:
        assert permissions.selected(stage) == (ENV, TARGET, "s3")
        # Independent operations each obtain a fresh Project snapshot.
        assert sources.load_model(stage / f"model/{ENV}/{TARGET}/s3.properties").values
        generated = render.generate_markdown(path, models["s3"], definitions)
        model_reference_tables(
            path, generated, tuple(models["s3"].items()), definitions
        )
        assert all(call.args[0] == root for call in io.catalog.call_args_list)
        assert io.catalog.call_count == 4
        with tasks.task_reads(root):
            io.catalog.reset_mock()
            io.read.reset_mock()
            sources.load_model(stage / f"model/{ENV}/{TARGET}/s3.properties")
            render.generate_markdown(path, models["s3"], definitions)
            once(io, root)
    assert sources.project_root(stage) == stage


@pytest.mark.parametrize(
    "operation",
    [
        "comparison-init",
        "comparison-run",
        "coverage",
        "aws",
        "observed",
        "destroy",
        "issues",
    ],
)
def check_command_io_budget(project, operation):
    root, _ = project
    paths = sources.model_paths(root, ENV, TARGET)
    items = [(aws.targets(root, ENV, TARGET)[0], path) for path in paths]
    stacks = [f"cfn-stack-app-dev-data{i}" for i in range(1, 4)]
    comparison = Comparison(root, ENV, TARGET, ["s3", "sqs"])
    with task_io() as io:
        if operation == "comparison-init":
            Comparison(
                root=root, environment=ENV, directory=TARGET, services=["s3", "sqs"]
            )
        elif operation == "comparison-run":
            comparison.run()
        elif operation == "coverage":
            assert aws.coverage(root, items)["modelCount"] == len(items)
        elif operation == "aws":
            # SDK transport only is replaced; Model loading/comparison still runs.
            with (
                patch.object(aws.Context, "verify"),
                patch.object(aws.Context, "call", return_value={}),
            ):
                assert aws.run(root, items)["results"]
        elif operation == "observed":
            with pytest.raises(observed.MappingError, match="task scope violation"):
                observed.preflight(root, ENV, TARGET, stacks)
        elif operation == "destroy":
            assert destroy.local_plan(root, ENV, TARGET, stacks, check_scope=False)[
                "units"
            ]
        else:
            with patch.object(
                issues._imports_issues_cfn_lint,
                "run_lint",
                side_effect=lambda comparison, result: result,
            ):
                assert issues.scan(root, ENV, TARGET, ["s3", "sqs"], jobs=1)
        # Live validation is intentionally counted separately by existing snapshot UTs.
        once(io, root)
    assert tasks._read_contracts.get() is None


def check_preparation_io_budget(tmp_path):
    root = tmp_path / "project"
    preparation_fixture(root)
    make_tasks(root)
    output = tmp_path / "preparation"
    output.mkdir()
    args = SimpleNamespace(
        task_file="tasks/deploy-offline.md",
        service=["ec2", "iam"],
        environment=ENV,
        aws_account_id=TARGET,
        alias=None,
        profile=None,
        stack=["cfn-stack-app-dev-one", "cfn-stack-app-dev-two"],
        sequential=False,
    )
    timing = preparation.Timing(root, tmp_path / "timing.jsonl")
    with patch.object(preparation, "environment", return_value={}), task_io() as io:
        assert preparation.prepare(root, args, output, timing)["scope"]
        once(io, root)
    assert tasks._read_contracts.get() is None


@pytest.mark.parametrize("operation", ["init", "run"])
@pytest.mark.parametrize("outer_scope", [False, True])
def check_comparison_stage_reuses_project_snapshot(
    project, tmp_path_factory, operation, outer_scope
):
    root, _ = project
    stage = tmp_path_factory.mktemp("comparison-stage") / "project"
    shutil.copytree(root, stage)
    make_tasks(stage, workflow="import", service="cloudwatch-logs")
    expected = Comparison(root, ENV, TARGET, ["s3", "sqs"]).run()
    with change_scope.index_stage(root, stage):
        comparison = Comparison(stage, ENV, TARGET, ["s3", "sqs"])
        with (
            task_io() as io,
            tasks.task_reads(root) if outer_scope else nullcontext() as parent,
        ):
            if outer_scope:
                tasks.contract_snapshot(root)
            if operation == "init":
                comparison = Comparison(stage, ENV, TARGET, ["s3", "sqs"])
                assert not comparison.load_errors
                assert set(comparison.models) == {"s3", "sqs"}
            else:
                assert comparison.run() == expected
            once(io, root)
            assert tasks._read_contracts.get() is parent
    assert tasks._read_contracts.get() is None


if __name__ == "__main__":
    raise SystemExit(run(__file__))
