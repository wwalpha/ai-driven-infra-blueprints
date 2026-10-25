#!/usr/bin/env python3
"""Lint planning/classification, artifact indexing and report-only input behavior."""

import io
import signal
import subprocess
import sys
from contextlib import ExitStack
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
import utils.cfn_lint as adapter
import utils.cfn_lint_worker as lint_worker
from issues.aggregate import aggregate
from issues.aggregate import aggregate as real_aggregate
from issues.artifact import detail_payload, scan_exit_code, summary, validate_artifact
from issues.cfn_lint import classify, owner, plan, run_lint
from issues.publication import save_scan
from issues.records import identifier
from issues.reports import notice_report, without_notices
from issues.runner import scan
from support.pytest_cli import run
from utils.cfn_lint import (
    LintSession,
    Worker,
    decode_response,
)
from utils.cfn_lint_worker import child
from utils.iac_values import safe_value
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


def check_pending_notices_replace_warnings():
    text='# 問題一覧\nhuman confirmation\n'
    current=notice_report(text,'dev','team',['s3'],{'warnings':[dict(code='W',message='new warning')]})
    pending=notice_report(current,'dev','team',['s3'],{'unverified':[dict(code='not_run')]})
    assert 'new warning' not in pending and '解消未確認' not in pending
    again=notice_report(pending,'dev','team',['s3'],{'unverified':[dict(code='not_run')]})
    assert again == pending and again.count('not_run') == 1
    assert 'warning' not in without_notices(again) and 'human confirmation' in without_notices(again)


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
    with patch('utils.cfn_lint.sys.platform', 'linux'), patch('utils.cfn_lint.subprocess.Popen',side_effect=OSError('launch unavailable')):
        assert Worker().request({})['processing_errors'][0]['code']=='launch_failure'
    packet={'progress':{'match':{'Rule':{'Id':'E3002'},'Level':'Error','Message':'<masked>'},'state':{'decode_complete':True}}}
    partial=decode_response(json.dumps(packet)+'\n',timeout=True)
    assert partial['matches'][0]['Rule']['Id']=='E3002' and not partial['completed']
    assert partial['processing_errors'][0]['code']=='timeout'
    assert decode_response(json.dumps(packet)+'\n',abnormal=True)['matches']==partial['matches']
    session=LintSession(Path.cwd())
    with patch.object(session.worker,'request',return_value={'matches':{},'completed':True}):
        assert session.validate(Path('explicit.yaml'),'ap-northeast-1')['processing_errors'][0]['code']=='invalid_protocol'
    session = LintSession(Path.cwd())
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


def _callback_check_scan_cache_guard_order_mechanical(validator, /, *args, **kwargs):
    kwargs['validator_out'].append(validator)
    return [],20,''


def _callback_check_scan_cache_guard_order_aggregation(events, /, *args, **kwargs):
    events.append('aggregation')
    return real_aggregate(*args,**kwargs)


def _callback_check_scan_cache_guard_order_lint(_state_check_scan_cache_guard_order_256, /, _):
    if _state_check_scan_cache_guard_order_256.failure=='changed':
        (_state_check_scan_cache_guard_order_256.root/'docs/designs/dev/team').mkdir(parents=True, exist_ok=True)
        (_state_check_scan_cache_guard_order_256.root/'docs/designs/dev/team/codepipeline.md').write_text('changed')
    if _state_check_scan_cache_guard_order_256.failure=='exception':
        raise RuntimeError('injected')
    if _state_check_scan_cache_guard_order_256.failure=='interrupt':
        raise KeyboardInterrupt()
    return dict(jobs=[],coverage=[],status='not_applicable',**{name:[] for name in ('ordinary','judgments','warnings','information','unverified','processing_errors')})


def check_scan_changes_without_cache():

    _state_check_scan_cache_guard_order_256 = _CallbackState()
    for _state_check_scan_cache_guard_order_256.failure in (None,'changed','exception','interrupt'):
        with tempfile.TemporaryDirectory() as temporary:
            _state_check_scan_cache_guard_order_256.root=Path(temporary).resolve()
            (_state_check_scan_cache_guard_order_256.root/'project.json').write_text('{}')
            view = _state_check_scan_cache_guard_order_256.root/'docs/designs/dev/team/codepipeline.md'
            view.parent.mkdir(parents=True)
            view.write_text('original')
            events=[]
            cache=SimpleNamespace(common=None,save=Mock(side_effect=lambda *_, events=events:events.append('cache')),
                                  common_key=lambda *, events=events, **kwargs: events.append('start' if kwargs else 'live') or 'common',
                                  service_key=lambda _: 'service-key')
            validator=SimpleNamespace(findings=SimpleNamespace(unverified=[],result=lambda *_:SimpleNamespace(metadata={})),
                                      cache=cache,checks=20,service_cache_pending=[('new-key',20)],check=lambda condition,_:condition)
            validator.finalize_service_cache=lambda key, *, validator=validator:Validator.finalize_service_cache(validator,key)
            comp=SimpleNamespace(inputs={_state_check_scan_cache_guard_order_256.root/'project.json'},read_hashes={},view_errors={},services=['codepipeline'],root=_state_check_scan_cache_guard_order_256.root,
                                 environment='dev',directory='team',warnings=[],catalog=None,models={},results=[],metrics={},display_differences={},
                                 redacted=lambda value,prop='':safe_value(value,prop),run=lambda:[])
            mechanical = _bind_framework_callback(_callback_check_scan_cache_guard_order_mechanical, validator)
            lint = _bind_framework_callback(_callback_check_scan_cache_guard_order_lint, _state_check_scan_cache_guard_order_256)
            aggregation = _bind_framework_callback(_callback_check_scan_cache_guard_order_aggregation, events)
            with patch('issues.runner.Comparison',return_value=comp), \
                 patch('issues.runner.mechanical',side_effect=mechanical),patch('issues.runner.naming_materials',return_value=({'names':[]},[])), \
                 patch('issues.runner.existing_materials',return_value=([],[])),patch('issues.cfn_lint.run_lint',side_effect=lint), \
                 patch('issues.runner.aggregate',side_effect=aggregation):
                if _state_check_scan_cache_guard_order_256.failure in ('exception','interrupt'):
                    expected=RuntimeError if _state_check_scan_cache_guard_order_256.failure=='exception' else KeyboardInterrupt
                    with pytest.raises(expected):
                        scan(_state_check_scan_cache_guard_order_256.root,'dev','team',['codepipeline'])
                    assert not cache.save.called
                else:
                    result=scan(_state_check_scan_cache_guard_order_256.root,'dev','team',['codepipeline'])
                    assert result['version']==2 and result['checks']==20
                    assert events == ['aggregation'] and not cache.save.called
                    assert not {'fingerprint', 'service_keys', 'lint_dependencies'} & result.keys()



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


@pytest.mark.parametrize('with_matches', [False, True])
def check_processing_coverage_keeps_matches(with_matches):
    failure = dict(code='schema_unavailable', resource_type='AWS::S3::Bucket')
    matches = [{'Rule': {'Id': 'E3002'}, 'Level': 'Error', 'Message': 'property error'},
               {'Rule': {'Id': 'E3006'}, 'Level': 'Error', 'Message': 'unknown resource'}]
    if not with_matches:
        matches = []
    result = dict(status='processing_error', completed=True, decode_complete=True, matches=matches,
                  processing_errors=[failure], unverified=[], dependencies={})
    job = dict(id='job', template='/fixture/template.yaml', region='ap-northeast-1', status='planned')
    comparison = SimpleNamespace(root=Path('/fixture'), sensitive_values=set(), redacted=lambda value: value)
    with patch('issues.cfn_lint.plan', return_value=([job], [])), \
         patch('issues.cfn_lint.lint_session'), patch('issues.cfn_lint.validate_template', return_value=result), \
         patch('issues.cfn_lint.owner', return_value=('s3', False)):
        lint = run_lint(comparison)
    assert lint['status'] == 'incomplete' and lint['coverage'][0]['status'] == 'unverified'
    assert len(lint['ordinary']) == (2 if with_matches else 0) and lint['processing_errors'][0]['code'] == 'schema_unavailable'
    assert len(lint['unverified']) == 1
    assert scan_exit_code(dict(ordinary=lint['ordinary'], processing_errors=lint['processing_errors'])) == 2


@pytest.mark.parametrize('packets,clock,expected', [
    ([b'{"progress":{"state":{"decode_complete":true}}}\n', b'{"status":'], [0, 0.01, 0.02, 0.1], 'timeout'),
    (None, [0, 0.01], 'timeout'),
    ([b'[]\n'], [0, 0.01], 'invalid_protocol'),
    ([b'garbage\n'], [0, 0.01], 'invalid_protocol'),
    ([b''], [0, 0.01], 'child_abnormal_exit'),
    ([b'{"completed":true}\n'], [0, 0.01], None),
])
def check_worker_deadline_and_response(packets, clock, expected):
    process = Mock(stdin=io.BytesIO(), stdout=Mock(), pid=12345)
    process.wait.return_value = 0
    worker = Worker()
    with patch.object(adapter.sys, 'platform', 'linux'), \
         patch.object(adapter.subprocess, 'Popen', return_value=process) as launch, \
         patch.object(adapter.time, 'monotonic', side_effect=clock), \
         patch.object(adapter.select, 'select', return_value=([process.stdout] if packets is not None else [], [], [])) as ready, \
         patch.object(adapter.os, 'read', side_effect=packets or []), patch.object(adapter.os, 'killpg', create=True, side_effect=[None, ProcessLookupError()] if expected else [ProcessLookupError()]) as kill:
        result = worker.request({}, timeout=0.1)
        assert launch.call_args.kwargs['start_new_session'] is True
        assert all(0 < call.args[3] <= 0.1 for call in ready.call_args_list)
        if expected:
            assert result['processing_errors'][-1]['code'] == expected and result['fatal']
            assert worker.process is None and worker.request({})['status'] == 'not_run'
            assert kill.call_args_list[0].args == (process.pid, signal.SIGTERM)
            assert process.stdin.closed
            process.stdout.close.assert_called_once()
            if packets and len(packets) > 1:
                assert result['decode_complete']
        else:
            assert result == {'completed': True} and worker.process is process
            worker.close()
            assert all(call.args[1] == 0 for call in kill.call_args_list)


@pytest.mark.parametrize('force,stubborn,orphan', [(False, False, False), (False, True, False), (True, False, False), (True, True, False), (True, False, True)])
def check_worker_shutdown_escalation(force, stubborn, orphan):
    process = Mock(stdin=io.BytesIO(), stdout=Mock(), pid=12345)
    process.wait.side_effect = ([subprocess.TimeoutExpired('worker', 0.5)] * (1 if force else 2) + [0]) if stubborn else [0]
    worker = Worker()
    worker.process = process
    signals = [None, None, None, None, None] if orphan else [None] * (2 if stubborn else 1 if force else 0) + [ProcessLookupError()]
    with patch.object(adapter.os, 'killpg', create=True, side_effect=signals) as kill, patch.object(adapter.signal, 'SIGKILL', 9, create=True):
        worker.close(force=force)
        worker.close()
    assert worker.process is None and process.stdin.closed
    process.stdout.close.assert_called_once()
    assert [call.args[1] for call in kill.call_args_list if call.args[1]] == ([signal.SIGTERM, signal.SIGTERM, 9] if orphan else [signal.SIGTERM, 9] if stubborn else [signal.SIGTERM] if force else [])


@pytest.mark.parametrize('running,alive', [(False, False), (True, False), (True, True)])
def check_child_shutdown_escalation(running, alive):
    process = Mock(pid=12345)
    process.is_alive.side_effect = [running, alive]
    lint_worker.reap_child(process)
    assert process.terminate.called is running
    assert process.kill.called is alive
    assert process.join.call_count == (2 if running else 1)
    process.close.assert_called_once()


@pytest.mark.parametrize('outcome', ['timeout', 'abnormal', 'invalid', 'completed'])
def check_windows_once_contract(outcome):
    progress = json.dumps({'progress': {'match': {'Rule': {'Id': 'E3002'}}}}) + '\n'
    returned = SimpleNamespace(returncode=7 if outcome == 'abnormal' else 0,
        stdout='invalid' if outcome == 'invalid' else progress + json.dumps({'completed': True}))
    with patch.object(adapter.sys, 'platform', 'win32'), \
         patch.object(adapter.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 0.1, output=progress.encode()) if outcome == 'timeout' else None,
                      return_value=returned) as invoke:
        worker = Worker()
        result = worker.request({}, timeout=0.1)
        assert invoke.call_args.args[0][-1] == '--once'
        assert 0 <= invoke.call_args.kwargs['timeout'] <= 0.1
        if outcome != 'completed':
            assert result['fatal']
            if outcome != 'invalid':
                assert result['matches'][0]['Rule']['Id'] == 'E3002'
            assert worker.request({})['status'] == 'not_run' and invoke.call_count == 1
        else:
            assert result['completed']


@pytest.mark.parametrize('mapping,kind,cause,removed,registry,expected', [
    (False, 'AWS::S3::Bucket', None, False, False, True),
    (True, 'AWS::S3::Bucket', 'missing', False, False, True),
    (True, 'AWS::S3::Bucket', 'json', False, False, True),
    (True, 'AWS::S3::Bucket', 'schema', False, False, True),
    (True, 'AWS::Fixture::Absent', None, False, False, False),
    (True, 'AWS::S3::Bucket', None, True, False, False),
    (True, 'AWS::S3::Bucket', None, False, True, False),
])
def check_schema_failure_classification(tmp_path, mapping, kind, cause, removed, registry, expected):
    response = dict(processing_errors=[], fatal=False)
    offline = _bind_framework_callback(lint_worker._callback_structured_offline, response)
    manager = Mock(_providers_dir=tmp_path, _resources_dir=tmp_path, _registry_schemas={kind} if registry else {},
        _removed_types={kind} if removed else {})
    manager._normalize_resource_type.side_effect = lambda value: value
    manager._load_provider_module.return_value = {kind: 'schema'} if cause else {}
    if mapping:
        (tmp_path / 'us-east-1.json').write_text('{}')
    if cause not in (None, 'missing'):
        (tmp_path / 'schema.json').write_text('{}')
    original = Mock(return_value={})
    if cause in ('json', 'schema'):
        error = lint_worker.ResourceNotFoundError(kind, 'ap-northeast-1')
        error.__cause__ = json.JSONDecodeError('private schema body', '', 0) if cause == 'json' else ValueError('private schema body')
        original.side_effect = error
    track, progress = Mock(), Mock()
    if not mapping:
        with pytest.raises(lint_worker.OfflineError):
            lint_worker._callback_structured_provider(offline, Mock(), track, manager, 'ap-northeast-1')
    else:
        try:
            lint_worker._callback_structured_schema(lint_worker.ResourceNotFoundError, offline, original,
                progress, response, track, manager, 'ap-northeast-1', kind)
        except (lint_worker.OfflineError, lint_worker.ResourceNotFoundError):
            pass
    assert bool(response['processing_errors']) is expected and response['fatal'] is expected
    assert all(e['code'] == 'schema_unavailable' for e in response['processing_errors'])
    assert 'private schema body' not in json.dumps(response)
    if cause in ('json', 'schema'):
        assert response['processing_errors'][0]['exception'] == ('JSONDecodeError' if cause == 'json' else 'ValueError')


def run_config_fixture(request, emit):
    # Restore the process-only pinned API changes without launching a Worker.
    with ExitStack() as stack:
        stack.enter_context(patch.object(lint_worker.sys, 'addaudithook'))
        stack.enter_context(patch.dict(lint_worker.manager.__dict__, clear=False))
        for target, names in (
            (lint_worker.ProviderSchemaManager, ('update', '_load_provider_module', 'get_resource_schema')),
            (lint_worker.ConfigMixIn, ('_glob_filenames', 'parameters', 'set_template_args')),
            (lint_worker.cfn_yaml, ('load',)), (lint_worker.cfn_json, ('load',)),
            (lint_worker.manager_module, ('get_url_content', 'get_url_metadata', 'get_url_retrieve', 'url_has_newer_version')),
            (lint_worker.helpers, ('get_url_content', 'get_url_metadata', 'get_url_retrieve', 'url_has_newer_version')),
        ):
            for name in names:
                if hasattr(target, name):
                    stack.enter_context(patch.object(target, name, getattr(target, name)))
        return lint_worker.structured(request, emit)


@pytest.mark.parametrize('setting', ['excluded', 'ignore_bad', 'ignore_rule', 'deployment', 'syntax', 'root'])
def check_config_input_branches(tmp_path, monkeypatch, setting):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / '.cache'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'AppData/Local'))
    monkeypatch.chdir(tmp_path)
    template = tmp_path / 'app.yaml'
    template.write_text('- not-an-object\n' if setting == 'root' else 'Resources: [broken')
    settings = {'excluded': {'ignore_templates': [str(template)]}, 'ignore_bad': {'ignore_bad_template': True},
        'ignore_rule': {'ignore_checks': ['E0000']}, 'deployment': {'deployment_files': ['other.json']}, 'syntax': {}, 'root': {}}[setting]
    (tmp_path / '.cfnlintrc').write_text(json.dumps(settings))
    result = run_config_fixture(dict(cwd=str(tmp_path), template=str(template), region='ap-northeast-1'), None)
    if setting == 'deployment':
        assert result['processing_errors'] and not result['completed']
    elif setting == 'excluded':
        assert result['status'] == 'excluded_by_config' and not result['completed'] and result['unverified']
    else:
        assert result['completed'] and not result['decode_complete'] and result['unverified'] and not result['processing_errors'], result
        assert bool(result['matches']) is (setting in ('syntax', 'root'))
        assert all(m['Message'] == 'Template decode incomplete; see Rule and Location' for m in result['matches'])


def check_noecho_redaction():
    secret = 'fixture-private-value'
    response, sensitive, noecho = dict(decode=[]), set(), set()
    loader = Mock(return_value={'Parameters': {'Input': {'NoEcho': True, 'Default': secret}}})
    loader.__module__ = 'fixture'
    lint_worker._callback_structured_observe_load(Mock(), Mock(), loader, noecho, response, sensitive, 'app.yaml')
    assert noecho == {'Input'} and sensitive == {secret}
    parameters = SimpleNamespace(fget=Mock(return_value=[SimpleNamespace(parameters={'Input': secret+'-override'})]))
    lint_worker._callback_structured_parameters(noecho, parameters, sensitive, Mock())
    matches = {'Rule': {'Id': 'E3002'}, 'Level': 'Error', 'Location': {'Path': ['Parameters']},
        'Message': secret, 'nested': [secret+'-override']}
    redacted = lint_worker._recursive_structured_redact(sensitive, matches)
    assert secret not in json.dumps(redacted) and redacted['Rule'] == matches['Rule']



def check_offline_and_write_guards(tmp_path):
    response = dict(processing_errors=[])
    state = SimpleNamespace(busy=False)
    with pytest.raises(lint_worker.OfflineError):
        lint_worker._callback_structured_audit(state, response, Mock(), 'socket.connect', ())
    assert response['processing_errors'] == [dict(code='schema_unavailable')]
    with pytest.raises(lint_worker.OfflineError):
        lint_worker._callback_structured_audit(state, response, Mock(), 'open', (str(tmp_path / 'output'), 'w', 0))



@pytest.mark.parametrize('dependency', ['files', 'directories', 'selections'])
def check_lint_jobs_accept_changed_dependencies(dependency):
    jobs = [dict(id=str(i), template=f'/fixture/{i}.yaml', region='ap-northeast-1', status='planned') for i in range(2)]
    results = [dict(status='completed', completed=True, decode_complete=True, matches=[],
        processing_errors=[], unverified=[], dependencies={dependency: [dict(locator='/fixture/shared', pattern='*', sha256=str(i))]}) for i in range(2)]
    comparison = SimpleNamespace(root=Path('/fixture'), sensitive_values=set(), redacted=lambda value: value)
    with patch('issues.cfn_lint.plan', return_value=(jobs, [])), \
         patch('issues.cfn_lint.lint_session'), patch('issues.cfn_lint.validate_template', side_effect=results) as lint:
        result = run_lint(comparison)
    assert lint.call_count == 2 and result['status'] == 'checked'
    assert all(item['status'] == 'completed' for item in result['coverage'])
    assert 'lint_dependencies' not in result


if __name__=='__main__':
    raise SystemExit(run(__file__))
