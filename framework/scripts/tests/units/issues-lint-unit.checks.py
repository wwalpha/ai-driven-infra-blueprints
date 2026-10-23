#!/usr/bin/env python3
"""Pure lint planning/classification, artifact indexing and deferred-cache boundaries."""

import hashlib
import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from iac_values import safe_value
from issues.aggregate import aggregate
from issues.aggregate import aggregate as real_aggregate
from issues.artifact import detail_payload, scan_exit_code, summary, validate_artifact
from issues.cfn_lint import classify, owner, plan, run_lint
from issues.integrity import live_common_key
from issues.publication import save_scan
from issues.records import identifier
from issues.reports import notice_report, without_notices
from issues.runner import scan
from support.pytest_cli import run
from utils.cfn_lint import (
    LintSession,
    Worker,
    decode_response,
    directory_state,
    file_state,
    runtime,
    verify_dependencies,
)
from utils.cfn_lint_worker import child
from utils.input_cache import input_recorder, recording_inputs
from validation.runner import Validator

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.mark.parametrize('rule,level,defect,expected', [
    ('E3002','Error',False,'ordinary'), ('W3001','Warning',False,'warnings'),
    ('I3011','Informational',False,'information'), ('E0000','Error',True,'ordinary'),
    ('E0000','Error',False,'processing_errors'), ('E0001','Error',True,'processing_errors'),
    ('E0002','Error',False,'processing_errors'), ('E0003','Error',False,'processing_errors'),
    ('E3002','unknown',False,'processing_errors')])
def check_classification(rule,level,defect,expected):
    assert classify({'Rule':{'Id':rule},'Level':level},{'input_defect':defect})==expected
    assert classify({'Rule':{'Id':'E3006'},'Level':'Error'},{'processing_errors':[{'code':'schema_unavailable'}]})=='ordinary'


def check_explicit_plan():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        template=root/'infra/cloudformation/templates/shared.yaml'
        template.parent.mkdir(parents=True)
        template.write_text('invalid: [')
        values={f'desired.stack.{i}.{field}':value for i,name in enumerate(['StackA','StackB'])
                for field,value in {'name':name,'template':'shared.yaml','parameters':'broken'}.items()}
        comparison=SimpleNamespace(root=root,target={'iacEngine':'cloudformation','awsRegion':'ap-northeast-1'},
            services=['s3','sqs'],models={'s3':True,'sqs':True},model=lambda _:SimpleNamespace(values=values),
            catalog=SimpleNamespace(api_schemas={'QuickSight.Group'}),track=Mock(),
            resources={'s3':{'1':{'cfn-logicalId':'StackA-Bucket'},'2':{'resourceMode':'IMPORT'},'3':{}},
                       'sqs':{'1':{'cfn-logicalId':'StackB-Queue'},'2':{'resourceType':'QuickSight.Group'}}})
        jobs,coverage=plan(comparison)
        assert len(jobs)==1 and len(jobs[0]['origins'])==2
        assert {o['stack'] for o in jobs[0]['origins']}=={'StackA','StackB'}
        assert len([c for c in coverage if c['status']=='not_applicable'])==2
        assert any(c['reason'].startswith('explicit') for c in coverage)
        assert owner(comparison,jobs[0],{'Location':{'Path':['Resources','Bucket','Properties']}})==('s3',False)
        assert owner(comparison,jobs[0],{'Location':{'Path':['Parameters','X']}})==(None,False)
        comparison.services.append('cloudformation-stacks')
        comparison.models['cloudformation-stacks']=True
        comparison.resources['cloudformation-stacks']={}
        jobs,_=plan(comparison)
        assert owner(comparison,jobs[0],{})==('cloudformation-stacks',False)
        template.unlink()
        assert plan(comparison)[0][0]['status']=='input_missing'
        comparison.target['iacEngine']='terraform'
        assert plan(comparison)==([], [{'status':'not_applicable','reason':'Terraform scope'}])


def fixture_v2(count=150):
    records=[dict(category='difference',service='s3',resource=str(i),property='S3.Bucket.X',reason='value mismatch',
                  desired='a',actual='b',stack='S',iac={'path':'template.yaml'}) for i in range(count)]
    artifact=dict(version=2,root='/fixture',scan_id='a'*32,naming_context_id=identifier({}),naming_context={},
        environment='dev',target='team',services=['s3'],ordinary=[],naming={'names':[]},judgments=[],human_confirmations=[],
        **aggregate(records,'dev','team',['s3']))
    return artifact


def check_v2_index_and_status():
    artifact=fixture_v2()
    validate_artifact(artifact)
    with patch('issues.aggregate.iac_dataset', side_effect=AssertionError('second aggregation')):
        assert summary(artifact)['iac_differences']==150
        selected=artifact['iac_issues'][100]
        page=detail_payload(artifact,'iac',issue_id=selected['id'])
        assert page['total']==1 and page['items'][0]['record_index']==selected['members'][0]
        assert len(detail_payload(artifact,'iac',140,50)['items'])==10
        assert detail_payload(artifact,'naming_context')['items']==[{}]
        assert detail_payload(artifact,'naming')['context']=={'naming_context_id':artifact['naming_context_id']}
        assert scan_exit_code(artifact)==0
        artifact['unverified']=[{'code':'not_run'}]
        assert summary(artifact)['validation_status']=='INCOMPLETE' and scan_exit_code(artifact)==0
        artifact['warnings']=[dict(code='warning',message='x'*1000) for _ in range(1000)]
        assert summary(artifact)['warnings']['total']==1000 and len(summary(artifact)['warnings']['preview'])==5
        artifact['ordinary']=[dict(message='Error',service='s3')]
        assert scan_exit_code(artifact)==1
        artifact['processing_errors']=[dict(code='timeout')]
        assert scan_exit_code(artifact)==2
    unsupported=dict(artifact,version=99)
    with pytest.raises(ValueError,match='unsupported scan artifact version'):
        detail_payload(unsupported,'iac')
    with pytest.raises(ValueError,match='unsupported scan artifact version'):
        validate_artifact(unsupported)
    with pytest.raises(ValueError,match='invalid scan artifact/root'):
        save_scan(Path('/fixture'),unsupported,{})
    with pytest.raises(ValueError,match='scan_id'):
        save_scan(Path('/fixture'),artifact,dict(scan_id='other',reviewed_naming_context_id=artifact['naming_context_id'],reviewed_names=[],reviewed_judgments=[],diagnostic_assignments={},issues=[],resolved=[]))


def check_dependency_guards():
    recorder=SimpleNamespace(tracks=lambda _:True)
    cache=SimpleNamespace(common_key=lambda:'memo' if input_recorder(Path('/fixture')) else 'live')
    with recording_inputs(recorder):
        assert cache.common_key()=='memo'
        assert live_common_key(cache)=='live'
        assert input_recorder(Path('/fixture')) is recorder
    legacy='<!-- reference-warnings:start -->\n## 参照警告\n- old warning\n<!-- reference-warnings:end -->\n'
    text='# 問題一覧\nhuman confirmation\n'+legacy+legacy
    current=notice_report(text,'dev','team',['s3'],{'warnings':[dict(code='W',message='new warning')]})
    assert current.count('reference-warnings:start')==1 and 'old warning' in current
    pending=notice_report(current,'dev','team',['s3'],{'unverified':[dict(code='not_run')]},preserve_prior=True)
    assert 'new warning' in pending and '解消未確認' in pending
    again=notice_report(pending,'dev','team',['s3'],{'unverified':[dict(code='not_run')]},preserve_prior=True)
    assert again.count('new warning')==1
    assert 'warning' not in without_notices(again) and 'human confirmation' in without_notices(again)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        config=root/'.cfnlintrc'
        rules=root/'rules'
        rules.mkdir()
        dependencies=dict(runtime=runtime(Path.cwd()),files=[file_state(config)],directories=[directory_state(rules)])
        verify_dependencies(dependencies)
        config.write_text('ignore_checks: [W]')
        with pytest.raises(ValueError,match='lint input changed'):
            verify_dependencies(dependencies)
        config.unlink()
        (rules/'new.py').write_text('# custom rule')
        with pytest.raises(ValueError,match='file set'):
            verify_dependencies(dependencies)
        dependencies['runtime']['home']='different'
        with pytest.raises(ValueError,match='HOME'):
            verify_dependencies(dependencies)


def check_deferred_cache_finalization():
    validator=Validator.__new__(Validator)
    validator.cache=SimpleNamespace(common='initial',save=Mock())
    validator.check=Mock()
    validator.service_cache_pending=[('key',20)]
    assert not validator.cache.save.called
    validator.finalize_service_cache('initial')
    validator.cache.save.assert_called_once_with('key',20)
    assert not validator.service_cache_pending
    validator.cache.save.reset_mock()
    validator.service_cache_pending=[('key',20)]
    validator.finalize_service_cache('changed')
    assert not validator.cache.save.called and not validator.service_cache_pending
    validator.check.assert_called_with(False,'framework/project inputs changed during service validation')


def check_worker_protocol_and_fatal():
    with patch('utils.cfn_lint.subprocess.Popen',side_effect=OSError('launch unavailable')):
        assert Worker().request({})['processing_errors'][0]['code']=='launch_failure'
    packet={'progress':{'match':{'Rule':{'Id':'E3002'},'Level':'Error','Message':'<masked>'},'state':{'decode_complete':True}}}
    partial=decode_response(json.dumps(packet)+'\n',timeout=True)
    assert partial['matches'][0]['Rule']['Id']=='E3002' and not partial['completed']
    assert partial['processing_errors'][0]['code']=='timeout'
    assert decode_response(json.dumps(packet)+'\n',abnormal=True)['matches']==partial['matches']
    session=LintSession(Path.cwd())
    with patch.object(session.worker,'request',return_value={'matches':{},'completed':True}):
        assert session.validate(Path('explicit.yaml'),'ap-northeast-1')['processing_errors'][0]['code']=='invalid_protocol'
    with patch.object(session.worker,'request',return_value=dict(matches=[],completed=False,fatal=True,status='processing_error')) as request:
        assert session.validate(Path('explicit.yaml'),'ap-northeast-1')['fatal']
        assert session.validate(Path('other.yaml'),'ap-northeast-1')['status']=='not_run'
        assert request.call_count==1


def _callback_check_child_builtin_packets_preserve_progress_execution(crash, dependencies, match, state, /, request, emit):
    emit(dict(progress=dict(state=state, match=match, dependencies=dependencies)))
    if crash:
        raise RuntimeError('private exception body')
    return dict(state, matches=[match], dependencies=dependencies)


def _recursive_check_child_builtin_packets_preserve_progress_builtins(value):
    assert type(value) in (dict, list, str, int, float, bool, type(None))
    if isinstance(value, dict):
        for key, item in value.items():
            _recursive_check_child_builtin_packets_preserve_progress_builtins(key)
            _recursive_check_child_builtin_packets_preserve_progress_builtins(item)
    elif isinstance(value, list):
        for item in value:
            _recursive_check_child_builtin_packets_preserve_progress_builtins(item)


@pytest.mark.parametrize('crash', [False, True])
def check_child_builtin_packets_preserve_progress(crash):
    class ParserString(str):
        pass
    state = dict(processing_errors=[dict(code=ParserString('schema_unavailable'),
                 resource_type=ParserString('AWS::S3::Bucket'))],
                 unverified=[dict(code='schema')], fatal=True, decode=[dict(success=True)],
                 status='processing_error', completed=False)
    match = dict(Rule=dict(Id=ParserString('E3002')), Location=dict(Path=[ParserString('Resources')]))
    dependencies = dict(files=[dict(locator=ParserString('/fixture/schema'), sha256='observed')])
    execution = _bind_framework_callback(_callback_check_child_builtin_packets_preserve_progress_execution, crash, dependencies, match, state)
    sender = Mock()
    with patch('utils.cfn_lint_worker.execute', execution):
        child({}, sender)
    packets = [call.args[0] for call in sender.send.call_args_list]
    builtins = _recursive_check_child_builtin_packets_preserve_progress_builtins
    for packet in packets:
        builtins(packet)
    result = packets[-1]
    assert result['matches'] == [match] and result['dependencies'] == dependencies
    assert result['decode'] == state['decode'] and result['fatal'] and not result['completed']
    assert result['status'] == 'processing_error' and result['unverified'][0] == state['unverified'][0]
    assert result['processing_errors'][0] == state['processing_errors'][0]
    assert 'private exception body' not in json.dumps(result)
    sender.close.assert_called_once()


def _callback_check_scan_cache_guard_order_track(comp, /, path):
    comp.inputs.add(path)
    comp.read_hashes[path]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _callback_check_scan_cache_guard_order_mechanical(validator, /, *args, **kwargs):
    kwargs['validator_out'].append(validator)
    kwargs['fingerprint_out']['dev/team/s3']='service-key'
    return [],20,''


def _callback_check_scan_cache_guard_order_aggregation(events, /, *args, **kwargs):
    events.append('aggregation')
    return real_aggregate(*args,**kwargs)


def _callback_check_scan_cache_guard_order_lint(_state_check_scan_cache_guard_order_256, /, _):
    if _state_check_scan_cache_guard_order_256.failure=='stale':
        (_state_check_scan_cache_guard_order_256.root/'docs/designs/dev/team').mkdir(parents=True)
        (_state_check_scan_cache_guard_order_256.root/'docs/designs/dev/team/s3.md').write_text('changed')
    if _state_check_scan_cache_guard_order_256.failure=='exception':
        raise RuntimeError('injected')
    if _state_check_scan_cache_guard_order_256.failure=='interrupt':
        raise KeyboardInterrupt()
    return dict(jobs=[],coverage=[],status='not_applicable',lint_dependencies={},**{name:[] for name in ('ordinary','judgments','warnings','information','unverified','processing_errors')})


def check_scan_cache_guard_order():

    _state_check_scan_cache_guard_order_256 = _CallbackState()
    for _state_check_scan_cache_guard_order_256.failure in (None,'stale','exception','interrupt'):
        with tempfile.TemporaryDirectory() as temporary:
            _state_check_scan_cache_guard_order_256.root=Path(temporary).resolve()
            (_state_check_scan_cache_guard_order_256.root/'project.json').write_text('{}')
            events=[]
            cache=SimpleNamespace(common=None,save=Mock(side_effect=lambda *_, events=events:events.append('cache')),
                                  common_key=lambda *, events=events, **kwargs: events.append('start' if kwargs else 'live') or 'common',
                                  service_key=lambda _: 'service-key')
            validator=SimpleNamespace(findings=SimpleNamespace(unverified=[],result=lambda *_:SimpleNamespace(metadata={})),
                                      cache=cache,checks=20,service_cache_pending=[('new-key',20)],check=lambda condition,_:condition)
            validator.finalize_service_cache=lambda key, *, validator=validator:Validator.finalize_service_cache(validator,key)
            comp=SimpleNamespace(inputs={_state_check_scan_cache_guard_order_256.root/'project.json'},read_hashes={},view_errors={},services=['s3'],root=_state_check_scan_cache_guard_order_256.root,
                                 environment='dev',directory='team',warnings=[],catalog=None,models={},results=[],metrics={},display_differences={},
                                 redacted=lambda value,prop='':safe_value(value,prop),run=lambda:[])
            track = _bind_framework_callback(_callback_check_scan_cache_guard_order_track, comp)
            comp.track=track
            mechanical = _bind_framework_callback(_callback_check_scan_cache_guard_order_mechanical, validator)
            lint = _bind_framework_callback(_callback_check_scan_cache_guard_order_lint, _state_check_scan_cache_guard_order_256)
            aggregation = _bind_framework_callback(_callback_check_scan_cache_guard_order_aggregation, events)
            with patch('issues.runner.Comparison',return_value=comp),patch('issues.runner.PassCache',return_value=cache), \
                 patch('issues.runner.mechanical',side_effect=mechanical),patch('issues.runner.naming_materials',return_value=({'names':[]},[])), \
                 patch('issues.runner.existing_materials',return_value=([],[])),patch('issues.cfn_lint.run_lint',side_effect=lint), \
                 patch('issues.runner.aggregate',side_effect=aggregation):
                if _state_check_scan_cache_guard_order_256.failure:
                    expected=ValueError if _state_check_scan_cache_guard_order_256.failure=='stale' else RuntimeError if _state_check_scan_cache_guard_order_256.failure=='exception' else KeyboardInterrupt
                    with pytest.raises(expected):
                        scan(_state_check_scan_cache_guard_order_256.root,'dev','team',['s3'])
                    assert not cache.save.called
                else:
                    result=scan(_state_check_scan_cache_guard_order_256.root,'dev','team',['s3'])
                    assert result['version']==2 and result['checks']==20
                    assert events.index('aggregation')<events.index('live')<events.index('cache')



@pytest.mark.parametrize('kinds,needs_stack', [
    (['IMPORT'], False), (['API'], False), (['IMPORT', 'API', 'CREATE'], True), (['CREATE'], True)])
def check_plan_without_stack(kinds, needs_stack):
    resources = {str(i): ({'resourceMode': 'IMPORT'} if kind == 'IMPORT' else
                         {'resourceType': 'QuickSight.Group'} if kind == 'API' else
                         {'cfn-logicalId': 'Stack-Bucket'}) for i, kind in enumerate(kinds)}
    loader = Mock(side_effect=FileNotFoundError())
    comparison = SimpleNamespace(target={'iacEngine': 'cloudformation'}, services=['s3'],
        models={'s3': True}, resources={'s3': resources}, model=loader,
        catalog=SimpleNamespace(api_schemas={'QuickSight.Group'}))
    jobs, coverage = plan(comparison)
    assert not jobs and loader.call_count == int(needs_stack)
    assert sum(item['status'] == 'not_applicable' for item in coverage) == sum(k != 'CREATE' for k in kinds)
    assert sum(item['status'] == 'unverified' for item in coverage) == sum(k == 'CREATE' for k in kinds)
    assert all(item['reason'] for item in coverage)


def check_processing_coverage_keeps_matches():
    failure = dict(code='schema_unavailable', resource_type='AWS::S3::Bucket')
    matches = [{'Rule': {'Id': 'E3002'}, 'Level': 'Error', 'Message': 'property error'},
               {'Rule': {'Id': 'E3006'}, 'Level': 'Error', 'Message': 'unknown resource'}]
    result = dict(status='processing_error', completed=True, decode_complete=True, matches=matches,
                  processing_errors=[failure], unverified=[], dependencies={})
    job = dict(id='job', template='/fixture/template.yaml', region='ap-northeast-1', status='planned')
    comparison = SimpleNamespace(root=Path('/fixture'), sensitive_values=set(), redacted=lambda value: value)
    with patch('issues.cfn_lint.plan', return_value=([job], [])), \
         patch('issues.cfn_lint.lint_session'), patch('issues.cfn_lint.validate_template', return_value=result), \
         patch('issues.cfn_lint.owner', return_value=('s3', False)):
        lint = run_lint(comparison)
    assert lint['status'] == 'incomplete' and lint['coverage'][0]['status'] == 'unverified'
    assert len(lint['ordinary']) == 2 and lint['processing_errors'][0]['code'] == 'schema_unavailable'
    assert len(lint['unverified']) == 1
    assert scan_exit_code(dict(ordinary=lint['ordinary'], processing_errors=lint['processing_errors'])) == 2

if __name__=='__main__':
    raise SystemExit(run(__file__))
