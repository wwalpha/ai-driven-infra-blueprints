"""Bounded metadata recovery and conservative partial reference matching."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from model.change_scope import change_reads
from model.reference_metadata import candidates, possible, recover
from support.producer_identifier_reference_fixtures import resource, setup, write_model
from support.pytest_cli import run

from model import dependency_index, sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_recovery_retains_every_candidate(project_workspace):
    root = project_workspace
    setup(root, ["s3"], ["S3.Bucket"])
    path = root / "model/preview/team/s3.properties"
    values = resource("001", "S3.Bucket", "bucket", [("BucketName", "fixture")])
    write_model(path, values)
    path.write_text(
        path.read_text(encoding="utf-8")
        + """BROKEN KEY
# comment ending with a backslash\\
invalid [ref](logs.md#logs-001)
desired.row.001-001.value=`{"$modelRef":{"logicalId":"Logs_LogGroup_001","attribute":"Arn"}}`
desired.row.001-002.value=`{"$modelRef":{"attribute":"Arn"}}`
desired.row.001-003.value=`{"$modelRef":
desired.row.001-004.value=`{"x":\\
{"$modelRef":{"logicalId":"S3_Bucket_002","attribute":"Arn"}}}`
""",
        encoding="utf-8",
    )
    snapshot, errors = recover(sources.edit_base(path, sources.FileReads()))
    assert snapshot.authoritative["desired.row.001-001.value"] == "fixture"
    assert any(
        error.get("producerScope") == "preview/team/logs"
        and error["anchor"] == "logs-001"
        for ds in errors.values()
        for error in ds
    )
    assert (
        errors["desired.row.001-001.value"][0]["targetLogicalId"] == "Logs_LogGroup_001"
    )
    assert errors["desired.row.001-001.value"][0]["attribute"] == "Arn"
    _, _, parsed_errors = dependency_index.reference_metadata(snapshot)
    assert parsed_errors["desired.row.001-002.value"][0]["attribute"] == "Arn"
    assert errors["desired.row.001-003.value"][0]["kind"] == "typed"
    with change_reads(root, sources.FileReads(), metadata={}):
        index = dependency_index.check_change_inventory(root, set())
    entry = index["models"][path.relative_to(root).as_posix()]
    assert "S3_Bucket_002" in entry["typed"]
    assert entry["errors"]
    dependency_index.validate(root, index)


@pytest.mark.parametrize(
    "error,related",
    [
        ({"kind": "link", "outsideModel": True}, False),
        ({"kind": "link", "producerScope": "preview/team/s3"}, False),
        ({"kind": "link", "producerScope": "preview/team/logs"}, True),
        ({"kind": "typed", "targetLogicalId": "Logs_LogGroup_002"}, False),
        ({"kind": "typed", "targetLogicalId": "Logs_LogGroup_001"}, True),
        ({"kind": "typed", "attribute": "Arn"}, True),
        ({"kind": "declaration", "producerScope": "other/team/logs"}, False),
    ],
)
def check_partial_target_filter(error, related):
    scope = SimpleNamespace(environment="preview", target="team")
    assert (
        possible(
            error,
            scope,
            {"preview/team/logs"},
            {("preview", "team", "Logs_LogGroup_001")},
        )
        is related
    )


@pytest.mark.parametrize(
    "raw",
    [
        '`{"$modelRef":',
        '`{"\\u0024modelRef":',
        '`{"$modelRef":{"logicalId":"Logs_LogGroup_001"}}`',
    ],
)
def check_unreadable_json_is_not_an_empty_edge(raw):
    errors = candidates(
        raw,
        SimpleNamespace(environment="preview", target="team", service="s3"),
        set(),
        set(),
    )
    assert errors
    assert any(
        possible(
            error,
            SimpleNamespace(environment="preview", target="team"),
            {"preview/team/logs"},
            {("preview", "team", "Logs_LogGroup_001")},
        )
        for error in errors
    )


def check_missing_part_keeps_unknown_references(project_workspace):
    root = project_workspace
    setup(root, ["s3"], ["S3.Bucket"])
    path = root / "model/preview/team/s3.properties"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# model-format: 2\n# model-index: 2\n# part: s3/part-001.properties\n",
        encoding="utf-8",
    )
    with change_reads(root, sources.FileReads(), metadata={}):
        entry = dependency_index.check_change_inventory(root, set())["models"][
            path.relative_to(root).as_posix()
        ]
    errors = [error for fields in entry["errors"].values() for error in fields]
    assert errors and errors[0]["kind"] == "unknown"
    assert possible(
        errors[0],
        sources.scope_for(path),
        {"other/team/logs"},
        {("other", "team", "Logs_LogGroup_001")},
    )


@pytest.mark.parametrize("old_version", [1, 2])
def check_index_rejects_unproven_metadata(project_workspace, old_version):
    root = project_workspace
    setup(root, ["s3"], ["S3.Bucket"])
    path = root / "model/preview/team/s3.properties"
    write_model(
        path, resource("001", "S3.Bucket", "bucket", [("BucketName", "fixture")])
    )
    dependency_index.rebuild(root)
    index = dependency_index.load(root)
    index["models"][path.relative_to(root).as_posix()].pop("errors")
    with pytest.raises(ValueError, match="dependency index"):
        dependency_index.validate(root, index)
    index["version"] = old_version
    if old_version == 2:
        index["models"][path.relative_to(root).as_posix()]["errors"] = {}
    dependency_index.write_sealed(root, dependency_index.location(root), index)
    with pytest.raises(ValueError, match="dependency index"):
        dependency_index.load(root)
    with change_reads(root, sources.FileReads(), metadata={}):
        with pytest.raises(ValueError, match="dependency index"):
            dependency_index.check_change_inventory(root, set())


if __name__ == "__main__":
    raise SystemExit(run(__file__))
