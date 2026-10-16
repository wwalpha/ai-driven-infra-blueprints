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

