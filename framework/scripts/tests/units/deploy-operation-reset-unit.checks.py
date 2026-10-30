"""One-step Reset consent and current-state semantics, without filesystem fixtures."""

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy import operation_reset as R
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


class TestResetConsent(TestCase):
    def setUp(self):
        self.plan = {
            "id": "a" * 64,
            "mode": "all",
            "target": {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
            "files": {"journal.json": "original"},
            "replacement": "private",
        }

    def test_report_lists_lost_information_and_no_aws_claim(self):
        report = R.report(self.plan)
        self.assertEqual(report["files"], self.plan["files"])
        self.assertNotIn("replacement", report)
        self.assertIn("does not stop AWS", report["warning"])

    def test_consent_is_exact_and_not_a_force_option(self):
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.object(sys.stdout, "isatty", return_value=True),
            patch("builtins.input", return_value=R.challenge(self.plan)) as consent,
        ):
            result = R.confirm(self.plan)
        self.assertEqual(result["challenge"], R.challenge(self.plan))
        consent.assert_called_once()

    def test_noninteractive_or_wrong_consent_is_rejected(self):
        with (
            patch.object(sys.stdin, "isatty", return_value=False),
            self.assertRaises(Blocked),
        ):
            R.confirm(self.plan)
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.object(sys.stdout, "isatty", return_value=True),
            patch("builtins.input", return_value="yes"),
            self.assertRaises(Blocked),
        ):
            R.confirm(self.plan)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
