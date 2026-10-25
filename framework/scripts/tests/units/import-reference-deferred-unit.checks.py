"""The shared exception/cause/category contract; callers test their own propagation."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.deferral import (
    CATEGORIES,
    ImportReferenceDeferred,
    defer_import_reference,
    failure_category,
    validate_cause,
)
from issues.aggregate import iac_summary
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize("phase", ["unobserved", "pending_deploy", "awaiting_handoff"])
def test_normal_wait(phase):
    error = ImportReferenceDeferred(
        phase,
        "vpc",
        "004",
        "EC2.Subnet",
        "SubnetId",
        "CodeBuild.Project.VpcConfig.Subnets[]",
    )
    category = "excluded" if phase == "pending_deploy" else "deferred"
    assert isinstance(error, Blocked) and failure_category(error) == category
    assert error.iac_cause == dict(
        kind="import-reference-excluded"
        if phase == "pending_deploy"
        else "import-reference-deferred",
        phase=phase,
        producer=dict(
            service="vpc",
            resource="004",
            resourceType="EC2.Subnet",
            attribute="SubnetId",
        ),
        consumer_property="CodeBuild.Project.VpcConfig.Subnets[]",
    )
    validate_cause(error.iac_cause)


def test_other_failures_are_not_normal_waits():
    for error in (Blocked("comparison deferred"), KeyError("IMPORT reference")):
        assert failure_category(error) == "uncompared"
    for error in (ValueError(), TypeError(), OSError(), ImportError(), IndexError()):
        assert failure_category(error) == "error"
    assert len(CATEGORIES) == len(set(CATEGORIES)) == 6
    with pytest.raises(ValueError, match="phase"):
        ImportReferenceDeferred(
            "unknown", "vpc", "004", "EC2.Subnet", "SubnetId", "consumer"
        )
    for cause in (
        None,
        {},
        {"kind": "import-reference-deferred", "phase": "unobserved"},
    ):
        with pytest.raises(ValueError, match="cause"):
            validate_cause(cause)


@pytest.mark.parametrize(
    "observed,phase",
    [
        (None, "unobserved"),
        ("PENDING_DEPLOY", "pending_deploy"),
        ("valid-id", "awaiting_handoff"),
    ],
)
def test_phase_selection_uses_authoritative_observations(observed, phase):
    authority = (
        {} if observed is None else {"observed.row.004-001.value": "`" + observed + "`"}
    )
    inputs = SimpleNamespace(
        local_comparison=True,
        rows={"vpc": {"004": [("004-001", {"property": "Test.Resource.Id"})]}},
        models={"vpc": SimpleNamespace(authoritative=authority)},
        catalog=Mock(),
    )
    inputs.catalog.property_schema.return_value = {"type": "string"}
    inputs.catalog.literal_errors.return_value = []
    symbol = {"$resource": ["vpc", "004"], "$attribute": "Id"}
    producer = {"resourceType": "Test.Resource", "resourceMode": "IMPORT"}
    consumer_property = "Consumer.Resource.Reference"
    with pytest.raises(ImportReferenceDeferred) as failure:
        defer_import_reference(inputs, symbol, producer, consumer_property)
    assert failure.value.iac_cause["phase"] == phase
    assert inputs.catalog.literal_errors.call_count == (
        1 if phase == "awaiting_handoff" else 0
    )

    for identifier_rows in ([], inputs.rows["vpc"]["004"] * 2):
        inputs.rows["vpc"]["004"] = [
            ("004-002", {"property": "Test.Resource.Name"})
        ] + identifier_rows
        with pytest.raises(Blocked) as failure:
            defer_import_reference(inputs, symbol, producer, consumer_property)
        category = failure_category(failure.value)
        assert category == "uncompared"
        report = iac_summary(
            [
                dict(
                    category=category,
                    service="consumer",
                    resource="001",
                    property=consumer_property,
                    reason=str(failure.value),
                )
            ],
            "fixture",
            "team",
            ["consumer"],
        )
        assert report["records"]["deferred"] == 0
        assert report["records"]["uncompared"] == 1
        assert report["categories"]["比較未完了"] == 1
        assert report["issue_count"] == 1


if __name__ == "__main__":
    raise SystemExit(run(__file__))
