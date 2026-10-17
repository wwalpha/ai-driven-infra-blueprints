#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.compare_environments_fixtures import *

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
    (tmp_path / "project.json").write_text(json.dumps(project) + "\n", encoding="utf-8")
    pair, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert pair["status"] == "incomplete" and pair["differences"][0]["service"] is None


@pytest.mark.parametrize("placements,selection,expected", [
    ([("test", None, "123456789012"), ("production", None, "210987654321")],
     ("test", "production", None, None), ("123456789012", "210987654321")),
    ([("test", None, "123456789012"), ("production", None, "210987654321")],
     ("test", "production", "123456789012", "210987654321"), ("123456789012", "210987654321")),
    ([(env, alias, "123456789012") for env in ("test", "production") for alias in ("core", "network")],
     ("test", "production", "network", "network"), ("network", "network")),
    ([(env, alias, "123456789012") for env in ("test", "production") for alias in ("core", "network")],
     ("test", "production", "network", "core"), ("network", "core")),
    ([("test-east", None, "123456789012"), ("production-west", None, "123456789012")],
     ("test-east", "production-west", None, None), ("123456789012", "123456789012")),
    ([("network", None, "123456789012"), ("test", "core", "123456789012"), ("test", "network", "123456789012")],
     ("network", "test", None, "core"), ("123456789012", "core")),
])
def check_project_targets(tmp_path, placements, selection, expected):
    write_project(tmp_path, placements)
    left, right, _, _ = selection
    for index, (env, directory) in enumerate(zip((left, right), expected)):
        destination = path(tmp_path, env, target=directory)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(yaml.safe_dump({"parameters": {"value": index}}), encoding="utf-8")
    result, = compare.compare(tmp_path, [selection], [])
    assert result["status"] == "complete" and result["difference_count"] == 1
    assert (result["left"], result["right"]) == (left, right)
    assert (result["left_target"], result["right_target"]) == expected
    shared = expected[0] if expected[0] == expected[1] else None
    assert result["target"] == result["differences"][0]["alias"] == shared
    item, = result["differences"]
    assert (item["left_target"], item["right_target"]) == expected
    assert (item["left"], item["right"], item["kind"]) == (0, 1, "changed")
    assert item["source_paths"] == {side: path(tmp_path, env, target=directory).relative_to(tmp_path).as_posix()
                                    for side, env, directory in zip(("left", "right"), (left, right), expected)}


@pytest.mark.parametrize("selection,message", [
    (("dev", "stg", None, "cde"), "multiple targets in dev"),
    (("dev", "stg", "cde", None), "multiple targets in stg"),
    (("unknown", "stg", "cde", "cde"), "unregistered environment: unknown"),
    (("dev", "unknown", "cde", "cde"), "unregistered environment: unknown"),
    (("dev", "stg", "unknown", "cde"), "unregistered target: dev/unknown"),
    (("dev", "stg", "cde", "unknown"), "unregistered target: stg/unknown"),
    (("dev", "stg", "123456789012", "cde"), "unregistered target: dev/123456789012"),
    (("/tmp", "stg", None, "cde"), "unregistered environment: /tmp"),
])
def check_selection_errors(tmp_path, selection, message):
    copy_inputs(tmp_path)
    result, = compare.compare(tmp_path, [selection], ["vpc"])
    assert result["status"] == "incomplete" and result["difference_count"] == 1
    assert any(message in item["message"] for item in result["errors"])
    assert result["differences"][0]["kind"] == "incomplete"


@pytest.mark.parametrize("change,message", [
    ("single-alias", "single-target environment must omit alias"),
    ("missing-alias", "multi-target environment requires alias"),
    ("duplicate", "duplicate target directory"),
    ("unsafe-alias", "invalid target alias"),
    ("unset-account", "invalid AWS account"),
    ("invalid-json", "invalid project.json"),
    ("missing-project", "project.json"),
])
def check_project_errors(tmp_path, change, message):
    copy_inputs(tmp_path)
    project_file = tmp_path / "project.json"
    project = json.loads(project_file.read_text(encoding="utf-8"))
    if change == "single-alias":
        project["targets"] = [entry for entry in project["targets"] if entry["alias"] == "cde"]
    elif change == "missing-alias":
        del project["targets"][0]["alias"]
    elif change == "duplicate":
        project["targets"].insert(0, project["targets"][0])
    elif change == "unsafe-alias":
        project["targets"][0]["alias"] = "../escape"
    elif change == "unset-account":
        project["targets"][0]["awsAccountId"] = "UNSET"
    project_file.write_text("{" if change == "invalid-json" else json.dumps(project) + "\n", encoding="utf-8")
    if change == "missing-project":
        project_file.unlink()
    result, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert result["status"] == "incomplete"
    assert any(message in item["message"] for item in result["errors"])


@pytest.mark.parametrize("text", ["parameters: {A: 1, A: 2}", "parameters: [", "[]", "parameters: {.nan: .inf}",
                                  "parameters: !!binary aGVsbG8=", "parameters: &self [*self]"])
def check_yaml_errors(tmp_path, text):
    copy_inputs(tmp_path)
    path(tmp_path, "stg").write_text(text, encoding="utf-8")
    result, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert result["status"] == "incomplete" and result["errors"]
    assert [item["kind"] for item in result["differences"]] == ["incomplete"]


def check_read_counts_and_read_only(tmp_path):
    copy_inputs(tmp_path, ("vpc", "datazone", "data-firehose"))
    reads = Counter()
    original_read = Path.read_text

    def counted(file, *args, **kwargs):
        assert file.name in ("project.json", "parameters.yaml"), file
        reads[file] += 1
        return original_read(file, *args, **kwargs)

    def snapshot():
        return {file.relative_to(tmp_path): (file.stat().st_mode, file.read_bytes() if file.is_file() else None)
                for file in tmp_path.rglob("*")}

    before = snapshot()
    with patch.object(Path, "read_text", counted), patch("subprocess.run", side_effect=AssertionError("AWS/process call")), \
            patch("socket.socket", side_effect=AssertionError("network call")):
        result, = compare.compare(tmp_path, PAIR, [])
    assert result["status"] == "complete"
    assert result["services"] == ["data-firehose", "datazone", "vpc"]
    assert reads == Counter({tmp_path / "project.json": 1, **{file: 1 for file in tmp_path.rglob("parameters.yaml")}})
    assert snapshot() == before
    reads.clear()
    with patch.object(Path, "read_text", counted):
        results = compare.compare(tmp_path, [("dev", "dev", "cde", "cde"), *PAIR, *PAIR], ["vpc", "vpc"])
    assert all(item["status"] == "complete" for item in results)
    assert results[0]["difference_count"] == 0
    assert reads == Counter({tmp_path / "project.json": 1, path(tmp_path, "dev"): 1, path(tmp_path, "stg"): 1})


def check_task_scope_independence(tmp_path):
    copy_inputs(tmp_path)
    with patch("import_scope.selected", side_effect=AssertionError("comparison must not select an IMPORT task")):
        result, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert result["status"] == "complete" and result["difference_count"] == 1


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
