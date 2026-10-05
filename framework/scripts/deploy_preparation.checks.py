#!/usr/bin/env python3
"""Offline preparation, reservation, dependency and timing regressions; no consumer/AWS."""
if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import deploy_preparation as M
from model_design import markdown_for
from model_files import model_file_contents
from task_contract import contracts, paths_in, start

ROOT = Path(__file__).resolve().parents[2]
TARGET = {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
STACKS = ["cfn-stack-app-dev-one", "cfn-stack-app-dev-two"]


def fixture(root):
    (root / "framework/scripts").mkdir(parents=True)
    for name in ("sync-model.py", "cloudformation-deploy.py", "check-deploy-context.py", "task_contract.py", "requirements-aws-compare.txt"):
        shutil.copy(ROOT / "framework/scripts" / name, root / "framework/scripts" / name)
    shutil.copytree(ROOT / "framework/rules", root / "framework/rules")
    (root / "framework/prompts/codex").mkdir(parents=True)
    shutil.copy(ROOT / "framework/prompts/codex/04_deploy.md", root / "framework/prompts/codex/04_deploy.md")
    for name in ("AGENTS.md", "README.md"):
        shutil.copy(ROOT / name, root / name)
    (root / "project.json").write_text(json.dumps({"targets": [TARGET]}), encoding="utf-8")
    model = root / "model/dev/123456789012"
    model.mkdir(parents=True)
    design = root / "docs/designs/dev/123456789012"
    design.mkdir(parents=True)
    values = {"desired.deployment.maxConcurrentStacks": "2"}
    for i, name in enumerate(STACKS, 1):
        values.update({f"desired.stack.{i:03d}.{key}": value for key, value in {
            "name": name, "template": "shared.yaml", "parameters": f"{i}.json", "deployOrder": str(i * 10)}.items()})
        values[f"display.stack.{i:03d}.comment"] = "アプリケーションの配置"
    (model / "cloudformation-stacks.properties").write_text("\n".join(f"{k}={v}" for k, v in values.items()), encoding="utf-8")
    view = design / "cloudformation-stacks.md"
    view.write_text(markdown_for(view, values, root), encoding="utf-8")
    # Exercise the existing split reader and reservations for observed-driven part growth.
    text = "\n".join(f"desired.row.001-{i:03d}.{field}={value}" for i in range(1, 205)
                     for field, value in (("property", "EC2.VPC.VpcId"), ("value", "[vpc](#ec2-vpc)"), ("comment", "識別子"))) + "\n"
    source = model / "ec2.properties"
    for path, content in model_file_contents(source, text).items():
        path.parent.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (design / "ec2.md").write_text("# EC2\n" + "読み取り対象\n" * 1500, encoding="utf-8")
    template = root / "infra/cloudformation/templates/shared.yaml"
    template.parent.mkdir(parents=True)
    template.write_text("Resources: {}\n", encoding="utf-8")
    params = root / "infra/cloudformation/parameters/dev/123456789012"
    params.mkdir(parents=True)
    for i in (1, 2):
        (params / f"{i}.json").write_text("[]\n", encoding="utf-8")


def arguments(root, base):
    return ["--repository-root", str(root), "--environment", "dev", "--aws-account-id", "123456789012",
            "--stack", STACKS[0], "--stack", STACKS[1], "--service", "ec2",
            "--task-file", "tasks/deploy-offline.md", "--sequential", "--log-dir", str(base / "logs")]


REAL_RUN = subprocess.run


def invoke(args):
    def local_contract(command, **kwargs):
        assert command[:2] == [sys.executable, str(Path(command[1]).parents[2] / "framework/scripts/task_contract.py")], "preparation invoked AWS/controller"
        return REAL_RUN(command, **kwargs)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
            patch.object(subprocess, "run", side_effect=local_contract):
        return M.main(args)


def check_preparation():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / "repo"
        fixture(root)
        original = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        started = time.perf_counter()
        assert invoke(arguments(root, base)) == 0
        wall = time.perf_counter() - started
        run = next((base / "logs").iterdir())
        path = run / "preparation.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == original
        assert plan["controllerArgv"].count("--stack") == 2
        assert "--sequential" in plan["controllerArgv"] and "--timing-log" in plan["controllerArgv"]
        assert plan["controllerArgv"][0] == sys.executable
        assert plan["scope"] == ["dev/123456789012/cloudformation-stacks", "dev/123456789012/ec2"]
        text = (run / "contract.md").read_text(encoding="utf-8")
        reserved = paths_in(text, "## Modified files")
        assert "model/dev/123456789012/ec2/part-003.properties" in reserved
        assert not any(p.startswith("infra/") for p in reserved)
        for document in plan["documents"]:
            assert all(len(Path(chunk).read_text(encoding="utf-8")) <= 6000 for chunk in document["chunks"])
        assert invoke(["--repository-root", str(root), "--register", str(path)]) == 0
        assert contracts(root)["tasks/deploy-offline.md"] == text
        with patch.object(M.subprocess, "run", return_value=subprocess.CompletedProcess(plan["controllerArgv"], 2)) as launch:
            assert M.main(["--repository-root", str(root), "--run-controller", str(path)]) == 2
            assert launch.call_count == 1 and launch.call_args.args[0] == plan["controllerArgv"]
            assert launch.call_args.kwargs["env"]["BLUEPRINT_TASK_FILE"] == "tasks/deploy-offline.md"
        events = [json.loads(line) for line in (run / "timing.jsonl").read_text().splitlines()]
        assert {"environment", "contractPreparation", "documentRead", "documentReview", "contractRegistration"} <= {e["phase"] for e in events}
        assert all(e["result"] == "PASS" and e["seconds"] >= 0 for e in events)
        assert all("aws" not in e["phase"].lower() for e in events)
        (run / "session.json").write_text("{}", encoding="utf-8")
        with patch.object(M.subprocess, "run", side_effect=AssertionError("existing session restarted")), redirect_stderr(io.StringIO()):
            assert M.main(["--repository-root", str(root), "--run-controller", str(path)]) == 1
        print(f"Offline preparation benchmark: {wall:.3f}s; phase timing generated (fixture, no AWS)")


def check_stale_and_conflicts():
    for reason in ("input", "issue", "reservation", "runtime", "candidate"):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            fixture(root)
            assert invoke(arguments(root, base)) == 0
            run = next((base / "logs").iterdir())
            path = run / "preparation.json"
            if reason == "input":
                (root / "README.md").write_text("changed", encoding="utf-8")
            elif reason == "issue":
                issue = root / "issues/dev/123456789012/issues.md"
                issue.parent.mkdir(parents=True)
                issue.write_text("### ec2\n1. 未解決\n", encoding="utf-8")
            elif reason == "reservation":
                text = (run / "contract.md").read_text(encoding="utf-8").replace("tasks/deploy-offline.md", "tasks/other.md")
                start(root, "tasks/other.md", text)
            elif reason == "candidate":
                (run / "contract.md").write_text("changed", encoding="utf-8")
            with patch.dict(M.os.environ, {"PATH": "changed"}) if reason == "runtime" else patch.dict(M.os.environ, {}):
                assert invoke(["--repository-root", str(root), "--register", str(path)]) == 1, reason
            assert not (root / "tasks/deploy-offline.md").exists()
            assert json.loads((run / "timing.jsonl").read_text().splitlines()[-1])["result"] == "FAIL"


def check_dependencies_and_timing():
    with patch.object(M.importlib, "import_module", side_effect=ImportError), patch.object(M.shutil, "which", return_value=None):
        try:
            M.environment(ROOT)
        except ValueError as error:
            assert all(name in str(error) for name in ("boto3", "botocore", "PyYAML", "cfn-lint", "aws", "git"))
        else:
            raise AssertionError("missing dependencies accepted")
    with tempfile.TemporaryDirectory() as directory:
        try:
            M.Timing(Path(directory), Path(directory) / "timing.jsonl")
        except ValueError:
            pass
        else:
            raise AssertionError("repository-local timing accepted")
        path = Path(directory) / "external.jsonl"
        timing = M.Timing(ROOT, path)
        try:
            with timing.phase("authenticationContext"):
                raise RuntimeError("credential failure")
        except RuntimeError:
            pass
        event = json.loads(path.read_text())
        assert event["result"] == "FAIL" and event["phase"] == "authenticationContext"


if __name__ == "__main__":
    check_dependencies_and_timing()
    check_preparation()
    check_stale_and_conflicts()
    print("Deployment preparation checks: PASS")
