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
    (tmp_path / "project.json").write_text(json.dumps(project), encoding="utf-8")
    pair, = compare.compare(tmp_path, PAIR, ["vpc"])
    assert pair["status"] == "incomplete" and pair["differences"][0]["service"] is None


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
