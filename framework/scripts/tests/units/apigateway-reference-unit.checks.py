"""API Gateway public/private domain ARN distinctions over synthetic settings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from comparison.services.apigateway import arn_components
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize(
    "configuration", [{}, {"Types": ["EDGE"]}, {"Types": ["REGIONAL"]}]
)
def test_public_domain(configuration):
    assert (
        arn_components({"EndpointConfiguration": configuration}, lambda value: value)
        == {}
    )


@pytest.mark.parametrize(
    "configuration",
    [
        {"Types": ["PRIVATE"]},
        {"Types": []},
        {"Types": ["UNKNOWN"]},
        {"Types": ["EDGE", "REGIONAL"]},
        {"Types": "EDGE"},
        None,
    ],
)
def test_unproven_domain(configuration):
    with pytest.raises(Blocked):
        arn_components({"EndpointConfiguration": configuration}, lambda value: value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
