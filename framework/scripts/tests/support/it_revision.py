"""Opt-in revision comparison; collection imports code in isolated child processes."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from support.it_discovery import discover


def node_difference(before, after):
    before, after = set(before), set(after)
    return {
        "removed": sorted(before - after),
        "added": sorted(after - before),
    }


def collect_nodes(tests, suite, output):
    """Use pytest's real collector, never test bodies or the suite's script entrypoint."""
    environment = os.environ.copy()
    environment.pop("BLUEPRINT_TASK_FILE", None)
    environment.pop("BLUEPRINT_IT_FIXTURES", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(Path(__file__).resolve().parents[1]), str(tests), str(tests.parent))
    )
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "--collect",
            str(tests),
            suite,
            str(output),
        ],
        cwd=tests.parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise ValueError(
            f"revision collection failed: {suite}: exit {result.returncode}\n{result.stdout}\n{result.stderr}"
        )
    nodes = json.loads(output.read_text(encoding="utf-8"))
    if (
        not isinstance(nodes, list)
        or not nodes
        or len(set(nodes)) != len(nodes)
        or any(
            not isinstance(node, str) or not node.startswith(suite + "::")
            for node in nodes
        )
    ):
        raise ValueError(f"invalid revision collection: {suite}")
    return nodes


def collection_inputs(tests):
    # Include data-driven parameters and Framework catalogs, never consumer Models.
    framework = tests.parent.parent
    suffixes = {".py", ".ini", ".json", ".yaml", ".yml", ".toml", ".properties", ".txt"}
    return {
        p.relative_to(framework): p.read_bytes()
        for p in framework.rglob("*")
        if p.is_file() and p.suffix in suffixes
    }


def compare_revisions(before, after):
    """Compare IDs and collect pytest suites only when collection inputs change."""
    requirements = [root.parent / "requirements.txt" for root in (before, after)]
    if any(path.exists() for path in requirements) and (
        not all(path.is_file() for path in requirements)
        or requirements[0].read_bytes() != requirements[1].read_bytes()
    ):
        raise ValueError(
            "revision comparison not verified: different Python requirements"
        )
    old_files, new_files = collection_inputs(before), collection_inputs(after)
    old, new = discover(before), discover(after)
    if old.errors or new.errors:
        raise ValueError(f"revision discovery failed: {old.errors}; {new.errors}")
    entries = node_difference(
        ("::".join(key) for key in old.cases), ("::".join(key) for key in new.cases)
    )
    # Dependencies/collection hooks can alter nodes without changing the suite itself.
    changed = (
        old_files != new_files
        or (before / "pytest.ini").read_bytes() != (after / "pytest.ini").read_bytes()
    )
    nodes_before, nodes_after = [], []
    if changed:
        with tempfile.TemporaryDirectory(prefix="it-revision-") as directory:
            for index, (tests, discovery, nodes) in enumerate(
                ((before, old, nodes_before), (after, new, nodes_after))
            ):
                for suite in discovery.suites:
                    expected = {
                        name
                        for (file, name), mode in discovery.cases.items()
                        if file == suite and mode == "pytest"
                    }
                    if not expected:
                        continue
                    found = collect_nodes(
                        tests, suite, Path(directory) / f"{index}.json"
                    )
                    actual = {node.split("::", 1)[1].split("[", 1)[0] for node in found}
                    if actual != expected:
                        raise ValueError(
                            f"revision collection/discovery mismatch: {suite}: {actual ^ expected}"
                        )
                    nodes.extend(found)
    if collection_inputs(before) != old_files or collection_inputs(after) != new_files:
        raise ValueError(
            "revision comparison not verified: inputs changed during collection"
        )
    return {
        "entries": entries,
        "pytest_nodes": node_difference(nodes_before, nodes_after),
        "collection": "compared"
        if changed
        else "unchanged Framework code, fixture data and pytest configuration",
        "review_required": bool(
            entries["removed"] or set(nodes_before) - set(nodes_after)
        ),
    }


class Collection:
    def __init__(self, tests):
        self.tests = tests
        self.nodes = []

    def pytest_collection_finish(self, session):
        self.nodes = [
            (session.config.rootpath / item.nodeid.split("::", 1)[0])
            .resolve()
            .relative_to(self.tests)
            .as_posix()
            + "::"
            + item.nodeid.split("::", 1)[1]
            for item in session.items
        ]


def main():
    import_arguments = sys.argv[1:]
    if len(import_arguments) != 4 or import_arguments[0] != "--collect":
        raise SystemExit("internal revision collector arguments required")
    tests, suite, output = (
        Path(import_arguments[1]).resolve(),
        import_arguments[2],
        Path(import_arguments[3]),
    )
    # Imported only in this explicit child, not during AST discovery.
    sys.path[:0] = [str(tests), str(tests.parent)]
    plugin = Collection(tests)
    result = pytest.main([str(tests / suite), "--collect-only", "-q"], plugins=[plugin])
    output.write_text(json.dumps(plugin.nodes), encoding="utf-8")
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
