#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.design_document_fixtures import *

def check_snapshots():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        _, path, _, _ = reference_fixture(root)
        read_text = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads, \
             patch.object(documents, "expanded_design", wraps=documents.expanded_design) as expands, \
             patch.object(documents, "resource_logical_ids", wraps=documents.resource_logical_ids) as identities:
            index = DesignIndex()
            first = index.get(path)
            def request(_):
                document = index.get(path.parent / ".." / path.parent.name / path.name)
                assert document is first
                return document.view(frozenset({"kms-aliastwo"})).expanded
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(request, range(12)))
            assert all(result is results[0] for result in results)
            assert sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == expands.call_count == identities.call_count == 1
            # A sibling alias selects the same grouped parent and shares its parse.
            assert first.view(frozenset({"kms-aliasone"})).expanded is results[0]
            assert expands.call_count == identities.call_count == 1
            original = first.text
            path.write_text(original.replace("alias/two", "alias/changed"), encoding="utf-8")
            assert index.get(path) is first and first.text == original
            index.invalidate(path)
            refreshed = index.get(path)
            assert refreshed is not first and "alias/changed" in refreshed.text
            assert sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2
            assert first.text == original
            path.unlink()
            index.invalidate(path)
            try:
                index.get(path)
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("invalidated missing target was reused")
        try:
            first.headings.expanded
        except ValueError as error:
            assert str(error) == "resource logical ID metadata must precede its anchor and heading"
        else:
            raise AssertionError("unrelated invalid metadata was not retained in the full snapshot")


import pytest
pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
