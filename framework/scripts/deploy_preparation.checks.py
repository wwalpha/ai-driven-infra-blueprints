#!/usr/bin/env python3
"""Offline preparation, reservation, dependency and timing regressions; no consumer/AWS."""
if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from contextlib import redirect_stdout, redirect_stderr
import io
import hashlib
import zipfile
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
from model_files import model_file_contents, model_parts, read_model
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
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [TARGET]}) + "\n", encoding="utf-8")
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
    # A real JSON-owning model; the synthetic EC2 view above only measures I/O.
    examples = M.module("preparation_model_examples", ROOT / "framework/scripts/model_design.checks.py")
    values = examples.model("iam", "IAM.Role", "app-dev-worker-role", [
        ("RoleName", "`app-dev-worker-role`", "ロール名"),
        ("AssumeRolePolicyDocument", "[Trust](iam/worker-role-trust-policy.json)", "信頼ポリシー"),
    ], "WorkerRole")
    document = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    values["desired.row.001-002.document"] = json.dumps(document, separators=(",", ":"))
    (model / "iam.properties").write_text(examples.text(values), encoding="utf-8")
    (design / "iam").mkdir()
    (design / "iam/worker-role-trust-policy.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (design / "iam.md").write_text(markdown_for(design / "iam.md", values, ROOT), encoding="utf-8")
    template = root / "infra/cloudformation/templates/shared.yaml"
    template.parent.mkdir(parents=True)
    template.write_text("Resources: {}\n", encoding="utf-8")
    params = root / "infra/cloudformation/parameters/dev/123456789012"
    params.mkdir(parents=True)
    for i in (1, 2):
        (params / f"{i}.json").write_text("[]\n", encoding="utf-8")


def arguments(root, base):
    return ["--repository-root", str(root), "--environment", "dev", "--aws-account-id", "123456789012",
            "--stack", STACKS[0], "--stack", STACKS[1], "--service", "ec2", "--service", "iam",
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
        base = Path(directory).resolve()
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
        assert plan["scope"] == ["dev/123456789012/cloudformation-stacks", "dev/123456789012/ec2", "dev/123456789012/iam"]
        text = (run / "contract.md").read_text(encoding="utf-8")
        reserved = paths_in(text, "## Modified files")
        assert "model/dev/123456789012/ec2/part-003.properties" in reserved
        assert not any(p.startswith("infra/") for p in reserved)
        for document in plan["documents"]:
            assert all(len(Path(chunk).read_text(encoding="utf-8")) <= 6000 for chunk in document["chunks"])
        documents = {d["source"]: d for d in plan["documents"]}
        generated = {"docs/designs/dev/123456789012/" + name for name in
                     ("ec2.md", "iam.md", "cloudformation-stacks.md", "iam/worker-role-trust-policy.json")}
        assert plan["generatedViews"] == sorted(generated)
        assert generated <= plan["inputs"].keys() and generated <= reserved
        assert not generated & documents.keys()
        for relative, digest in plan["inputs"].items():
            assert digest == hashlib.sha256((root / relative).read_bytes()).hexdigest()
        assert {Path(c) for d in plan["documents"] for c in d["chunks"]} == {p.resolve() for p in (run / "documents").iterdir()}
        assert len(documents) == len(plan["documents"])
        entrance = root / "model/dev/123456789012/ec2.properties"
        assert all(p.relative_to(root).as_posix() in documents for p in [entrance, *model_parts(entrance)])
        iam = documents["model/dev/123456789012/iam.properties"]
        assert "desired.row.001-002.document=" in "".join(Path(c).read_text(encoding="utf-8") for c in iam["chunks"])
        assert all("infra/cloudformation/parameters/dev/123456789012/" + str(i) + ".json" in documents for i in (1, 2))
        assert "AGENTS.md" in documents
        assert all(name in plan["controllerArgv"] for name in STACKS)
        model_rules = documents["framework/rules/model-information.md"]
        selected = "".join(Path(chunk).read_text(encoding="utf-8") for chunk in model_rules["chunks"])
        assert "## CloudFormation deployment policy" in selected
        assert "### Resource単位のCloudFormation identity" in selected
        assert "## Service display inputs" not in selected
        assert model_rules["readCharacters"] < model_rules["sourceCharacters"]
        assert "framework/rules/task-contract.md" in documents
        assert "framework/rules/issue-gate.md" in documents
        assert "framework/rules/project-configuration.md" in documents
        assert "framework/rules/terraform.md" not in documents and "README.md" not in documents
        assert invoke(["--repository-root", str(root), "--register", str(path)]) == 0
        assert contracts(root)["tasks/deploy-offline.md"] == text
        assert invoke(arguments(root, base)) == 1  # Registered tasks keep the existing resume path.
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
    for reason in ("input", "issue", "reservation", "runtime", "candidate", "model", "markdown-change",
                   "markdown-delete", "json-change", "json-delete", "legacy-change", "legacy-delete"):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "repo"
            fixture(root)
            assert invoke(arguments(root, base)) == 0
            run = next((base / "logs").iterdir())
            path = run / "preparation.json"
            if reason.startswith(("markdown-", "json-", "legacy-")):
                generated = root / "docs/designs/dev/123456789012" / ("iam/worker-role-trust-policy.json" if reason.startswith("json-") else "ec2.md")
                if reason.startswith("legacy-"):
                    plan = json.loads(path.read_text(encoding="utf-8"))
                    plan.pop("generatedViews")
                    path.write_text(json.dumps(plan), encoding="utf-8")
                if reason.endswith("delete"):
                    generated.unlink()
                else:
                    generated.write_text("changed", encoding="utf-8")
            elif reason == "model":
                source = root / "model/dev/123456789012/iam.properties"
                source.write_text(source.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
            elif reason == "input":
                # Unread sections still invalidate the full-file immutable input guard.
                path_to_rule = root / "framework/rules/model-information.md"
                path_to_rule.write_text(path_to_rule.read_text(encoding="utf-8") + "\n## Unread section\nchanged\n", encoding="utf-8")
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


def check_generated_boundaries():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory).resolve()
        root = base / "repo"
        fixture(root)
        source = root / "model/dev/123456789012/iam.properties"
        original = source.read_text(encoding="utf-8")
        source.write_text("\n".join(line for line in original.splitlines() if ".document=" not in line) + "\n", encoding="utf-8")
        try:
            M.candidate(root, "tasks/deploy-offline.md", "dev", "123456789012", TARGET, STACKS, ["iam"])
        except ValueError as error:
            assert all(value in str(error) for value in ("authoritative JSON document missing", "resource 001", "row 001-002", "iam/worker-role-trust-policy.json"))
        else:
            raise AssertionError("missing document accepted")
        source.write_text(original, encoding="utf-8")
        source.write_text(original.replace("iam/worker-role-trust-policy.json", "ec2/worker-role-trust-policy.json"), encoding="utf-8")
        try:
            M.candidate(root, "tasks/deploy-offline.md", "dev", "123456789012", TARGET, STACKS, ["iam"])
        except ValueError as error:
            assert "belong to selected service" in str(error)
        else:
            raise AssertionError("foreign JSON accepted")
        source.write_text(original, encoding="utf-8")
        controller = M.module("boundary_controller", root / "framework/scripts/cloudformation-deploy.py")
        real_module = M.module
        real_load = controller.load_units
        artifacts = root / "infra/cloudformation/artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "execution.json").write_text('{"StartAt":"Done"}', encoding="utf-8")
        with zipfile.ZipFile(artifacts / "build.zip", "w") as archive:
            archive.writestr("main.py", "pass")
        def load_with_artifacts(*args):
            limit, units = real_load(*args)
            units[0]["artifacts"] = [
                {"source": "infra/cloudformation/artifacts/execution.json", "property": "DefinitionS3Location"},
                {"source": "infra/cloudformation/artifacts/build.zip", "property": "Code"},
            ]
            return limit, units
        def modules(name, path):
            return controller if name == "preparation_controller" else real_module(name, path)
        with patch.object(controller, "load_units", side_effect=load_with_artifacts), patch.object(M, "module", side_effect=modules):
            assert invoke(arguments(root, base)) == 0
        run = next((base / "logs").iterdir())
        plan = json.loads((run / "preparation.json").read_text(encoding="utf-8"))
        documents = {d["source"] for d in plan["documents"]}
        assert "infra/cloudformation/artifacts/execution.json" in documents
        assert "infra/cloudformation/artifacts/build.zip" not in documents
        assert "infra/cloudformation/artifacts/build.zip" in plan["inputs"]
        assert "infra/cloudformation/artifacts/build.zip" not in plan["generatedViews"]
        for relative, digest in plan["inputs"].items():
            assert digest == M.sha(root / relative)
        with patch.object(controller.AwsBackend, "paths", return_value=(root / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json", artifacts / "execution.json")), patch.object(M, "module", side_effect=modules):
            output = io.StringIO()
            with redirect_stderr(output):
                assert M.main(arguments(root, base)) == 1
            assert "generated view conflicts with execution/required input" in output.getvalue()
        view = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
        original_view = view.read_text(encoding="utf-8")
        view.write_text(original_view + "changed", encoding="utf-8")
        try:
            real_load(root, "dev", "123456789012", STACKS)
        except Exception as error:
            assert "stack model/generated design mismatch" in str(error)
        else:
            raise AssertionError("stack mismatch accepted")
        view.write_text(original_view, encoding="utf-8")
        parameter = root / "infra/cloudformation/parameters/dev/123456789012/1.json"
        parameter.unlink()
        parameter.symlink_to(parameter.with_name("2.json"))
        output = io.StringIO()
        with redirect_stderr(output):
            assert M.main(arguments(root, base)) == 1
        assert "task path must not use symlinks" in output.getvalue()
        assert not (root / "tasks/deploy-offline.md").exists()


def check_service_generated_equality():
    # Only the valid IAM model/view is used for schema/generated equality evidence.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve() / "repo"
        fixture(root)
        shutil.copytree(ROOT / "framework/materials", root / "framework/materials")
        sync = M.module("equality_sync", ROOT / "framework/scripts/sync-model.py")
        contract, _, _, _ = M.candidate(root, "tasks/deploy-offline.md", "dev", "123456789012", TARGET, STACKS, ["iam"])
        start(root, "tasks/deploy-offline.md", contract)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert sync.sync(root, True, "dev", "123456789012", services=["iam"]) == 0
            assert sync.sync(root, False, "dev", "123456789012", services=["iam"]) == 0
            for relative in ("iam.md", "iam/worker-role-trust-policy.json"):
                path = root / "docs/designs/dev/123456789012" / relative
                original = path.read_text(encoding="utf-8")
                path.write_text(original + "\nchanged\n", encoding="utf-8")
                try:
                    sync.sync(root, False, "dev", "123456789012", services=["iam"])
                except ValueError as error:
                    assert "generated Markdown is stale or missing" in str(error)
                else:
                    raise AssertionError("service generated mismatch accepted")
                path.write_text(original, encoding="utf-8")


def check_workflow_contract():
    prompt = (ROOT / "framework/prompts/codex/04_deploy.md").read_text(encoding="utf-8")
    reading = M.markdown_sections(prompt)["read-before-changing-files"]
    assert "docs/designs/<environment>/<target-directory>/<service-id>.md" not in reading
    for text in (prompt, *((ROOT / "framework/rules" / (engine + ".md")).read_text(encoding="utf-8") for engine in ("cloudformation", "terraform"))):
        assert all(value in text for value in ("authoritative model properties", "desired.row.*.document", "desired.resource.*", "observed.*", "存在確認", "hash", "予約", "local loop", "fallback", "停止"))
        assert "承認済みの詳細設計とservice modelをinputとして読み取る" not in text
    assert all(value in prompt for value in ("generatedViews", "inputs", "未読section", "load_units()", "登録済みtaskを新規登録し直さない"))


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


def check_rule_section_boundaries():
    text = "# Rules\r\n\r\n## Required\r\nkeep\r\n```md\r\n## Required\r\n```\r\n### Child\r\nchild\r\n## Unrelated\r\nomit\r\n"
    text = text.replace("## Required\r\nkeep", '<a id="explicit"></a>\r\n\r\n## Required\r\nkeep')
    sections = M.markdown_sections(text)
    assert sections["explicit"] == sections["required"]
    assert "child" in sections["required"] and "omit" not in sections["required"]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "workflow.md"
        rule = root / "framework/rules/example.md"
        rule.parent.mkdir(parents=True)
        rule.write_bytes(text.encode("utf-8"))
        reading = M.rule_readings(root, source, "[Required](framework/rules/example.md#required)\n```md\n[Example](framework/rules/absent.md#missing)\n```\n`[Inline](framework/rules/absent.md#missing)`\n")
        assert reading[rule.resolve()]["sourceText"] == text
        assert reading[rule.resolve()]["text"] == sections["required"]
        try:
            M.rule_readings(root, source, "[Required](framework/rules/example.md#missing)")
        except ValueError as error:
            assert "missing rule section" in str(error)
        else:
            raise AssertionError("missing required section accepted")


if __name__ == "__main__":
    check_rule_section_boundaries()
    check_dependencies_and_timing()
    check_preparation()
    check_stale_and_conflicts()
    check_generated_boundaries()
    check_service_generated_equality()
    check_workflow_contract()
    print("Deployment preparation checks: PASS")
