#!/usr/bin/env python3
"""Local issues: one target-batched scan, minimal review materials, guarded Python save."""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from collections import Counter
from contextlib import redirect_stdout
import io
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from design_layout import resource_mode, resource_name_fields, resource_has_name_property, REQUIRED_NAME_TAG_TYPES
from design_catalog import selected_properties
from model_design import entries, naming_rule_files, naming_targets, naming_target_matches, catalog_outputs, NAMING_EXEMPT_PROPERTIES
from policy_tables import literal
from validation_cache import input_scope, digest_files, PassCache
from task_contract import SELECTOR, DeferredExhausted
from issues_iac import Comparison, module, safe_value
from issues_reports import save, identifier, blocks, owned_blocks, numbered, inventories, safe_text, iac_summary, iac_dataset, brief


def outside(root, path):
    path = path.resolve()
    if path.is_relative_to(root):
        raise ValueError('scan/review/diagnostics artifacts must be outside the repository')
    return path


def selected_scope(environment, directory, services):
    values = [environment, directory, *services]
    if not services or any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', value) for value in values):
        raise ValueError('explicit environment/target/services required')
    return {(environment, directory, service) for service in services}


def mechanical(root, scope, *, fresh=False, jobs=4, catalog=None, fingerprint_out=None):
    """Reuse service checks/cache/parallelism, without contract/deploy/full-loop execution."""
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    validator_module = module('validate-blueprint.py', 'issues_validator')
    def model_check(selected):
        groups = {}
        for env, target, service in sorted(selected):
            groups.setdefault((env, target), []).append(service)
        errors = []
        sync = module('sync-model.py', 'issues_sync')
        for (env, target), services in groups.items():
            try:
                sync.sync(root, False, env, target, services=services, jobs=jobs)
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(str(error))
        return errors
    validator = validator_module.Validator(root, scope, cache=True, fresh=fresh, workers=jobs, model_check=model_check)
    validator.schema_catalog = catalog
    output = io.StringIO()
    with redirect_stdout(output):
        validator.check_project_topology()
        validator.check_validation_scope()
        validator.check_model_files()
        # Continue diagnosable checks even when model/Markdown equality fails.
        if all((root / base / env / target / f'{service}{suffix}').is_file()
               for env, target, service in scope for base, suffix in [('model', '.properties'), ('docs/designs', '.md')]):
            try:
                validator.check_scoped_designs()
            except (OSError, ValueError, KeyError, TypeError) as error:
                validator.check(False, 'service validation could not complete: ' + str(error))
        validator.check_iac_selection()
    if fingerprint_out is not None:
        fingerprint_out.update({'/'.join(entry): key for entry, key in getattr(validator, 'service_keys', {}).items()})
    return validator.errors, validator.checks, output.getvalue()


def rule_section(text, heading):
    lines = text.splitlines()
    result, active = [], False
    for line in lines:
        if line == heading:
            active = True
        elif active and line.startswith('## '):
            break
        if active:
            result.append(line)
    return '\n'.join(result)


def naming_materials(comparison):
    rules, names, judgments = {}, [], []
    for service in comparison.services:
        if service not in comparison.models:
            judgments.append({'id': identifier([service, 'load-error']), 'service': service, 'kind': 'input-load-error', 'materials': 'model unavailable; validators retain actual diagnostics'})
            continue
        loaded = comparison.model(service)
        notes = [dict(key=key, value=safe_text(value), source=comparison.source(service, key))
                 for key, value in loaded.values.items() if key.startswith('desired.note.')]
        if notes:
            judgments.append({'id': identifier([service, 'notes']), 'service': service, 'kind': 'human-components/exceptions', 'materials': notes})
        for identity, resource in comparison.resources[service].items():
            try:
                mode = resource_mode(resource)
            except ValueError as error:
                judgments.append({'id': identifier([service, identity, 'mode-error']), 'service': service, 'resource': identity, 'kind': 'invalid-resource-mode', 'materials': str(error), 'source': comparison.source(service, f'desired.resource.{identity}.resourceMode')})
                continue
            owned = {}
            for rid, row in comparison.rows[service][identity]:
                kind = '.'.join(row.get('property', '').split('.')[:2])
                owned.setdefault(kind, []).append((rid, row))
            owned.setdefault(resource['resourceType'], [])
            for kind, rows in owned.items():
                namespace = kind.partition('.')[0]
                if namespace not in rules:
                    shared = []
                    for file in naming_rule_files(comparison.root, namespace):
                        comparison.inputs.add(file)
                        text = file.read_text(encoding='utf-8')
                        if file.name == 'aws-resource-naming.md':
                            text = '\n\n'.join(rule_section(text, heading) for heading in ('## Scope', '## General rules', '## Name tag policy'))
                        if file.name == 'aws-resource-naming.md':
                            rules.setdefault('common', [{'path': file.relative_to(comparison.root).as_posix(), 'text': text}])
                        else:
                            shared.append({'path': file.relative_to(comparison.root).as_posix(), 'text': text})
                    rules[namespace] = shared
                targets = naming_targets(comparison.root, namespace).get(kind, set())
                outputs = catalog_outputs(comparison.root, kind)
                fields = set(resource_name_fields(kind)) | targets
                selected = []
                for pos, (rid, row) in enumerate(rows):
                    prop = row['property'].removeprefix(kind + '.')
                    if row['property'] in outputs:
                        continue
                    if prop in fields or naming_target_matches(prop, targets, kind):
                        selected.append((rid, row, prop, row['value']))
                    if prop in {'Tags[].Key', 'HostedZoneTags[].Key'} and literal(row['value']) == 'Name':
                        valuefield = prop.replace('.Key', '.Value')
                        pair = rows[pos + 1] if pos + 1 < len(rows) and rows[pos + 1][1]['property'] == kind + '.' + valuefield else None
                        selected.append((pair[0] if pair else rid, pair[1] if pair else row, 'Name tag', pair[1]['value'] if pair else None))
                    if prop in {'Tags', 'HostedZoneTags'}:
                        try:
                            value = json.loads(literal(row['value']))
                        except ValueError:
                            value = None
                        if isinstance(value, dict) and 'Name' in value:
                            selected.append((rid, row, 'Name tag', value['Name']))
                        elif isinstance(value, list):
                            for tag in value:
                                if isinstance(tag, dict) and tag.get('Key') == 'Name':
                                    selected.append((rid, row, 'Name tag', tag.get('Value')))
                required = {'Name'} if kind in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog', 'CodeBuild.Project'} else {'RoleName'} if kind == 'IAM.Role' else {'Name tag'} if kind in REQUIRED_NAME_TAG_TYPES else set()
                if resource_has_name_property(comparison.root, kind, mode) and kind not in REQUIRED_NAME_TAG_TYPES:
                    required.update(set(resource_name_fields(kind)) & selected_properties(comparison.root, kind) - {field.removeprefix(kind + '.') for field in catalog_outputs(comparison.root, kind)})
                # IMPORT removes framework mandatory Name policy, not confirmed IAM/CodeBuild names.
                if mode == 'IMPORT' and kind not in {'IAM.Role', 'CodeBuild.Project'}:
                    required = set()
                for field in sorted(required - {item[2] for item in selected}):
                    selected.append((None, None, field, None))
                if not selected:
                    selected.append((None, None, '(no selected naming property)', None))
                for rid, row, field, value in selected:
                    key = f'desired.row.{rid}.value' if rid else f'desired.resource.{identity}.resourceType'
                    entry = {'id': identifier([service, identity, kind, field, rid]), 'service': service, 'resource': identity,
                             'resourceType': kind, 'resourceMode': mode, 'property': field, 'value': comparison.redacted(value, field),
                             'required_missing': field in required and value is None,
                             'rule': namespace, 'rule_targets': sorted(targets),
                             'scope': 'IMPORT framework convention excluded' if mode == 'IMPORT' else
                                      'coverage exemption; apply exact convention/value scope from common rule' if kind + '.' + field in NAMING_EXEMPT_PROPERTIES else 'CREATE selected naming target',
                             'source': comparison.source(service, key),
                             'comment': safe_text(row['comment']) if row else None,
                             'pattern_review': 'not applicable' if field == '(no selected naming property)' else 'exact exemption scope applies' if kind + '.' + field in NAMING_EXEMPT_PROPERTIES else 'required' if mode == 'CREATE' else 'framework convention excluded',
                             'human_context_id': identifier([service, 'notes']) if notes else None,
                             'identity': {key: resource[key] for key in ('logicalId', 'cfn-logicalId', 'anchor') if key in resource}}
                    names.append(entry)
    return {'target_context': comparison.target, 'rules': rules, 'names': names,
            'review_policy': '全名称のpattern/正本component/例外scopeを確認する。human_context_idの注記とrow commentを根拠にし、不足componentを値から推測しない。coverage除外をconvention/値検証除外へ拡大しない。'}, judgments


def existing_materials(root, environment, directory, services):
    path = root / 'issues' / environment / directory / 'issues.md'
    inventories(root, path)
    if not path.is_file():
        return [], []
    preamble, sections = owned_blocks(root, path, path.read_text(encoding='utf-8'))
    items = []
    for service, body in sections:
        if service in services or service is None:
            _, issues = numbered(body)
            items.extend({'id': identifier([service, text]), 'service': service, 'message': safe_text(text),
                          'kind': 'existing-unresolved; preserve unless explicitly revalidated'} for text in issues)
    human = [line for line in preamble.splitlines() if line.strip() and not line.startswith(('#', '更新日時:', '今回確認した範囲:'))]
    return items, human


def file_sets(comparison):
    roots = {path.with_suffix('') for path in comparison.inputs if path.suffix in {'.properties', '.md'} and path.is_relative_to(comparison.root / 'model')}
    roots.update(comparison.root / 'docs/designs' / comparison.environment / comparison.directory / service for service in comparison.services)
    return {path.relative_to(comparison.root).as_posix(): sorted(file.relative_to(comparison.root).as_posix() for file in path.rglob('*')
              if file.is_file() or file.is_symlink()) for path in roots}


def fingerprint(comparison):
    paths = sorted(path.relative_to(comparison.root).as_posix() for path in comparison.inputs)
    return {'paths': paths, 'digest': digest_files(comparison.root, comparison.inputs),
            'file_sets': file_sets(comparison), 'framework': PassCache(comparison.root).common_key()}


def verify_inputs(root, artifact):
    expected = artifact['fingerprint']
    if digest_files(root, [root / path for path in expected['paths']]) != expected['digest']:
        raise ValueError('stale scan: scoped model/IaC/parameter/reference input changed; rescan affected scope')
    for directory, files in expected['file_sets'].items():
        current = sorted(file.relative_to(root).as_posix() for file in (root / directory).rglob('*') if file.is_file() or file.is_symlink())
        if current != files:
            raise ValueError('stale scan: input file set changed')
    verify_service_keys(root, artifact)
    if PassCache(root).common_key() != expected['framework']:
        raise ValueError('stale scan: framework/project input changed')


def verify_service_keys(root, artifact):
    for entry, expected_key in artifact.get('service_keys', {}).items():
        if expected_key is not None and PassCache(root).service_key(tuple(entry.split('/'))) != expected_key:
            raise ValueError('stale scan: validation/reference dependency changed')


@input_scope
def scan(root, environment, directory, services, *, fresh=False, jobs=4):
    started = time.perf_counter()
    scope = selected_scope(environment, directory, services)
    comparison = Comparison(root, environment, directory, services)
    # Capture before checks too: an edit during diagnostics must not produce a current artifact.
    for service in services:
        doc = root / 'docs/designs' / environment / directory / (service + '.md')
        comparison.track(doc)
    service_keys = {}
    before = fingerprint(comparison)
    begin = time.perf_counter()
    errors, checks, diagnostics = mechanical(root, scope, fresh=fresh, jobs=jobs, catalog=comparison.catalog, fingerprint_out=service_keys)
    mechanical_seconds = time.perf_counter() - begin
    ordinary, judgments = [], []
    for message in dict.fromkeys(errors):
        found = [service for service in services if re.search(r'/' + re.escape(service) + r'(?:\.md|\.properties|/)', message)]
        owner = found[0] if len(found) == 1 else services[0] if len(services) == 1 else None
        candidate = {'id': identifier(message), 'service': owner, 'message': safe_text(comparison.redacted(message)), 'key': identifier(message)}
        (ordinary if owner else judgments).append(candidate)
    naming, naming_judgments = naming_materials(comparison)
    judgments.extend(naming_judgments)
    existing, human = existing_materials(root, environment, directory, services)
    judgments.extend({'id': item['id'], 'service': item['service'], 'kind': 'existing-issue-correspondence', 'materials': item} for item in existing)
    for service in services:
        doc = root / 'docs/designs' / environment / directory / (service + '.md')
        if doc.is_file():
            text = doc.read_text(encoding='utf-8')
            # Only notes/implementation prose remains for LLM review; verified tables are not repeated.
            known_notes = {value for key, value in comparison.models[service].values.items() if key.startswith('desired.note.')} if service in comparison.models else set()
            notes = []
            for line in text.splitlines():
                if line.strip() and not line.startswith(('#', '|', '<', '- Design', '- Owned')) and not line.startswith('```') and line.removeprefix('- ').strip() not in known_notes:
                    notes.append(safe_text(line))
            if notes:
                judgments.append({'id': identifier([service, 'design-notes']), 'service': service, 'kind': 'nonmechanical-design-prose', 'materials': notes})
    begin = time.perf_counter()
    try:
        iac = comparison.run()
    except (OSError, ValueError, KeyError, ImportError, TypeError) as error:
        iac = [{'category': 'error', 'service': service, 'resource': '*', 'property': '*', 'reason': safe_text(str(error))}
               for service in services]
    iac_seconds = time.perf_counter() - begin
    # Reference models/artifacts discovered during evaluation become guarded inputs too.
    for path, expected_hash in comparison.read_hashes.items():
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual_hash != expected_hash:
            raise ValueError('inputs changed after decoding: ' + path.relative_to(root).as_posix())
    after = fingerprint(comparison)
    if digest_files(root, [root / path for path in before['paths']]) != before['digest'] or before['framework'] != after['framework']:
        raise ValueError('inputs changed during scan')
    artifact = {'version': 1, 'root': str(root), 'environment': environment, 'target': directory,
                'services': sorted(set(services)), 'executed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'ordinary': ordinary, 'naming': naming, 'judgments': judgments,
                'human_confirmations': [safe_text(line) for line in human], 'iac': iac, 'fingerprint': after,
                'iac_display': comparison.display_differences,
                'machine_diagnostics': safe_text(diagnostics), 'checks': checks,
                'service_keys': service_keys,
                'metrics': comparison.metrics | {'mechanical_seconds': mechanical_seconds, 'iac_seconds': iac_seconds,
                                                  'wall_seconds': time.perf_counter() - started}}
    entries, actions, _ = iac_dataset(iac, environment, directory, services, artifact['iac_display'])
    artifact['iac_issues'] = [dict(group, members=[entries[i]['record_index'] for i in group['members']]) for group in actions]
    verify_service_keys(root, artifact)
    return artifact


def summary(artifact):
    counts = Counter(item['category'] for item in artifact.get('iac', []))
    status = 'error' if counts['error'] else 'partial' if counts['uncompared'] else 'differences' if counts['difference'] else 'complete match'
    return {'ordinary_candidates': len(artifact.get('ordinary', [])), 'judgment_items': len(artifact.get('judgments', [])),
            'naming_items': len(artifact.get('naming', {}).get('names', [])), 'iac_differences': counts['difference'],
            'iac_uncompared': counts['uncompared'], 'iac_errors': counts['error'], 'iac_matched': counts['matched'], 'iac_excluded': counts['excluded'], 'iac_status': status,
            'validation_status': 'FAIL' if artifact.get('ordinary') or any('message' in item for item in artifact.get('judgments', [])) else 'checked',
            'checks': artifact.get('checks')}


def save_scan(root, artifact, review):
    if artifact.get('version') != 1 or artifact.get('root') != str(root):
        raise ValueError('invalid scan artifact/root')
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
                 review.get('resolved', []), artifact['iac'], guard=lambda: verify_inputs(root, artifact), display=artifact.get('iac_display'), stamp=artifact.get('executed_at'))
    return paths


def review_payload(artifact, artifact_path):
    return {'summary': summary(artifact), 'scope': {key: artifact[key] for key in ('environment', 'target', 'services')},
            'executed_at': artifact.get('executed_at'), 'artifact': str(artifact_path),
            'iac_summary': iac_summary(artifact['iac'], artifact['environment'], artifact['target'], artifact['services'], artifact.get('iac_display')),
            'review_required': {'names': len(artifact['naming']['names']), 'judgments': len(artifact['judgments']),
                'policy': 'naming/judgmentsの全ページ・全IDを確認する。代表例だけではsave不可。'},
            'human_confirmations': {'total': len(artifact['human_confirmations']), 'items': [brief(line) for line in artifact['human_confirmations'][:3]],
                                    'omitted': max(0, len(artifact['human_confirmations']) - 3)},
            'detail': 'issues_scan.py detail --artifact <path> --section naming|judgments|ordinary|human_confirmations|iac_issues|iac --offset 0 --limit 50; IaC: --category <分類> / --issue-id ISSUE-<id>'}


def detail_payload(artifact, section, offset=0, limit=50, category=None, issue_id=None):
    if offset < 0 or limit < 1:
        raise ValueError('invalid detail range')
    if (category or issue_id) and section not in {'iac', 'iac_issues'}:
        raise ValueError('IaC filters require section iac or iac_issues')
    context = {}
    if section in {'iac', 'iac_issues'}:
        actions = artifact.get('iac_issues')
        if actions is None:
            entries, groups, _ = iac_dataset(artifact['iac'], artifact['environment'], artifact['target'], artifact['services'], artifact.get('iac_display'))
            actions = [dict(group, members=[entries[i]['record_index'] for i in group['members']]) for group in groups]
        selected = [action for action in actions if (not category or action['category'] == category) and (not issue_id or action['id'] == issue_id)]
        if issue_id and not selected:
            raise ValueError('Issue ID not found in selected artifact/category')
        if section == 'iac_issues':
            content = selected
        else:
            membership = {index: action['id'] for action in selected for index in action['members']}
            indices = sorted(membership) if category or issue_id else range(len(artifact['iac']))
            content = [dict(artifact['iac'][i], record_index=i, issue_id=membership.get(i),
                            value_differences=artifact.get('iac_display', {}).get(identifier(artifact['iac'][i]), [])) for i in indices]
    elif section == 'naming':
        content = artifact['naming']['names']
        context = {key: value for key, value in artifact['naming'].items() if key != 'names'}
    elif section == 'machine_diagnostics':
        content = artifact[section].splitlines()
    else:
        content = artifact[section]
    return {'total': len(content), 'offset': offset, 'items': content[offset:offset + limit],
            'omitted': max(0, len(content) - len(content[offset:offset + limit])), **({'context': context} if context else {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--task-file')
    commands = parser.add_subparsers(dest='command', required=True)
    scanparser = commands.add_parser('scan')
    scanparser.add_argument('--environment', required=True)
    scanparser.add_argument('--target-directory', required=True)
    scanparser.add_argument('--service', action='append', required=True)
    scanparser.add_argument('--artifact', type=Path, required=True)
    scanparser.add_argument('--fresh', action='store_true')
    scanparser.add_argument('--jobs', type=int, choices=(1, 2, 4), default=4)
    detail = commands.add_parser('detail')
    detail.add_argument('--artifact', type=Path, required=True)
    detail.add_argument('--section', choices=('ordinary', 'naming', 'judgments', 'human_confirmations', 'iac', 'iac_issues', 'machine_diagnostics'), required=True)
    detail.add_argument('--offset', type=int, default=0)
    detail.add_argument('--limit', type=int, default=50)
    detail.add_argument('--category', choices=('要対応', '要判断', '比較未完了', '処理エラー', '原因未確定'), help='IaC classification filter; applied before pagination')
    detail.add_argument('--issue-id', help='stable ISSUE-<id>; retrieve members from this artifact without comparison')
    saveparser = commands.add_parser('save')
    saveparser.add_argument('--artifact', type=Path, required=True)
    saveparser.add_argument('--review', type=Path, required=True)
    results = commands.add_parser('save-results')
    results.add_argument('--environment', required=True)
    results.add_argument('--target-directory', required=True)
    results.add_argument('--service', action='append', required=True)
    results.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    if args.task_file:
        os.environ[SELECTOR] = args.task_file
    try:
        if args.command == 'scan':
            artifact_path = outside(root, args.artifact)
            artifact = scan(root, args.environment, args.target_directory, args.service, fresh=args.fresh, jobs=args.jobs)
            artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            output = review_payload(artifact, artifact_path)
            print(json.dumps(output, ensure_ascii=False))
            return 2 if any(item['category'] == 'error' for item in artifact['iac']) else 1 if artifact['ordinary'] or any('message' in item for item in artifact['judgments']) else 0
        if args.command == 'detail':
            artifact = json.loads(outside(root, args.artifact).read_text(encoding='utf-8'))
            print(json.dumps(detail_payload(artifact, args.section, args.offset, args.limit, args.category, args.issue_id), ensure_ascii=False))
            return 0
        if args.command == 'save':
            artifact = json.loads(outside(root, args.artifact).read_text(encoding='utf-8'))
            review = json.loads(outside(root, args.review).read_text(encoding='utf-8'))
            paths = save_scan(root, artifact, review)
        else:
            selected_scope(args.environment, args.target_directory, args.service)
            results = json.loads(outside(root, args.results).read_text(encoding='utf-8'))
            if set(results) - {'issues', 'resolved'}:
                raise ValueError('save-results accepts acquired ordinary results only; no automatic comparison')
            paths = save(root, args.environment, args.target_directory, args.service, additions=results.get('issues', []), resolutions=results.get('resolved', []))
        print(json.dumps({'saved': [path.relative_to(root).as_posix() for path in paths], 'summary': summary(artifact) if args.command == 'save' else 'acquired results saved; no rescan', 'post_save_validation': 'required: blueprint-loop.py --mode local'}, ensure_ascii=False))
        return 2 if args.command == 'save' and any(item['category'] == 'error' for item in artifact['iac']) else 0
    except DeferredExhausted as error:
        print(str(error))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Local issues: ERROR: ' + safe_text(str(error)), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
