#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contextlib import chdir
from unittest import TestCase

import model.sources as _imports_model_sources
from support.deploy_preparation_fixtures import (
    ROOT,
    STACKS,
    TARGET,
    M,
    Path,
    arguments,
    contracts,
    fixture,
    hashlib,
    invoke,
    io,
    json,
    patch,
    paths_in,
    redirect_stderr,
    subprocess,
    sys,
    tempfile,
    zipfile,
)
from support.it_case_receipt import it_case

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def check_preparation():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory).resolve()
        root = base / "repo"
        fixture(root)
        inventory = root / "issues/dev/123456789012/issues.md"
        inventory.parent.mkdir(parents=True)
        inventory.write_text(
            "### ec2\n1. ERROR: Framework diagnostic\n", encoding="utf-8"
        )
        original = {
            p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
        }
        with chdir(root):
            assert invoke(arguments(root, base)[2:]) == 0
        run = next((base / "logs").iterdir())
        path = run / "preparation.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert {
            p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
        } == original
        assert plan["controllerArgv"].count("--stack") == 2
        assert "--repository-root" not in plan["controllerArgv"]
        assert not (root / "framework").exists()
        assert (
            "--sequential" in plan["controllerArgv"]
            and "--timing-log" in plan["controllerArgv"]
        )
        assert plan["controllerArgv"][0] == sys.executable
        assert plan["scope"] == [
            "dev/123456789012/ec2",
            "dev/123456789012/iam",
        ]
        text = (run / "contract.md").read_text(encoding="utf-8")
        TestCase().assertEqual(text.count("- Deploy execution method: `sdk`\n"), 1)
        declared = paths_in(text, "## Modified files")
        assert "model/dev/123456789012/cloudformation-stacks.properties" not in declared
        model_parts = _imports_model_sources.model_parts
        outputs = {
            p.relative_to(root).as_posix()
            for p in model_parts(root / "model/dev/123456789012/ec2.properties")
        }
        assert outputs <= declared
        assert "model/dev/123456789012/iam.properties" in declared
        assert not any(
            p.endswith(("observed.json", "source.json", ".tpl")) for p in declared
        )
        assert not {p for p in declared if p.startswith("infra/")}
        assert "- Runtime recovery: `allowed`" in text
        assert "--state" not in plan["controllerArgv"]
        assert "documents" not in plan and not (run / "documents").exists()
        assert Path(plan["contract"]) == run / "contract.md"
        assert Path(plan["targetSummary"]) == run / "target-summary.json"
        generated = {
            "docs/designs/dev/123456789012/" + name
            for name in (
                "ec2.md",
                "iam.md",
                "iam/worker-role-trust-policy.json",
            )
        }
        assert plan["generatedViews"] == sorted(generated)
        TestCase().assertFalse(generated & plan["inputIdentities"].keys())
        TestCase().assertFalse(generated & plan["inputs"].keys())
        TestCase().assertLessEqual(generated, declared)
        for relative, digest in plan["inputs"].items():
            assert (
                digest
                == hashlib.sha256(
                    (
                        (
                            ROOT
                            if relative.startswith(("framework/", ".agents/"))
                            else root
                        )
                        / relative
                    ).read_bytes()
                ).hexdigest()
            )
        entrance = root / "model/dev/123456789012/ec2.properties"
        TestCase().assertTrue(
            all(
                p.relative_to(root).as_posix()
                in plan["inputIdentities"] | plan["inputs"]
                for p in model_parts(entrance)
            )
        )
        assert all(name in plan["controllerArgv"] for name in STACKS)
        assert (
            plan["controllerArgv"][plan["controllerArgv"].index("--action") + 1]
            == "advance"
        )
        (root / "AGENTS.md").write_text("changed instructions", encoding="utf-8")
        assert invoke(["--repository-root", str(root), "--register", str(path)]) == 0
        registered = contracts(root)["tasks/deploy-offline.md"]
        TestCase().assertIn("- Deploy execution method: `sdk`\n", registered)
        assert paths_in(registered, "## Modified files") == paths_in(
            text, "## Modified files"
        )
        plan = json.loads(path.read_text(encoding="utf-8"))
        events = [
            json.loads(line) for line in (run / "timing.jsonl").read_text().splitlines()
        ]
        assert {
            "environment",
            "contractPreparation",
            "inputSnapshot",
            "contractReview",
            "contractRegistration",
        } <= {e["phase"] for e in events}
        assert all(e["result"] == "PASS" and e["seconds"] >= 0 for e in events)
        assert all("aws" not in e["phase"].lower() for e in events)
        (run / "session.json").write_text("{}", encoding="utf-8")
        with (
            patch.object(
                subprocess,
                "run",
                return_value=subprocess.CompletedProcess(plan["controllerArgv"], 0),
            ) as launch,
            redirect_stderr(io.StringIO()),
        ):
            assert (
                M.main(["--repository-root", str(root), "--run-controller", str(path)])
                == 0
            )
            assert launch.call_args.args[0] == plan["controllerArgv"]
            assert not any("session" in arg for arg in launch.call_args.args[0])
        assert (run / "session.json").read_text(encoding="utf-8") == "{}"
        alias_root = base / "alias-repo"
        fixture(alias_root)
        for prefix in ("model", "docs/designs", "infra/cloudformation/parameters"):
            original_path = alias_root / prefix / "dev/123456789012"
            original_path.rename(original_path.with_name("app"))
        alias_template = alias_root / "infra/cloudformation/templates/app/shared.yaml"
        alias_template.parent.mkdir()
        alias_template.write_bytes(
            (alias_root / "infra/cloudformation/templates/shared.yaml").read_bytes()
        )
        (alias_root / "project.json").write_text(
            json.dumps(
                {
                    "projectName": "test",
                    "targets": [TARGET | {"alias": "app"}, TARGET | {"alias": "other"}],
                }
            ),
            encoding="utf-8",
        )
        alias_base = base / "alias-logs"
        args = arguments(alias_root, alias_base)
        selector = args.index("--aws-account-id")
        args[selector : selector + 2] = ["--alias", "app"]
        second = args.index(STACKS[1])
        del args[second - 1 : second + 1]
        service = args.index("ec2")
        del args[service - 1 : service + 1]
        assert invoke(args) == 0
        alias_run = next((alias_base / "logs").iterdir())
        alias_plan = json.loads((alias_run / "preparation.json").read_text())
        assert alias_plan["controllerArgv"].count("--stack") == 1
        TestCase().assertIn("dev/app/iam", alias_plan["scope"])
        assert (
            invoke(
                [
                    "--repository-root",
                    str(alias_root),
                    "--register",
                    str(alias_run / "preparation.json"),
                ]
            )
            == 0
        )
        with patch.object(
            subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ) as alias_launch:
            assert (
                M.main(
                    [
                        "--repository-root",
                        str(alias_root),
                        "--run-controller",
                        str(alias_run / "preparation.json"),
                    ]
                )
                == 0
            )
            assert alias_launch.call_args.kwargs["cwd"] == alias_root
        print("Offline preparation: input fingerprints and timing verified")


def _callback_check_generated_boundaries_load_with_artifacts(
    real_load, /, *args, **kwargs
):
    limit, units = real_load(*args, **kwargs)
    units[0]["artifacts"] = [
        {
            "source": "infra/cloudformation/artifacts/execution.json",
            "property": "DefinitionS3Location",
        },
        {"source": "infra/cloudformation/artifacts/build.zip", "property": "Code"},
    ]
    return limit, units


@it_case
def check_generated_boundaries():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory).resolve()
        root = base / "repo"
        fixture(root)
        # Exact generation authority requires readable Model rows, never saved View content.
        real_load = M.load_units
        artifacts = root / "infra/cloudformation/artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "execution.json").write_text(
            '{"StartAt":"Done"}', encoding="utf-8"
        )
        with zipfile.ZipFile(artifacts / "build.zip", "w") as archive:
            archive.writestr("main.py", "pass")
        load_with_artifacts = _bind_framework_callback(
            _callback_check_generated_boundaries_load_with_artifacts, real_load
        )
        with patch.object(M, "load_units", side_effect=load_with_artifacts):
            assert invoke(arguments(root, base)) == 0
        run = next((base / "logs").iterdir())
        plan = json.loads((run / "preparation.json").read_text(encoding="utf-8"))
        assert (
            "infra/cloudformation/artifacts/execution.json" in plan["inputIdentities"]
        )
        assert "infra/cloudformation/artifacts/build.zip" in plan["inputIdentities"]
        assert "infra/cloudformation/artifacts/build.zip" not in plan["generatedViews"]
        for relative, digest in plan["inputs"].items():
            assert digest == M.sha(
                (ROOT if relative.startswith(("framework/", ".agents/")) else root)
                / relative
            )


@it_case
def check_order_scope_preparation():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory).resolve()
        root = base / "repo"
        fixture(root)
        args = [
            "--repository-root",
            str(root),
            "--environment",
            "dev",
            "--aws-account-id",
            "123456789012",
            "--order-to",
            "10",
            "--task-file",
            "tasks/deploy-order.md",
            "--log-dir",
            str(base / "logs"),
        ]
        TestCase().assertEqual(invoke(args), 0)
        run = next((base / "logs").iterdir())
        plan = json.loads((run / "preparation.json").read_text(encoding="utf-8"))
        TestCase().assertEqual(plan["scope"], ["dev/123456789012/iam"])
        argv = plan["controllerArgv"]
        TestCase().assertEqual(argv.count("--stack"), 1)
        TestCase().assertEqual(argv[argv.index("--stack") + 1], STACKS[0])
        TestCase().assertNotIn(STACKS[1], argv)
        TestCase().assertIn(
            f"`{STACKS[0]}`", (run / "contract.md").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    from support.model_sources import catalog_display

    with catalog_display():
        check_preparation()
        check_generated_boundaries()
        check_order_scope_preparation()
        print("Deployment preparation checks: PASS")
