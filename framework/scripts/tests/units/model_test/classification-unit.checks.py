import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

import pytest
from support.fixture_cases import load_case
from support.model_test_cases import queue_exclusion_case, sensitive_exclusion_case
from support.pytest_cli import run
from support.regression_cases import case_ids

from model import audit_runtime as audit


@pytest.mark.parametrize(
    "case_id", case_ids("model_test_classification", prefix="queue-")
)
def test_queue_policy_exclusion(case_runner, case_id):
    case_runner.run("model_test_classification", case_id, queue_exclusion_case)


@pytest.mark.parametrize(
    "case_id", case_ids("model_test_classification", prefix="sensitive-")
)
def test_sensitive_exclusion(case_runner, case_id):
    case_runner.run("model_test_classification", case_id, sensitive_exclusion_case)


def test_classification_secret_failure_before_snapshot():
    case = load_case("model_test_classification", "sensitive-normal")
    with (
        patch.object(
            audit, "classify_exclusion", return_value={"designValue": "secret"}
        ),
        pytest.raises(pytest.fail.Exception, match="secret exposed") as caught,
    ):
        sensitive_exclusion_case(case)
    TestCase().assertEqual(
        str(caught.value), "Audit exclusion secret exposed before snapshot"
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
