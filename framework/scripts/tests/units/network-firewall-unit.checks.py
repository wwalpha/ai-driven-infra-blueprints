"""Network Firewall ARN components; all inputs are synthetic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from utils.arn_components import rule_group as arn_components
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize(
    "value,expected", [("STATEFUL", "stateful"), ("STATELESS", "stateless")]
)
def test_rule_group_type(value, expected):
    assert arn_components({"Type": value}, str) == {"type": expected}


@pytest.mark.parametrize("value", [None, "", "stateful", "UNKNOWN", {}, []])
def test_unproven_rule_group_type(value):
    with pytest.raises(Blocked):
        arn_components({"Type": value}, lambda value: value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
