"""The lightweight adapter transport must reject invalid SDK contracts."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import boto3
import pytest
from botocore.exceptions import ParamValidationError
from support.check_model_aws_fixtures import (
    PATCHES,
    TARGET,
    FakeResource,
    SchemaOffline,
    m,
    service_model,
)
from support.check_model_aws_fixtures import (
    offline_network as offline_network,
)
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_schema_rejections(tmp_path):
    ctx = SchemaOffline(tmp_path)
    client = ctx.client("s3")
    with pytest.raises(KeyError):
        client.nonexistent_api()
    with pytest.raises(ParamValidationError):
        client.get_bucket_versioning(Bogus="fixture")
    with pytest.raises(ParamValidationError):
        client.get_bucket_versioning(Bucket=123)
    with patch.dict(PATCHES, {("s3", "get_bucket_versioning"): {"Status": 123}}):
        with pytest.raises(ParamValidationError):
            client.get_bucket_versioning(Bucket="fixture")
    ctx.verify()
    resource = FakeResource(ctx, "s3", "S3.Bucket")
    assert m.select(ctx.fetch(resource, "base"), "NonexistentField") == m.MISSING
    with pytest.raises(ValueError):
        ctx.call("s3", "delete_bucket", Bucket="fixture")


def check_context_isolation_and_cache(tmp_path):
    with (
        patch.object(boto3, "Session", side_effect=AssertionError("no boto3 Session")),
        patch.object(m.Context, "cli", side_effect=AssertionError("no CLI")),
    ):
        a = SchemaOffline(tmp_path)
        b = SchemaOffline(
            tmp_path, target=dict(TARGET, awsRegion="us-east-1", awsProfile="other")
        )
        a.verify()
        b.verify()
        assert a.client("sts") is a.client("sts")
        assert a.client("sts") is not b.client("sts")
        assert service_model("sts") is a.client("sts").model is b.client("sts").model
        resource = FakeResource(a, "s3", "S3.Bucket")
        start = len(a.trace)
        first = a.fetch(resource, "base")
        calls = a.request_count
        trace = list(a.trace)
        assert a.fetch(resource, "base") == first
        assert a.request_count == calls and a.trace[len(trace) :] == trace[start:]
        first["Name"] = "mutated"
        assert a.fetch(resource, "base")["Name"] == "fixture"
        a.target["awsRegion"] = "us-west-2"
        with pytest.raises(ValueError, match="connection changed"):
            a.call("sts", "get_caller_identity")


if __name__ == "__main__":
    raise SystemExit(run(__file__))
