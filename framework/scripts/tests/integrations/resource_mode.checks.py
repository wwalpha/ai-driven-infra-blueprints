#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from model.sources import model_parts
from support.it_case_receipt import it_case
from support.resource_mode_fixtures import (
    SYNC,
    Path,
    json,
    markdown_for,
    model,
    read_model,
    snapshot_model,
    sync_views,
    sys,
    tempfile,
    write_model,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def _callback_main_check(path, root, source, /, values):
    values = {key: value for key, value in values.items() if not (key.startswith("observed.row.") and key.endswith((".property", ".comment")))}
    original = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    write_model(source, original)
    original = {file: file.read_bytes() for file in (source, *model_parts(source))}
    try:
        read_model(source)
        path.write_text(markdown_for(path, values, root), encoding="utf-8")
        sync_views.validate_views(root, root, [path], {path: values})
    except (ValueError, KeyError) as error:
        return str(error)
    assert snapshot_model(source) == original
    assert path.read_text(encoding="utf-8") == markdown_for(path, values, root)
    assert "resource-mode:" not in path.read_text(encoding="utf-8")
    assert "resource-entry:" not in path.read_text(encoding="utf-8")
    return ""


@it_case
def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation",
        }]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/ec2.md"
        source = root / "model/dev/123456789012/ec2.properties"
        path.parent.mkdir(parents=True)
        source.parent.mkdir(parents=True)

        write_model(source.with_name('cloudformation-stacks.properties'), {
            'desired.stack.001.name': 'fixture', 'desired.stack.001.placementName': 'fixture',
            'desired.stack.001.template': 'fixture.yaml', 'desired.stack.001.parameters': 'fixture.json',
            'desired.stack.001.deployOrder': '1', 'display.stack.001.comment': '合成Stack'})
        check = _bind_framework_callback(_callback_main_check, path, root, source)

        imported = model(name="PRIVATE_SUBNET_01", mode="IMPORT")
        assert not (error := check(imported)), error
        original = path.read_text(encoding="utf-8")
        stale = original + '# edited generated view\n'
        path.write_text(stale, encoding='utf-8')
        try:
            SYNC.sync(root, False, "dev", "123456789012", services=["ec2"])
        except ValueError as error:
            assert "stale or missing" in str(error), error
        else:
            raise AssertionError("stale generated view accepted")
        # Coverage-only exemption does not waive confirmed actual name checks.
        assert not (error := check(imported)), error
        before = snapshot_model(source)
        assert SYNC.sync(root, True, "dev", "123456789012", services=["ec2"]) == 0
        assert SYNC.sync(root, False, "dev", "123456789012", services=["ec2"]) == 0
        assert snapshot_model(source) == before
        assert "PRIVATE_SUBNET_01" in path.read_text(encoding="utf-8")



if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()
