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





@pytest.mark.parametrize('diagnostic', [
    'ambiguous/type-mismatched fixed reference target',
    'unknown external instance reference: service-a/producer',
    'ambiguous/type-mismatched reference: consumer/Origin: 001',
    'IMPORT removed resource still has an incoming reference',
])
@pytest.mark.parametrize('mixed', [False, True])
def check_legacy_diagnostic_forms(tmp_path, diagnostic, mixed):
    from issue_gate import issue_errors, reference_issue_parts, task_issue_errors
    from issues_scan import existing_materials
    path = tmp_path / 'issues/dev/target/issues.md'
    path.parent.mkdir(parents=True)
    source = '7. <!-- issue-id: old-7 --> invalid service model: model/dev/target/service.properties: ' + diagnostic + '\n'
    if mixed:
        source += '   literal timeout differs\n'
    path.write_text(source)
    warnings = []
    scope = {('dev', 'target', 'service')}
    assert bool(issue_errors(tmp_path, scope, warnings=warnings)) is mixed
    assert warnings and all(w['code'] == 'reference.legacy_issue' for w in warnings)
    assert bool(task_issue_errors(tmp_path, scope, warnings=[])) is mixed
    references, errors = reference_issue_parts(source)
    assert references and bool(errors) is mixed
    items, _ = existing_materials(tmp_path, 'dev', 'target', ['service'], warnings=[])
    assert bool(items) is mixed
    assert path.read_text() == source


def check_bucket_missing_source_and_real_errors(tmp_path, monkeypatch):
    from model_references import deployment_bucket
    from support.model_sources import write_model
    view = tmp_path / 'docs/designs/dev/target/cloudformation-stacks.md'
    with pytest.raises(ReferenceResolutionError) as caught:
        deployment_bucket('[bucket](s3.md#bucket)', view, tmp_path)
    assert caught.value.diagnostic['reference'] == '[bucket](s3.md#bucket)'
    source = tmp_path / 'model/dev/target/s3.properties'
    write_model(source, {'desired.service.s3.serviceId': 's3', 'desired.service.s3.ownedCatalogResourceTypes': 'S3.Bucket'})
    parameters = tmp_path / 'model/parameters/dev/target/s3/parameters.yaml'
    parameters.write_text('instances: [')
    with pytest.raises(ValueError) as caught:
        deployment_bucket('[bucket](s3.md#bucket)', view, tmp_path)
    assert not isinstance(caught.value, ReferenceResolutionError)
    parameters.write_text('instances: {}\n')
    import model_files
    def denied(*args):
        raise PermissionError('read denied')
    monkeypatch.setattr(model_files, 'read_model', denied)
    with pytest.raises(PermissionError, match='read denied'):
        deployment_bucket('[bucket](s3.md#bucket)', view, tmp_path)


def check_link_display_and_readback_classification(tmp_path):
    from model_display import display_rows, row_table
    from design_layout import expanded_display_rows
    definitions = Path(__file__).resolve().parents[4]
    prop = 'CodeBuild.Project.VpcConfig.Subnets'
    with pytest.raises(ReferenceResolutionError):
        display_rows('CodeBuild.Project', [['1', prop, '`subnet-a`', '配置先']], definitions)
    rows = display_rows('CodeBuild.Project', [['1', prop, '[subnet-a](vpc.md#subnet-a)', '配置先']], definitions)
    document = ['### CodeBuild.Project: project', '', *row_table(rows)]
    document = [line.replace('[subnet-a](vpc.md#subnet-a)', '`subnet-a`') for line in document]
    findings = Findings(tmp_path)
    result = findings.evaluate('display', None, lambda: expanded_display_rows(document, definitions))
    assert result.model_completion_allowed and result.status == 'NOT_RUN'
    assert result.warnings and not result.errors
    with pytest.raises(ValueError) as caught:
        display_rows('CodeBuild.Project', [['1', prop, '[1]', '配置先']], definitions)
    assert not isinstance(caught.value, ReferenceResolutionError)
    with pytest.raises(ValueError) as caught:
        expanded_display_rows([line.replace('Subnets[1]', 'Subnets[2]') for line in document], definitions)
    assert not isinstance(caught.value, ReferenceResolutionError)


def codebuild_values(anchor='project', missing_name=False, second=False):
    values = {'desired.service.codebuild.serviceId': 'codebuild',
              'desired.service.codebuild.ownedCatalogResourceTypes': 'CodeBuild.Project'}
    for rid in (['001', '002'] if second else ['001']):
        values.update({f'desired.resource.{rid}.resourceType': 'CodeBuild.Project',
                       f'desired.resource.{rid}.resourceMode': 'CREATE',
                       f'desired.resource.{rid}.anchor': anchor if rid == '001' else 'other',
                       f'desired.resource.{rid}.logicalId': 'Project' + rid,
                       f'display.resource.{rid}.label': 'project' if rid == '001' else 'other'})
        rows = [('Artifacts.Type', '`NO_ARTIFACTS`'), ('Environment.Type', '`LINUX_CONTAINER`'),
                ('Environment.ComputeType', '`BUILD_GENERAL1_SMALL`'), ('Environment.Image', '`image`'),
                ('ServiceRole', '[role](iam.md#role)'), ('Source.Type', '`NO_SOURCE`')]
        if not missing_name or second and rid == '001':
            rows.append(('Name', '`project`' if rid == '001' else '`other`'))
        for n, (prop, value) in enumerate(rows, 1):
            prefix = f'desired.row.{rid}-{n:03d}.'
            values.update({prefix + 'property': 'CodeBuild.Project.' + prop, prefix + 'value': value, prefix + 'comment': '合成設定'})
    return values


@pytest.mark.parametrize('anchor', ['project', 'broken'])
@pytest.mark.parametrize('second', [False, True])
def check_independent_model_validation(tmp_path, anchor, second):
    from model_design import check_model_inputs
    values = codebuild_values(anchor, missing_name=True, second=second)
    result = check_model_inputs(tmp_path / 'model/dev/target/codebuild.properties', values, tmp_path,
                                definitions_root=Path(__file__).resolve().parents[4])
    assert any('CodeBuild.Project.Name must appear exactly once' in e for e in result.errors)
    if anchor == 'broken':
        assert any('anchor' in w['message'] for w in result.warnings)


def check_generation_warning_keeps_independent_error(tmp_path, monkeypatch):
    import sync_runtime as runtime
    root, stage = tmp_path / 'root', tmp_path / 'stage'
    path = root / 'docs/designs/dev/target/codebuild.md'
    values = codebuild_values('broken', missing_name=True)
    for name in ('validate_mappings', 'validate_required_properties', 'validate_kms_policy_accounts'):
        monkeypatch.setattr(runtime, name, lambda *a, **k: None)
    monkeypatch.setattr(runtime, 'design_target', lambda *a: {})
    def unavailable(*a, **k):
        raise ReferenceResolutionError('resource anchor mismatch')
    monkeypatch.setattr(runtime, 'markdown_for', unavailable)
    failures, warnings, unverified = [], [], {}
    assert runtime.generate_views(stage, root, {path: values}, failures,
        definitions_root=Path(__file__).resolve().parents[4], warnings=warnings, unavailable=unverified) == {}
    assert any('Name must appear exactly once' in error for error in failures)
    assert warnings and unverified[path]['retainedView'] is None
    assert unverified[path]['reason'] == 'reference' and not (stage / path.relative_to(root)).exists()



@pytest.mark.parametrize('missing_name', [False, True])
def check_unavailable_service_keeps_source_errors_and_no_cache(tmp_path, monkeypatch, missing_name):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from validation.runner import Validator
    from support.model_sources import write_model
    root = tmp_path
    scope = {('dev', 'target', 'codebuild')}
    path = root / 'model/dev/target/codebuild.properties'
    values = codebuild_values('broken', missing_name=missing_name)
    write_model(path, values)
    validator = Validator(root, scope, workers=1, definitions_root=Path(__file__).resolve().parents[4])
    validator.cache = SimpleNamespace(common=None, service_key=lambda _: 'key', load=lambda _: None, save=Mock())
    monkeypatch.setattr(Validator, 'check_design_service_ownership', lambda *a: None)
    monkeypatch.setattr(Validator, 'check_stack_designs', lambda *a: None)
    def generation(self):
        result = self.findings.result('framework.generated-service-model', scope)
        result.metadata = {'unverified': {'dev/target/codebuild': {'status': 'NOT_RUN', 'reason': 'reference', 'retainedView': None}}}
    monkeypatch.setattr(Validator, 'check_generated_service_models', generation)
    validator.check_scoped_designs()
    assert bool(validator.errors) is missing_name, validator.errors
    assert validator.warnings
    if missing_name:
        assert any('Name must appear exactly once' in e for e in validator.errors)
    result = validator.findings.result('design.service', scope)
    assert result.metadata['reason'] == 'reference'
    validator.cache.save.assert_not_called()


@pytest.mark.parametrize('missing_name', [False, True])
def check_model_warning_only_completion_and_literal_error(tmp_path, missing_name):
    from model_design import check_model_inputs
    values = codebuild_values('broken', missing_name=missing_name)
    if missing_name:
        # A separate literal error must survive the unresolved anchor too.
        values.update({'desired.row.001-999.property': 'CodeBuild.Project.TimeoutInMinutes',
                       'desired.row.001-999.value': '`invalid-integer`',
                       'desired.row.001-999.comment': '不正な設定'})
    findings = check_model_inputs(tmp_path / 'model/dev/target/codebuild.properties', values, tmp_path,
                                 definitions_root=Path(__file__).resolve().parents[4])
    assert bool(findings.errors) is missing_name, findings.errors
    assert findings.warnings
    if missing_name:
        assert any('provider schema violation' in e for e in findings.errors)
    else:
        assert all(result.model_completion_allowed for result in findings.results.values())



def check_model_document_uses_authoritative_json(tmp_path):
    from model_design import check_model_inputs
    values = {'desired.service.iam.serviceId': 'iam',
              'desired.service.iam.ownedCatalogResourceTypes': 'IAM.Role',
              'desired.resource.001.resourceType': 'IAM.Role',
              'desired.resource.001.resourceMode': 'IMPORT',
              'desired.resource.001.logicalId': 'Role',
              'desired.resource.001.anchor': 'broken',
              'desired.row.001-001.property': 'IAM.Role.RoleName',
              'desired.row.001-001.value': '`role`',
              'desired.row.001-001.comment': 'ロール名',
              'desired.row.001-002.property': 'IAM.Role.AssumeRolePolicyDocument',
              'desired.row.001-002.value': '[policy](iam/policy.json)',
              'desired.row.001-002.document': '{"Version":"2012-10-17","Statement":[]}',
              'desired.row.001-002.comment': '合成設定'}
    result = check_model_inputs(tmp_path / 'model/dev/target/iam.properties', values, tmp_path,
                                definitions_root=Path(__file__).resolve().parents[4])
    assert not result.errors, result.errors
    assert result.warnings



@pytest.mark.parametrize('missing_name', [False, True])
def check_analysis_generation_keeps_independent_checks(tmp_path, monkeypatch, missing_name):
    import sync_runtime as runtime
    from support.model_sources import write_model
    model = tmp_path / 'model/dev/target/codebuild.properties'
    write_model(model, codebuild_values('broken', missing_name=missing_name))
    def unresolved(*a, **k):
        raise ReferenceResolutionError('typed producer unavailable')
    monkeypatch.setattr(runtime, 'load_model', unresolved)
    monkeypatch.setattr(runtime, 'stage_inputs', lambda *a, **k: (set(), {}))
    plan = runtime.prepare_generation(tmp_path, {('dev', 'target', 'codebuild')}, write=False,
                                      definitions_root=Path(__file__).resolve().parents[4])
    try:
        assert bool(plan.failures) is missing_name, plan.failures
        assert plan.reference_warnings
        view = tmp_path / 'docs/designs/dev/target/codebuild.md'
        assert plan.unavailable[view]['reason'] == 'reference'
        assert plan.unavailable[view]['retainedView'] is None
    finally:
        plan.close()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
