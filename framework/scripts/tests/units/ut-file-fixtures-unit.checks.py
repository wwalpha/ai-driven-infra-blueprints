#!/usr/bin/env python3
"""Checks for fixed-file UT fixtures."""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.pytest_cli import run
from support.ut_file_fixtures import assert_expected_files, load_workspace

CASE = "01_bytes"
SOURCE = Path(__file__).parent.parent / "fixtures/units/ut-file-fixtures-unit/01_bytes"


def check_copy_and_independence(tmp_path):
    before = {
        p.relative_to(SOURCE): p.read_bytes() for p in SOURCE.rglob("*") if p.is_file()
    }
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    assert load_workspace(__file__, CASE, first) == first
    load_workspace(__file__, CASE, second)
    for relative in (Path("nested/sample.txt"), Path("nested/sample.bin")):
        assert (first / relative).read_bytes() == (
            SOURCE / "input" / relative
        ).read_bytes()
        assert (second / relative).read_bytes() == (first / relative).read_bytes()
    (first / "nested/sample.txt").unlink()
    assert (second / "nested/sample.txt").is_file()
    assert {
        p.relative_to(SOURCE): p.read_bytes() for p in SOURCE.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize(
    "case", ["../01_bytes", "/01_bytes", "01_../bytes", "01_BAD", "1_bytes", "01_x/y"]
)
def check_invalid_case(tmp_path, case):
    with pytest.raises(ValueError, match="invalid case ID"):
        load_workspace(__file__, case, tmp_path)


def check_missing_case_and_expected(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_workspace(__file__, "99_missing", tmp_path)
    with pytest.raises(FileNotFoundError):
        assert_expected_files(__file__, "99_missing", tmp_path)
    with pytest.raises(FileNotFoundError):
        assert_expected_files(
            Path(__file__).with_name("sync-model-unit.checks.py"),
            "01_internal_sync_arguments",
            tmp_path,
        )


def check_expected_comparison(tmp_path):
    load_workspace(__file__, CASE, tmp_path)
    assert_expected_files(__file__, CASE, tmp_path)
    (tmp_path / "nested/sample.txt").unlink()
    with pytest.raises(AssertionError, match="nested/sample.txt"):
        assert_expected_files(__file__, CASE, tmp_path)
    shutil.copyfile(SOURCE / "input/nested/sample.bin", tmp_path / "nested/sample.txt")
    with pytest.raises(AssertionError, match="nested/sample.txt"):
        assert_expected_files(__file__, CASE, tmp_path)


def check_existing_file_preflight(tmp_path):
    (tmp_path / "nested").mkdir()
    shutil.copyfile(SOURCE / "input/nested/sample.txt", tmp_path / "nested/sample.txt")
    with pytest.raises(FileExistsError, match="nested/sample.txt"):
        load_workspace(__file__, CASE, tmp_path)
    assert not (tmp_path / "nested/sample.bin").exists()


@pytest.mark.parametrize("where", ["file", "directory"])
def check_source_symlink(tmp_path, where):
    test = tmp_path / "tests/units/ut-file-fixtures-unit.checks.py"
    test.parent.mkdir(parents=True)
    fixture = tmp_path / "tests/fixtures/units/ut-file-fixtures-unit/01_bytes"
    shutil.copytree(SOURCE, fixture)
    target = fixture / "input/nested"
    if where == "file":
        target = target / "sample.txt"
    target.rename(target.with_name(target.name + "_original"))
    target.symlink_to(
        target.with_name(target.name + "_original"),
        target_is_directory=where == "directory",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError, match="symlink"):
        load_workspace(test, CASE, workspace)
    assert not list(workspace.iterdir())


@pytest.mark.parametrize("where", ["workspace", "directory", "file"])
def check_destination_symlink(tmp_path, where):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if where == "workspace":
        workspace = tmp_path / "link"
        workspace.symlink_to(outside, target_is_directory=True)
    elif where == "directory":
        (workspace / "nested").symlink_to(outside, target_is_directory=True)
    else:
        (workspace / "nested").mkdir()
        (workspace / "nested/sample.txt").symlink_to(outside / "missing")
    with pytest.raises(ValueError, match="symlink"):
        load_workspace(__file__, CASE, workspace)
    assert not list(outside.iterdir())
    assert not (workspace / "nested/sample.bin").exists()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
