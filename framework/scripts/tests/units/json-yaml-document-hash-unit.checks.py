#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.json_yaml_document_hash_fixtures import (
    Path,
    document_sha256,
    hashlib,
    json,
    json_text,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_json_hash_types():
    sample = {"x": "日本語", "n": 2, "b": False}
    assert json_text(sample) == '{"x":"日本語","n":2,"b":false}'
    assert (
        document_sha256(sample)
        == hashlib.sha256(
            json.dumps(
                sample, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
    )
    assert document_sha256({"n": "2"}) != document_sha256({"n": 2})
    document = {
        "Statement": [
            {"Action": ["s3:GetObject", "s3:ListBucket"], "Enabled": False, "Count": 2}
        ]
    }
    reordered = {"Statement": [dict(reversed(list(document["Statement"][0].items())))]}
    assert document_sha256(reordered) == document_sha256(document)
    reordered["Statement"][0]["Action"] = list(
        reversed(reordered["Statement"][0]["Action"])
    )
    assert document_sha256(reordered) != document_sha256(document)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
