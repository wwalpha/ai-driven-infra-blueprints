#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.framework_input_isolation_fixtures import (
    MODULE,
    Findings,
    PassCache,
    TemporaryDirectory,
)
from support.framework_input_isolation_fixtures import (
    check_structure as _check_structure,
)
from support.framework_input_isolation_fixtures import (
    check_validation_scope as _check_validation_scope,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_framework_input_guards():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        findings = Findings(root)
        _check_validation_scope({}, {'model/qa/team/vpc.properties'}, None,
                               findings, root, set(), None)
        assert 'Model source changes require service Validation scope' in findings.errors
        findings = Findings(root)
        _check_structure(findings, root)
        assert 'required directory missing: model' in findings.errors
        cache = PassCache(root, include_project=False)
        before = cache.common_key()
        (root/'project.json').write_text('invalid project', encoding='utf-8')
        assert cache.common_key() == before
        assert PassCache(root).common_key() != before
        consumer = MODULE.Validator(root, {('dev', 'fixture', 'vpc')})
        consumer.check_project_topology()
        assert any('invalid project.json' in error for error in consumer.errors)



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
