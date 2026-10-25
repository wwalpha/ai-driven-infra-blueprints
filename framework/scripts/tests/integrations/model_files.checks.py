#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
from contextlib import redirect_stderr

from model.cli import main as cli_main
from model.format import split
from support.it_case_receipt import it_case
from support.model_files_fixtures import (
    DEPLOY,
    ROOT,
    Path,
    io,
    load_model,
    markdown_for,
    model_parts,
    os,
    patch,
    redirect_stdout,
    resource_reading_fixture,
    subprocess,
    sync_files,
    sys,
    tempfile,
    write_model,
)
from utils.input_cache import input_context, memo_table

from model import sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _check_resource_reading_assert_inputs(inputs):
    for file, raw in inputs.items():
        if (file.read_bytes() if file.is_file() else None) != raw:
            raise ValueError("input changed after validation")


def _callback_check_resource_reading_cli(source, /, command, selector, *extra):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "framework/scripts/model/cli.py"),
            command,
            str(source),
            selector,
            *extra,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _callback_check_resource_reading_invoke(path, command, selector):
    stdout, stderr = io.StringIO(), io.StringIO()
    with (
        patch.object(sources, "_read_model", wraps=sources._read_model) as body,
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        code = cli_main([command, str(path), selector])
    return (code, stdout.getvalue(), stderr.getvalue()), body.call_count


@it_case
def check_resource_reading(root):
    source, values = resource_reading_fixture(root)
    cli = _bind_framework_callback(_callback_check_resource_reading_cli, source)

    invoke = _callback_check_resource_reading_invoke

    write_model(source, values)
    authority = dict(load_model(source).authoritative)
    # Exercise both a single source and Resource-aligned parts with identical values.
    for limit in (600, 100):
        old = set(model_parts(source))
        output = split(source, authority, limit=limit)
        sync_files.save_files(output)
        for obsolete in old - output.keys():
            obsolete.unlink()
        loaded = load_model(source)
        snapshot = {path: path.read_bytes() for path in loaded.files}
        assert len(loaded.parts) == 1 if limit == 600 else len(loaded.parts) > 1
        for command, selector in (
            ("find", "KMS_Key_060"),
            ("resource", "001"),
            ("trace", "desired.row.001-001.value"),
        ):
            result, count = invoke(source, command, selector)
            actual = cli(command, selector)
            assert result == (actual.returncode, actual.stdout, actual.stderr)
            assert result[0] == 0 and not result[2] and count == 1, result
        assert all(path.read_bytes() == raw for path, raw in snapshot.items())

    tasks = root / "tasks"
    tasks.mkdir()
    try:
        for name in ("one", "two"):
            (tasks / f"{name}.md").write_text(
                f"## Task contract\n- Task type: `governance`\n- Task status: `running`\n"
                f"## Modified files\n- `tasks/{name}.md`\n## Allowed paths\n- `tasks/{name}.md`\n",
                encoding="utf-8",
            )
        for command, selector in (
            ("find", "KMS_Key_001"),
            ("resource", "001"),
            ("trace", "desired.row.001-001.value"),
        ):
            with patch.dict(os.environ, {"BLUEPRINT_TASK_FILE": ""}):
                result, count = invoke(source, command, selector)
                assert (
                    result[0] == 1
                    and not result[1]
                    and "multiple running tasks" in result[2]
                    and count == 0
                )
            with patch.dict(os.environ, {"BLUEPRINT_TASK_FILE": "tasks/one.md"}):
                result, count = invoke(source, command, selector)
                assert result[0] == 0 and count == 1
    finally:
        for file in tasks.iterdir():
            file.unlink()
        tasks.rmdir()

    first = load_model(source).parts[0]
    assert_inputs = _check_resource_reading_assert_inputs

    # Publication invalidates the invocation cache; stale raw-input snapshots still fail closed.
    with input_context():
        original = load_model(source)
        saved = first.read_text()
        inputs = dict(original.dependencies)
        try:
            with sources.publication_lock(root) as journal:
                sources._publish_transaction(
                    root,
                    {first: saved.replace("用途1", "公開後の用途1")},
                    (),
                    journal,
                    start=lambda: assert_inputs(inputs),
                )
            changed = load_model(source)
            assert (
                changed is not original
                and changed.values["display.resource.001.comment"] == "公開後の用途1"
            )
            inputs = dict(changed.dependencies)
            first.write_text(saved, encoding="utf-8")
            try:
                with sources.publication_lock(root) as journal:
                    sources._publish_transaction(
                        root, {}, (), journal, start=lambda: assert_inputs(inputs)
                    )
            except ValueError as error:
                assert "changed" in str(error)
            else:
                raise AssertionError("changed snapshot accepted")
        finally:
            with sources.publication_lock(root) as journal:
                sources._publish_transaction(root, {first: saved}, (), journal)
    assert memo_table() is None


def main():
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import sys, model.core, model.files; "
            "assert not {'model.render', 'design.layout', 'sync_runtime', 'model_core', 'model_files'} & sys.modules.keys()",
        ],
        cwd=ROOT / "framework/scripts",
        check=True,
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "project.json").write_text(
            json.dumps(
                {
                    "projectName": "test",
                    "targets": [
                        {
                            "environment": "dev",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        }
                    ],
                }
            )
        )
        source = root / "model/dev/123456789012/config.properties"
        source.parent.mkdir(parents=True)
        check_resource_reading(root)
        values = {"desired.deployment.maxConcurrentStacks": "2"}
        for number in range(1, 111):
            key = f"{number:03d}"
            values.update(
                {
                    f"desired.stack.{key}.name": f"cfn-stack-app-dev-core-{key}",
                    f"desired.stack.{key}.deployOrder": "10",
                    f"desired.stack.{key}.template": "app.yaml",
                    f"desired.stack.{key}.parameters": f"app-{key}.json",
                    f"display.stack.{key}.comment": "アプリケーションのstack",
                }
            )
        stack = source.with_name("cloudformation-stacks.properties")
        write_model(stack, values)
        docs = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
        docs.parent.mkdir(parents=True)
        docs.write_text(markdown_for(docs, values, root))
        limit, units = DEPLOY.load_units(
            root, "dev", "123456789012", [values["desired.stack.001.name"]]
        )
        assert limit == 2 and len(units) == 1
        for part in load_model(stack).files:
            saved = part.read_bytes()
            part.unlink()
            try:
                load_model(stack)
            except (OSError, ValueError):
                pass
            else:
                raise AssertionError("missing authoritative part accepted")
            finally:
                part.write_bytes(saved)
        assert load_model(stack).values == values
    print(
        "model-files: PASS (format-2 parts, CLI resource/find/trace, grouped context, read-only, value/order retention, scope/cache isolation, publication and stale inputs)"
    )


if __name__ == "__main__":
    main()
