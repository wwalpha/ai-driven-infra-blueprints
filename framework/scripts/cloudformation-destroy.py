#!/usr/bin/env python3
"""Destroy explicitly scoped CloudFormation stacks; never enter deploy validation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cloudformation_inputs import Blocked
from cloudformation_observed import destroy_plan, sync_destroyed
from issue_gate import require_target_no_issues
from model_core import stack_model
from model_files import load_model
from task_contract import task_path, status, require_writable, paths_in, matches
from validation_scope import active_scope


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def context_module():
    spec = importlib.util.spec_from_file_location("destroy_context", Path(__file__).with_name("check-deploy-context.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_plan(root, environment, directory, requested, check_scope=True):
    source = root / "model" / environment / directory / "cloudformation-stacks.properties"
    limit, stacks = stack_model(load_model(source).values)
    by_name = {stack["name"]: stack for _, stack in stacks}
    if not requested or len(set(requested)) != len(requested) or set(requested) - by_name.keys():
        raise Blocked("destroy scope must contain unique designed StackName values")
    units = [{"name": name, "deployOrder": int(by_name[name]["deployOrder"])} for name in sorted(requested)]
    observed = destroy_plan(root, environment, directory, sorted(requested), check_scope)
    return {"units": units, "maxConcurrentStacks": limit, "observed": observed}


def task_snapshot(root, environment, target, requested, plan):
    path = task_path(root)
    text = path.read_text(encoding="utf-8")
    if status(text, path.name == "active.md") != "running":
        raise Blocked("destroy requires a running task")
    required = ["- Task type: `infrastructure`", "- Infrastructure phase: `destroy`",
                "- AWS API execution: `allowed`", "- Destroy: `allowed`",
                f"- Target environment: `{environment}`", f"- Target AWS account: `{target['awsAccountId']}`"]
    if target.get("alias"):
        required.append(f"- Target alias: `{target['alias']}`")
    for line in required:
        if text.splitlines().count(line) != 1:
            raise Blocked(f"active task must explicitly contain {line}")
    scopes = [line for line in text.splitlines() if line.startswith("- Destroy scope:")]
    if len(scopes) != 1 or sorted(re.findall(r"`([^`]+)`", scopes[0])) != sorted(requested):
        raise Blocked("requested StackName scope must exactly match active task Destroy scope")
    scope = active_scope(root)
    services = {tuple(service.split("/")) for service in plan["observed"]["services"]}
    if scope is None or not services <= scope:
        raise Blocked("destroy requires explicit service Validation scope covering ownership and incoming references")
    paths = {root / value for value in plan["observed"]["paths"]} | {path}
    require_writable(root, paths)
    allowed = paths_in(text, "## Allowed paths")
    if any(not any(matches(file.relative_to(root).as_posix(), pattern) for pattern in allowed) for file in paths):
        raise Blocked("destroy observed outputs outside Allowed paths")
    return path, text


def issue_snapshot(root, environment, directory):
    path = root / "issues" / environment / directory / "issues.md"
    return fingerprint(path.read_text(encoding="utf-8") if path.exists() else None)


class AwsBackend:
    READS = {"describe-stacks", "list-exports", "list-imports", "describe-stack-events"}

    def __init__(self, root, environment, directory, target, profile=None, timing_log=None):
        self.root, self.environment, self.directory, self.target = root, environment, directory, target
        self.profile = target.get("awsProfile") or profile
        self.timing_log = timing_log
        self.env = os.environ.copy()  # Freeze the invocation's credential chain; never persist credentials.

    def aws(self, operation, *arguments):
        if operation not in self.READS | {"delete-stack"}:
            raise Blocked(f"operation outside standard destroy: {operation}")
        command = ["aws", "--region", self.target["awsRegion"]]
        if self.profile:
            command += ["--profile", self.profile]
        command += ["cloudformation", operation, *arguments, "--output", "json", "--no-cli-pager"]
        started = time.perf_counter()
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60, env=self.env)
            if result.returncode:
                # Only this exact CFN not-found diagnostic constitutes absence.
                if operation == "describe-stacks" and re.search(r"\(ValidationError\).*Stack with id .+ does not exist", result.stderr):
                    return None
                if operation == "list-imports" and re.search(
                        r"\(ValidationError\) when calling the ListImports operation: Export .+ is not imported by any stack\.?\s*$", result.stderr):
                    return {"Imports": []}
                raise Blocked(f"{operation}: {result.stderr.strip() or 'AWS CLI failed'}")
            return json.loads(result.stdout) if result.stdout.strip() else {}
        finally:
            if self.timing_log:
                with self.timing_log.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"phase": "awsApi", "operation": operation,
                                             "seconds": time.perf_counter() - started}) + "\n")

    def describe(self, identity):
        response = self.aws("describe-stacks", "--stack-name", identity)
        if response is None:
            return None
        stacks = response.get("Stacks", [])
        if len(stacks) != 1:
            raise Blocked("describe-stacks must return exactly one stack")
        return stacks[0]

    def delete(self, stack_id):
        return self.aws("delete-stack", "--stack-name", stack_id)

    def events(self, stack_id):
        # Stop at this deletion's root start, avoiding old retained events/history pages.
        events, arguments = [], []
        while True:
            response = self.aws("describe-stack-events", "--stack-name", stack_id, "--no-paginate", *arguments)
            page = response.get("StackEvents")
            if not isinstance(page, list):
                raise Blocked("invalid describe-stack-events response")
            for event in page:
                events.append(event)
                if (event.get("PhysicalResourceId") == stack_id and event.get("ResourceType") == "AWS::CloudFormation::Stack"
                        and event.get("ResourceStatus") == "DELETE_IN_PROGRESS"):
                    return events
            if not response.get("NextToken"):
                return events
            arguments = ["--next-token", response["NextToken"]]


def validate_identity(stack, name, target, pinned=None):
    identity = stack.get("StackId", "")
    parts = identity.split(":", 5)
    account = target.get("awsExecutionAccountId", target["awsAccountId"])
    if (len(parts) != 6 or parts[0] != "arn" or parts[2:5] != ["cloudformation", target["awsRegion"], account]
            or not re.fullmatch(r"stack/" + re.escape(name) + r"/[A-Za-z0-9-]+", parts[5])
            or stack.get("StackName") != name or pinned and identity != pinned):
        raise Blocked(f"Stack identity/account/region mismatch: {name}")
    if not isinstance(stack.get("StackStatus"), str):
        raise Blocked(f"StackStatus missing: {name}")
    return identity


def protection(stack, name):
    if stack.get("EnableTerminationProtection") is not False:
        raise Blocked(f"termination protection enabled or unknown: {name}")
    if stack.get("ParentId"):
        raise Blocked(f"nested stack direct target forbidden: {name}; request its parent in a separate scope")
    if stack.get("RootId") and stack["RootId"] != stack["StackId"]:
        raise Blocked(f"nested root identity mismatch: {name}")


def preflight(session, backend, limit, save):
    states = session["states"]
    # Fresh absence is terminal for this session; never adopt a later same-name creation.
    names = sorted(name for name, state in states.items() if state["status"] != "ALREADY_ABSENT")
    with ThreadPoolExecutor(max_workers=limit) as pool:
        results = list(pool.map(lambda name: backend.describe(states[name].get("StackId") or name), names))
    errors = []
    for name, stack in zip(names, results):
        state = states[name]
        try:
            evidence = state.get("deleteObserved") or state["status"] == "DELETE_IN_PROGRESS"
            if stack is not None:
                identity = validate_identity(stack, name, backend.target, state.get("StackId"))
            if stack is None or stack.get("StackStatus") == "DELETE_COMPLETE":
                state["status"] = "DELETE_COMPLETE" if evidence and state.get("StackId") else "ALREADY_ABSENT"
                if state["status"] == "DELETE_COMPLETE":
                    state["deleteObserved"] = True
                continue
            state.update(StackId=identity, StackStatus=stack["StackStatus"],
                         EnableTerminationProtection=stack.get("EnableTerminationProtection"),
                         ParentId=stack.get("ParentId"), RootId=stack.get("RootId"))
            if state["status"] == "DELETE_COMPLETE":
                raise Blocked(f"completed stack exists again: {name}")
            actual = stack["StackStatus"]
            if actual == "DELETE_IN_PROGRESS":
                state.update(status="DELETE_IN_PROGRESS", deleteObserved=True)
            elif actual == "DELETE_FAILED":
                state.update(status="DELETE_FAILED", reason=stack.get("StackStatusReason", actual))
                state["events"] = backend.events(identity)
                raise Blocked(f"DELETE_FAILED requires Human action: {name}")
            elif actual.endswith("_IN_PROGRESS"):
                raise Blocked(f"stack operation already in progress: {name}: {actual}")
            else:
                state["status"] = "NOT_STARTED"
            protection(stack, name)
            state["exportNames"] = sorted(output["ExportName"] for output in stack.get("Outputs", []) if output.get("ExportName"))
        except (ValueError, Blocked) as error:
            state["preflightError"] = str(error)
            errors.append(str(error))
    save()
    if errors:
        raise Blocked("; ".join(errors))


def dependencies(session, backend, save):
    states = session["states"]
    if "exports" not in session:
        # AWS CLI auto-pagination covers all pages in one logical list-exports call.
        exports = backend.aws("list-exports").get("Exports")
        if (not isinstance(exports, list) or any(not isinstance(export, dict) or
                not all(isinstance(export.get(key), str) and export[key] for key in ("Name", "ExportingStackId")) for export in exports)
                or len({export["Name"] for export in exports}) != len(exports)):
            raise Blocked("invalid list-exports response; cannot prove dependencies")
        session["exports"] = [{key: export[key] for key in ("Name", "ExportingStackId")}
                              for export in exports
                              if export.get("ExportingStackId") in {state.get("StackId") for state in states.values()}]
        save()
    else:
        # Reuse the single export snapshot only when current scoped Outputs prove it unchanged.
        for name, state in states.items():
            if state["status"] in {"DELETE_COMPLETE", "ALREADY_ABSENT"}:
                continue
            expected = sorted(export["Name"] for export in session["exports"] if export["ExportingStackId"] == state.get("StackId"))
            if expected != state.get("exportNames", []):
                raise Blocked(f"export snapshot changed on resume: {name}; require a new session")
    owners = {state.get("StackId"): name for name, state in states.items() if state.get("StackId")}
    snapshot, errors = [], []
    for export in session["exports"]:
        producer = owners[export["ExportingStackId"]]
        if states[producer]["status"] in {"DELETE_COMPLETE", "ALREADY_ABSENT"}:
            continue
        imports = backend.aws("list-imports", "--export-name", export["Name"]).get("Imports")
        if not isinstance(imports, list) or any(not isinstance(name, str) or not name for name in imports):
            raise Blocked("invalid list-imports response; cannot prove dependencies")
        snapshot.append({"export": export["Name"], "producer": producer, "importers": imports})
        for consumer in imports:
            if consumer not in states or states[consumer]["status"] in {"DELETE_COMPLETE", "ALREADY_ABSENT"}:
                errors.append(f"importer outside live destroy scope: {consumer} imports {export['Name']}")
            elif states[consumer]["DeployOrder"] <= states[producer]["DeployOrder"]:
                errors.append(f"actual import dependency conflicts with designed DeployOrder: {consumer} -> {producer}")
    session["dependencySnapshot"] = snapshot
    save()
    if errors:
        raise Blocked("; ".join(errors))


def poll(name, state, backend):
    stack = backend.describe(state["StackId"])
    if stack is None:
        return "DELETE_COMPLETE" if state.get("deleteObserved") else "ALREADY_ABSENT", None
    validate_identity(stack, name, backend.target, state["StackId"])
    return stack["StackStatus"], stack.get("StackStatusReason")


def run_session(session, backend, limit, save, guard, sleep=time.sleep, drain_only=False):
    """Poll all active peers before freeing slots; never advance a failed group."""
    states = session["states"]
    stopped = drain_only or any(state["status"] == "DELETE_FAILED" for state in states.values())
    for order in sorted({state["DeployOrder"] for state in states.values()}, reverse=True):
        group = [name for name in sorted(states) if states[name]["DeployOrder"] == order]
        while True:
            active = [name for name in group if states[name]["status"] == "DELETE_IN_PROGRESS"]
            def read(name):
                try:
                    return name, poll(name, states[name], backend), None
                except Exception as error:
                    return name, None, str(error)
            with ThreadPoolExecutor(max_workers=limit) as pool:
                results = list(pool.map(read, active))
            unavailable = False
            for name, result, error in results:
                state = states[name]
                if error:
                    stopped = True
                    state["pollError"] = error
                    state["readFailures"] = state.get("readFailures", 0) + 1
                    unavailable |= state["readFailures"] >= 3
                    continue
                state.pop("pollError", None)
                state["readFailures"] = 0
                actual, reason = result
                state["StackStatus"] = actual
                if actual == "DELETE_IN_PROGRESS":
                    state["deleteObserved"] = True
                elif actual == "DELETE_COMPLETE":
                    state["status"] = actual
                else:
                    stopped = True
                    state.update(status="DELETE_FAILED" if actual == "DELETE_FAILED" else "BLOCKED", reason=reason or actual)
                if state["status"] in {"DELETE_COMPLETE", "DELETE_FAILED"}:
                    try:
                        state["events"] = backend.events(state["StackId"])
                        state["retained"] = [event for event in state["events"] if event.get("ResourceStatus") == "DELETE_SKIPPED"]
                    except Exception as error:
                        # Destruction proof is independent of diagnostics availability.
                        state["eventsError"] = str(error)
            save()
            if unavailable:
                session["reason"] = "read access unavailable; running stacks require resume/drain"
                return "BLOCKED"
            active = [name for name in group if states[name]["status"] == "DELETE_IN_PROGRESS"]
            if not stopped:
                for name in group:
                    if states[name]["status"] != "NOT_STARTED" or len(active) >= limit:
                        continue
                    state = states[name]
                    try:
                        guard(name, state)
                        stack = backend.describe(state["StackId"])
                        if stack is None:
                            state["status"] = "ALREADY_ABSENT"
                            continue
                        validate_identity(stack, name, backend.target, state["StackId"])
                        protection(stack, name)
                        if stack["StackStatus"].endswith("_IN_PROGRESS") or stack["StackStatus"] in {"DELETE_COMPLETE", "DELETE_FAILED"}:
                            raise Blocked(f"stack state changed before delete: {name}: {stack['StackStatus']}")
                        state["status"] = "DELETE_INTENT"
                        save()  # Durable identity/intent before mutation; intent alone never proves deletion.
                        backend.delete(state["StackId"])
                        state.update(status="DELETE_IN_PROGRESS", deleteObserved=True)
                        active.append(name)
                        save()
                    except Exception as error:
                        stopped = True
                        state.update(status="BLOCKED", reason=str(error))
                        # A timed-out DeleteStack may have been accepted; inspect and drain the pinned ID.
                        try:
                            actual, _ = poll(name, state, backend)
                            if actual == "DELETE_IN_PROGRESS":
                                state.update(status=actual, deleteObserved=True)
                        except Exception as read_error:
                            state["pollError"] = str(read_error)
                        save()
                        break
            active = [name for name in group if states[name]["status"] == "DELETE_IN_PROGRESS"]
            if not active:
                break
            sleep(5)
        if stopped:
            # Also drain pre-existing running stacks in lower groups, without starting new deletes.
            continue
    return "BLOCKED" if stopped else "COMPLETE"


def controller_main(argv=None, root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--alias")
    selector.add_argument("--aws-account-id")
    parser.add_argument("--stack", action="append", required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sequential", action="store_true")
    parser.add_argument("--local-plan", action="store_true", help="local JSON ownership/reservation plan; no AWS calls")
    parser.add_argument("--timing-log", type=Path)
    args = parser.parse_args(argv)
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    session, lock, save = None, None, None
    try:
        context = context_module()
        target = context.load_target(root, args.environment, args.aws_account_id, args.alias)
        if target["iacEngine"] != "cloudformation":
            raise Blocked("destroy requires CloudFormation target")
        directory = args.alias or args.aws_account_id
        plan = local_plan(root, args.environment, directory, args.stack, check_scope=not args.local_plan)
        if args.local_plan:
            print(json.dumps({"target": target, "directory": directory, **plan}, indent=2))
            return 0
        contract_path, contract = task_snapshot(root, args.environment, target, args.stack, plan)
        if not args.state or args.state.resolve().is_relative_to(root):
            raise Blocked("destroy requires --state outside repository")
        state_path = args.state.resolve()
        if args.timing_log and args.timing_log.resolve().is_relative_to(root):
            raise Blocked("timing log must be outside repository")
        limit = 1 if args.sequential else plan["maxConcurrentStacks"]
        identity = {"repository": str(root), "environment": args.environment, "target": target,
                    "profile": target.get("awsProfile") or args.profile, "scope": sorted(args.stack),
                    "profileIdentity": target.get("awsProfile") or args.profile or os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE") or "default credential chain",
                    "limit": limit, "taskFile": contract_path.relative_to(root).as_posix(), "plan": plan}
        immutable = fingerprint(identity)
        if args.resume:
            session = json.loads(state_path.read_text(encoding="utf-8"))
            if session.get("version") != 1 or session.get("identity") != identity:
                raise Blocked("destroy session target/profile/scope/ownership/reservations changed")
        else:
            if state_path.exists():
                raise Blocked("new destroy session requires unused state path")
            session = {"version": 1, "identity": identity, "states": {
                unit["name"]: {"StackName": unit["name"], "DeployOrder": unit["deployOrder"],
                               "status": "NOT_STARTED", "observedSynced": False} for unit in plan["units"]}}
        if set(session["states"]) != set(args.stack):
            raise Blocked("saved StackName scope changed")
        for unit in plan["units"]:
            state = session["states"][unit["name"]]
            if state.get("StackName") != unit["name"] or state.get("DeployOrder") != unit["deployOrder"]:
                raise Blocked("saved stack identity/DeployOrder changed")
            if state.get("StackId"):
                validate_identity({"StackName": unit["name"], "StackId": state["StackId"],
                                   "StackStatus": state["status"]}, unit["name"], target)
        # Share deploy's target lock; do not run deploy code or its guard.
        lock_target = {key: value for key, value in target.items() if key != "awsProfile"}
        lock_path = Path(tempfile.gettempdir()) / ("blueprint-cfn-" + fingerprint([args.environment, lock_target]) + ".lock")
        lock = lock_path.open("x")
        def persist():
            temporary = state_path.with_suffix(state_path.suffix + ".tmp")
            temporary.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
            temporary.replace(state_path)
        save = persist
        save()
        started = time.perf_counter()
        authenticated = context.check_deploy_context(root, args.environment, args.aws_account_id, args.alias,
                                                    args.profile, read_only=True)
        if authenticated != target:
            raise Blocked("AWS context changed during authentication")
        if args.timing_log:
            with args.timing_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"phase": "authenticationContext", "seconds": time.perf_counter() - started}) + "\n")
        backend = AwsBackend(root, args.environment, directory, target, args.profile, args.timing_log)
        session["context"] = {"account": target.get("awsExecutionAccountId", target["awsAccountId"]),
                              "region": target["awsRegion"], "profile": backend.profile}
        issue_digest = issue_snapshot(root, args.environment, directory)
        pinned = {}
        def guard(name, state):
            # Only cheap invariants: no templates, infra manifests or validation tree digests.
            if contract_path.read_text(encoding="utf-8") != contract or status(contract) != "running":
                raise Blocked("selected active task changed before mutation")
            if context.load_target(root, args.environment, args.aws_account_id, args.alias) != target:
                raise Blocked("project target/account/region/profile changed before mutation")
            if issue_snapshot(root, args.environment, directory) != issue_digest:
                raise Blocked("issue gate snapshot changed before mutation")
            if fingerprint(session["identity"]) != immutable or name not in identity["scope"]:
                raise Blocked("session scope changed before mutation")
            if state["StackId"] != pinned.get(name):
                raise Blocked("pinned StackId changed before mutation")
            validate_identity({"StackName": name, "StackId": state["StackId"], "StackStatus": state["StackStatus"]}, name, target)
        try:
            preflight(session, backend, limit, save)
            pinned = {name: state.get("StackId") for name, state in session["states"].items()}
            dependencies(session, backend, save)
            require_target_no_issues(root, (args.environment, directory))  # Once before the first mutation.
            if issue_snapshot(root, args.environment, directory) != issue_digest:
                raise Blocked("issue list changed during preflight")
            session.pop("reason", None)
            session["status"] = run_session(session, backend, limit, save, guard)
        except Exception as error:
            session["reason"] = str(error)
            session["status"] = run_session(session, backend, limit, save, guard, drain_only=True)
        finally:
            sync_destroyed(backend, session["states"], plan["observed"])
            save()
        if session["status"] == "COMPLETE":
            # The workflow owns exactly one final scoped local loop, never a full regression here.
            session["completion"] = "Run blueprint-loop.py --mode task --task-file " + identity["taskFile"]
        save()
        print(json.dumps(session, indent=2))
        return 0 if session["status"] == "COMPLETE" else 1
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        if session is not None and save:
            session.update(status="BLOCKED", reason=str(error))
            save()
        print(f"Destroy: BLOCKED: {error}", file=sys.stderr)
        return 1
    finally:
        if lock:
            lock.close()
            lock_path.unlink()


if __name__ == "__main__":
    raise SystemExit(controller_main())
