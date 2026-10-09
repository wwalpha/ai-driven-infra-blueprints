"""Pilot CLI diagnostics shared by pytest checks; framework dispatch stays unchanged."""

from pathlib import Path
import sys
import pytest


class Diagnostics:
    """Keep legacy success output while retaining pytest's failure diagnostics."""

    def pytest_runtest_logreport(self, report):
        if report.failed:
            print(report.longrepr, file=sys.stderr)

    pytest_collectreport = pytest_runtest_logreport


def run(path, checks=(), message=None):
    path = str(Path(path).resolve())
    targets = [f"{path}::{name}" for name in checks] or [path]
    result = pytest.main([*targets, "-s", "-p", "no:terminal"], plugins=[Diagnostics()])
    if result == 0 and message is not None:
        print(message)
    return int(result != 0)
