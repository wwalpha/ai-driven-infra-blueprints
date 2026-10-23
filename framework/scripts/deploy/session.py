"""External Deploy sessions, immutable guards, target locks and observed barriers."""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from functools import partial as _bind_framework_callback
from pathlib import Path

import model.observed as _imports_model_observed
from cloudformation_inputs import Blocked
from model.sources import authority_snapshot, load_model, model_paths, source_scope
from task_contract_core import paths_in, status, task_path
from utils.aws_mappings import definition_root
from utils.json_format import fingerprint
from utils.source_reads import FileReads
from validation_scope import active_scope as validation_scope

import deploy.context as _imports_deploy_context
import deploy.contracts as _imports_deploy_contracts
import deploy.observed as _dependency_deploy_observed
from deploy import failures, handoff, observed_resume
from deploy import resume as repair_resume
from deploy.scheduler import run_group
from deploy.secret_bootstrap import BOOTSTRAP_STAGES


def save_session(path, session):
    handoff.save(path, session)


def active_scope(root, requested, environment, account, alias=None):
    contract = task_path(root)
    text = contract.read_text(encoding="utf-8")
    if status(text) != "running":
        raise Blocked("completed task cannot deploy")
    for line in ("- Task type: `infrastructure`", "- AWS API execution: `allowed`", "- Deploy/apply: `allowed`",
                 f"- Target environment: `{environment}`", f"- Target AWS account: `{account}`"):
        if line not in text.splitlines():
            raise Blocked(f"active task must explicitly contain {line}")
    if not any(f"- Infrastructure phase: `{phase}`" in text.splitlines() for phase in ("deploy", "update")):
        raise Blocked("controller requires infrastructure deploy/update phase")
    if alias and f"- Target alias: `{alias}`" not in text.splitlines():
        raise Blocked("requested alias must exactly match active task Target alias")
    scopes = [line for line in text.splitlines() if line.startswith("- Deployment scope:")]
    if len(scopes) != 1 or set(re.findall(r"`([^`]+)`", scopes[0])) != set(requested):
        raise Blocked("requested StackName scope must exactly match active task Deployment scope")
    return "update" if "- Infrastructure phase: `update`" in text.splitlines() else "deploy"


def design_digest(root, environment, directory, *, contract_file=None):
    scope = validation_scope(root, contract_file=contract_file)
    pending = ([root / "model" / env / target / (service + ".properties") for env, target, service in scope
                if (env, target) == (environment, directory)] if scope is not None
               else model_paths(root, environment, directory))
    pending.append(root / "model" / environment / directory / "cloudformation-stacks.properties")
    snapshot, reads = {}, FileReads()
    while pending:
        path = pending.pop().resolve()
        if path in snapshot:
            continue
        if reads.kind(path) == 'missing':
            snapshot[path] = None
            continue
        model = load_model(path, reads)
        snapshot[path] = {key: value for key, value in model.authoritative.items() if not key.startswith('observed.')}
        for dependency in model.dependencies:
            if dependency.is_relative_to(root / 'model'):
                pending.append(source_scope(root, dependency).path)
    return fingerprint({str(path.relative_to(root)): values for path, values in snapshot.items()})


def model_input_manifest(root, environment, directory):
    return {path.relative_to(root).as_posix(): None if raw is None else hashlib.sha256(raw).hexdigest()
            for path, raw in authority_snapshot(root, environment, directory).items()}


def require_session_format(session):
    expected = {'version': 4, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1}
    if any(type(session.get(key)) is not int or session[key] != value for key, value in expected.items()):
        raise Blocked('controller session format is incompatible; explicit v3 to v4 migration must retain original identity/history/candidates')


def verify_observed_transition(root, environment, directory, previous, outputs, intended_design):
    verify_observed_outputs = _imports_model_observed.verify_observed_outputs
    verify_observed_outputs(previous, outputs)
    expected = {**previous, **{path: text.encode('utf-8') for path, text in outputs.items()}}
    if authority_snapshot(root, environment, directory) != expected:
        raise Blocked('Model sources changed outside authorized observed publication')
    if design_digest(root, environment, directory) != intended_design:
        raise Blocked('observed publication changed intended Model design')
    return model_input_manifest(root, environment, directory)


def execution_digest(root, target, file_digest, unit_digests):
    # Reuse is invalidated by controller, validators, rules, catalog/schema and project changes.
    paths = sorted(path for path in (definition_root(root) / "framework").rglob("*")
                   if path.is_file() and path.suffix in {".py", ".json", ".md", ".properties", ".sha256"})
    paths += [root / "AGENTS.md", root / "project.json"]
    paths += sorted((definition_root(root) / '.agents/skills').rglob('*.md'))
    paths.append(definition_root(root) / 'framework/scripts/requirements.txt')
    return fingerprint([target, sys.version,
        [(str(path.relative_to(root if path.is_relative_to(root) else definition_root(root))), file_digest(path))
         for path in paths if path.is_file()]])



def _callback_run_session_sync_once(backend, save, session, units, /):
    unsynced = [u for u in units if session["states"][u["name"]]["status"] == "SUCCESS"
                and not session["states"][u["name"]].get("observedSynced")]
    if not unsynced:
        return True
    started = time.perf_counter()
    try:
        if hasattr(backend, 'guard'):
            backend.guard()
        previous = backend.before_observed() if hasattr(backend, 'before_observed') else None
        outputs = sync_successful(backend, unsynced, session["states"])
        if hasattr(backend, 'after_observed'):
            backend.after_observed(previous, outputs or {})
        session.pop('pendingObserved', None)
        session.pop("observedError", None)
        session.pop('observedRecoveryError', None)
        return True
    except Exception as error:
        for unit in unsynced:
            session["states"][unit["name"]].pop("observedSynced", None)
        session.setdefault('observedError', str(error))
        session['observedRecoveryError'] = str(error)
        failure = {'stage': session.get('pendingObserved', {}).get('stage', 'PLANNING'), 'cause': str(error)}
        failures = session.setdefault('observedFailures', [])
        if not failures or failures[-1] != failure:
            failures.append(failure)
        return False
    finally:
        session["metrics"]["observedSyncSeconds"] += time.perf_counter() - started
        save()


# Peers may have completed while an earlier persisted plan was blocked.
def _callback_run_session_sync_completed(session, sync_once, /):
    # Peers may have completed while an earlier persisted plan was blocked.
    while True:
        pending = session.get('pendingObserved')
        if not sync_once():
            return False
        if not pending:
            return True


def run_session(units, limit, session, backend, save, pause_after_group=False, sleep=time.sleep):
    """Observed synchronization is an idempotent, persisted barrier between groups."""
    sync_once = _bind_framework_callback(_callback_run_session_sync_once, backend, save, session, units)

    sync_completed = _bind_framework_callback(_callback_run_session_sync_completed, session, sync_once)

    backend.sync_completed = sync_completed
    while True:
        if not sync_completed():
            # A restart may contain both unsynced successes and still-running peers.
            run_group(units, limit, session["states"], backend, save, sleep=sleep, drain_only=True)
            return "STOPPED"
        result = run_group(units, limit, session["states"], backend, save, sleep=sleep)
        if result == "GROUP_COMPLETE":
            completed = sorted({int(u["deployOrder"]) for u in units
                                if all(session["states"][v["name"]]["status"] == "SUCCESS"
                                       for v in units if v["deployOrder"] == u["deployOrder"])})
            session["metrics"]["deployOrderCount"] = len(completed)
            # Sync even the final group before returning COMPLETE.
            if pause_after_group:
                if not sync_completed():
                    return "STOPPED"
                return "COMPLETE" if all(s["status"] == "SUCCESS" for s in session["states"].values()) else "GROUP_COMPLETE"
            continue
        if result == "STOPPED":
            # Do not abandon successful peers' observed values after another stack fails.
            synced = sync_completed()
            handoff.record_stop(session, units)
            save()
            failed = [u for u in units if session["states"][u["name"]]["status"] == "FAILED"]
            if synced and failed and hasattr(backend, "repair"):
                repaired = all([backend.repair(u, session["states"][u["name"]]) for u in failed])
                save()
                if repaired:
                    continue
        return result


def _callback_run_infra_manifest(backend, root, units, /):
    return {path.relative_to(root).as_posix(): backend.file_digest(path)
            for path in sorted(set(backend.deployment_input_paths(units)))}


def _callback_run_save(invocation_started, metrics, previous_duration, session, state_path, /):
    metrics["totalControllerSeconds"] = previous_duration + time.perf_counter() - invocation_started
    metrics["awsPollCount"] = sum(s.get("pollApiCount", 0) for s in session["states"].values())
    save_session(state_path, session)


def _callback_run_guard(args, backend, context, current_design, directory, infra_manifest, root, selected, session, target, task_digest, unit_digests, units, /):
    active_scope(root, args.stack, args.environment, selected["awsAccountId"], args.alias)
    if context.load_target(root, args.environment, args.aws_account_id, args.alias) != target:
        raise Blocked("project target changed before mutation")
    if design_digest(root, args.environment, directory) != current_design:
        raise Blocked("intended model changed before mutation")
    if model_input_manifest(root, args.environment, directory) != session['modelInputManifest']:
        raise Blocked('Model raw inputs or dependency file set changed before mutation')
    if infra_manifest() != session['infraManifest']:
        raise Blocked('unauthorized IaC change outside accepted input revision')
    if task_digest(task_path(root).read_text(encoding='utf-8')) != session['taskDigest']:
        raise Blocked('task contract changed before mutation')
    if any(backend.input_digest(unit) != unit_digests[unit["name"]] for unit in units):
        raise Blocked("deployment inputs changed before mutation")
    if execution_digest(backend.root, backend.target, backend.file_digest, unit_digests) != session.get("executionDigest"):
        raise Blocked("execution definitions changed before mutation")


def _callback_run_after_observed(args, current_design, directory, root, session, /, previous, outputs):
    session['modelInputManifest'] = verify_observed_transition(
        root, args.environment, directory, previous, outputs, current_design)


# Runtime bootstrap does not change IaC or grant a validation/hash exception.
def _callback_run_refresh_validation(backend, unit_digests, /, unit):
    # Runtime bootstrap does not change IaC or grant a validation/hash exception.
    backend.load_inputs(unit)
    if backend.input_digest(unit, fresh=True) != unit_digests[unit['name']]:
        raise Blocked('runtime recovery changed immutable IaC inputs')


def run(args, root, timing, script_directory, backend_type, load_units):
    state_path = args.state.resolve()
    lock_path = None
    lock = None
    session = None
    persist = None
    handoff_lock = None
    invocation_started = time.perf_counter()
    try:
        if state_path.is_relative_to(root):
            raise Blocked("deployment session must be outside repository; never store AWS status in Git")
        context = _imports_deploy_context
        selected = context.load_target(root, args.environment, args.aws_account_id, args.alias)
        phase = active_scope(root, args.stack, args.environment, selected["awsAccountId"], args.alias)
        if args.pause_after_group and phase != "update":
            raise Blocked("--pause-after-group requires the explicit update phase")
        context_started = time.perf_counter()
        with timing.phase("authenticationContext"):
            target = context.check_deploy_context(root, args.environment, args.aws_account_id, args.alias, args.profile)
        context_seconds = time.perf_counter() - context_started
        if target["iacEngine"] != "cloudformation":
            raise Blocked("controller requires CloudFormation target")
        lock_target = {key: value for key, value in target.items() if key != "awsProfile"}
        lock_path = Path(tempfile.gettempdir()) / ("blueprint-cfn-" + fingerprint([args.environment, lock_target]) + ".lock")
        try:
            lock = lock_path.open("x")
        except FileExistsError as error:
            raise Blocked(f"controller session already active or interrupted; verify no controller is running before removing {lock_path}") from error
        candidate_lock = handoff.locked(state_path)
        candidate_lock.__enter__()
        handoff_lock = candidate_lock
        directory = args.alias or args.aws_account_id
        if args.resume:
            session = json.loads(state_path.read_text(encoding='utf-8'))
            handoff.restore(root, state_path, session)
            if not getattr(args, 'observe_only', False):
                require_session_format(session)
            if session.get('pendingObserved') and not getattr(args, 'observe_only', False):
                # Recovery must precede load_units/design_digest and all read-only Model snapshots.
                sha = _imports_deploy_contracts.sha
                try:
                    if any(sha(root / path) != digest for path, digest in session['infraManifest'].items()):
                        raise Blocked('IaC changed during pending observed publication')
                    if execution_digest(root, target, sha, session['unitDigests']) != session['executionDigest']:
                        raise Blocked('execution definitions changed during pending observed publication')
                    observed_resume.reconcile(root, session, target, args.environment, directory)
                except Exception as error:
                    session['observedRecoveryError'] = str(error)
                    save_session(state_path, session)
                    raise
                save_session(state_path, session)
        limit, units = load_units(root, args.environment, directory, args.stack)
        if args.sequential:
            limit = 1
        backend = backend_type(root, args.environment, directory, target, args.profile, args.approve_change_set)
        backend.timing = timing
        if phase == "deploy" and not args.resume:
            paths = sorted({str(path.relative_to(root)) for unit in units for path in backend.paths(unit)})
            revision = subprocess.run(["git", "status", "--porcelain", "--", *paths], cwd=root,
                                      capture_output=True, text=True, timeout=30)
            if revision.returncode or revision.stdout.strip():
                raise Blocked("deploy template/parameter revision must be clean; cannot deploy uncommitted IaC")
        digest = fingerprint([str(root), target, args.environment, phase, limit, units])
        current_design = design_digest(root, args.environment, directory)
        backend.workdir = state_path.with_name(state_path.name + ".files").resolve()
        if backend.workdir.is_relative_to(root):
            raise Blocked("deployment files directory must be outside repository")
        unit_digests = {unit["name"]: backend.input_digest(unit) for unit in units}
        infra_manifest = _bind_framework_callback(_callback_run_infra_manifest, backend, root, units)
        current_infra = infra_manifest()
        if args.resume:
            if getattr(args, 'observe_only', False):
                if session['inputDigest'] != digest or session.get('repository') != str(root) or session.get('taskFile') != task_path(root).relative_to(root).as_posix():
                    raise Blocked('observation session target/Task identity changed')
                return repair_resume.observe_only(backend, units, limit, state_path, session)
            require_session_format(session)
            if session.get('workflow', {}).get('status') == 'CLOSED':
                raise Blocked('closed workflow cannot resume AWS execution; unresolved history still owns overlapping scope')
            if session.get('workflow', {}).get('legacyUncertain'):
                raise Blocked('WAITING_HUMAN: legacy repair identity/cycles require diagnosis; no candidate reapplication')
            current_execution = execution_digest(root, target, backend.file_digest, unit_digests)
            if session.get('executionDigest') != current_execution:
                raise Blocked('execution definitions changed; explicitly migrate original session first')
            if getattr(args, 'repair_result', None):
                repair_resume.accept(root, args.repair_result, session, backend, units, unit_digests, current_infra)
            elif session.get('pendingRequest'):
                raise Blocked('pending external repair requires --resume --repair-result')
            # Older sessions watched all infra; retain only current execution inputs.
            previous_infra = {path: digest for path, digest in session.get('infraManifest', current_infra).items()
                              if path in current_infra}
            changed_infra = {path for path in previous_infra.keys() | current_infra.keys()
                             if previous_infra.get(path) != current_infra.get(path)}
            update_handoff = {path.relative_to(root).as_posix() for unit in units
                       if phase == 'update' and session['states'][unit['name']]['status'] == 'NOT_STARTED'
                       for path in backend.deployment_input_paths([unit])}
            if changed_infra - update_handoff:
                raise Blocked('unauthorized IaC change outside recorded repair; cannot resume')
            session['infraManifest'] = current_infra
            if phase == 'deploy':
                paths = sorted({str(path.relative_to(root)) for path in backend.deployment_input_paths(units)})
                revision = subprocess.run(['git', 'status', '--porcelain', '--', *paths], cwd=root,
                                          capture_output=True, text=True, timeout=30)
                if revision.returncode or revision.stdout.strip():
                    raise Blocked('resumed deploy inputs must be committed verified child bytes')
            require_session_format(session)
            if session.get('modelInputManifest') != model_input_manifest(root, args.environment, directory):
                raise Blocked('Model raw inputs or dependency file set changed; cannot resume this session')
            if session["inputDigest"] != digest:
                raise Blocked("target, design or scope changed; cannot resume this session")
            for name, state in session["states"].items():
                if (phase == "deploy" or state["status"] != "NOT_STARTED") and session["unitDigests"][name] != unit_digests[name]:
                    raise Blocked(f"prepared/executed unit IaC changed; cannot resume: {name}")
            session["unitDigests"] = unit_digests
            if session.get("designDigest", current_design) != current_design or session.get("profile", backend.profile) != backend.profile:
                raise Blocked("intended model or AWS profile changed; cannot resume")
        else:
            if state_path.exists() or args.approve_change_set:
                raise Blocked("new session requires unused state path and no approvals")
            session = {"inputDigest": digest, "unitDigests": unit_digests,
                       "states": {unit["name"]: {"status": "NOT_STARTED"} for unit in units}}
        session.update(version=4, modelFormat=2, snapshotVersion=2, referenceMeaningVersion=1,
                       designDigest=current_design, profile=backend.profile,
                       modelInputManifest=model_input_manifest(root, args.environment, directory))
        session.setdefault('repository', str(root))
        session.setdefault('taskFile', task_path(root).relative_to(root).as_posix())
        sha = _imports_deploy_contracts.sha
        task_digest = _imports_deploy_contracts.task_digest
        session.setdefault('taskDigest', task_digest(task_path(root).read_text(encoding='utf-8')))
        session.setdefault('infraManifest', current_infra)
        session.setdefault('unitInputPaths', {u['name']: [p.relative_to(root).as_posix() for p in backend.deployment_input_paths([u])] for u in units})
        session.setdefault('environment', args.environment)
        session.setdefault('directory', directory)
        session.setdefault('target', target)
        session.setdefault('logicalTarget', [args.environment, directory, target['awsAccountId'], target['awsRegion']])
        budget_lines = re.findall(r'^- Repair cycle budget: `([0-9]+)`$', task_path(root).read_text(), re.M)
        if budget_lines and (len(budget_lines) != 1 or int(budget_lines[0]) <= 0):
            raise Blocked('invalid repair cycle budget')
        session.setdefault('repairBudget', int(budget_lines[0]) if budget_lines else 20)
        session.setdefault('validationScope', sorted(paths_in(task_path(root).read_text(), '## Validation scope')))
        if phase == 'update' and args.resume and not getattr(args, 'repair_result', None):
            session['effectiveDigests'] = handoff.effective(root, units, backend.paths, backend.deployment_input_paths)
        session.setdefault('effectiveDigests', handoff.effective(root, units, backend.paths, backend.deployment_input_paths))
        session.setdefault("executionDigest", execution_digest(root, target, backend.file_digest, unit_digests))
        handoff.bind(root, state_path, session)
        backend.session = session
        contract = task_path(root).read_text(encoding='utf-8')
        if '- External IaC repair: `allowed`' in contract.splitlines() and f'- Deploy repair session: `{state_path}`' not in contract.splitlines():
            raise Blocked('external repair session path must match task contract')
        metrics = session.setdefault("metrics", {})
        for key in ("controllerInvocationCount", "deployOrderCount", "observedSyncSeconds",
                    "inputLoadSeconds", "totalControllerSeconds", "contextCheckSeconds"):
            metrics.setdefault(key, 0)
        metrics["controllerInvocationCount"] += 1
        metrics["contextCheckSeconds"] += context_seconds
        for change_id in args.approve_change_set:
            matches = [state for state in session["states"].values() if state.get("changeSetId") == change_id]
            if len(matches) != 1 or matches[0]["status"] != "BLOCKED" or not matches[0].get("changeDigest"):
                raise Blocked("approve only the saved blocked change set after human confirmation")
        backend.states = session["states"]
        backend.expected_digests = session["unitDigests"]
        previous_duration = metrics["totalControllerSeconds"]
        save = _bind_framework_callback(_callback_run_save, invocation_started, metrics, previous_duration, session, state_path)
        backend.save = save
        persist = save
        guard = _bind_framework_callback(_callback_run_guard, args, backend, context, current_design, directory, infra_manifest, root, selected, session, target, task_digest, unit_digests, units)
        backend.guard = guard
        backend.before_observed = lambda: authority_snapshot(root, args.environment, directory)
        after_observed = _bind_framework_callback(_callback_run_after_observed, args, current_design, directory, root, session)
        backend.after_observed = after_observed
        refresh_validation = _bind_framework_callback(_callback_run_refresh_validation, backend, unit_digests)
        backend.refresh_validation = refresh_validation
        backend.units = units
        started = time.perf_counter()
        try:
            for unit in units:
                state = session['states'][unit['name']]
                try:
                    backend.load_inputs(unit)
                except Exception as error:
                    state['preparationId'] = state.get('preparationId') or __import__('uuid').uuid4().hex
                    failures.exception(state, error, 'INPUT_DECODE' if getattr(error, 'deploy_input_kind', None) == 'DECODE' else 'INPUT_GUARD')
                    if state['status'] not in {'RUNNING', 'FAILED', 'SUCCESS'}:
                        state['status'] = 'BLOCKED'
                    handoff.record_stop(session, units)
                    save()
                    raise
                state = session['states'][unit['name']]
                if state['status'] not in {'SUCCESS', 'RUNNING', 'FAILED'}:
                    migrate_delivery = _imports_deploy_contracts.migrate_delivery
                    if migrate_delivery(root, target, unit, state, backend.templates[unit['name']], backend.file_digest):
                        session['migration'] = 'v3 SDK delivery arguments; execution identity retained'
            current_execution = execution_digest(root, target, backend.file_digest, unit_digests)
            if args.resume and session.get('executionDigest', current_execution) != current_execution:
                raise Blocked('execution definitions changed; review and explicitly migrate the same session')
            session.setdefault('executionDigest', current_execution)
            session.setdefault('declaredConsumers', handoff.dependencies(backend, units))
            save()
        except Exception:
            run_group(units, limit, session['states'], backend, save, drain_only=True)
            raise
        finally:
            metrics['inputLoadSeconds'] += time.perf_counter() - started
        for unit in units:
            state = session['states'][unit['name']]
            repair_resume.recover(backend, unit, state)
            if state.get('repairs') and state['repairs'][-1].get('classification') == 'RUNTIME_BOOTSTRAP' and state['repairs'][-1].get('stage') in BOOTSTRAP_STAGES:
                if not backend.repair(unit, state):
                    session['result'] = 'STOPPED'
                    save()
                    return 2
        session["result"] = run_session(units, limit, session, backend, save, args.pause_after_group)
        handoff.record_outcomes(session)
        if session.get('repairOutcomeUnverified'):
            session['result'] = 'STOPPED'
        save()
        print(json.dumps(session, indent=2))
        return 2 if session["result"] == "STOPPED" else 0
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"CloudFormation controller: BLOCKED: {error}", file=sys.stderr)
        return 2
    finally:
        try:
            if persist is not None:
                persist()
        finally:
            try:
                if handoff_lock is not None:
                    handoff_lock.__exit__(None, None, None)
            finally:
                if lock is not None:
                    lock.close()
                    lock_path.unlink(missing_ok=True)


def sync_successful(backend, units, states):
    return _dependency_deploy_observed.sync_successful(backend, units, states)
