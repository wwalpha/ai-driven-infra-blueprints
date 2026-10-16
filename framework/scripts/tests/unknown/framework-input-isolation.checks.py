#!/usr/bin/env python3
"""Framework validation must never inspect real consumer inputs."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from contextlib import ExitStack, redirect_stdout
import io
from tempfile import TemporaryDirectory
from unittest.mock import patch

from support.validator import MODULE
from validation.framework_contracts import check_structure
from validation.findings import Findings
from validation.project import check_validation_scope
from validation_cache import PassCache
from support.validation_checks.task import check_task_type_dispatch

ROOT = Path(__file__).resolve().parents[4]


def check():
    if not __debug__:
        raise SystemExit('Focused checks require assertions; run without -O')
    validator = MODULE.Validator(ROOT, set(), cache=True, fresh=True)
    with ExitStack() as stack, redirect_stdout(io.StringIO()) as output:
        for name in ('stat', 'open', 'glob', 'rglob', 'iterdir'):
            original = getattr(Path, name)
            def guarded(path, *args, original=original, **kwargs):
                assert path != ROOT/'project.json' and not path.is_relative_to(ROOT/'model'), path
                return original(path, *args, **kwargs)
            stack.enter_context(patch.object(Path, name, guarded))
        assert validator.run() == 0, output.getvalue()
        check_task_type_dispatch()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        findings = Findings(root, True)
        check_validation_scope({}, {'model/templates/team/vpc.properties.tpl'}, None,
                               findings, root, set(), None)
        assert 'Model source changes require service Validation scope' in findings.errors
        findings = Findings(root, True)
        check_structure(findings, root)
        assert 'required directory missing: model/parameters' in findings.errors
        assert 'required directory missing: model/templates' in findings.errors
        cache = PassCache(root, include_project=False)
        before = cache.common_key()
        (root/'project.json').write_text('invalid project', encoding='utf-8')
        assert cache.common_key() == before
        assert PassCache(root).common_key() != before
        consumer = MODULE.Validator(root, {('dev', 'fixture', 'vpc')})
        consumer.check_project_topology()
        assert any('invalid project.json' in error for error in consumer.errors)
    print('Framework input isolation: PASS (no Model/project access; consumer validation retained)')


if __name__ == '__main__':
    check()
