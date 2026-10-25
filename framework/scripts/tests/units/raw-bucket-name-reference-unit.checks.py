#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.raw_bucket_name_reference_fixtures import (
    Path,
    declarations,
    reference,
    rejected,
    resource,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_reference_schema():
    key = "desired.row.008-001.value"
    values = resource(
        "008", "EC2.VPCEndpoint", "consumer", [("PolicyDocument", "saved")]
    )
    values.update(
        reference(
            "fixed",
            key,
            "saved",
            "vpc",
            "001",
            "S3.Bucket",
            mode="name",
            prop="S3.Bucket.BucketName",
        )
    )
    assert declarations(values)["fixed"]["format"] == "name"
    for fields, phrase in [
        ({"format": "unknown"}, "format/scope"),
        ({"labelPolicy": "fixed"}, "non-link"),
        ({"contextProperty": "environment"}, "forbidden"),
        ({"producerScope": "../team/vpc"}, "unsafe"),
        ({"selector": "first"}, "fields"),
    ]:
        bad = {
            **values,
            **{
                "desired.reference.fixed." + field: value
                for field, value in fields.items()
            },
        }
        rejected(lambda *, bad=bad: declarations(bad), phrase)
    bad = {
        key: value
        for key, value in values.items()
        if key != "desired.reference.fixed.property"
    }
    rejected(lambda: declarations(bad), "missing or forbidden")


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
