#!/usr/bin/env python3
"""Source discovery, runtime reconciliation and revision reduction fault injection."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import run_it
from support.it_discovery import discover
from support.it_revision import compare_revisions, node_difference
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


DIRECT = "from support.it_case_receipt import it_case\n@it_case\ndef check_one():\n    pass\ncheck_one()\n"
PYTEST = "from support.pytest_cli import run\ndef check_one():\n    pass\nif __name__ == '__main__':\n    raise SystemExit(run(__file__))\n"


def tree(root, source=PYTEST):
    tests = root / "framework/scripts/tests"
    (tests / "integrations").mkdir(parents=True)
    (tests / "integrations/example.checks.py").write_text(source, encoding="utf-8")
    (tests / "pytest.ini").write_text(
        "[pytest]\npython_functions = check_* test_*\naddopts = --import-mode=importlib -p no:cacheprovider\n",
        encoding="utf-8",
    )
    return tests


def receipt(
    suite="integrations/example.checks.py", collected=(), passed=(), completed=None
):
    return {
        "version": 1,
        "suite": suite,
        "collected": list(collected),
        "passed": list(passed),
        "completed": completed or {},
        "metrics": {},
    }


def check_empty_and_no_suites(tmp_path):
    empty = discover(tmp_path)
    assert any("empty IT discovery" in error for error in empty.errors)
    tests = tree(tmp_path, DIRECT)
    (tests / "integrations/example.checks.py").rename(tests / "integrations/helper.py")
    assert any("No integration suites" in error for error in discover(tests).errors)
    (tests / "integrations/empty.checks.py").write_text("pass\n", encoding="utf-8")
    assert any("empty IT suite" in error for error in discover(tests).errors)


@pytest.mark.parametrize(
    "source,message",
    [
        ("def check_one():\n    pass\ncheck_one()\n", "decorator"),
        (DIRECT.replace("@it_case", "@other\n@it_case"), "decorator"),
        (DIRECT.replace("@it_case", "@it_case()"), "decorator"),
        (DIRECT.rsplit("check_one()", 1)[0], "orphan"),
        (DIRECT + "def check_one():\n    pass\n", "duplicate"),
        (DIRECT + "def test_orphan():\n    pass\n", "responsibility"),
        (
            "from support.it_case_receipt import module_complete\npass\n",
            "terminal module",
        ),
        (
            "from support.it_case_receipt import module_complete\nmodule_complete(__file__)\npass\n",
            "terminal module",
        ),
        ("def broken(:\n", "cannot discover"),
        (DIRECT + "value = 'integrations.foo.checks'\n", "module dependency"),
    ],
)
def check_discovery_faults(tmp_path, source, message):
    tests = tree(tmp_path, source)
    assert any(message in error for error in discover(tests).errors)


def check_discovery_has_no_execution_and_alias(tmp_path):
    tests = tree(
        tmp_path,
        PYTEST.replace("check_one", "body").replace(
            "if __name__", "test_alias = body\nif __name__"
        )
        + "raise RuntimeError('discovery must never execute this')\n",
    )
    discovery = discover(tests)
    assert not discovery.errors, discovery.errors
    assert discovery.cases == {
        ("integrations/example.checks.py", "test_alias"): "pytest"
    }
    entry = tests / "integrations/example.checks.py"
    entry.write_text(entry.read_text() + "test_alias = body\n", encoding="utf-8")
    assert any("duplicate" in error for error in discover(tests).errors)


def check_helper_ownership_and_completion(tmp_path):
    tests = tree(
        tmp_path,
        DIRECT + "from integrations.helper import check_helper\ncheck_helper()\n",
    )
    (tests / "integrations/helper.py").write_text(
        DIRECT.replace("check_one", "check_helper"), encoding="utf-8"
    )
    discovery = discover(tests)
    assert not discovery.errors, discovery.errors
    assert discovery.suites == ("integrations/example.checks.py",)
    helper = "integrations/helper.py::check_helper"
    own = "integrations/example.checks.py::check_one"
    data = receipt(completed={own: 2, helper: 3})
    assert not run_it.reachability(discovery.cases, [data], owners=discovery.owners)
    assert run_it.reachability(
        discovery.cases, [receipt(completed={own: 2})], owners=discovery.owners
    )
    assert run_it.reachability(
        discovery.cases,
        [{**data, "suite": "integrations/foreign.checks.py"}],
        owners=discovery.owners,
    )
    source = tests / "integrations/example.checks.py"
    source.write_text(
        DIRECT + "def test_helper():\n    pass\ntest_helper()\n", encoding="utf-8"
    )
    assert not any("test_helper" in error for error in discover(tests).errors)


def check_exact_nodes_and_receipt_errors():
    suite = "integrations/example.checks.py"
    key = suite + "::check_one"
    cases = {(suite, "check_one"): "pytest"}
    data = receipt(
        collected=[key + "[a]", key + "[b]"], passed=[key + "[a]", key + "[b]"]
    )
    assert not run_it.reachability(cases, [data])
    for invalid in (
        receipt(),
        {**data, "passed": data["passed"][:1]},
        {**data, "passed": data["passed"] + [key + "[unknown]"]},
        {**data, "collected": data["collected"] * 2},
        {**data, "completed": {suite + "::unknown": 1}},
        {**data, "suite": "integrations/foreign.checks.py"},
    ):
        assert run_it.reachability(cases, [invalid])
    assert run_it.reachability(cases, [data, data])
    assert run_it.reachability(cases, [])
    # An entire expected function missing cannot hide behind matching node counts.
    assert run_it.reachability({**cases, (suite, "check_missing"): "pytest"}, [data])
    partial = {(suite, "check_one"): "pytest"}
    assert not run_it.reachability(
        partial, [data], {**partial, (suite, "check_peer"): "pytest"}
    )


@pytest.mark.parametrize("body", ["pytest.skip('skip')", "assert False"])
def check_real_skip_and_failure(tmp_path, body):
    tests = tree(
        tmp_path, "import pytest\n" + PYTEST.replace("    pass", "    " + body)
    )
    output = tmp_path / "receipts"
    output.mkdir()
    rows, receipts = run_it.execute_suites(tests, output, sys.stdout)
    assert run_it.reachability(discover(tests).cases, receipts)
    assert rows[0]["code"] == (0 if "skip" in body else 1)


@pytest.mark.parametrize("data_file", [False, True])
def check_revision_parameter_reduction(tmp_path, data_file):
    source = "import pytest\n" + PYTEST.replace(
        "def check_one", "@pytest.mark.parametrize('value', [1, 2])\ndef check_one"
    ).replace("check_one():", "check_one(value):")
    before = tree(tmp_path / "before", source)
    after = tree(tmp_path / "after", source.replace("[1, 2]", "[1]"))
    if data_file:
        source = "import json\nfrom pathlib import Path\n" + source.replace(
            "[1, 2]",
            "json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))",
        )
        for tests, values in ((before, "[1, 2]"), (after, "[1]")):
            (tests / "integrations/example.checks.py").write_text(
                source, encoding="utf-8"
            )
            (tests / "integrations/example.checks.json").write_text(
                values, encoding="utf-8"
            )
    result = compare_revisions(before, after)
    assert result["review_required"]
    assert result["entries"] == {"removed": [], "added": []}
    assert result["pytest_nodes"]["removed"] == [
        "integrations/example.checks.py::check_one[2]"
    ]
    with patch(
        "support.it_revision.collect_nodes",
        side_effect=AssertionError("unnecessary collection"),
    ):
        result = compare_revisions(before, before)
    assert not result["review_required"]
    assert node_difference(iter(["old"]), iter(["renamed"])) == {
        "removed": ["old"],
        "added": ["renamed"],
    }


def check_revision_removed_and_renamed_entries(tmp_path):
    before = tree(tmp_path / "before", DIRECT)
    after = tree(tmp_path / "after", DIRECT.replace("check_one", "check_renamed"))
    result = compare_revisions(before, after)
    assert result["entries"] == {
        "removed": ["integrations/example.checks.py::check_one"],
        "added": ["integrations/example.checks.py::check_renamed"],
    }
    assert result["review_required"]
    (before.parent / "requirements.txt").write_text("pytest==old", encoding="utf-8")
    with pytest.raises(ValueError, match="not verified"):
        compare_revisions(before, after)


def check_helper_direct_real_receipt(tmp_path):
    tests = tree(
        tmp_path, "from integrations.helper import check_helper\ncheck_helper()\n"
    )
    # The suite's own module marker gives the script a completion boundary.
    entry = tests / "integrations/example.checks.py"
    entry.write_text(
        entry.read_text()
        + "from support.it_case_receipt import module_complete\nmodule_complete(__file__)\n",
        encoding="utf-8",
    )
    (tests / "integrations/helper.py").write_text(
        DIRECT.replace("check_one", "check_helper"), encoding="utf-8"
    )
    discovery = discover(tests)
    assert not discovery.errors, discovery.errors
    output = tmp_path / "receipts"
    output.mkdir()
    rows, receipts = run_it.execute_suites(tests, output, sys.stdout)
    assert not any(row["code"] for row in rows)
    assert not run_it.reachability(discovery.cases, receipts, owners=discovery.owners)


def check_comparison_cli_does_not_run_suites(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    with (
        patch.object(sys, "argv", ["run_it.py", "--compare-root", str(tmp_path)]),
        patch.object(
            run_it, "compare_revisions", return_value={"review_required": True}
        ) as compare,
        patch.object(run_it, "run_all") as execute,
    ):
        assert run_it.main() == 0
    compare.assert_called_once_with(tmp_path / "framework/scripts/tests", run_it.TESTS)
    execute.assert_not_called()
    assert '"review_required": true' in capsys.readouterr().out
    assert '"review_required": true' in (tmp_path / "summary.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("errors,code", [([], 0), (["missing"], 0), ([], 1)])
def check_it_only_skips_ut_and_preserves_it_failures(errors, code, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    outcome = {"reachability_errors": errors, "suites": [{"code": code}]}
    with (
        patch.object(sys, "argv", ["run_it.py", "--it-only"]),
        patch.object(run_it._imports_validation_loop, "select_checks") as select,
        patch.object(run_it._imports_validation_loop, "run_commands") as units,
        patch.object(run_it, "run_all", return_value=outcome) as integrations,
    ):
        assert run_it.main() == int(bool(errors or code))
    select.assert_not_called()
    units.assert_not_called()
    integrations.assert_called_once()


def check_it_only_cannot_combine_with_ut_only():
    with (
        patch.object(sys, "argv", ["run_it.py", "--it-only", "--ut-only"]),
        pytest.raises(SystemExit) as error,
    ):
        run_it.main()
    assert error.value.code == 2


def check_it_only_baseline_runs_both_it_sides(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    tests = tree(tmp_path)
    (tests.parent / "requirements.txt").write_bytes(
        (run_it.TESTS.parent / "requirements.txt").read_bytes()
    )
    outcome = {"seconds": 1, "reachability_errors": [], "suites": []}
    with (
        patch.object(sys, "argv", ["run_it.py", "--it-only", "--baseline-root", str(tmp_path)]),
        patch.object(run_it._imports_validation_loop, "run_commands") as units,
        patch.object(run_it, "run_all", return_value=outcome) as integrations,
    ):
        assert run_it.main() == 0
    units.assert_not_called()
    assert integrations.call_count == 2
    assert integrations.call_args_list[0].args[0] == tests
    assert integrations.call_args_list[0].kwargs == {"baseline": True}
    assert integrations.call_args_list[1].args[0] == run_it.TESTS


def _callback_change_collection_input(tests, suite, output):
    (tests / "integrations/example.checks.py").write_text(
        PYTEST + "# changed during collection\n", encoding="utf-8"
    )
    return [suite + "::check_one"]


def check_revision_rejects_changed_inputs(tmp_path):
    before = tree(tmp_path / "before")
    after = tree(tmp_path / "after", PYTEST + "# candidate\n")
    with (
        patch(
            "support.it_revision.collect_nodes",
            side_effect=_callback_change_collection_input,
        ),
        pytest.raises(ValueError, match="inputs changed"),
    ):
        compare_revisions(before, after)


@pytest.mark.parametrize("suffix", [".csv", ".fixture", ""])
def check_revision_reduction_from_arbitrary_fixture_formats(tmp_path, suffix):
    source = (
        "import csv\nfrom pathlib import Path\nimport pytest\n"
        + f"values = [int(row[0]) for row in csv.reader(Path(__file__).with_name('parameters{suffix}').read_text(encoding='utf-8').splitlines())]\n"
        + PYTEST.replace(
            "def check_one", "@pytest.mark.parametrize('value', values)\ndef check_one"
        ).replace("check_one():", "check_one(value):")
    )
    before = tree(tmp_path / "before", source)
    after = tree(tmp_path / "after", source)
    for tests, values in ((before, "1\n2\n"), (after, "1\n")):
        (tests / "integrations" / ("parameters" + suffix)).write_text(
            values, encoding="utf-8"
        )
    assert (before / "integrations/example.checks.py").read_bytes() == (
        after / "integrations/example.checks.py"
    ).read_bytes()
    result = compare_revisions(before, after)
    assert result["collection"] == "compared"
    assert result["review_required"]
    assert result["entries"] == {"removed": [], "added": []}
    assert result["pytest_nodes"]["removed"] == [
        "integrations/example.checks.py::check_one[2]"
    ]


@pytest.mark.parametrize("cache", ["__pycache__", ".pytest_cache"])
def check_revision_ignores_generated_caches(tmp_path, cache):
    before = tree(tmp_path / "before")
    after = tree(tmp_path / "after")
    for tests, value in ((before, b"old cache"), (after, b"new cache")):
        directory = tests / cache
        directory.mkdir()
        (directory / "cached-data").write_bytes(value)
    with patch(
        "support.it_revision.collect_nodes",
        side_effect=AssertionError("cache output must not trigger collection"),
    ):
        result = compare_revisions(before, after)
    assert not result["review_required"]
    assert result["collection"].startswith("unchanged")


@pytest.mark.parametrize(
    "statement,call,expected",
    [
        ("from support.pytest_cli import run as execute", "execute", True),
        ("import support.pytest_cli as cli", "cli.run", True),
        ("import support.pytest_cli", "support.pytest_cli.run", True),
        ("import unrelated as cli", "cli.run", False),
        ("from unrelated import run as execute", "execute", False),
        ("import unrelated as pytest", "pytest.main", False),
    ],
)
def check_pytest_runner_import_aliases(tmp_path, statement, call, expected):
    source = PYTEST.replace("from support.pytest_cli import run", statement).replace(
        "run(__file__)", call + "(__file__)"
    )
    tests = tree(tmp_path, source)
    discovery = discover(tests)
    if expected:
        assert not discovery.errors, discovery.errors
        assert discovery.cases == {
            ("integrations/example.checks.py", "check_one"): "pytest"
        }
    else:
        assert any("unknown execution" in error for error in discovery.errors)


def check_pytest_runner_module_alias_in_fixture_wrapper(tmp_path):
    tests = tree(
        tmp_path,
        PYTEST.replace(
            "from support.pytest_cli import run", "from support.cli_fixture import main"
        ).replace("run(__file__)", "main(__file__)"),
    )
    support = tests / "support"
    support.mkdir()
    (support / "cli_fixture.py").write_text(
        "import support.pytest_cli as cli\ndef main(path):\n    return cli.run(path)\n",
        encoding="utf-8",
    )
    discovery = discover(tests)
    assert not discovery.errors, discovery.errors
    assert discovery.cases == {
        ("integrations/example.checks.py", "check_one"): "pytest"
    }


if __name__ == "__main__":
    raise SystemExit(run(__file__))
