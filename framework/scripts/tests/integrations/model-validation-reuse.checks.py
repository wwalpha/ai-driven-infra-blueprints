#!/usr/bin/env python3
"""Synthetic checks for invocation-local reuse and single-service validation handoff."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import io
import os
import pytest
from support.pytest_cli import run
from unittest.mock import patch
from contextlib import redirect_stdout
from support.sync_model_fixtures import MODULE, generated_policy
from support.model_sources import write_model
from model.files import load_model, read_model
import sync_runtime
import sync_views

pytestmark = pytest.mark.usefixtures('catalog_display_fixture')
from support.validator import MODULE as validator_module
from contextvars import ContextVar
from collections import defaultdict
import subprocess
import threading
import validation_cache
import model.sources as model_sources
from support.validator import diagnostics
from validation.findings import Findings
import utils.aws_mappings as mapping_state
from utils.aws_mappings import mappings_for, mapping_alias
from support.aws_mapping_fixtures import mapping_fixture
import aws_mapping

COMMON = ('check_resource_names', 'check_design_tables', 'check_design_overviews',
          'check_design_links', 'check_design_artifacts', 'check_observed_values')
ENTRY = ('dev', '123456789012', 'iam')


def trace_validation(root, legacy=False):
    records = defaultdict(list)
    current = ContextVar('test_check', default=None)
    original_factory = sync_views.view_validator
    def instrument(validator, side):
        for name in (*COMMON, 'check_generated_service_models'):
            original = getattr(validator, name)
            def call(*args, _original=original, _name=name, **kwargs):
                records[side, _name].append(('invoked', ()))
                token = current.set((side, _name))
                try:
                    before = len(validator.errors)
                    result = _original(*args, **kwargs)
                    records[side, _name].extend((False, (error.replace(str(validator.root), '<root>'),)) for error in validator.errors[before:])
                    return result
                finally:
                    current.reset(token)
            setattr(validator, name, call)
        return validator
    def factory(stage, source, definitions_root=None):
        return instrument(original_factory(stage, source, definitions_root), 'candidate')
    def record(original):
        def call(findings, condition, *args):
            key = current.get()
            if key is None and findings.canonical_root == root.resolve():
                key = ('saved', 'other')
            if key:
                normalized = tuple(str(arg).replace(str(findings.canonical_root), '<root>').replace(str(root), '<root>') for arg in args)
                records[key].append((bool(condition), normalized))
            return original(findings, condition, *args)
        return call
    original_init = validator_module.Validator.__init__
    def init(validator, *args, **kwargs):
        original_init(validator, *args, **kwargs)
        if validator.root.resolve() == root.resolve():
            instrument(validator, 'saved')
    def generate(scope):
        try:
            MODULE.sync(root, False, *ENTRY[:2], [ENTRY[2]], jobs=4)
            return []
        except (ValueError, OSError, KeyError, TypeError) as error:
            return [str(error)]
    with patch.object(sync_views, 'view_validator', factory), \
         patch.object(validator_module.Validator, '__init__', init), \
         patch.object(Findings, 'warn', record(Findings.warn)), \
         patch.object(Findings, 'check', record(Findings.check)), \
         patch.object(Findings, 'check_file', record(Findings.check_file)):
        validator = validator_module.Validator(root, {ENTRY}, model_check=generate if legacy else None)
        validator.check_project_topology()
        validator.check_scoped_designs()
    return validator, records


@pytest.mark.parametrize('fault', ['none', 'names', 'tables', 'overview', 'links', 'json', 'observed'])
def check_common_conditions_preserved(generated_policy, monkeypatch, fault):
    root, model, values, design, artifact, register = generated_policy
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', register([])['BLUEPRINT_TASK_FILE'])
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    text = design.read_text(encoding='utf-8')
    if fault == 'names':
        text = text.replace('id="resource-IAM_Role_001"', 'id="wrong-anchor"')
    elif fault == 'tables':
        text = text.replace('RoleName', 'Unknown')
    elif fault == 'overview':
        text = text.replace('## リソース一覧', '## 一覧なし')
    elif fault == 'links':
        text += '\n[壊れた参照](missing.md#absent)\n'
    elif fault == 'json':
        artifact.write_text('{', encoding='utf-8')
    elif fault == 'observed':
        values['observed.row.001-001.value'] = '`arn:aws:iam::123456789012:role/unexpected`'
        write_model(model, values)
    design.write_text(text, encoding='utf-8')
    before, old = trace_validation(root, legacy=True)
    after, new = trace_validation(root)
    assert old['saved', 'other'] == new['saved', 'other'], fault
    for name in COMMON:
        assert old['saved', name], name
        assert new['saved', name] == old['saved', name], (fault, name)
        assert not new['candidate', name], name
        if fault == 'none':
            assert old['candidate', name], name
            assert set(old['candidate', name]) <= set(new['saved', name]), name
            assert not before.errors and not after.errors, (before.errors, after.errors)
    assert bool(after.errors) == bool(before.errors), (fault, before.errors, after.errors)
    if fault != 'none':
        assert diagnostics(after), fault
        name = {'names': COMMON[0], 'tables': COMMON[1], 'overview': COMMON[2],
                'links': COMMON[3], 'json': COMMON[4], 'observed': COMMON[5]}[fault]
        assert any(not condition for condition, _ in new['saved', name]), (fault, new['saved', name])


def check_read_scope_lifetime(generated_policy):
    root, model, values, _, _, _ = generated_policy
    original = model_sources._read_model
    scopes = []
    def expand(*args):
        scopes.append(validation_cache.memo_table())
        return original(*args)
    with patch.object(model_sources, '_read_model', side_effect=expand):
        first = read_model(model)
        assert scopes[-1] is not None
        assert validation_cache.memo_table() is None
        values['desired.row.001-001.value'] = '`changed-role`'
        write_model(model, values)
        assert read_model(model) != first
        @validation_cache.input_scope
        def nested():
            scope = validation_cache.memo_table()
            read_model(model)
            assert scopes[-1] is scope
            read_model(model)
            assert validation_cache.memo_table() is scope
        nested()
    assert validation_cache.memo_table() is None
    with patch.object(model_sources, '_read_model', side_effect=ValueError('injected')):
        with pytest.raises(ValueError, match='injected'):
            read_model(model)
    assert validation_cache.memo_table() is None


def check_deferred_guard_and_cleanup(generated_policy, monkeypatch):
    root, _, _, design, artifact, register = generated_policy
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', register([design, artifact])['BLUEPRINT_TASK_FILE'])
    for write, services in ((True, ['iam']), (False, ['iam', 's3']), (False, ['s3'])):
        with sync_views.saved_design_validation(root, ENTRY):
            with pytest.raises(ValueError, match='read-only generation'):
                MODULE.sync(root, write, *ENTRY[:2], services)
        assert sync_views._saved_design_validation.get() is None
    with pytest.raises(RuntimeError), sync_views.saved_design_validation(root, ENTRY):
        raise RuntimeError('injected')
    assert sync_views._saved_design_validation.get() is None
    seen = []
    original_factory = sync_views.view_validator
    def factory(*args):
        validator = original_factory(*args)
        for name in COMMON:
            original = getattr(validator, name)
            def call(*args, _name=name, _original=original, **kwargs):
                seen.append(_name)
                return _original(*args, **kwargs)
            setattr(validator, name, call)
        return validator
    with patch.object(sync_views, 'view_validator', side_effect=factory):
        for write in (False, True):
            seen.clear()
            assert MODULE.sync(root, write, *ENTRY[:2], ['iam']) == 0
            assert set(COMMON) <= set(seen)


@pytest.mark.parametrize('fault', ['projection', 'input', 'stale', 'exception'])
def check_generation_failures_never_pass(generated_policy, monkeypatch, fault):
    root, model, _, design, _, register = generated_policy
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', register([])['BLUEPRINT_TASK_FILE'])
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    original = sync_runtime.generate_views
    def generate(*args, **kwargs):
        generated = original(*args, **kwargs)
        stage = args[0]
        if fault == 'projection':
            staged = stage / design.relative_to(root)
            staged.write_text(staged.read_text(encoding='utf-8').replace('app-dev-role', 'different-role'), encoding='utf-8')
        elif fault == 'input':
            source = model
            source.write_bytes(source.read_bytes() + b'\n')
        elif fault == 'exception':
            raise ValueError('injected generation exception')
        return generated
    if fault == 'stale':
        design.write_bytes(design.read_bytes() + b'\nold Markdown\n')
    with patch.object(sync_runtime, 'generate_views', side_effect=generate):
        validator = validator_module.Validator(root, {ENTRY})
        argv = sys.argv[:]
        validator.check_generated_service_models()
        assert sys.argv == argv
    assert validator.errors
    assert sync_views._saved_design_validation.get() is None
    assert validation_cache.memo_table() is None


def check_single_and_parallel_threads(tmp_path):
    root, stage = tmp_path / 'root', tmp_path / 'stage'
    mapping_fixture(root, 'iam', 's3')
    provider = mappings_for(root)
    paths = [root / 'docs/designs/dev/team' / (s + '.md') for s in ('iam', 's3')]
    main = threading.get_ident()
    for count in (1, 2):
        threads = []
        barrier = threading.Barrier(2) if count == 2 else None
        def validate(*args, **kwargs):
            assert mappings_for(stage) is provider
            assert mappings_for(stage).get('iam') is provider.get('iam')
            threads.append((threading.get_ident(), validation_cache.memo_table()))
            if barrier:
                barrier.wait(timeout=10)
        @validation_cache.input_scope
        def run_candidates():
            scope = validation_cache.memo_table()
            failures = []
            with patch.object(sync_views, 'validate_views', side_effect=validate):
                sync_runtime.validate_candidates(stage, root, {p: [] for p in paths[:count]},
                                                 {p: {} for p in paths[:count]}, failures, 4, False)
            assert not failures
            if count == 1:
                assert threads == [(main, scope)]
            else:
                assert len({thread for thread, _ in threads}) == 2
                assert all(thread != main for thread, _ in threads)
        with mapping_alias(root, stage):
            run_candidates()
        assert stage not in mapping_state._aliases and stage not in mapping_state._instances


def check_authorization_before_memo_and_publication(generated_policy, monkeypatch):
    import model.importing.scope as import_scope
    root, model, _, design, artifact, register = generated_policy
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', register([design, artifact])['BLUEPRINT_TASK_FILE'])
    @validation_cache.input_scope
    def authorize():
        with patch.object(import_scope, 'read_context', return_value=('synthetic',)), \
             patch.object(import_scope, 'require_readable') as readable:
            read_model(model)
            before = readable.call_count
            readable.side_effect = ValueError('permission revoked')
            with pytest.raises(ValueError, match='permission revoked'):
                read_model(model)
            assert readable.call_count == before + 1
    authorize()
    @validation_cache.input_scope
    def publish():
        loaded = load_model(model)
        assert validation_cache.memo_table()
        original = model.read_bytes()
        assert MODULE.sync(root, True, *ENTRY[:2], ['iam']) == 0
        assert load_model(model) is loaded
        assert model.read_bytes() == original
    publish()


def check_scoped_validation_threads_and_failures(tmp_path):
    main = threading.get_ident()
    for count in (1, 2):
        entries = {('dev', 'team', s) for s in ('iam', 's3')[:count]}
        seen = []
        barrier = threading.Barrier(2) if count == 2 else None
        def designs(validator):
            seen.append((threading.get_ident(), validation_cache.memo_table()))
            if barrier:
                barrier.wait(timeout=10)
            validator.check(False, 'synthetic service failure')
        @validation_cache.input_scope
        def validate():
            scope = validation_cache.memo_table()
            validator = validator_module.Validator(tmp_path, entries, model_check=lambda _: [])
            validator.schema_catalog = object()
            with patch.object(validator_module.Validator, 'design_files', return_value=[]), \
                 patch.object(validator_module.Validator, 'check_design_service_ownership'), \
                 patch.object(validator_module.Validator, 'check_stack_designs'), \
                 patch.object(validator_module.Validator, 'check_designs', designs), \
                 patch.object(validator_module.Validator, 'check_observed_values'):
                validator.check_scoped_designs()
            assert validator.errors == ['synthetic service failure'] * count
            if count == 1:
                assert seen == [(main, scope)]
            else:
                assert len({thread for thread, _ in seen}) == 2
                assert all(thread != main and memo is not scope for thread, memo in seen)
        validate()


@pytest.mark.parametrize('fault', ['none', 'stage', 'generation', 'worker'])
def check_sync_mapping_lifetime(generated_policy, monkeypatch, fault):
    root, _, _, _, _, register = generated_policy
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', register([])['BLUEPRINT_TASK_FILE'])
    provider = mappings_for(root)
    stages = []
    already_loaded = 'iam' in provider._runtime
    original = sync_runtime.stage_inputs
    def stage_inputs(stage, source, *args):
        stages.append(stage)
        assert source == root and mappings_for(stage) is provider
        assert stage not in mapping_state._instances
        assert mappings_for(stage).get('iam') is provider.get('iam')
        if fault == 'stage':
            raise ValueError('injected stage failure')
        return original(stage, source, *args)
    def fail(*args, **kwargs):
        assert mappings_for(args[0]) is provider
        raise ValueError('injected ' + fault + ' failure')
    with patch.object(sync_runtime, 'stage_inputs', side_effect=stage_inputs), \
         patch.object(aws_mapping, 'yaml_read', wraps=aws_mapping.yaml_read) as parse:
        from contextlib import nullcontext
        target = (patch.object(sync_runtime, 'generate_views', side_effect=fail) if fault == 'generation' else
                  patch.object(sync_views, 'validate_views', side_effect=fail) if fault == 'worker' else nullcontext())
        with target:
            if fault == 'none':
                assert MODULE.sync(root, False, *ENTRY[:2], ['iam']) == 0
            else:
                with pytest.raises(ValueError, match='injected'):
                    MODULE.sync(root, False, *ENTRY[:2], ['iam'])
        assert len(stages) == 1 and parse.call_count == (0 if already_loaded else 1)
    assert all(stage not in mapping_state._aliases and stage not in mapping_state._instances for stage in stages)
    assert mappings_for(root) is provider


if __name__ == '__main__':
    raise SystemExit(run(__file__))
