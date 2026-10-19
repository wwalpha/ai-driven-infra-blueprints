"""Reference diagnostics retain literal validation and never require live AWS or Git."""
import json
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
import pytest
from model_core import ReferenceResolutionError
from model_operation_checks import reference_equal
from model_reference_usage import _Reference, incoming_references
from model_templates import load_for_analysis
from support.import_model_fixtures import dependency_fixture
from validation.findings import Findings


def check_reference_leaf_preservation():
    reference = ('prefix-', _Reference('dev/target/service/001', 'typed'), '-suffix')
    assert reference_equal({'target': reference, 'timeout': 30}, {'target': 'prefix-new-suffix', 'timeout': 30})
    assert not reference_equal({'target': reference, 'timeout': 30}, {'target': 'prefix-new-suffix', 'timeout': 31})
    assert not reference_equal(reference, 'changed-new-suffix')
    assert not reference_equal({'target': reference}, {'target': 3})


def check_typed_findings(tmp_path):
    findings = Findings(tmp_path)
    def unresolved():
        raise ReferenceResolutionError('missing target', key='desired.row.001-001.value')
    result = findings.evaluate('links', set(), unresolved)
    assert result.status == 'NOT_RUN' and result.metadata['reason'] == 'reference'
    assert result.warnings and not result.errors
    findings.evaluate('structure', set(), lambda: findings.check(False, 'bad structure'))
    assert findings.errors == ['bad structure']


def check_incomplete_references_keep_known_records(tmp_path):
    dependency_fixture(tmp_path)
    parameters = tmp_path / 'model/parameters/stg/cde/service-b/parameters.yaml'
    original = parameters.read_text(encoding='utf-8')
    parameters.write_text(original.replace('001', '999'), encoding='utf-8')
    result = incoming_references(tmp_path, 'stg/cde/service-a/999')
    assert not result['complete'] and result['warnings']
    assert result['references'][0]['producer'] == 'stg/cde/service-a/999'
    assert result['references'][0]['consumer'] == 'stg/cde/service-b/002'
    assert json.loads(json.dumps(result))['warnings']
    assert incoming_references(tmp_path, 'stg/cde/service-a/999') == result
    model = load_for_analysis(tmp_path / 'model/stg/cde/service-b.properties')
    assert not model.complete and model.warnings


def check_reference_analysis_keeps_invalid_source_error(tmp_path):
    dependency_fixture(tmp_path)
    parameters = tmp_path / 'model/parameters/stg/cde/service-b/parameters.yaml'
    parameters.write_text('instances: [', encoding='utf-8')
    with pytest.raises(ValueError) as caught:
        incoming_references(tmp_path, 'stg/cde/service-a/001')
    assert not isinstance(caught.value, ReferenceResolutionError)



def check_deleted_target_retains_before_value(tmp_path):
    import shutil
    import yaml
    before, after = tmp_path / 'before', tmp_path / 'after'
    dependency_fixture(before)
    shutil.copytree(before / 'model', after / 'model')
    shutil.copyfile(before / 'project.json', after / 'project.json')
    directory = after / 'model/parameters/stg/cde/service-a'
    for filename, loader, dumper in [('parameters.yaml', yaml.safe_load, yaml.safe_dump),
                                      ('bindings.json', json.loads, json.dumps)]:
        file = directory / filename
        value = loader(file.read_text())
        del value['instances']['producer']
        file.write_text(dumper(value))
    result = incoming_references(after, 'stg/cde/service-a/001', before=before)
    assert result['references'] and not result['complete']
    assert any(w.get('previous_value') == 'same-name-stg' for w in result['warnings'])
    assert any(w.get('consumer') == 'stg/cde/service-b/002' and w.get('key') for w in result['warnings'])


def check_replace_keeps_snapshot_and_reports_impact(tmp_path):
    from import_promotion import replacement_inputs
    dependency_fixture(tmp_path)
    warnings = []
    inputs, services = replacement_inputs(tmp_path, ('stg', 'cde', 'service-a'),
                                         {'001': {'_action': 'replace'}}, warnings)
    assert inputs and services
    assert all((path.read_text() if path.is_file() else None) == content for path, content in inputs.items())
    assert any(w['code'] == 'reference.replace_impact' for w in warnings)


def check_reference_view_retained_but_io_still_fails(tmp_path, monkeypatch):
    import sync_runtime as runtime
    root, stage = tmp_path / 'root', tmp_path / 'stage'
    path = root / 'docs/designs/dev/target/service.md'
    path.parent.mkdir(parents=True)
    path.write_text('saved view')
    artifact = path.with_suffix('') / 'policy.json'
    artifact.parent.mkdir()
    artifact.write_text('{"original":true}')
    for name in ('validate_mappings', 'validate_required_properties', 'validate_kms_policy_accounts'):
        monkeypatch.setattr(runtime, name, lambda *a, **k: None)
    monkeypatch.setattr(runtime, 'design_target', lambda *a: {})
    def fail(*a, **k):
        raise ReferenceResolutionError('missing target')
    monkeypatch.setattr(runtime, 'markdown_for', fail)
    warnings, unavailable, failures = [], {}, []
    generated = runtime.generate_views(stage, root, {path: {}}, failures, definitions_root=root,
                                      warnings=warnings, unavailable=unavailable)
    assert generated == {} and failures == [] and warnings
    assert unavailable[path]['status'] == 'NOT_RUN'
    assert (stage / path.relative_to(root)).read_text() == 'saved view'
    assert (stage / artifact.relative_to(root)).read_text() == '{"original":true}'
    def io_fail(*a, **k):
        raise OSError('write denied')
    monkeypatch.setattr(runtime, 'markdown_for', io_fail)
    runtime.generate_views(stage, root, {path: {}}, failures, definitions_root=root)
    assert failures and 'write denied' in failures[0]


def check_completion_only_waives_reference_not_run(tmp_path):
    from validation.findings import CheckResult
    result = CheckResult('check', frozenset(), object())
    assert not result.model_completion_allowed
    result.metadata['reason'] = 'reference'
    assert result.model_completion_allowed
    result.errors = ('literal mismatch',)
    assert not result.model_completion_allowed
    findings = Findings(tmp_path)
    def mixed():
        findings.check(False, 'literal mismatch')
        raise ReferenceResolutionError('missing target')
    result = findings.evaluate('mixed', set(), mixed)
    assert result.status == 'FAIL' and result.warnings and result.errors


def check_legacy_issues_keep_number_and_mixed_error(tmp_path):
    from issue_gate import issue_errors, unresolved_services, reference_issue_parts
    path = tmp_path / 'issues/dev/target/issues.md'
    path.parent.mkdir(parents=True)
    source = '1. broken local parentReference\n'
    path.write_text(source)
    warnings = []
    assert not issue_errors(tmp_path, {('dev', 'target', 'service')}, warnings=warnings)
    assert warnings and unresolved_services(tmp_path, path)[0][0] == '1'
    assert path.read_text() == source
    assert reference_issue_parts('reference timeout differs')[1]
    path.write_text(source + '   literal timeout differs\n')
    assert issue_errors(tmp_path, {('dev', 'target', 'service')})



def check_json_leaf_warning_keeps_sibling_error(tmp_path):
    from import_references import Resolver
    resolver = Resolver(tmp_path, 'dev', 'target')
    with pytest.raises(ValueError, match='literal differs'):
        resolver.verify_tree('Example.Config', {'target': '<<Missing>>', 'timeout': 30},
                             {'target': 'resource', 'timeout': 31}, {},
                             location={'key': 'desired.row.001-001.document'})
    assert resolver.warnings[0]['pointer'] == '/target'
    assert resolver.warnings[0]['key'] == 'desired.row.001-001.document'


def check_json_cli_warning_success(tmp_path, monkeypatch, capsys):
    import model_reference_usage as usage
    dependency_fixture(tmp_path)
    path = tmp_path / 'model/parameters/stg/cde/service-b/parameters.yaml'
    path.write_text(path.read_text().replace('001', '999'))
    monkeypatch.setattr(sys, 'argv', ['reference', 'stg/cde/service-a/999', '--repository-root', str(tmp_path)])
    assert usage.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['warnings'] and payload['complete'] is False


def check_generation_metadata_reaches_findings(tmp_path, monkeypatch):
    from contextlib import ExitStack
    import sync_runtime as runtime
    path = tmp_path / 'docs/designs/dev/target/service.md'
    plan = runtime.Generation(tmp_path, tmp_path / 'stage', {('dev', 'target', 'service')}, [], [], None, ExitStack())
    plan.unavailable[path] = {'reason': 'reference', 'status': 'NOT_RUN', 'retainedView': str(path)}
    plan.reference_warnings.append(ReferenceResolutionError('missing target').diagnostic)
    monkeypatch.setattr(runtime, 'prepare_generation', lambda *a, **k: plan)
    monkeypatch.setattr(runtime, 'validate_generation', lambda *a, **k: None)
    findings = Findings(tmp_path)
    assert runtime.compare_generation(tmp_path, plan.scope, findings=findings) == ()
    metadata = findings.result('framework.generated-service-model', plan.scope).metadata
    assert metadata['complete'] is False
    assert metadata['unverified']['dev/target/service']['retainedView'] == str(path)
    assert findings.warnings


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
