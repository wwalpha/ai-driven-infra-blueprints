#!/usr/bin/env python3
"""Real pinned lint/config/worker integration on temporary inputs and HOME only."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import subprocess
from unittest.mock import patch

import pytest
from cfnlint.helpers import get_cache_dir
from issues.publication import save_scan
from issues.runner import scan
from issues.runner import verify_inputs as original_guard
from support.issues_scan_fixtures import fixture, review_for, task
from support.pytest_cli import run
from utils.cfn_lint import (
    Worker,
    lint_session,
    scope,
    validate_template,
    verify_dependencies,
)
from utils.cfn_lint import validate_template as real_lint
from validation.runner import Validator
from validation_cache import PassCache

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


def isolated(tmp_path, monkeypatch):
    home=tmp_path/'home'
    home.mkdir()
    cwd=tmp_path/'project'
    cwd.mkdir()
    monkeypatch.setenv('HOME',str(home))
    monkeypatch.setenv('USERPROFILE',str(home))
    monkeypatch.setenv('XDG_CACHE_HOME',str(home/'.cache'))
    monkeypatch.setenv('LOCALAPPDATA',str(home/'AppData/Local'))
    monkeypatch.chdir(cwd)
    return home,cwd


def args(template):
    return ['cfn-lint','--regions','ap-northeast-1','--template',str(template.resolve()),'--format','json']


def baseline(template):
    code='from cfnlint.runner import main; main()'
    return subprocess.run([sys.executable,'-B','-c',code,*args(template)[1:]],capture_output=True,text=True,timeout=60)


def signature(matches, decoded=True):
    return sorted((m['Rule']['Id'],m['Level'],json.dumps(m['Location'],sort_keys=True),
                   m['Message'] if decoded else 'Template decode incomplete; see Rule and Location') for m in matches)


@pytest.mark.parametrize('body', [
    'Resources:\n  B:\n    Type: AWS::S3::Bucket\n',
    'Resources:\n  B:\n    Type: AWS::S3::Bucket\n    Properties:\n      Wrong: true\n',
    'Resources: [broken',
    '- not-an-object\n'])
def check_cli_equivalence(tmp_path,monkeypatch,body):
    home,cwd=isolated(tmp_path,monkeypatch)
    (home/'.cfnlintrc.yml').write_text('include_checks: [I]\n')
    template=cwd/'app.yaml'
    template.write_text(body)
    previous=baseline(template)
    with lint_session(cwd) as session:
        execution=validate_template(session,template,'ap-northeast-1')
    assert execution['completed'] and not execution['processing_errors'],execution
    assert signature(execution['matches'])==signature(json.loads(previous.stdout or '[]'),execution['decode_complete'])
    assert execution['requested_region']=='ap-northeast-1'
    assert execution['effective_regions']==['ap-northeast-1']
    verify_dependencies(execution['dependencies'])


def check_config_exclusion_and_outputs(tmp_path,monkeypatch):
    home,cwd=isolated(tmp_path,monkeypatch)
    template=cwd/'app.yaml'
    template.write_text('Resources: [broken')
    output=cwd/'forbidden.json'
    config=cwd/'.cfnlintrc'
    config.write_text(json.dumps({'ignore_templates':[str(template)],'output_file':str(output)}))
    with lint_session(cwd) as session:
        result=validate_template(session,template,'ap-northeast-1')
        assert result['status']=='excluded_by_config' and not result['completed'] and result['unverified']
        assert not output.exists()
        for setting in ({'ignore_bad_template':True},{'ignore_checks':['E0000']}):
            config.write_text(json.dumps(dict(setting,output_file=str(output))))
            result=validate_template(session,template,'ap-northeast-1')
            assert result['completed'] and result['matches']==[] and not result['decode_complete']
            assert result['unverified'] and not result['processing_errors']
            assert not output.exists()
        config.write_text(json.dumps({'deployment_files':['other.json']}))
        result=validate_template(session,template,'ap-northeast-1')
        assert result['processing_errors'] and not result['completed']


def check_noecho_and_dependencies(tmp_path,monkeypatch):
    home,cwd=isolated(tmp_path,monkeypatch)
    template=cwd/'app.yaml'
    config=cwd/'.cfnlintrc'
    secret='fixture-super-private'
    template.write_text('Parameters:\n  Input:\n    Type: String\n    NoEcho: true\n    Default: '+secret+'\n    AllowedValues: [other]\nResources:\n  B:\n    Type: AWS::S3::Bucket\n')
    config.write_text(json.dumps({'parameters':[{'Input':secret}]}))
    with lint_session(cwd) as session:
        result=validate_template(session,template,'ap-northeast-1')
    result.pop('sensitive_values',None)  # This in-memory channel feeds the caller's existing redactor.
    assert secret not in json.dumps(result)
    dependencies=result['dependencies']
    verify_dependencies(dependencies)
    candidate=home/'.cfnlintrc.yaml'
    candidate.write_text('{}')
    with pytest.raises(ValueError,match='stale scan'):
        verify_dependencies(dependencies)
    candidate.unlink()
    config.write_text('{}')
    with pytest.raises(ValueError,match='stale scan'):
        verify_dependencies(dependencies)


def check_rule_schema_state_and_reaping(tmp_path,monkeypatch):
    home,cwd=isolated(tmp_path,monkeypatch)
    template=cwd/'app.yaml'
    template.write_text('Resources:\n  B:\n    Type: AWS::S3::Bucket\n')
    rules=cwd/'rules'
    rules.mkdir()
    rule=rules/'Stateful.py'
    rule.write_text("""from cfnlint.rules import CloudFormationLintRule, RuleMatch
calls=0
class Stateful(CloudFormationLintRule):
    id='E9999'
    shortdesc='State isolation'
    description='Synthetic stateful rule'
    tags=['fixture']
    def match(self,cfn):
        global calls
        calls+=1
        return [RuleMatch(['Resources'],'invocation '+str(calls))]
""")
    registry=cwd/'registry'
    registry.mkdir()
    schema=registry/'bucket.json'
    schema.write_text(json.dumps({'typeName':'AWS::S3::Bucket','description':'fixture',
        'properties':{'RequiredFixture':{'type':'string'}},'required':['RequiredFixture'],
        'primaryIdentifier':['/properties/RequiredFixture'],'additionalProperties':False}))
    config=cwd/'.cfnlintrc'
    override=cwd/'override.json'
    override.write_text(json.dumps({'IncludeResourceTypes':['AWS::S3::Bucket']}))
    with lint_session(cwd) as session:
        for settings in ({'append_rules':[str(rules)]},{'registry_schemas':[str(registry)]},{'override_spec':str(override)},{},{'append_rules':[str(rules)]}):
            config.write_text(json.dumps(settings))
            result=validate_template(session,template,'ap-northeast-1')
            assert result['completed'] and not result['processing_errors'],result
            messages=[m['Message'] for m in result['matches']]
            assert ('invocation 1' in messages)==bool(settings.get('append_rules'))
            assert any('RequiredFixture' in message for message in messages)==bool(settings.get('registry_schemas'))
        process=session.worker.process
    assert process.poll() is not None
    config.write_text(json.dumps({'append_rules':[str(rules)]}))
    rule.write_text('import os; os._exit(7)')
    with lint_session(cwd) as session:
        assert validate_template(session,template,'ap-northeast-1')['processing_errors']
        rule.write_text('# no custom rules')
        assert validate_template(session,template,'ap-northeast-1')['completed']
        process=session.worker.process
    assert process.poll() is not None


def check_legacy_worker_scope(tmp_path,monkeypatch):
    _,cwd=isolated(tmp_path,monkeypatch)
    template=cwd/'app.yaml'
    template.write_text('Resources:\n  B:\n    Type: AWS::S3::Bucket\n')
    backend=type('Backend',(),{})()
    with pytest.raises(RuntimeError,match='injected'),scope(backend,[1,2]):
        worker=backend.lint.__self__
        expected=baseline(template)
        actual=worker.run(args(template))
        assert (actual.returncode,actual.stdout,actual.stderr)==(expected.returncode,expected.stdout,expected.stderr)
        process=worker.process
        raise RuntimeError('injected')
    assert not hasattr(backend,'lint') and process.poll()==0


@pytest.mark.parametrize('mapping_missing',[False,True])
def check_offline_schema(tmp_path,monkeypatch,mapping_missing):
    home,cwd=isolated(tmp_path,monkeypatch)
    cache=Path(get_cache_dir())
    (cache/'providers').mkdir(parents=True)
    (cache/'resources').mkdir()
    (cache/'version.json').write_text('{"schema_date":"9999-12-31"}')
    (cache/'providers'/('sam.json' if mapping_missing else 'us-east-1.json')).write_text(
        json.dumps({'AWS::S3::Bucket':'missing-fixture-schema'}))
    template=cwd/'app.yaml'
    template.write_text('Resources:\n  B:\n    Type: AWS::S3::Bucket\n')
    with lint_session(cwd) as session:
        result=validate_template(session,template,'ap-northeast-1')
        assert any(error['code']=='schema_unavailable' for error in result['processing_errors']),result
        assert result['fatal'] and result['unverified']
        assert validate_template(session,template,'ap-northeast-1')['status']=='not_run'
    assert not (cache/'resources/missing-fixture-schema.json').exists()


def check_timeout(tmp_path,monkeypatch):
    _,cwd=isolated(tmp_path,monkeypatch)
    template=cwd/'app.yaml'
    template.write_text('Resources: {}')
    rules=cwd/'rules'
    rules.mkdir()
    (rules/'Slow.py').write_text('import time; time.sleep(30)')
    (cwd/'.cfnlintrc').write_text(json.dumps({'append_rules':[str(rules)]}))
    worker=Worker()
    try:
        result=worker.request(dict(cwd=str(cwd),template=str(template.resolve()),region='ap-northeast-1'),timeout=0.01)
        assert result['processing_errors'][0]['code']=='timeout'
        assert worker.process is None
    finally:
        worker.close()


def _callback_check_scan_publication_and_missing_view_cache_save(events, save_cache, /, cache, *args):
    events.append('cache')
    return save_cache(cache,*args)


def _callback_check_scan_publication_and_missing_view_guard(events, /, *args, **kwargs):
    result=original_guard(*args,**kwargs)
    events.append('guard')
    return result


@pytest.mark.parametrize("view_failure", ["missing", "utf8"])
def check_scan_publication_and_missing_view(tmp_path,monkeypatch,view_failure):
    _,cwd=isolated(tmp_path,monkeypatch)
    root=cwd/'fixture'
    fixture(root,stacks=3,services=['s3','sqs'])
    events=[]
    save_cache=PassCache.save
    cache_save = _bind_framework_callback(_callback_check_scan_publication_and_missing_view_cache_save, events, save_cache)
    guard = _bind_framework_callback(_callback_check_scan_publication_and_missing_view_guard, events)
    with patch('issues.runner.verify_inputs',side_effect=guard),patch.object(PassCache,'save',cache_save):
        artifact=scan(root,'dev','123456789012',['s3','sqs'],fresh=True,jobs=1)
    assert artifact['version']==2 and len(artifact['cfn_lint']['jobs'])==1
    assert all(index>events.index('guard') for index,event in enumerate(events) if event=='cache')
    assert artifact['metrics']['template_decodes']==1
    with task(root,['s3','sqs']):
        review=review_for(artifact)
        with patch('issues.aggregate.iac_dataset',side_effect=AssertionError('repeat aggregation')), \
             patch('comparison.Comparison.run',side_effect=AssertionError('repeat comparison')), \
             patch('utils.cfn_lint.validate_template',side_effect=AssertionError('repeat lint')):
            files=save_scan(root,artifact,review)
        assert len(files)==2 and all(path.is_file() for path in files)
        with pytest.raises(ValueError,match='scan_id'):
            save_scan(root,artifact,dict(review,scan_id='wrong'))
        template=root/'infra/cloudformation/templates/shared.yaml'
        previous=template.read_bytes()
        template.write_bytes(previous+b'\n')
        with pytest.raises(ValueError,match='stale scan'):
            save_scan(root,artifact,review)
        template.write_bytes(previous)
    bad = root/'docs/designs/dev/123456789012/s3.md'
    if view_failure == 'missing':
        bad.unlink()
    else:
        bad.write_bytes(b'\xff private fixture body')
    doc=root/'docs/designs/dev/123456789012/sqs.md'
    doc.write_text(doc.read_text()+'\nfixture drift\n')
    result=scan(root,'dev','123456789012',['s3','sqs'],fresh=True,jobs=1)
    code = 'mechanical.view_missing' if view_failure == 'missing' else 'mechanical.view_unverified'
    assert any(n['code'] == code and n.get('service') == 's3' for n in result['unverified'])
    assert result['cfn_lint']['jobs'] and all(j['completed'] for j in result['cfn_lint']['jobs'])
    if view_failure == 'utf8':
        assert result['processing_errors'] and result['validation_status'] == 'ERROR'
        assert 'private fixture body' not in json.dumps(result)
        with task(root, ['s3', 'sqs']):
            files = save_scan(root, result, review_for(result))
            assert all(p.is_file() for p in files)
            assert '処理エラー' in files[0].read_text()
            original = bad.read_bytes()
            bad.write_bytes(b'repaired')
            with pytest.raises(ValueError, match='stale scan'):
                save_scan(root, result, review_for(result))
            bad.write_bytes(original)
    assert any('sqs' in str(item) for item in result['ordinary']+result['judgments'])


@pytest.mark.parametrize('broken', ['{ broken json', '{}'])
def check_corrupt_provider_schema(tmp_path, monkeypatch, broken):
    home, cwd = isolated(tmp_path, monkeypatch)
    cache = Path(get_cache_dir())
    (cache / 'providers').mkdir(parents=True)
    (cache / 'resources').mkdir()
    (cache / 'version.json').write_text('{"schema_date":"9999-12-31"}')
    (cache / 'providers/us-east-1.json').write_text(json.dumps({
        'AWS::S3::Bucket': 'broken-local-schema', 'AWS::SQS::Queue': 'valid-local-schema'}))
    schema = cache / 'resources/broken-local-schema.json'
    schema.write_text(broken)
    (cache / 'resources/valid-local-schema.json').write_text(json.dumps({
        'typeName': 'AWS::SQS::Queue', 'description': 'synthetic queue',
        'properties': {'QueueName': {'type': 'string'}}, 'additionalProperties': False,
        'primaryIdentifier': ['/properties/QueueName']}))
    template = cwd / 'app.yaml'
    template.write_text('Resources:\n  Queue:\n    Type: AWS::SQS::Queue\n    Properties:\n      Wrong: true\n  Bucket:\n    Type: AWS::S3::Bucket\n    Properties:\n      MadeUpProperty: true\n  Unknown:\n    Type: AWS::Fixture::Absent\n')
    with lint_session(cwd) as session:
        result = validate_template(session, template, 'ap-northeast-1')
        assert result['status'] == 'processing_error' and not result['completed'] and result['unverified'], result
        assert any(error.get('resource_type') == 'AWS::S3::Bucket' and error['code'] == 'schema_unavailable'
                   for error in result['processing_errors']), result
        assert all(type(error['resource_type']) is str for error in result['processing_errors'] if 'resource_type' in error), result
        assert {'E3002', 'E3006'} <= {m['Rule']['Id'] for m in result['matches']}, result
        assert result['fatal'] and validate_template(session, template, 'ap-northeast-1')['status'] == 'not_run'
    assert not any(e['code'] == 'child_execution' for e in result['processing_errors']), result
    assert result['decode_complete'] and result['decode']
    observed = {item['locator']: item for item in result['dependencies']['files']}
    assert str(schema) in observed and observed[str(schema)]['sha256']
    assert str(template) in observed
    verify_dependencies(result['dependencies'])
    # A zero-match schema failure still cannot become completed lint.
    template.write_text('Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n    Properties:\n      MadeUpProperty: true\n')
    with lint_session(cwd) as session:
        empty = validate_template(session, template, 'ap-northeast-1')
    assert not empty['matches'] and empty['processing_errors'] and empty['unverified'] and not empty['completed'], empty
    # Unknown and intentionally removed resource types keep normal diagnostics.
    for body, settings in [('Resources:\n  Unknown:\n    Type: AWS::Fixture::Absent\n', {}),
                           (template.read_text(), {'override_spec': str(cwd / 'override.json')})]:
        (cwd / 'override.json').write_text(json.dumps({'IncludeResourceTypes': ['AWS::SQS::Queue']}))
        (cwd / '.cfnlintrc').write_text(json.dumps(settings))
        template.write_text(body)
        with lint_session(cwd) as session:
            normal = validate_template(session, template, 'ap-northeast-1')
        assert normal['completed'] and not normal['processing_errors'] and not normal['unverified'], normal
        assert any(m['Rule']['Id'] == 'E3006' for m in normal['matches']), normal
    assert schema.read_text() == broken


def _callback_check_scan_dependency_view_failure_read(bad, read_bytes, /, path):
    if path == bad:
        raise PermissionError('private permission body')
    return read_bytes(path)


@pytest.mark.parametrize('failure', ['utf8', 'missing', 'permission'])
def check_scan_dependency_view_failure(tmp_path, monkeypatch, failure):
    _, cwd = isolated(tmp_path, monkeypatch)
    root = cwd / 'fixture'
    fixture(root)
    docs = root / 'docs/designs/dev/123456789012'
    source, bad = docs / 'sqs.md', docs / 's3.md'
    source.write_text(source.read_text() + '\n[dependent bucket](s3.md#s3-bucket-app-dev-data1)\n')
    if failure == 'utf8':
        bad.write_bytes(b'\xff private dependency body')
    elif failure == 'missing':
        bad.unlink()
    else:
        read_bytes = Path.read_bytes
        read = _bind_framework_callback(_callback_check_scan_dependency_view_failure_read, bad, read_bytes)
        monkeypatch.setattr(Path, 'read_bytes', read)
    template = root / 'infra/cloudformation/templates/shared.yaml'
    data = json.loads(template.read_text())
    data['Resources']['Log']['Properties']['RetentionInDays'] = 14
    template.write_text(json.dumps(data))
    with patch.object(PassCache, 'save') as cache_save, \
         patch('issues.cfn_lint.validate_template', wraps=real_lint) as lint:
        artifact = scan(root, 'dev', '123456789012', ['sqs', 'cloudwatch-logs'], fresh=True, jobs=1)
    errors = [e for e in artifact['processing_errors'] if e['code'] == 'mechanical.view_read']
    assert len(errors) == 1 and errors[0]['path'].endswith('/s3.md'), artifact
    assert errors[0]['phase'] == 'design-links-reference' and errors[0]['consumers'] == [source.relative_to(root).as_posix()]
    assert any(e.get('service') == 'sqs' and e['code'] == 'design.links_unavailable' for e in artifact['unverified'])
    assert any(r['category'] == 'difference' and r['service'] == 'cloudwatch-logs' for r in artifact['iac'])
    assert lint.call_count == 1 and artifact['cfn_lint']['jobs'][0]['completed'], (lint.call_count, artifact['cfn_lint'], artifact['processing_errors'])
    assert not cache_save.called and artifact['validation_status'] == 'ERROR'
    assert artifact['checks'] > 0 and 'private dependency body' not in json.dumps(artifact)
    assert artifact['services'] == ['cloudwatch-logs', 'sqs']
    with task(root, ['sqs', 'cloudwatch-logs']):
        if failure == 'permission':
            assert artifact['fingerprint']['unreadable']
            with pytest.raises(ValueError, match='freshness unprovable'):
                save_scan(root, artifact, review_for(artifact))
            return
        save_scan(root, artifact, review_for(artifact))
        bad.write_bytes(b'changed dependency bytes')
        with pytest.raises(ValueError, match='stale scan'):
            save_scan(root, artifact, review_for(artifact))
    if failure == 'utf8':
        bad.write_bytes(b'\xff private dependency body')
        normal = Validator(root, {('dev', '123456789012', 'sqs')}, workers=1)
        normal.design_sources = {source: {}}
        with pytest.raises(UnicodeDecodeError):
            normal.check_design_links({}, [source])


if __name__=='__main__':
    raise SystemExit(run(__file__))
