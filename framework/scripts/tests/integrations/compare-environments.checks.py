#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.compare_environments_fixtures import *

def check_fixture_parameters(tmp_path):
    copy_inputs(tmp_path, ("vpc","codepipeline","datazone","data-firehose","security-group","cloudformation-stacks"))
    args = ("--from-env", "dev", "--to-env", "stg", "--from-target", "cde", "--to-target", "cde", "--service", "vpc", "--service", "codepipeline",
            "--service", "datazone", "--service", "data-firehose", "--service", "security-group")
    code, report, output = cli(tmp_path, *args)
    assert code == 0
    assert cli(tmp_path, *args)[2] == output
    pair = report["comparisons"][0]
    assert pair["status"] == "complete" and pair["difference_count"] == 6
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
    code, report, _ = cli(tmp_path, "--from-env", "dev", "--to-env", "stg", "--from-target", "non-cde", "--to-target", "non-cde", "--service", "cloudformation-stacks")
    assert code == 0
    expected = tuple(yaml.safe_load(path(tmp_path, env, "cloudformation-stacks", "non-cde").read_text(encoding="utf-8"))["parameters"]["MaxConcurrentStacks"] for env in ("dev", "stg"))
    differences = [item for item in report["comparisons"][0]["differences"]
                   if item["key_path"] == "parameters.MaxConcurrentStacks"]
    assert [(item["left"], item["right"]) for item in differences] == ([expected] if expected[0] != expected[1] else [])
    code, report, _ = cli(tmp_path, "--from-env", "stg", "--to-env", "prod", "--from-target", "cde", "--to-target", "cde", "--service", "vpc")
    pair = report["comparisons"][0]
    assert code == 1 and pair["status"] == "incomplete"
    assert {item["kind"] for item in pair["differences"]} == {"incomplete"}


@pytest.mark.parametrize("text", ["parameters: {A: 1, A: 2}", "parameters: [", "[]", "parameters: {.nan: .inf}",
                                  "parameters: !!binary aGVsbG8=", "parameters: &self [*self]"])
def check_yaml_errors(tmp_path, text):
    copy_inputs(tmp_path)
    path(tmp_path, "stg").write_text(text, encoding="utf-8")
    code, report, _ = cli(tmp_path, "--from-env", "dev", "--to-env", "stg", "--from-target", "cde", "--to-target", "cde", "--service", "vpc")
    pair = report["comparisons"][0]
    assert code == 1 and pair["status"] == "incomplete" and pair["errors"]
    assert pair["errors"][0]["path"] == path(tmp_path, "stg").relative_to(tmp_path).as_posix()
    assert [item["kind"] for item in pair["differences"]] == ["incomplete"]


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
        pairs = compare.compare(tmp_path, [(left, right, target, target) for target in ("cde", "non-cde")
                                 for left, right in (("dev", "stg"), ("stg", "prod"))], ["vpc"])
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
    for args in (("--from-env", "dev", "--to-env", "stg"),
                 ("--from-env", "dev", "--to-env", "stg", "--from-target", "cde")):
        code, report, _ = cli(tmp_path, *args, "--service", "vpc")
        assert code == 1 and len(report["comparisons"]) == 1
        assert report["comparisons"][0]["status"] == "incomplete"
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--repository-root", str(tmp_path)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 2 and "--from-env" in result.stderr and "--to-env" in result.stderr
    assert compare.compare(tmp_path, PAIR, [])[0]["status"] == "incomplete"  # Union includes malformed codepipeline.


@pytest.mark.parametrize("explicit", [False, True])
def check_single_target_cli(tmp_path, explicit):
    write_project(tmp_path, [("test-east", None, "123456789012"), ("production-west", None, "210987654321")])
    for env, account, value in (("test-east", "123456789012", 1), ("production-west", "210987654321", 2)):
        destination = path(tmp_path, env, target=account)
        destination.parent.mkdir(parents=True)
        destination.write_text(yaml.safe_dump({"parameters": {"value": value}}), encoding="utf-8")
    args = ["--from-env", "test-east", "--to-env", "production-west"]
    if explicit:
        args += ["--from-target", "123456789012", "--to-target", "210987654321"]
    code, report, _ = cli(tmp_path, *args)
    result, = report["comparisons"]
    assert code == 0 and result["difference_count"] == 1
    assert (result["left"], result["right"]) == ("test-east", "production-west")
    assert (result["left_target"], result["right_target"]) == ("123456789012", "210987654321")
    assert result["target"] is None and result["differences"][0]["alias"] is None


def check_independent_targets_cli(tmp_path):
    write_project(tmp_path, [(env, target, "123456789012") for env in ("test", "production")
                             for target in ("core", "network")])
    for env, target, value in (("test", "network", 1), ("production", "core", 2),
                               ("test", "core", 99), ("production", "network", 99)):
        destination = path(tmp_path, env, target=target)
        destination.parent.mkdir(parents=True)
        destination.write_text(yaml.safe_dump({"parameters": {"value": value}}), encoding="utf-8")
    code, report, _ = cli(tmp_path, "--from-env", "test", "--from-target", "network",
                          "--to-env", "production", "--to-target", "core", "--service", "vpc")
    result, = report["comparisons"]
    item, = result["differences"]
    assert code == 0 and (item["left"], item["right"]) == (1, 2)
    assert (result["left_target"], result["right_target"]) == ("network", "core")
    assert item["source_paths"] == {"left": "model/parameters/test/network/vpc/parameters.yaml",
                                    "right": "model/parameters/production/core/vpc/parameters.yaml"}


@pytest.mark.parametrize("environment,target,message", [("unknown", "cde", "unregistered environment"),
                                                         ("stg", "unknown", "unregistered target")])
def check_unknown_selection_cli(tmp_path, environment, target, message):
    copy_inputs(tmp_path)
    code, report, _ = cli(tmp_path, "--from-env", "dev", "--from-target", "cde",
                          "--to-env", environment, "--to-target", target, "--service", "vpc")
    result, = report["comparisons"]
    assert code == 1 and result["status"] == "incomplete"
    assert any(message in error["message"] for error in result["errors"])


@pytest.mark.parametrize("args", [("--pair", "dev-stg", "--target", "cde"),
                                   ("--from-env", "dev"), ("--to-env", "stg"),
                                   ("--from-env", "dev", "--to-env", "stg", "--service", "../vpc")])
def check_cli_arguments(tmp_path, args):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--repository-root", str(tmp_path), *args],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 2 and "error:" in result.stderr and not result.stdout


if __name__ == "__main__":
    raise SystemExit(run(__file__, message="Parameter environment comparison checks: PASS"))

