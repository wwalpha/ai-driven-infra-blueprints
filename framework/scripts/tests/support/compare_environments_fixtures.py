"""Parameter comparison checks using authored disposable inputs."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

import importlib.util

import json

import shutil

import subprocess

from collections import Counter

from unittest.mock import patch

import pytest

import yaml

from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPT = (Path(__file__).resolve().parents[2] / 'compare-environments.py')

ROOT = SCRIPT.resolve().parents[2]

spec = importlib.util.spec_from_file_location("compare_environments", SCRIPT)

compare = importlib.util.module_from_spec(spec)

spec.loader.exec_module(compare)

PAIR = [("dev", "stg", "cde", "cde")]

def path(root, environment, service="vpc", target="cde"):
    return root / "model/parameters" / environment / target / service / "parameters.yaml"

def write_project(root, placements):
    targets = [{"environment": env, "awsAccountId": account, "awsRegion": "ap-northeast-1",
                "iacEngine": "cloudformation", **({"alias": alias} if alias is not None else {})}
               for env, alias, account in placements]
    targets.sort(key=lambda item: (item["environment"], item.get("alias", item["awsAccountId"])))
    (root / "project.json").write_text(json.dumps({"projectName": "fixture", "targets": targets}) + "\n", encoding="utf-8")

def copy_inputs(root, services=("vpc",)):
    write_project(root, [(env, alias, account) for env in ("dev", "stg", "prod")
                         for alias, account in (("cde", "123456789012"), ("non-cde", "210987654321"))])
    for environment in ("dev", "stg"):
        for service in services:
            if (service,environment) in (("datazone","stg"),("data-firehose","dev")):
                continue
            parameters = {"parameters":{"ResourceMode":"CREATE" if environment=="dev" else "IMPORT"}} if service=="vpc" else (
                {"instances":{"build":{"parameters":{"SourceBranch":"main" if environment=="dev" else "stg"}}}} if service=="codepipeline" else
                {"instances":{"ec2-vpcendpoint-sts-01" if environment=="dev" else "ec2-vpc-endpoint-sts-01":{"parameters":{}}}} if service=="security-group" else {"instances":{}})
            destination = path(root,environment,service)
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(yaml.safe_dump(parameters),encoding="utf-8")
        if "cloudformation-stacks" in services:
            destination=path(root,environment,"cloudformation-stacks","non-cde")
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(yaml.safe_dump({"parameters":{"MaxConcurrentStacks":2 if environment=="dev" else 4}}),encoding="utf-8")

def cli(root, *args):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--repository-root", str(root), *args],
                            capture_output=True, text=True, encoding="utf-8")
    assert not result.stderr, result.stderr
    report = json.loads(result.stdout)
    assert report["namespace"] == "parameters"
    assert all(item["difference_count"] == len(item["differences"]) for item in report["comparisons"])
    return result.returncode, report, result.stdout


__all__ = ['Counter', 'PAIR', 'Path', 'ROOT', 'SCRIPT', 'cli', 'compare', 'copy_inputs', 'importlib', 'json', 'patch', 'path', 'pytest', 'run', 'shutil', 'spec', 'subprocess', 'sys', 'yaml', 'write_project']
