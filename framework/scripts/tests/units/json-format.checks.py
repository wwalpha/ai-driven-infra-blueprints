"""JSON contracts use fixed pre-refactor bytes, messages and digests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import math
from unittest import TestCase

import pytest
from support.regression_cases import case_ids
from utils.json_format import (
    canonical_json,
    document_sha256,
    fingerprint,
    json_text,
    policy_json,
    strict_json,
    validate_aws_document,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def json_parse_case(case):
    data = case["data"]
    reader = {"strict": strict_json, "policy": policy_json}[data["reader"]]
    value = reader(case["files"]["input.json"])
    if data["shape"] == "object":
        TestCase().assertIs(type(value), dict)
        items = value["日本語"]
        TestCase().assertIs(type(items[0]), bool)
        TestCase().assertIs(type(items[1]), bool)
        TestCase().assertIsNone(items[2])
        TestCase().assertIs(type(items[3]), int)
        TestCase().assertIs(type(items[4]), float)
        TestCase().assertEqual(math.copysign(1, items[4]), -1)
        TestCase().assertIs(type(items[5]), float)
    else:
        TestCase().assertIs(type(value), list)
        TestCase().assertIs(type(value[0]), int)
    return {"value": value}


@pytest.mark.parametrize("case_id", case_ids("json_format", prefix="parse-"))
def check_parse(case_runner, case_id):
    case_runner.run("json_format", case_id, json_parse_case)


def json_error_case(case):
    data = case["data"]
    reader = {"strict": strict_json, "policy": policy_json}[data["reader"]]
    with pytest.raises(ValueError) as caught:
        reader(case["files"]["input.json"])
    TestCase().assertEqual(str(caught.value), data["message"])
    return {"error": type(caught.value).__name__, "message": str(caught.value)}


@pytest.mark.parametrize("case_id", case_ids("json_format", prefix="error-"))
def check_errors(case_runner, case_id):
    case_runner.run("json_format", case_id, json_error_case)


@pytest.mark.parametrize("raw", ["1e999", "-1e999", "[1e999]"])
def check_model_overflow_only(raw):
    with pytest.raises(ValueError) as error:
        strict_json(raw)
    assert str(error.value) == "nonfinite JSON number: " + raw.strip("[]")
    value = policy_json(raw)
    assert math.isinf(value[0] if isinstance(value, list) else value)


def check_output_bytes_and_hashes():
    value = {"z": ["日本語", True, None], "a": 1.0}
    assert json_text(value).encode(
        "utf-8"
    ) == '{"z":["日本語",true,null],"a":1.0}'.encode("utf-8")
    assert canonical_json(value).encode("utf-8") == (
        '{\n  "a": 1.0,\n  "z": [\n    "日本語",\n    true,\n    null\n  ]\n}\n'
    ).encode("utf-8")
    assert (
        document_sha256(value)
        == "39e63c66da6ddc3cd6e40fde0c98e3394095d21045500770a07ef0c24824c796"
    )
    assert (
        fingerprint(value)
        == "93d0eda33a52baf70abb1d83105d47c8657cfa4be82f89a3e5979f356d2f22a1"
    )
    assert document_sha256(value) != fingerprint(value)
    assert document_sha256({"a": 1.0, "z": value["z"]}) == document_sha256(value)
    for number in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(
            ValueError, match="Out of range float values are not JSON compliant"
        ):
            json_text(number)
    # Existing canonical/hash writers deliberately retain json.dumps allow_nan defaults.
    assert canonical_json(float("inf")) == "Infinity\n"
    assert len(document_sha256(float("nan"))) == len(fingerprint(float("nan"))) == 64


@pytest.mark.parametrize("template", [False, True])
@pytest.mark.parametrize("encoded", [False, True])
def check_aws_boundary_rejects_model_nodes(template, encoded):
    node = {"$modelRef": {"logicalId": "KMS_Key_001", "attribute": "Arn"}}
    value = {"nested": [json_text(node) if encoded else node, "literal", 3, True]}
    with pytest.raises(ValueError, match="Model reference"):
        validate_aws_document(value, template=template)
    value["nested"][0] = "arn:aws:s3:::literal"
    validate_aws_document(value, template=template)
    expression = {"Fn::GetAtt": ["Resource", "Arn"]}
    if template:
        validate_aws_document(expression, template=True)
    else:
        with pytest.raises(ValueError, match="template context"):
            validate_aws_document(expression)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
