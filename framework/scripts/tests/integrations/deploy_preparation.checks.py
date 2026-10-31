#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contextlib import chdir
from unittest import TestCase

import model.format as _imports_model_format
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
    read_model,
    redirect_stderr,
    subprocess,
    sys,
    tempfile,
    write_model,
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
        assert "- External IaC repair: `forbidden`" in text
        assert (
            "Deploy repair session" not in text
            and "--state" not in plan["controllerArgv"]
        )
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
        assert all(
            p.relative_to(root).as_posix() in plan["inputIdentities"]
            for p in model_parts(entrance)
        )
        assert all(name in plan["controllerArgv"] for name in STACKS)
        assert (
            plan["controllerArgv"][plan["controllerArgv"].index("--action") + 1]
            == "advance"
        )
        (root / "AGENTS.md").write_text("changed instructions", encoding="utf-8")
        assert invoke(["--repository-root", str(root), "--register", str(path)]) == 0
        registered = contracts(root)["tasks/deploy-offline.md"]
        assert paths_in(registered, "## Modified files") == paths_in(
            text, "## Modified files"
        )
        assert (
            invoke(arguments(root, base)) == 1
        )  # Registered tasks keep the existing resume path.
        with patch.object(
            subprocess,
            "run",
            return_value=subprocess.CompletedProcess(plan["controllerArgv"], 2),
        ) as launch:
            assert (
                M.main(["--repository-root", str(root), "--run-controller", str(path)])
                == 2
            )
            assert (
                launch.call_count == 1
                and launch.call_args.args[0] == plan["controllerArgv"]
            )
            assert (
                launch.call_args.kwargs["env"]["BLUEPRINT_TASK_FILE"]
                == "tasks/deploy-offline.md"
            )
        plan = json.loads(path.read_text(encoding="utf-8"))
        original_command = plan["controllerArgv"][:]
        for command in (
            [str(base / "other-python"), *original_command[1:]],
            [
                original_command[0],
                str(base / "other-controller.py"),
                *original_command[2:],
            ],
            [
                *original_command[:2],
                "--repository-root",
                str(root),
                *original_command[2:],
            ],
            [*original_command, "--repository-root=" + str(root)],
        ):
            plan["controllerArgv"] = command
            path.write_text(json.dumps(plan), encoding="utf-8")
            with (
                patch.object(
                    subprocess,
                    "run",
                    side_effect=AssertionError("foreign Project launched"),
                ),
                redirect_stderr(io.StringIO()),
            ):
                assert (
                    M.main(
                        ["--repository-root", str(root), "--run-controller", str(path)]
                    )
                    == 1
                )
        plan["controllerArgv"] = original_command
        for field, value in (
            ("repository", str(base / "other")),
            ("registeredContractDigest", "changed"),
        ):
            saved = plan[field]
            plan[field] = value
            path.write_text(json.dumps(plan), encoding="utf-8")
            with (
                patch.object(
                    subprocess,
                    "run",
                    side_effect=AssertionError("unapproved plan launched"),
                ),
                redirect_stderr(io.StringIO()),
            ):
                assert (
                    M.main(
                        ["--repository-root", str(root), "--run-controller", str(path)]
                    )
                    == 1
                )
            plan[field] = saved
        path.write_text(json.dumps(plan), encoding="utf-8")
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
        assert invoke(args) == 0
        alias_run = next((alias_base / "logs").iterdir())
        alias_plan = json.loads((alias_run / "preparation.json").read_text())
        assert alias_plan["controllerArgv"].count("--stack") == 1
        assert "dev/app/ec2" in alias_plan["scope"]
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


@it_case
def check_registration_input_changes():
    for reason in (
        "runtime",
        "project",
        "stack",
        "iac",
        "parameters",
        "candidate",
        "model",
        "markdown-change",
        "markdown-delete",
        "json-change",
        "json-delete",
    ):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "repo"
            fixture(root)
            assert invoke(arguments(root, base)) == 0
            run = next((base / "logs").iterdir())
            path = run / "preparation.json"
            if reason.startswith(("markdown-", "json-")):
                generated = (
                    root
                    / "docs/designs/dev/123456789012"
                    / (
                        "iam/worker-role-trust-policy.json"
                        if reason.startswith("json-")
                        else "ec2.md"
                    )
                )
                if reason.endswith("delete"):
                    generated.unlink()
                else:
                    generated.write_text("changed", encoding="utf-8")
            elif reason in {"project", "stack", "iac", "parameters"}:
                source = (
                    root
                    / {
                        "project": "project.json",
                        "stack": "model/dev/123456789012/cloudformation-stacks.properties",
                        "iac": "infra/cloudformation/templates/shared.yaml",
                        "parameters": "infra/cloudformation/parameters/dev/123456789012/1.json",
                    }[reason]
                )
                source.write_text(source.read_text() + "\nchanged", encoding="utf-8")
            elif reason == "model":
                source = root / "model/dev/123456789012/iam.properties"
                write_model(source, read_model(source) + "# changed\n")
            elif reason == "candidate":
                (run / "contract.md").write_text("changed", encoding="utf-8")
            with (
                patch.dict(M.os.environ, {"PATH": "changed"})
                if reason == "runtime"
                else patch.dict(M.os.environ, {})
            ):
                result = invoke(
                    ["--repository-root", str(root), "--register", str(path)]
                )
                TestCase().assertEqual(
                    result,
                    0 if reason.startswith(("markdown-", "json-")) else 1,
                    reason,
                )
            TestCase().assertEqual(
                json.loads((run / "timing.jsonl").read_text().splitlines()[-1])[
                    "result"
                ],
                "PASS" if reason.startswith(("markdown-", "json-")) else "FAIL",
            )


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
        source = root / "model/dev/123456789012/iam.properties"
        serialize = _imports_model_format.serialize
        load_model = _imports_model_sources.load_model
        original = serialize(load_model(source).authoritative)
        # Exact generation authority requires readable Model rows, never saved View content.
        source.write_text("invalid unrelated service body", encoding="utf-8")
        with TestCase().assertRaises(ValueError):
            M.candidate(
                root,
                "tasks/deploy-offline.md",
                "dev",
                "123456789012",
                TARGET,
                STACKS,
                ["iam"],
            )
        source.write_text(original, encoding="utf-8")
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
        with (
            patch.object(
                M,
                "paths",
                return_value=(
                    root
                    / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json",
                    artifacts / "execution.json",
                ),
            ),
            patch.object(
                M,
                "deployment_input_paths",
                return_value=[
                    root
                    / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json"
                ],
            ),
        ):
            output = io.StringIO()
            with redirect_stderr(output):
                assert M.main(arguments(root, base)) == 1
            assert (
                "generated view conflicts with execution/required input"
                in output.getvalue()
            )
        parameter = root / "infra/cloudformation/parameters/dev/123456789012/1.json"
        parameter.unlink()
        parameter.symlink_to(parameter.with_name("2.json"))
        output = io.StringIO()
        with redirect_stderr(output):
            assert M.main(arguments(root, base)) == 1
        assert "task path must not use symlinks" in output.getvalue()


if __name__ == "__main__":
    from support.model_sources import catalog_display

    with catalog_display():
        check_preparation()
        check_registration_input_changes()
        check_generated_boundaries()
        print("Deployment preparation checks: PASS")
