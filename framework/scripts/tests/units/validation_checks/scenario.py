"""Scenario/Result metadata and state handoff without running scenarios."""


from support.validator import project as project
from support.validator import write as write
from validation.scenario import is_rfc3339


def check_timestamp():
    assert is_rfc3339('2026-01-01 12:00:00+09:00') and is_rfc3339('NOT_EXECUTED')
    assert not is_rfc3339('2026-01-01T12:00:00') and not is_rfc3339('invalid')
