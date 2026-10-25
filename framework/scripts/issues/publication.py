"""Ordinary issue merge, current-run IaC display and atomic scoped publication."""
from __future__ import annotations

import model.sources as _imports_model_sources
from task_contract_core import (
    issues_save_only,
    paths_in,
    safe_path,
    status,
    task_read_scope,
    task_snapshot,
)
from utils.file_operations import atomic_files
from utils.input_cache import input_scope
from validation_scope import active_scope

import issues.artifact as _imports_issues_artifact
import issues.reports as _imports_issues_reports

from .reports import iac_report, normal_merge


@task_read_scope
def save_authority(root, environment, directory, services, filenames):
    snapshot = task_snapshot(root)
    text = snapshot.text
    scope = active_scope(root)
    selected = {(environment, directory, service) for service in services}
    if status(text) != 'running' or not scope or not selected <= scope:
        raise ValueError('report save requires a running report-only migration with explicit service scope')
    allowed = paths_in(text, '## Allowed paths')
    if not issues_save_only(root, scope=scope, text=text):
        raise ValueError('save-only exception does not permit model/IaC/unscoped outputs')
    paths = [safe_path(root, f'issues/{environment}/{directory}/{name}') for name in filenames]
    if any(path.relative_to(root).as_posix() not in allowed for path in paths):
        raise ValueError('report is outside Allowed paths')
    return paths


@input_scope
def save(root, environment, directory, services, candidates=(), additions=(), resolutions=(), iac=None, display=None, stamp=None, warnings=(), artifact=None):
    publication_lock = _imports_model_sources.publication_lock
    with publication_lock(root, read_only=True):
        names = ['issues.md'] + (['iac-issues.md'] if iac is not None else [])
        paths = save_authority(root, environment, directory, services, names)
        contents = {paths[0]: normal_merge(root, paths[0], environment, directory, services, candidates, additions, resolutions)}
        notice_report = _imports_issues_reports.notice_report
        channels = {name: artifact.get(name, []) for name in ('warnings','information','unverified','processing_errors')} if artifact else {'warnings': list(warnings)}
        if artifact is not None or warnings:
            contents[paths[0]] = notice_report(contents[paths[0]], environment, directory, services, channels)
        if iac is not None:
            contents[paths[1]] = iac_report(environment, directory, services, iac, display, stamp=stamp, artifact=artifact)
        atomic_files(contents)
        return paths




def save_scan(root, artifact, review):
    if artifact.get('version') != 3 or artifact.get('root') != str(root):
        raise ValueError('invalid scan artifact/root')
    validate_artifact = _imports_issues_artifact.validate_artifact
    validate_artifact(artifact)
    required = {'scan_id','reviewed_naming_context_id','reviewed_names','reviewed_judgments','diagnostic_assignments','issues','resolved'}
    if not required <= review.keys() or review['scan_id'] != artifact['scan_id'] or review['reviewed_naming_context_id'] != artifact['naming_context_id']:
        raise ValueError('review scan_id/naming_context_id mismatch; review this scan completely')
    if not all(isinstance(review[key], list) for key in ('reviewed_names','reviewed_judgments','issues','resolved')) or not isinstance(review['diagnostic_assignments'],dict):
        raise ValueError('malformed review')
    names = {item['id'] for item in artifact['naming']['names']}
    judgments = {item['id'] for item in artifact['judgments']}
    if set(review.get('reviewed_names', [])) != names or set(review.get('reviewed_judgments', [])) != judgments:
        raise ValueError('all naming and remaining judgment materials need explicit review; no representative sampling')
    assignments = review.get('diagnostic_assignments', {})
    additions = list(review.get('issues', []))
    for item in artifact['judgments']:
        if 'message' in item:
            owner = assignments.get(item['id'])
            if owner not in artifact['services']:
                raise ValueError('diagnostic requires scoped service assignment')
            additions.append(dict(item, service=owner))
    paths = save(root, artifact['environment'], artifact['target'], artifact['services'], artifact['ordinary'], additions,
                 review.get('resolved', []), artifact['iac'], display=artifact.get('iac_display'), stamp=artifact.get('executed_at'), warnings=artifact.get('warnings', []), artifact=artifact)
    return paths
