#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.json_yaml_document_hash_fixtures import *

def check_json_hash_types():
    sample={'x':'日本語','n':2,'b':False}
    assert t.json_text(sample)=='{"x":"日本語","n":2,"b":false}'
    assert t.digest(sample)==hashlib.sha256(t.json_text(sorted(sample.items())).encode('utf-8')).hexdigest()
    assert t.digest({'n':'2'})!=t.digest({'n':2})



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
