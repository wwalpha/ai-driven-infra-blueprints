from contextlib import redirect_stdout
import io
import hashlib
import os
import re
import time

from model.core import ReferenceResolutionError
from model.sources import FileReads
from validation_cache import input_scope, digest_files, PassCache
from task_contract import contract_read_scope
from script_loader import module
from .comparison import Comparison
from .records import identifier, safe_text
from .materials import naming_materials, existing_materials
from .integrity import selected_scope, fingerprint, verify_inputs, live_common_key
from .aggregate import aggregate
from .inputs import view_text
import uuid

@contract_read_scope
def mechanical(root, scope, *, fresh=False, jobs=4, catalog=None, fingerprint_out=None, warnings=None, cache=None, validator_out=None, view_errors=None):
    """Reuse service checks/cache/parallelism, without contract/deploy/full-loop execution."""
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    validator_module = module('validate-blueprint.py', 'issues_validator')
    validator = validator_module.Validator(root, scope, cache=True, fresh=fresh, workers=jobs)
    if cache is not None:
        validator.cache = cache
    validator.schema_catalog = catalog
    output = io.StringIO()
    with redirect_stdout(output):
        validator.check_project_topology()
        validator.check_validation_scope()
        validator.check_model_files()
        # Continue diagnosable checks even when model/Markdown equality fails.
        validator.check_scoped_designs(defer_cache=validator_out is not None, view_errors=view_errors)
        validator.check_iac_selection()
    if validator_out is not None:
        validator_out.append(validator)
    if fingerprint_out is not None:
        fingerprint_out.update({'/'.join(entry): key for entry, key in getattr(validator, 'service_keys', {}).items()})
    if warnings is not None:
        warnings.extend(validator.warnings)
    return validator.errors, validator.checks, output.getvalue()


@input_scope
def scan(root, environment, directory, services, *, fresh=False, jobs=4):
    started = time.perf_counter()
    scope = selected_scope(environment, directory, services)
    scan_id = uuid.uuid4().hex
    reads = FileReads()
    cache = PassCache(root, fresh=fresh)
    cache.common = cache.common_key(snapshot=reads)
    comparison = Comparison(root, environment, directory, services)
    # Capture before checks too: an edit during diagnostics must not produce a current artifact.
    for service in services:
        doc = root / 'docs/designs' / environment / directory / (service + '.md')
        view_text(comparison, doc, phase='view-preflight')
        entrance = root / 'model' / environment / directory / (service + '.properties')
        comparison.track(entrance)
        for part in entrance.with_suffix('').rglob('*'):
            if part.is_file() or part.is_symlink():
                comparison.track(part)
    service_keys = {}
    warnings = list(comparison.warnings)
    before = fingerprint(comparison, common_key=cache.common)
    begin = time.perf_counter()
    validators = []
    errors, checks, diagnostics = mechanical(root, scope, fresh=fresh, jobs=jobs, catalog=comparison.catalog, fingerprint_out=service_keys, warnings=warnings, cache=cache, validator_out=validators, view_errors=comparison.view_errors)
    mechanical_seconds = time.perf_counter() - begin
    ordinary, judgments = [], []
    for message in dict.fromkeys(errors):
        found = [service for service in services if re.search(r'/' + re.escape(service) + r'(?:\.md|\.properties|/)', message)]
        owner = found[0] if len(found) == 1 else services[0] if len(services) == 1 else None
        candidate = {'id': identifier(message), 'service': owner, 'message': safe_text(comparison.redacted(message)), 'key': identifier(message)}
        (ordinary if owner else judgments).append(candidate)
    naming, naming_judgments = naming_materials(comparison)
    judgments.extend(naming_judgments)
    existing, human = existing_materials(root, environment, directory, services, warnings)
    judgments.extend({'id': item['id'], 'service': item['service'], 'kind': 'existing-issue-correspondence', 'materials': item} for item in existing)
    for service in services:
        doc = root / 'docs/designs' / environment / directory / (service + '.md')
        if doc.is_file() and doc not in comparison.view_errors:
            text = view_text(comparison, doc, phase='review-prose')
            if text is None:
                continue
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
    except ReferenceResolutionError as error:
        warnings.append(comparison.redacted(error.diagnostic))
        iac = list(comparison.results) + [{'category': 'uncompared', 'service': service, 'resource': '*', 'property': '*',
                'reason': safe_text(comparison.redacted(str(error))), 'comparison_incomplete': True,
                'cause': {'kind': 'reference-unresolved'}} for service in services]
    except (OSError, ValueError, KeyError, ImportError, TypeError) as error:
        iac = list(comparison.results) + [{'category': 'error', 'service': service, 'resource': '*', 'property': '*',
                'reason': safe_text(comparison.redacted(str(error))), 'comparison_incomplete': True}
               for service in services]
    warnings.extend(w for w in comparison.warnings if w not in warnings)
    iac_seconds = time.perf_counter() - begin
    from .cfn_lint import run_lint
    begin = time.perf_counter()
    lint = run_lint(comparison)
    lint_seconds = time.perf_counter() - begin
    ordinary.extend(lint.pop('ordinary'))
    judgments.extend(lint.pop('judgments'))
    warnings.extend(lint.pop('warnings'))
    naming_context = comparison.redacted({key: value for key, value in naming.items() if key != 'names'})
    context_id = identifier(naming_context)
    naming = {'names': [dict(item, naming_context_id=context_id) for item in naming['names']]}
    unverified = list(lint.pop('unverified'))
    validator = validators[0]
    unverified.extend(validator.findings.unverified)
    view_errors = list(comparison.view_errors.values())
    unverified.extend(dict(error, code='mechanical.view_unverified') for error in view_errors)
    for entry in sorted(scope):
        view = root / 'docs/designs' / entry[0] / entry[1] / (entry[2] + '.md')
        if not view.is_file():
            unverified.append({'code': 'mechanical.view_missing', 'service': entry[2], 'message': 'saved View checks unavailable'})
    for entry, info in validator.findings.result('framework.generated-service-model', scope).metadata.get('unverified', {}).items():
        unverified.append({'code': 'mechanical.view_unverified', 'scope': entry, 'details': info})
    processing = lint.pop('processing_errors')
    processing.extend(view_errors)
    # Stage failures are distinct from the number of affected comparison records.
    stage_errors = {}
    for record in iac:
        if record['category'] == 'error':
            key = identifier([record.get('reason'), record.get('cause'), record.get('iac')])
            stage_errors.setdefault(key, dict(id=key, code='iac.processing', message=record.get('reason'), affected_records=0))['affected_records'] += 1
    processing.extend(stage_errors.values())
    begin = time.perf_counter()
    data = aggregate(iac, environment, directory, services, comparison.display_differences, redact=comparison.redacted)
    aggregation_seconds = time.perf_counter() - begin
    artifact = dict(version=2, root=str(root), scan_id=scan_id, naming_context_id=context_id, naming_context=naming_context,
        environment=environment, target=directory, services=sorted(set(services)),
        executed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), ordinary=ordinary, naming=naming,
        judgments=judgments, warnings=warnings, human_confirmations=[safe_text(line) for line in human],
        information=lint.pop('information'), unverified=unverified, processing_errors=processing,
        fingerprint=fingerprint(comparison, common_key=cache.common), service_keys=service_keys,
        lint_dependencies=lint.pop('lint_dependencies'), cfn_lint=lint, machine_diagnostics=safe_text(comparison.redacted(diagnostics)),
        **data)
    # Redact every channel before hashing/review/output; masked material never regains raw values.
    for key in ('ordinary','judgments','warnings','information','unverified','processing_errors','naming_context','naming','human_confirmations'):
        artifact[key] = comparison.redacted(artifact[key])
    begin = time.perf_counter()
    for path, expected_hash in comparison.read_hashes.items():
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual_hash != expected_hash:
            raise ValueError('stale scan: inputs changed after decoding: ' + path.relative_to(root).as_posix())
    if digest_files(root, [root / path for path in before['paths']]) != before['digest']:
        raise ValueError('stale scan: inputs changed during scan')
    for directory_name, files in before['file_sets'].items():
        current = sorted(file.relative_to(root).as_posix() for file in (root / directory_name).rglob('*') if file.is_file() or file.is_symlink())
        if current != files:
            raise ValueError('stale scan: initial input file set changed')
    verify_inputs(root, artifact, cache=cache, common=False)
    current_common = live_common_key(cache)  # Live enumeration and bytes, never the starting memo.
    if current_common != cache.common:
        raise ValueError('stale scan: framework/project input changed')
    if view_errors:
        # Scope-wide ownership/reference coverage was incomplete; discard unproved candidates.
        validator.service_cache_pending = []
    validator.finalize_service_cache(current_common)
    artifact['checks'] = validator.checks
    artifact['metrics'] = comparison.metrics | dict(mechanical_seconds=mechanical_seconds, iac_seconds=iac_seconds,
        lint_seconds=lint_seconds, aggregation_seconds=aggregation_seconds, input_guard_seconds=time.perf_counter()-begin,
        wall_seconds=time.perf_counter()-started, wall_scope='runner through aggregation, final input guards and cache finalization; excludes CLI JSON/output')
    from .artifact import validation_status, channel_summary, CHANNELS
    artifact['validation_status'] = validation_status(artifact)
    artifact['review_required'] = True
    artifact['notice_overview'] = {name:channel_summary(artifact[name],name) for name in CHANNELS}
    artifact['metrics']['wall_seconds'] = time.perf_counter()-started
    return artifact
