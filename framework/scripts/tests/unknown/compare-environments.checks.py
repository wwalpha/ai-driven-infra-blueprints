#!/usr/bin/env python3
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
PAIR = [("dev", "stg", "cde")]


def path(root, environment, service="vpc", target="cde"):
    return root / "model/parameters" / environment / target / service / "parameters.yaml"


def copy_inputs(root, services=("vpc",)):
    project = {"projectName":"fixture", "targets":[
        {"environment":env, "alias":alias, "awsAccountId":account, "awsRegion":"ap-northeast-1", "iacEngine":"cloudformation"}
        for env in ("dev","stg","prod") for alias,account in (("cde","123456789012"),("non-cde","210987654321"))]}
    (root/"project.json").write_text(json.dumps(project),encoding="utf-8")
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


def check_fixture_parameters(tmp_path):
    copy_inputs(tmp_path, ("vpc","codepipeline","datazone","data-firehose","security-group","cloudformation-stacks"))
    args = ("--pair", "dev-stg", "--target", "cde", "--service", "vpc", "--service", "codepipeline",
            "--service", "datazone", "--service", "data-firehose", "--service", "security-group")
    code, report, output = cli(tmp_path, *args)
    assert code == 0
    assert cli(tmp_path, *args)[2] == output
    pair = report["comparisons"][0]
    assert pair["status"] == "complete"
    differences = {(item["service"], item["key_path"]): item for item in pair["differences"]}
    mode = differences["vpc", "parameters.ResourceMode"]
    assert (mode["left"], mode["right"], mode["kind"]) == ("CREATE", "IMPORT", "changed")
    branch = differences["codepipeline", "instances.build.parameters.SourceBranch"]
    assert (branch["left"], branch["right"]) == ("main", "stg")
    for service, kind in (("datazone", "only_left"), ("data-firehose", "only_right")):
        items = [item for item in pair["differences"] if item["service"] == service]
        assert len(items) == 1 and items[0]["key_path"] == "" and items[0]["kind"] == kind
        assert items[0]["left_exists"] == (kind == "only_left")
        assert items[0]["right_exists"] == (kind == "only_right")
    for identity, kind in (("ec2-vpcendpoint-sts-01", "only_left"), ("ec2-vpc-endpoint-sts-01", "only_right")):
        assert differences["security-group", f"instances.{identity}"]["kind"] == kind
    assert mode["pair"] == "dev-stg" and mode["alias"] == "cde"
    assert mode["source_paths"] == {side: path(tmp_path, env).relative_to(tmp_path).as_posix()
                                    for side, env in (("left", "dev"), ("right", "stg"))}
    code, report, _ = cli(tmp_path, "--pair", "dev-stg", "--target", "non-cde", "--service", "cloudformation-stacks")
    assert code == 0
    expected = tuple(yaml.safe_load(path(tmp_path, env, "cloudformation-stacks", "non-cde").read_text(encoding="utf-8"))["parameters"]["MaxConcurrentStacks"] for env in ("dev", "stg"))
    differences = [item for item in report["comparisons"][0]["differences"]
                   if item["key_path"] == "parameters.MaxConcurrentStacks"]
    assert [(item["left"], item["right"]) for item in differences] == ([expected] if expected[0] != expected[1] else [])
    code, report, _ = cli(tmp_path, "--pair", "stg-prod", "--target", "cde", "--service", "vpc")
    pair = report["comparisons"][0]
    assert code == 1 and pair["status"] == "incomplete"
    assert {item["kind"] for item in pair["differences"]} == {"incomplete"}


def check_yaml_values(tmp_path):
    copy_inputs(tmp_path)
    original = compare.yaml_read(path(tmp_path, "dev").read_text(encoding="utf-8"))

    def reverse(value):
        if isinstance(value, dict):
            return {key: reverse(value[key]) for key in reversed(value)}
        return value

    path(tmp_path, "stg").write_text("# reordered input\n" + yaml.safe_dump(reverse(original), sort_keys=False), encoding="utf-8")
    pair, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert pair["status"] == "complete" and pair["difference_count"] == 0
    left = {**original, "extra": {"integer": 1, "boolean": True, "number": 1, "nil": None,
                                "sequence": ["A", "B", None], "content": [1], "nested": [{"value": 1}]}}
    right = {**original, "extra": {"integer": "1", "boolean": 1, "number": 1.0, "added": None,
                                 "sequence": ["B", "A"], "content": [2], "nested": [{"value": True}]},
             "definition": "alternative"}
    for env, value in (("dev", left), ("stg", right)):
        path(tmp_path, env).write_text(yaml.safe_dump(value), encoding="utf-8")
    pair, = compare.compare(tmp_path, PAIR, ["vpc"])
    differences = {item["key_path"]: item for item in pair["differences"]}
    assert len(differences) == 11 and pair["status"] == "complete"
    for key in ("integer", "boolean", "number"):
        item = differences[f"extra.{key}"]
        assert item["kind"] == "changed" and type(item["left"]) is not type(item["right"])
    assert differences["extra.nil"]["left_exists"] and not differences["extra.nil"]["right_exists"]
    assert not differences["extra.added"]["left_exists"] and differences["extra.added"]["right_exists"]
    assert differences["extra.nil"]["left"] is differences["extra.added"]["right"] is None
    assert [differences[f"extra.sequence[{i}]"]["kind"] for i in range(3)] == ["changed", "changed", "only_left"]
    assert differences["extra.content[0]"]["kind"] == differences["extra.nested[0].value"]["kind"] == "changed"
    assert differences["definition"]["kind"] == "only_right"


@pytest.mark.parametrize("text", ["parameters: {A: 1, A: 2}", "parameters: [", "[]", "parameters: {.nan: .inf}",
                                  "parameters: !!binary aGVsbG8=", "parameters: &self [*self]"])
def check_yaml_errors(tmp_path, text):
    copy_inputs(tmp_path)
    path(tmp_path, "stg").write_text(text, encoding="utf-8")
    code, report, _ = cli(tmp_path, "--pair", "dev-stg", "--target", "cde", "--service", "vpc")
    pair = report["comparisons"][0]
    assert code == 1 and pair["status"] == "incomplete" and pair["errors"]
    assert pair["errors"][0]["path"] == path(tmp_path, "stg").relative_to(tmp_path).as_posix()
    assert [item["kind"] for item in pair["differences"]] == ["incomplete"]


def check_missing_and_read_errors(tmp_path):
    copy_inputs(tmp_path)
    missing, = compare.compare(tmp_path, PAIR, ["unknown"])
    assert missing["status"] == "incomplete" and missing["errors"]
    path(tmp_path, "stg").unlink()
    pair, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert pair["status"] == "complete" and pair["differences"][0]["kind"] == "only_left"
    assert len(pair["differences"]) == 1
    path(tmp_path, "dev").unlink()
    pair, = compare.compare(tmp_path, PAIR, [])
    assert pair["status"] == "incomplete" and pair["errors"]
    copy_inputs(tmp_path)
    original_read = Path.read_text

    def unreadable(file, *args, **kwargs):
        if file == path(tmp_path, "stg"):
            raise PermissionError("input read denied")
        return original_read(file, *args, **kwargs)

    with patch.object(Path, "read_text", unreadable):
        pair, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert pair["status"] == "incomplete" and "input read denied" in pair["errors"][0]["message"]
    path(tmp_path, "stg").write_bytes(b"\xff")
    pair, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert pair["status"] == "incomplete" and pair["errors"]
    # An absent alias is incomplete even when its environment has another alias.
    project = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    project["targets"] = [item for item in project["targets"] if (item["environment"], item["alias"]) != ("stg", "cde")]
    (tmp_path / "project.json").write_text(json.dumps(project), encoding="utf-8")
    pair, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert pair["status"] == "incomplete" and pair["differences"][0]["service"] is None


def check_scope_reads_and_templates(tmp_path):
    copy_inputs(tmp_path, ("vpc", "codepipeline"))
    for target in ("cde", "non-cde"):
        for env in ("dev", "stg", "prod"):
            destination = path(tmp_path, env, target=target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination != path(tmp_path, "dev"):
                shutil.copyfile(path(tmp_path, "dev"), destination)
    reads = Counter()
    original_read = Path.read_text

    def counted(file, *args, **kwargs):
        assert file.name in ("parameters.yaml", "project.json"), file
        reads[file] += 1
        return original_read(file, *args, **kwargs)

    with patch.object(Path, "read_text", counted):
        pairs = compare.compare(tmp_path, compare.PAIRS, ["vpc"])
    assert all(pair["status"] == "complete" for pair in pairs)
    assert reads == Counter({tmp_path / "project.json": 1, **{path(tmp_path, env, target=target): 1
                            for env in ("dev", "stg", "prod") for target in ("cde", "non-cde")}})
    before = compare.compare(tmp_path, PAIR, ["vpc"])
    template = tmp_path / "model/templates/vpc/source.json"
    template.parent.mkdir(parents=True)
    template.write_text("invalid template changed independently", encoding="utf-8")
    path(tmp_path, "prod").write_text("invalid: [", encoding="utf-8")
    path(tmp_path, "stg", "codepipeline").write_text("invalid: [", encoding="utf-8")
    reads.clear()
    snapshot = {file.relative_to(tmp_path): file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    with patch.object(Path, "read_text", counted):
        assert compare.compare(tmp_path, PAIR, ["vpc"]) == before
    assert reads == Counter({tmp_path / "project.json": 1, path(tmp_path, "dev"): 1, path(tmp_path, "stg"): 1})
    assert {file.relative_to(tmp_path): file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()} == snapshot
    code, report, _ = cli(tmp_path, "--pair", "dev-stg", "--service", "vpc")
    assert code == 0 and [item["target"] for item in report["comparisons"]] == ["cde", "non-cde"]
    code, report, _ = cli(tmp_path, "--target", "non-cde", "--service", "vpc")
    assert code == 0 and [f'{item["left"]}-{item["right"]}' for item in report["comparisons"]] == ["dev-stg", "stg-prod"]
    assert len(cli(tmp_path, "--service", "vpc")[1]["comparisons"]) == 4
    assert compare.compare(tmp_path, PAIR, [])[0]["status"] == "incomplete"  # Union includes malformed codepipeline.


if __name__ == "__main__":
    raise SystemExit(run(__file__, message="Parameter environment comparison checks: PASS"))
