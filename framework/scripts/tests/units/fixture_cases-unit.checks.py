#!/usr/bin/env python3
"""Generic static fixture loading and workspace path boundaries."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

import pytest
from support import fixture_cases as fixtures

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_suite_write(tmp_path, /, text):
    fixtures._suite.cache_clear()
    (tmp_path / "example.yaml").write_text(text, encoding="utf-8")


@pytest.fixture
def suite(tmp_path, monkeypatch):
    monkeypatch.setattr(fixtures, "_FIXTURES", tmp_path)
    fixtures._suite.cache_clear()
    write = _bind_framework_callback(_callback_suite_write, tmp_path)
    yield write
    fixtures._suite.cache_clear()


def check_loading_and_independence(suite):
    suite("""version: 1
base:
  data: {shared: [1, true, null], nested: {old: 1}, retained: yes}
  files: {one.txt: old, two.txt: " 日本語 \\r\\n"}
  expected: {old: true}
cases:
  first:
    data: {nested: {new: 2}}
    files: {one.txt: new}
    expected: [2]
  second: {}
""")
    with patch.object(fixtures, "yaml_read", wraps=fixtures.yaml_read) as parse:
        first = fixtures.load_case("example", "first")
        second = fixtures.load_case("example", "second")
        public = fixtures.load_suite("example")
        assert parse.call_count == 1
    assert first["data"] == {
        "shared": [1, True, None],
        "nested": {"new": 2},
        "retained": "yes",
    }
    assert first["files"] == {"one.txt": "new", "two.txt": " 日本語 \r\n"}
    assert first["expected"] == [2] and second["expected"] == {"old": True}
    first["data"]["shared"].append("changed")
    public["base"]["data"]["nested"]["old"] = 99
    assert fixtures.load_case("example", "second") == second
    assert second["data"]["nested"] == {"old": 1}
    fixtures._suite.cache_clear()
    assert fixtures.load_case("example", "second") == second
    with pytest.raises(ValueError, match="unknown fixture case"):
        fixtures.load_case("example", "missing")
    for name in ("../example", "/example", "", "Example"):
        with pytest.raises(ValueError, match="invalid fixture suite"):
            fixtures.load_suite(name)


def check_invalid_schema(suite):
    documents = [
        "version: 1\nversion: 1\ncases: {ok: {}}",
        "version: 1\ncases: {ok: {}, ok: {}}",
        "version: 1\ncases: {ok: {data: {x: 1, x: 2}}}",
        "version: true\ncases: {ok: {}}",
        "version: 2\ncases: {ok: {}}",
        "version: 1\ncases: {}",
        "version: 1",
        "[]",
        "version: 1\ncases: []",
        "version: 1\ncases: {bad/id: {}}",
        "version: 1\ncases: {ok: null}",
        "version: 1\nbase: []\ncases: {ok: {}}",
        "version: 1\nunknown: 1\ncases: {ok: {}}",
        "version: 1\ncases: {ok: {unknown: 1}}",
        "version: 1\ncases: {ok: {data: []}}",
        "version: 1\ncases: {ok: {files: []}}",
        "version: 1\ncases: {ok: {files: {a: 1}}}",
        "version: 1\ncases: {ok: {files: {../escape: text}}}",
        "version: 1\ncases: {ok: {data: {x: .nan}}}",
        "version: 1\ncases: {ok: {data: {x: !!set {a: null}}}}",
        "version: 1\ncases: {ok: {data: &cycle {x: *cycle}}}",
    ]
    for document in documents:
        suite(document)
        with pytest.raises(ValueError):
            fixtures.load_suite("example")


def check_materialize_files(tmp_path):
    root = tmp_path / "workspace"
    files = {"a/b.txt": " 日本語 \r\n\n ", "empty.txt": "", "no-newline.md": "end"}
    fixtures.materialize_files(root, files)
    for name, text in files.items():
        assert (root / name).read_bytes() == text.encode("utf-8")
    fixtures.materialize_files(root, {"no-newline.md": "replacement\n"})
    assert (root / "no-newline.md").read_bytes() == b"replacement\n"
    fixtures.materialize_files(root, {})
    for name in (
        "/absolute",
        "../escape",
        "a/../../escape",
        "a/../alias",
        "./alias",
        "",
        "a//alias",
        "a/",
        "a:stream",
        "C:/escape",
        "C:escape",
        "\\\\host\\share",
        "a\\b",
        "a\x00b",
    ):
        with pytest.raises(ValueError):
            fixtures.materialize_files(
                root, {"untouched.txt": "never written", name: "bad"}
            )
        assert not (root / "untouched.txt").exists()
    for collision in (
        {"same": "file", "same/child": "child"},
        {"same/child": "child", "same": "file"},
        {"no-newline.md/child": "bad"},
        {"a": "directory"},
    ):
        with pytest.raises(ValueError):
            fixtures.materialize_files(root, collision)
    assert not (root / "same").exists()
    (root / "hardlink").hardlink_to(root / "no-newline.md")
    with pytest.raises(ValueError, match="conflicting"):
        fixtures.materialize_files(root, {"hardlink": "one", "no-newline.md": "two"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"unchanged")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "file-link").symlink_to(outside / "file")
    (root / "internal").symlink_to(root / "a", target_is_directory=True)
    for name in ("link/file", "file-link", "internal/file"):
        with pytest.raises(ValueError, match="symlink"):
            fixtures.materialize_files(root, {name: "bad"})
    assert (outside / "file").read_bytes() == b"unchanged"
    with pytest.raises(ValueError, match="symlink"):
        fixtures.materialize_files(root / "link", {"file": "bad"})


def check_authored_suite():
    suite = fixtures.load_suite("issues_scan")
    assert list(suite["cases"]) == ["naming-target-scope", "malformed-report"]
    assert list(
        fixtures.load_case("issues_scan", "naming-target-scope")["data"][
            "specifications"
        ]
    ) == ["codebuild", "codepipeline", "glue"]
    files = fixtures.load_case("issues_scan", "malformed-report")["files"]
    assert files == {
        "issues/dev/123456789012/issues.md": "malformed report without inventory\n"
    }


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
