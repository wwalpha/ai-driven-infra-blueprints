"""External Deploy sessions, immutable guards, target locks and observed barriers."""
import importlib.util
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from model_core import properties, LINK
from model_files import read_model
from iac_values import fingerprint
from cloudformation_inputs import Blocked
from cloudformation_observed import MappingError, mappings, sync_successful, removed_resources
from task_contract import task_path, status, paths_in
from validation_scope import active_scope as validation_scope
from deployment.scheduler import run_group
from deployment.secret_bootstrap import BOOTSTRAP_STAGES


def active_scope(root, requested, environment, account, alias=None):
    contract = task_path(root)
    text = contract.read_text(encoding="utf-8")
    if status(text, contract.name == "active.md") != "running":
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


def design_digest(root, environment, directory):
    scope = validation_scope(root)
    pending = ([root / "model" / env / target / (service + ".properties") for env, target, service in scope
                if (env, target) == (environment, directory)] if scope is not None
               else list((root / "model" / environment / directory).glob("*.properties")))
    pending.append(root / "model" / environment / directory / "cloudformation-stacks.properties")
    snapshot = {}
    while pending:
        path = pending.pop().resolve()
        if path in snapshot:
            continue
        values = {key: value for key, value in properties(read_model(path)).items() if not key.startswith("observed.")}
        snapshot[path] = values
        for value in values.values():
            link = LINK.fullmatch(value)
            if link and link.group(2):
                reference = (path.parent / link.group(2)).with_suffix(".properties").resolve()
                if not reference.is_relative_to(root / "model"):
                    raise Blocked("model reference escapes immutable design scope")
                pending.append(reference)
    return fingerprint({str(path.relative_to(root)): values for path, values in snapshot.items()})


def validation_digest(root, target, file_digest, unit_digests):
    # Reuse is invalidated by controller, validators, rules, catalog/schema and project changes.
    paths = sorted(path for path in (root / "framework").rglob("*")
                   if path.is_file() and path.suffix in {".py", ".json", ".md", ".properties", ".sha256"})
    paths += [root / "AGENTS.md", root / "project.json"]
    try:
        lint_version = importlib.metadata.version("cfn-lint")
    except importlib.metadata.PackageNotFoundError:
        lint_version = None
    return fingerprint([unit_digests, target, sys.version, lint_version,
                        [(str(path.relative_to(root)), file_digest(path)) for path in paths if path.is_file()]])


def run_session(units, limit, session, backend, save, pause_after_group=False, sleep=time.sleep):
    """Observed synchronization is an idempotent, persisted barrier between groups."""
    def sync_completed():
        unsynced = [u for u in units if session["states"][u["name"]]["status"] == "SUCCESS"
                    and not session["states"][u["name"]].get("observedSynced")]
        if not unsynced:
            return True
        started = time.perf_counter()
        try:
            sync_successful(backend, unsynced, session["states"])
            session.pop("observedError", None)
            return True
        except Exception as error:
            session["observedError"] = str(error)
            return False
        finally:
            session["metrics"]["observedSyncSeconds"] += time.perf_counter() - started
            save()

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
            for state in session['states'].values():
                if state['status'] == 'BLOCKED':
                    state['failureClassification'] = 'HUMAN_REQUIRED'
            # Do not abandon successful peers' observed values after another stack fails.
            synced = sync_completed()
            failed = [u for u in units if session["states"][u["name"]]["status"] == "FAILED"]
            if synced and failed and hasattr(backend, "repair"):
                repaired = all([backend.repair(u, session["states"][u["name"]]) for u in failed])
                save()
                if repaired:
                    continue
        return result


def run(args, root, timing, script_directory, backend_type, load_units):
    state_path = args.state.resolve()
    lock_path = None
    lock = None
    session = None
    persist = None
    invocation_started = time.perf_counter()
    try:
        if state_path.is_relative_to(root):
            raise Blocked("deployment session must be outside repository; never store AWS status in Git")
        spec = importlib.util.spec_from_file_location("deploy_context", script_directory / "check-deploy-context.py")
        context = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(context)
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
        directory = args.alias or args.aws_account_id
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
        def infra_manifest():
            return {path.relative_to(root).as_posix(): backend.file_digest(path)
                    for path in sorted(set(backend.deployment_input_paths(units)))}
        current_infra = infra_manifest()
        if args.resume:
            session = json.loads(state_path.read_text(encoding="utf-8"))
            for unit in units:
                state = session['states'][unit['name']]
                pending = state.get('repairs', [])[-1:]
                if not pending or pending[0].get('stage') not in {'REPAIR_INTENT', 'VALIDATING', 'VALIDATED'}:
                    continue
                entry = pending[0]
                if entry.get('classification') != 'AUTO_REPAIRABLE':
                    raise Blocked('unapproved pending repair')
                relative = entry['path']
                if current_infra.get(relative) == entry['newFileDigest'] and backend.input_digest(unit) == entry['newDigest']:
                    session['unitDigests'][unit['name']] = entry['newDigest']
                    session['infraManifest'][relative] = entry['newFileDigest']
                    entry['stage'] = 'VALIDATING'  # Resume repeats affected validation, never assumes interrupted PASS.
                elif current_infra.get(relative) != entry['oldFileDigest'] or backend.input_digest(unit) != entry['oldDigest']:
                    raise Blocked('pending repair bytes/digest changed outside authorized transaction')
            # Older sessions watched all infra; retain only current execution inputs.
            previous_infra = {path: digest for path, digest in session.get('infraManifest', current_infra).items()
                              if path in current_infra}
            changed_infra = {path for path in previous_infra.keys() | current_infra.keys()
                             if previous_infra.get(path) != current_infra.get(path)}
            handoff = {path.relative_to(root).as_posix() for unit in units
                       if phase == 'update' and session['states'][unit['name']]['status'] == 'NOT_STARTED'
                       for path in backend.deployment_input_paths([unit])}
            if changed_infra - handoff:
                raise Blocked('unauthorized IaC change outside recorded repair; cannot resume')
            session['infraManifest'] = current_infra
            if phase == 'deploy':
                from deploy_preparation import repair_changes
                paths = sorted({str(path.relative_to(root)) for unit in units for path in backend.paths(unit)})
                revision = subprocess.run(['git', 'status', '--porcelain', '--', *paths], cwd=root,
                                          capture_output=True, text=True, timeout=30)
                if revision.returncode:
                    raise Blocked('cannot verify resumed IaC revision')
                if revision.stdout.strip():
                    repaired = {entry['path'] for state in session['states'].values() for entry in state.get('repairs', [])
                                if entry.get('classification') == 'AUTO_REPAIRABLE' and entry.get('stage') != 'REPAIR_INTENT'}
                    repair_changes(root, task_path(root).read_text(encoding='utf-8'), repaired)
                    # Exact input digests/manifest below reject any other dirty bytes.
                    if not repaired:
                        raise Blocked('deploy revision dirty without repair evidence')
            if session.get("version", 1) not in {1, 2}:
                raise Blocked("unsupported controller session version")
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
        # v1 sessions resume conservatively: no cached validation or observed barrier is assumed.
        session.update(version=2, designDigest=current_design, profile=backend.profile)
        session.setdefault('repository', str(root))
        session.setdefault('taskFile', task_path(root).relative_to(root).as_posix())
        from deploy_preparation import sha, task_digest
        session.setdefault('taskDigest', task_digest(task_path(root).read_text(encoding='utf-8')))
        session.setdefault('infraManifest', current_infra)
        backend.session = session
        contract = task_path(root).read_text(encoding='utf-8')
        if '- Controlled repair: `allowed`' in contract.splitlines() and f'- Deploy repair session: `{state_path}`' not in contract.splitlines():
            raise Blocked('controlled repair session path must match task contract')
        metrics = session.setdefault("metrics", {})
        for key in ("controllerInvocationCount", "validationCount", "deployOrderCount", "observedSyncSeconds",
                    "inputLoadSeconds", "mappingCheckSeconds", "lintSeconds", "totalControllerSeconds", "contextCheckSeconds"):
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
        def save():
            metrics["totalControllerSeconds"] = previous_duration + time.perf_counter() - invocation_started
            metrics["awsPollCount"] = sum(s.get("pollApiCount", 0) for s in session["states"].values())
            temporary = state_path.with_suffix(state_path.suffix + ".tmp")
            temporary.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
            temporary.replace(state_path)
        backend.save = save
        persist = save
        def guard():
            active_scope(root, args.stack, args.environment, selected["awsAccountId"], args.alias)
            if context.load_target(root, args.environment, args.aws_account_id, args.alias) != target:
                raise Blocked("project target changed before mutation")
            if design_digest(root, args.environment, directory) != current_design:
                raise Blocked("intended model changed before mutation")
            if infra_manifest() != session['infraManifest']:
                raise Blocked('unauthorized IaC change outside controlled repair')
            if task_digest(task_path(root).read_text(encoding='utf-8')) != session['taskDigest']:
                raise Blocked('task contract changed before mutation')
            if any(backend.input_digest(unit) != unit_digests[unit["name"]] for unit in units):
                raise Blocked("deployment inputs changed before mutation")
            if validation_digest(backend.root, backend.target, backend.file_digest, unit_digests) != session.get("validationDigest"):
                raise Blocked("validation dependencies changed before mutation")
        backend.guard = guard
        def refresh_validation(unit):
            # Reuse validator/cache, but schema/naming/policy/model checks concern only affected services.
            mapped = backend.mapping_plan[1][unit['name']]
            affected = {(args.environment, directory, entry[0].stem) for entry in mapped.values()}
            spec = importlib.util.spec_from_file_location('repair_validator', root / 'framework/scripts/validate-blueprint.py')
            validator_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(validator_module)
            validator = validator_module.Validator(root, affected, validation_scope(root), cache=True,
                                                   iac_paths=set(backend.deployment_input_paths([unit])))
            if validator.run():
                raise Blocked('affected repair repository validation failed')
            backend.validate(unit)
            backend.mapping_plan = mappings(root, args.environment, directory, backend.templates, units,
                                            removed_resources(units, session['states']), target=target)
            session['validationDigest'] = validation_digest(backend.root, backend.target, backend.file_digest, unit_digests)
            session['validationStatus'] = 'PASS'
            metrics['validationCount'] += 1
            save()
        backend.refresh_validation = refresh_validation
        save()
        # Cheap whole-scope diagnostics precede lint and every change set.
        try:
            session.pop("validationErrors", None)
            session.pop("validationError", None)
            for state in session["states"].values():
                state.pop("preflightErrors", None)
            started = time.perf_counter()
            try:
                for unit in units:
                    backend.load_inputs(unit)
            finally:
                metrics["inputLoadSeconds"] += time.perf_counter() - started
            started = time.perf_counter()
            try:
                backend.mapping_units = units
                backend.mapping_plan = mappings(root, args.environment, directory, backend.templates, units,
                                                removed_resources(units, session["states"]), target=target)
            finally:
                metrics["mappingCheckSeconds"] += time.perf_counter() - started
            digest = validation_digest(backend.root, backend.target, backend.file_digest, unit_digests)
            if session.get("validationStatus") == "PASS" and session.get("validationDigest") == digest:
                backend.validated_digests = dict(unit_digests)
            else:
                session["validationStatus"] = "RUNNING"
                session["validationDigest"] = digest
                metrics["validationCount"] += 1
                save()
                started = time.perf_counter()
                try:
                    for unit in units:
                        try:
                            backend.validate(unit)
                        except Blocked:
                            state = session['states'][unit['name']]
                            events = getattr(backend, 'validation_failures', {}).get(unit['name'])
                            if state['status'] != 'NOT_STARTED' or not events:
                                raise
                            state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=events)
                            save()
                            if not backend.repair(unit, state):
                                raise
                            digest = validation_digest(backend.root, backend.target, backend.file_digest, unit_digests)
                finally:
                    metrics["lintSeconds"] += time.perf_counter() - started
                if any(backend.input_digest(unit, fresh=True) != unit_digests[unit["name"]] for unit in units):
                    raise Blocked("deployment inputs changed during scope validation")
                session["validationDigest"], session["validationStatus"] = digest, "PASS"
                metrics["validatedInputDigest"] = fingerprint(unit_digests)
                save()
        except Exception as error:
            session["result"] = "STOPPED"
            session["validationStatus"], session["validationError"] = "FAILED", str(error)
            if isinstance(error, MappingError):
                session["validationErrors"] = error.errors
                for name, errors in error.errors.items():
                    session["states"][name]["preflightErrors"] = errors
            save()
            # A resumed invocation may already own executions; validation cannot abandon them.
            run_group(units, limit, session["states"], backend, save, drain_only=True)
            raise
        for unit in units:
            state = session['states'][unit['name']]
            if state.get('repairs') and state['repairs'][-1].get('stage') in {'REPAIR_INTENT', 'VALIDATING', 'VALIDATED'} | BOOTSTRAP_STAGES:
                if not backend.repair(unit, state):
                    session['result'] = 'STOPPED'
                    save()
                    return 2
        session["result"] = run_session(units, limit, session, backend, save, args.pause_after_group)
        save()
        print(json.dumps(session, indent=2))
        return 2 if session["result"] == "STOPPED" else 0
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"CloudFormation controller: BLOCKED: {error}", file=sys.stderr)
        return 2
    finally:
        if persist is not None:
            persist()
        if lock is not None:
            lock.close()
            lock_path.unlink(missing_ok=True)
