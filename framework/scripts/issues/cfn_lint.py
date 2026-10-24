"""Explicit selected-Model lint plan, ownership, diagnostic channels and coverage."""

from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

import model.sources as _imports_model_sources
from design_layout import resource_mode
from model.core import entries
from utils.cfn_lint import POLICY, file_state, lint_session, runtime, validate_template
from utils.iac_values import cfn_resource_identity

from .records import identifier, safe_text


def _callback_plan_add(comparison, coverage, jobs, /, unit, origin):
    filename = unit.get('template')
    if not isinstance(filename,str) or Path(filename).name != filename or Path(filename).suffix not in {'.yaml','.yml'} or '\\' in filename:
        coverage.append(dict(status='unverified', reason='explicit template filename invalid', **origin))
        return
    raw = comparison.root/'infra/cloudformation/templates'/comparison.target.get('alias','')/unit['template']
    if not raw.resolve().is_relative_to(comparison.root.resolve()):
        coverage.append(dict(status='unverified', reason='unsafe explicit template', **origin))
        return
    comparison.track(raw)
    path = raw.resolve()
    key = identifier([str(path), comparison.target['awsRegion'], POLICY])
    job = jobs.setdefault(key,dict(id=key, template=str(path), region=comparison.target['awsRegion'],
        policy=POLICY, origins=[], status='planned' if path.is_file() else 'input_missing'))
    job['origins'].append(origin)


def _callback_plan_declared_stacks(_state_plan_32, comparison, /):
    pass
    if _state_plan_32.stacks is None:
        _state_plan_32.stacks = {}
        try:
            for _, unit in entries(comparison.model('cloudformation-stacks').values, 'desired.stack.'):
                _state_plan_32.stacks.setdefault(unit['name'], []).append(unit)
        except (OSError, ValueError, KeyError, TypeError) as error:
            _state_plan_32.stack_error = type(error).__name__
    return _state_plan_32.stacks


def plan(comparison):
    _state_plan_32 = _CallbackState()
    jobs, coverage = {}, []
    if comparison.target['iacEngine'] != 'cloudformation':
        return [], [dict(status='not_applicable', reason='Terraform scope')]
    _state_plan_32.stacks, _state_plan_32.stack_error = None, None
    declared_stacks = _bind_framework_callback(_callback_plan_declared_stacks, _state_plan_32, comparison)
    add = _bind_framework_callback(_callback_plan_add, comparison, coverage, jobs)
    for service in comparison.services:
        if service not in comparison.models:
            coverage.append(dict(status='unverified', service=service, reason='selected Model unavailable'))
            continue
        if service=='cloudformation-stacks':
            for units in declared_stacks().values():
                for unit in units:
                    add(unit,dict(service=service,stack=unit['name'],logical=None,resource=None))
            if _state_plan_32.stack_error:
                coverage.append(dict(status='unverified', service=service, reason='declared Stack Model unavailable', exception=_state_plan_32.stack_error))
        for identity, resource in comparison.resources[service].items():
            origin = dict(service=service, resource=identity)
            try:
                mode = resource_mode(resource)
                if mode=='IMPORT' or resource.get('resourceType') in comparison.catalog.api_schemas:
                    coverage.append(dict(status='not_applicable', reason='IMPORT' if mode=='IMPORT' else 'API-only',**origin))
                    continue
                if not resource.get('cfn-logicalId'):
                    raise ValueError('explicit cfn-logicalId unavailable')
                name, logical = cfn_resource_identity(resource['cfn-logicalId'])
                units = declared_stacks().get(name, [])
                if _state_plan_32.stack_error:
                    coverage.append(dict(status='unverified', reason='declared Stack Model unavailable', exception=_state_plan_32.stack_error, **origin))
                    continue
                if len(units)!=1:
                    raise ValueError('Stack correspondence is not unique/declared')
                add(units[0], dict(origin, stack=name, logical=logical))
            except (ValueError,KeyError,TypeError):
                coverage.append(dict(status='unverified', reason='explicit Stack/template correspondence unconfirmed', **origin))
    return list(jobs.values()), coverage


def classify(match, execution):
    level, rule = match.get('Level'), match.get('Rule',{}).get('Id')
    if level not in {'Error','Warning','Informational'}:
        return 'processing_errors'
    if rule in {'E0001','E0002','E0003'}:
        return 'processing_errors'
    if rule=='E0000' and not execution.get('input_defect'):
        return 'processing_errors'
    return {'Error':'ordinary','Warning':'warnings','Informational':'information'}[level]


def owner(comparison, job, match):
    model_paths = _imports_model_sources.model_paths
    path = match.get('Location',{}).get('Path')
    logical = path[1] if isinstance(path,list) and len(path)>1 and path[0]=='Resources' else None
    if logical is None:
        return ('cloudformation-stacks' if 'cloudformation-stacks' in comparison.services else None), False
    owners = {origin['service'] for origin in job['origins'] if origin['logical']==logical}
    if len(owners)==1:
        return next(iter(owners)), False
    if owners:
        return None, False
    # Only proven explicit out-of-scope correspondence can make a finding scope-external.
    for source in model_paths(comparison.root,comparison.environment,comparison.directory):
        if source.stem in comparison.services or source.stem=='cloudformation-stacks':
            continue
        try:
            comparison.model(source.stem)
            for resource in comparison.resources[source.stem].values():
                if resource.get('cfn-logicalId'):
                    stack, candidate = cfn_resource_identity(resource['cfn-logicalId'])
                    if candidate==logical and any(origin['stack']==stack for origin in job['origins']):
                        return None, True
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return None, False


def run_lint(comparison):
    jobs, coverage = plan(comparison)
    channels = {name:[] for name in ('ordinary','judgments','warnings','information','unverified','processing_errors')}
    dependencies = dict(runtime=runtime(comparison.root), files=[], directories=[], selections=[])
    files, directories, selections = {}, {}, {}
    for job in jobs:
        state = file_state(job['template'])
        files[state['locator']] = state
    with lint_session(comparison.root) as session:
        for job in jobs:
            job['diagnostic_ids'] = []
            if job['status']=='input_missing':
                coverage.append(dict(job_id=job['id'], status='input_missing', reason='explicit template missing at plan start'))
                continue
            result = validate_template(session,job['template'],job['region'])
            comparison.sensitive_values.update(result.pop('sensitive_values', []))
            for state in result.get('dependencies',{}).get('files',[]):
                prior = files.setdefault(state['locator'],state)
                if prior!=state:
                    raise ValueError('stale scan: lint dependency changed during jobs')
            for state in result.get('dependencies',{}).get('directories',[]):
                key = (state['locator'],state['pattern'])
                prior = directories.setdefault(key,state)
                if prior!=state:
                    raise ValueError('stale scan: lint file set changed during jobs')
            for state in result.get('dependencies',{}).get('selections',[]):
                prior = selections.setdefault(state['pattern'],state)
                if prior!=state:
                    raise ValueError('stale scan: lint selection changed during jobs')
            job.update(status=result['status'], completed=result['completed'], effective_regions=result.get('effective_regions',[]),
                       effective_config_fingerprint=result.get('effective_config_fingerprint'), decode=result.get('decode',[]),
                       configuration_sources=result.get('configuration_sources',[]),schema_roots=result.get('schema_roots',{}))
            for notice in result.get('unverified',[]):
                channels['unverified'].append(dict(notice,job_id=job['id']))
            for error in result.get('processing_errors',[]):
                value = dict(error,job_id=job['id'])
                value['id'] = identifier(value)
                channels['processing_errors'].append(value)
                job['diagnostic_ids'].append(value['id'])
            counts = {}
            for match in result['matches']:
                channel = classify(match,result)
                service, outside = owner(comparison,job,match)
                if channel=='processing_errors':
                    outside = False
                diagnostic = dict(code='cfn_lint.'+str(match.get('Rule',{}).get('Id','unknown')),
                    job_id=job['id'], service=service, diagnostic=comparison.redacted(match), scope='outside' if outside else 'selected')
                diagnostic['id'] = identifier([job['id'],match])
                diagnostic['message'] = safe_text(comparison.redacted(str(match.get('Message',''))))
                job['diagnostic_ids'].append(diagnostic['id'])
                counts[channel] = counts.get(channel,0)+1
                if outside:
                    # Keep the structured diagnostic, without affecting selected-scope status.
                    channels['information'].append(dict(diagnostic,kind='out_of_scope_diagnostic'))
                elif channel=='ordinary' and service is None:
                    channels['judgments'].append(dict(diagnostic,kind='lint-owner-assignment'))
                else:
                    channels[channel].append(diagnostic)
                if channel=='processing_errors' and not outside:
                    channels['unverified'].append(dict(code='lint.diagnostic_not_completed', diagnostic_id=diagnostic['id']))
                if match.get('Rule',{}).get('Id')=='E0001' and not outside:
                    channels['unverified'].append(dict(code='lint.rules_after_transform_not_run',diagnostic_id=diagnostic['id']))
            job['counts'] = counts
            coverage.append(dict(job_id=job['id'],status='completed' if result.get('decode_complete') and result['completed'] and not result['unverified'] and not result['processing_errors'] and not any(m.get('Rule',{}).get('Id') in {'E0001','E0002','E0003'} for m in result['matches']) else 'unverified'))
    for item in coverage:
        if item['status'] in {'unverified','input_missing','excluded_by_config'}:
            channels['unverified'].append(dict(code='lint.coverage', **item))
    dependencies['files'] = list(files.values())
    dependencies['directories'] = list(directories.values())
    dependencies['selections'] = list(selections.values())
    return dict(jobs=jobs, coverage=coverage,
                status='not_applicable' if not jobs and coverage and all(c['status']=='not_applicable' for c in coverage) else 'incomplete' if channels['unverified'] else 'checked',
                lint_dependencies=dependencies, **channels)
