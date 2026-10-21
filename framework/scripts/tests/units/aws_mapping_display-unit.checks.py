#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.aws_mapping_display_fixtures import *







def check_validation_projection_scope(tmp_path):
    import aws_mapping_display as display
    import sync_views
    source = {'first': 'one', 'second': 'two'}
    provider = object()
    calls = []

    def projected(values, root):
        calls.append((tuple(values.items()), root))
        if 'invalid' in values:
            raise ValueError('projection failure')
        return dict(values)

    with patch.object(display, 'projection', side_effect=projected), patch.object(
            display, 'mappings_for', return_value=provider) as providers:
        with display._validation_projection_scope():
            first = display._validation_projection(source, tmp_path)
            first['first'] = 'caller mutation'
            assert display._validation_projection(source, tmp_path) == source
            assert len(calls) == 1
            for operation in ('change', 'add', 'delete', 'order'):
                if operation == 'change':
                    source['first'] = 'changed'
                elif operation == 'add':
                    source['third'] = 'three'
                elif operation == 'delete':
                    del source['third']
                else:
                    source['first'] = source.pop('first')
                before = len(calls)
                assert list(display._validation_projection(source, tmp_path).items()) == list(source.items())
                assert len(calls) == before + 1
            display._validation_projection(dict(source), tmp_path)
            assert len(calls) == 6
            display._validation_projection(source, tmp_path / 'other-root')
            assert len(calls) == 7
            providers.return_value = object()
            display._validation_projection(source, tmp_path)
            assert len(calls) == 8
            source['invalid'] = 'yes'
            for _ in range(2):
                try:
                    display._validation_projection(source, tmp_path)
                except ValueError as error:
                    assert str(error) == 'projection failure'
                else:
                    raise AssertionError('exception must propagate')
            assert len(calls) == 10
            del source['invalid']
            # Direct callers always compute, even inside validation.
            display.projection(source, tmp_path)
            display.projection(source, tmp_path)
            assert len(calls) == 12
        assert display._validation_projections.get() is None
        with display._validation_projection_scope():
            display._validation_projection(source, tmp_path)
            assert len(calls) == 13
        display._validation_projection(source, tmp_path)
        display._validation_projection(source, tmp_path)
        assert len(calls) == 15

    def fail(*args):
        assert display._validation_projections.get() == {}
        raise ValueError('validator failure')

    with patch.object(sync_views, 'view_validator', side_effect=fail):
        for _ in range(2):
            try:
                sync_views.validate_views(tmp_path, tmp_path, [], {})
            except ValueError as error:
                assert str(error) == 'validator failure'
            else:
                raise AssertionError('validator must fail')
            assert display._validation_projections.get() is None




if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
