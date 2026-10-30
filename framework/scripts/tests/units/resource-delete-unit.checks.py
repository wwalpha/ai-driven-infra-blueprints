#!/usr/bin/env python3
"""Parent deletion transactions use synthetic sources; no consumer checkout or AWS."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import shutil
from unittest.mock import patch

import pytest
import task_contract_core as tasks
from model.adapters.task import source_write_context
from model.core import entries
from model.operations import verify_model_operation
from model.sources import load_model
from support.import_model_fixtures import (
    dependency_contract,
    dependency_fixture,
    dependency_refactor,
    reference_fields,
    resource_values,
)
from support.model_sources import write_model
from support.resource_delete_fixtures import (
    changed,
    contract,
    deletion,
    fixture,
    save,
    write_candidate,
)
from utils.function_wrapper import BoundCallback as _bind_framework_callback

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize("multiple", [False, True])
def check_ten_deletions(tmp_path, multiple):
    before, after = tmp_path / "before", tmp_path / "after"
    sources = fixture(before, multiple)
    shutil.copytree(before, after)
    operation = tasks.model_operation(contract(sources))
    assert len(operation.delete_sources) == 10
    for address in sources:
        save(deletion(after, address))
    verify_model_operation(before, after, operation, changed(before, after))
    missing = tasks.model_operation(contract(["stg/cde/service-a/999"]))
    with pytest.raises(ValueError, match="existing source"):
        verify_model_operation(before, before, missing, set())
    path = before / "model/stg/cde/service-a.properties"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        original.replace(
            "desired.resource.001.resourceMode=CREATE",
            "desired.resource.001.resourceMode=INVALID",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="resourceMode"):
        verify_model_operation(before, after, operation, changed(before, after))
    path.write_text(original, encoding="utf-8")
    assert (before / "model/dev").exists()
    for source_scope in operation.source_scopes:
        env, target, service = source_scope
        current = load_model(after / "model" / env / target / (service + ".properties"))
        assert len(entries(current.authoritative, "desired.resource.")) == 1
        assert (
            current.authoritative["desired.service." + service + ".serviceId"]
            == service
        )


@pytest.mark.parametrize(
    "bad",
    [
        "duplicate",
        "empty",
        "cross-target",
        "merge",
        "reference-unrelated",
        "detach-unrelated",
    ],
)
def check_contract_rejects_unscoped_deletion(bad):
    sources = ["stg/cde/service-a/001", "stg/cde/service-b/002"]
    text = contract(sources)
    if bad == "duplicate":
        text += "- `" + sources[0] + "`\n"
    elif bad == "empty":
        text = contract([])
    elif bad == "cross-target":
        text = text.replace("stg/cde/service-b", "dev/cde/service-b")
    elif bad == "merge":
        text = text.replace("model-delete", "import-merge")
    elif bad == "reference-unrelated":
        text = contract(
            sources,
            [
                {
                    "consumer": "stg/cde/service-c/003",
                    "field": "value",
                    "property": "Example.Resource.Name",
                    "source": "stg/cde/service-a/099",
                    "destination": "stg/cde/service-a/004",
                }
            ],
        )
    elif bad == "detach-unrelated":
        text = contract(
            sources,
            detaches=[
                {
                    "consumer": "stg/cde/service-c/003",
                    "producer": "stg/cde/service-a/099",
                    "key": "desired.row.003-001.value",
                }
            ],
        )
    with pytest.raises(ValueError):
        tasks.model_operation(text)


def check_deletion_and_detach_normalization():
    operation = tasks.model_operation(contract(["stg/cde/vpc/009"]))
    assert operation.action == "model-delete"
    assert operation.delete_sources == ("stg/cde/vpc/009",)
    text = dependency_contract().replace(
        "## Model dependency detach",
        "- Model operation: `model-delete`\n## Model delete sources\n- `stg/cde/service-a/001`\n## Model dependency detach",
    )
    operation = tasks.model_operation(text)
    assert operation.detaches == tasks.model_refactor(text)
    assert operation.scopes == {
        ("stg", "cde", "service-a"),
        ("stg", "cde", "service-b"),
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra-delete",
        "setting",
        "identity",
        "observation",
        "shared-consumer",
    ],
)
def check_final_rejects_unrequested_changes(tmp_path, mutation):
    before, after = tmp_path / "before", tmp_path / "after"
    sources = fixture(before)
    shutil.copytree(before, after)
    for source in sources:
        if mutation == "missing" and source == sources[-1]:
            continue
        save(deletion(after, source))
    if mutation == "extra-delete":
        save(deletion(after, "stg/cde/service-a/011"))
    elif mutation != "missing":
        file = after / (
            "model/dev/cde/service-a.properties"
            if mutation == "shared-consumer"
            else "model/stg/cde/service-a.properties"
        )
        values = dict(load_model(file).authoritative)
        field = (
            "desired.row.011-001.value"
            if mutation in {"setting", "shared-consumer"}
            else "desired.resource.011.anchor"
            if mutation == "identity"
            else "observed.row.011-001.value"
        )
        values[field] = "changed"
        write_model(file, values)
    with pytest.raises(ValueError):
        verify_model_operation(
            before,
            after,
            tasks.model_operation(contract(sources)),
            changed(before, after),
        )


def check_related_detach_and_two_consumers(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    file = before / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    values.update(
        resource_values(
            "004", "ServiceB.Resource", "second", "IMPORT", [("Name", "same-name-stg")]
        )
    )
    values.update(
        reference_fields(
            "second",
            "desired.row.004-001.value",
            "same-name-stg",
            "stg/cde/service-a/001",
        )
    )
    write_model(file, values)
    dependency_refactor(before, after)
    file = after / file.relative_to(before)
    values = {
        key: value
        for key, value in load_model(file).authoritative.items()
        if not key.startswith("desired.reference.second.")
    }
    write_model(file, values)
    save(deletion(after, "stg/cde/service-a/001"))
    detaches = [
        {
            "consumer": "stg/cde/service-b/" + rid,
            "producer": "stg/cde/service-a/001",
            "key": "desired.row." + rid + "-001.value",
        }
        for rid in ("002", "004")
    ]
    operation = tasks.model_operation(
        contract(["stg/cde/service-a/001"], detaches=detaches)
    )
    verify_model_operation(before, after, operation, changed(before, after))
    file = after / "model/dev/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    values["desired.row.002-001.value"] = "unrelated"
    write_model(file, values)
    with pytest.raises(ValueError):
        verify_model_operation(before, after, operation, changed(before, after))


def check_remaining_reference_is_warning(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    shutil.copytree(before, after)
    save(deletion(after, "stg/cde/service-a/001"))
    warnings = verify_model_operation(
        before,
        after,
        tasks.model_operation(contract(["stg/cde/service-a/001"])),
        changed(before, after),
    )
    assert any(
        item["code"] == "reference.mismatch" and "absent" in item["message"]
        for item in warnings
    )


def _callback_check_fifth_save_failure_retains_first_four_fail_partial_write(
    original_write, path, /, destination, content, *args, **kwargs
):
    if destination == path:
        raise OSError("injected fifth leaf write failure")
    return original_write(destination, content, *args, **kwargs)


@pytest.mark.parametrize("failure", ["syntax", "io"])
def check_fifth_save_failure_retains_first_four(tmp_path, failure):
    sources = fixture(tmp_path, True)
    name = "tasks/parent.md"
    paths = sorted(
        {
            path.relative_to(tmp_path).as_posix()
            for source in sources
            for path in deletion(tmp_path, source)
        }
    )
    listed = "\n".join("- `" + path + "`" for path in [name, *paths])
    text = (
        contract(sources)
        + "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        + "## Validation scope\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n## Modified files\n"
        + listed
        + "\n## Allowed paths\n"
        + listed
        + "\n"
    )
    tasks.start(tmp_path, name, text)
    with patch(
        "model.operations.verify_model_operation",
        side_effect=AssertionError("leaf must not run final validation"),
    ):
        for source in sources[:4]:
            with source_write_context(tmp_path, name) as context:
                write_candidate(context, deletion(tmp_path, source))
        saved = {
            path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
        }
        with source_write_context(tmp_path, name) as context:
            edits = deletion(tmp_path, sources[4])
            path = next(iter(edits))
            if failure == "syntax":
                edits[path] = "# model-format: 2\ninvalid\n"
                with pytest.raises(ValueError):
                    write_candidate(context, edits)
            else:
                original_write = Path.write_text
                fail_partial_write = _bind_framework_callback(
                    _callback_check_fifth_save_failure_retains_first_four_fail_partial_write,
                    original_write,
                    path,
                )
                with (
                    patch.object(Path, "write_text", fail_partial_write),
                    pytest.raises(OSError, match="fifth leaf"),
                ):
                    write_candidate(context, edits)
        assert all(path.read_bytes() == content for path, content in saved.items())
        assert tasks.status((tmp_path / name).read_text()) == "running"
        # Resume the same parent; each next save sees the preceding successful sources.
        for source in sources[4:]:
            with source_write_context(tmp_path, name) as context:
                write_candidate(context, deletion(tmp_path, source))


def check_related_retarget(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    shutil.copytree(before, after)
    file = after / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    values["desired.reference.origin.producerLogicalId"] = "ServiceA_Resource_003"
    write_model(file, values)
    save(deletion(after, "stg/cde/service-a/001"))
    references = [
        {
            "consumer": "stg/cde/service-b/002",
            "field": "value",
            "property": "ServiceB.Resource.Name",
            "source": "stg/cde/service-a/001",
            "destination": "stg/cde/service-a/003",
        }
    ]
    operation = tasks.model_operation(contract(["stg/cde/service-a/001"], references))
    verify_model_operation(before, after, operation, changed(before, after))
    with pytest.raises(ValueError, match="scope|undeclared"):
        verify_model_operation(
            before,
            after,
            tasks.model_operation(contract(["stg/cde/service-a/001"])),
            changed(before, after),
        )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
