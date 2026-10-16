"""Offline preparation, reservation, dependency and timing regressions; no consumer/AWS."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model_files import read_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model, write_fixture_files

from contextlib import redirect_stdout, redirect_stderr

import io

import hashlib

import zipfile

import json

import shutil

import subprocess

import tempfile

import time

from unittest.mock import patch

import deploy_preparation as M

from model_design import markdown_for

from model_files import model_file_contents, model_parts, read_model

from task_contract import contracts, paths_in, start

ROOT = Path(__file__).resolve().parents[4]

TARGET = {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}

STACKS = ["cfn-stack-app-dev-one", "cfn-stack-app-dev-two"]

def fixture(root):
    (root / "framework/scripts").mkdir(parents=True)
    for name in ("sync-model.py", "cloudformation-deploy.py", "check-deploy-context.py", "task_contract.py", "sync_files.py", "validation_cache.py", "sync_progress.py", "requirements.txt"):
        shutil.copy(ROOT / "framework/scripts" / name, root / "framework/scripts" / name)
    shutil.copytree(ROOT / "framework/scripts/deployment", root / "framework/scripts/deployment")
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
    write_model(model / "cloudformation-stacks.properties", "\n".join(f"{k}={v}" for k, v in values.items()))
    view = design / "cloudformation-stacks.md"
    view.write_text(markdown_for(view, values, root), encoding="utf-8")
    # Exercise the existing split reader and reservations for observed-driven part growth.
    text = "\n".join(f"desired.row.001-{i:03d}.{field}={value}" for i in range(1, 205)
                     for field, value in (("property", "EC2.VPC.VpcId"), ("value", "[vpc](#ec2-vpc)"), ("comment", "識別子"))) + "\n"
    source = model / "ec2.properties"
    text += "desired.resource.001.resourceType=EC2.VPC\ndesired.resource.001.anchor=ec2-vpc\n"
    write_model(source, text)
    (design / "ec2.md").write_text("# EC2\n" + "読み取り対象\n" * 1500, encoding="utf-8")
    # A real JSON-owning model; the synthetic EC2 view above only measures I/O.
    examples = M.module("preparation_model_examples", ROOT / "framework/scripts/tests/support/model_design_fixtures.py")
    values = examples.model("iam", "IAM.Role", "app-dev-worker-role", [
        ("RoleName", "`app-dev-worker-role`", "ロール名"),
        ("AssumeRolePolicyDocument", "[Trust](iam/worker-role-trust-policy.json)", "信頼ポリシー"),
    ], "WorkerRole")
    document = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    values["desired.row.001-002.document"] = json.dumps(document, separators=(",", ":"))
    write_model(model / "iam.properties", examples.text(values))
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
        if command == [sys.executable, "-m", "pip", "check"]:
            return REAL_RUN(command, **kwargs)
        assert command[:2] == [sys.executable, str(Path(command[1]).parents[2] / "framework/scripts/task_contract.py")], "preparation invoked AWS/controller"
        return REAL_RUN(command, **kwargs)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
            patch.object(subprocess, "run", side_effect=local_contract):
        return M.main(args)


__all__ = ['M', 'Path', 'REAL_RUN', 'ROOT', 'STACKS', 'TARGET', 'arguments', 'contracts', 'fixture', 'hashlib', 'invoke', 'io', 'json', 'markdown_for', 'model_file_contents', 'model_parts', 'patch', 'paths_in', 'read_model', 'redirect_stderr', 'redirect_stdout', 'shutil', 'start', 'subprocess', 'sys', 'tempfile', 'time', 'write_fixture_files', 'write_model', 'zipfile']
