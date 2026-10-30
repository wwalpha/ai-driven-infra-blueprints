"""Only unresolved AWS submissions are shared across Tasks and Worktrees."""

import json
import uuid

from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked
from utils.file_operations import atomic_replace_file
from utils.json_format import fingerprint

from deploy import current_state
from deploy import operation_journal as journal

TOKENS = {
    "create_change_set": "ClientToken",
    "execute_change_set": "ClientRequestToken",
    "delete_stack": "ClientRequestToken",
    "continue_update_rollback": "ClientRequestToken",
    "put_secret_value": "ClientRequestToken",
    "update_secret_version_stage": "MoveToVersionId",
}


def location(target, name):
    return journal.location(target).parent / ("request-" + fingerprint(name) + ".json")


def read(path):
    if not path.exists():
        return None
    journal.private_path(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(record, dict)
        or record.get("operation") not in TOKENS
        or not record.get("token")
    ):
        raise Blocked("current Stack request is unreadable: " + str(path))
    return record


def owns(state, record):
    operation = record.get("operation")
    if operation == "delete_stack":
        return state.get("cleanupStatus") == "DELETE_INTENT" and state.get(
            "cleanupStackId"
        ) == record.get("stackId")
    if record.get("service") == "secretsmanager":
        bootstrap = state.get("bootstrap", {})
        return bootstrap.get("secretId") == record.get("resourceId") and bootstrap.get(
            "clientRequestToken"
        ) == record.get("token")
    token = "preparationId" if operation == "create_change_set" else "clientToken"
    return bool(
        record.get("token")
        and state.get(token) == record["token"]
        and current_state.same_change_set(
            state.get("changeSetId"), record.get("changeSetId")
        )
    )


def root_events(events, token, identity):
    return [
        event
        for event in events
        if identity
        and event.get("ResourceType") == "AWS::CloudFormation::Stack"
        and event.get("ClientRequestToken") == token
        and event.get("StackId") == identity
        and event.get("PhysicalResourceId") == identity
    ]


def settled(aws, record, current):
    operation = record["operation"]
    status = current["StackStatus"]
    if record.get("service") == "secretsmanager":
        metadata = aws(
            "describe_secret", SecretId=record["resourceId"], service="secretsmanager"
        )
        stages = metadata.get("VersionIdsToStages", {}).get(record["token"])
        # Bootstrap never removes another version's current label, so external repair supersedes it.
        return stages is not None and (
            operation == "put_secret_value"
            or any(
                "AWSCURRENT" in labels
                for labels in metadata.get("VersionIdsToStages", {}).values()
            )
        )
    if operation in {"create_change_set", "execute_change_set"}:
        change_set = aws(
            "describe_change_set",
            StackName=record["name"],
            ChangeSetName=record["changeSetId"],
        )
        identity = change_set.get("ChangeSetId", "")
        same_change = current_state.same_change_set(record["changeSetId"], identity)
        if (
            not same_change
            or record.get("stackId")
            and change_set.get("StackId") != record["stackId"]
        ):
            raise Blocked("current request ChangeSet/Stack identity differs")
        if operation == "create_change_set":
            return change_set.get("Status") in {
                "CREATE_COMPLETE",
                "FAILED",
                "DELETE_COMPLETE",
            }
        execution = change_set.get("ExecutionStatus")
        if operation == "execute_change_set" and execution in {
            "EXECUTE_FAILED",
            "OBSOLETE",
        }:
            record["result"] = "FAIL"
            return True
        if (
            operation == "execute_change_set"
            and execution == "EXECUTE_COMPLETE"
            and current_state.category(current) not in {"RUNNING", "UNKNOWN", "REVIEW"}
            and (
                not record.get("before")
                or current_state.identity(current) != record["before"]
            )
        ):
            record["result"] = "SETTLED"
            return True
    if operation == "delete_stack" and status == "ABSENT":
        return True
    events = current_state.pages(
        aws,
        "describe_stack_events",
        "StackEvents",
        StackName=record.get("stackId") or record["name"],
    )
    matches = root_events(
        events, record["token"], record.get("stackId") or current.get("StackId")
    )
    if matches:
        terminal = matches[0].get("ResourceStatus")
        if terminal in {"CREATE_FAILED", "UPDATE_FAILED"} and status != terminal:
            return False
        if terminal in current_state.SUCCESS | current_state.FAILED:
            record["result"] = "FAIL" if terminal in current_state.FAILED else "SETTLED"
            return True
        return False
    return False


def reconcile(backend, unit, state=None):
    name = unit["name"]
    path = location(backend.target, name)
    state = backend.states[name] if state is None else state
    with journal.locked(path):
        record = None
        try:
            record = read(path)
            if record and record.get("name") != name:
                raise Blocked("current request belongs to another Stack")
            if record and settled(backend.aws, record, state["currentStack"]):
                if record.get("result") == "FAIL" and owns(state, record):
                    state["failureDetected"] = True
                path.unlink()
                record = None
            state.pop("requestError", None)
            return record
        except AwsError as error:
            if (
                record
                and record["operation"] == "create_change_set"
                and error.code == "ChangeSetNotFound"
            ):
                state["createUnconfirmed"] = True
                state.pop("requestError", None)
                return record
            state["requestError"] = str(error)
            return {"uncertain": True}
        except (OSError, ValueError, KeyError, TypeError, Blocked) as error:
            state["requestError"] = str(error)
            return {"uncertain": True}


def send(
    runtime,
    operation,
    arguments,
    transport,
    *,
    service="cloudformation",
    stack_name=None,
):
    if service == "secretsmanager" and (
        not isinstance(arguments.get(TOKENS[operation]), str)
        or not arguments[TOKENS[operation]]
    ):
        raise Blocked("Secret bootstrap needs its original version token")
    if (
        service == "secretsmanager"
        and operation == "update_secret_version_stage"
        and (
            arguments.get("VersionStage") != "AWSCURRENT"
            or arguments.get("RemoveFromVersionId") is not None
        )
    ):
        raise Blocked("initial bootstrap never moves another version's staging label")
    name = (stack_name or arguments["StackName"]).split(":stack/")[-1].split("/")[0]
    path = location(runtime.target, name)
    with journal.locked(path):
        current = current_state.read(runtime.aws, name)
        prior = read(path)
        if prior and prior.get("name") != name:
            raise Blocked("current request belongs to another Stack")
        if prior:
            try:
                confirmed = settled(runtime.aws, prior, current)
            except AwsError as error:
                if (
                    prior["operation"] != "create_change_set"
                    or error.code != "ChangeSetNotFound"
                ):
                    raise
                confirmed = False
            if confirmed:
                path.unlink()
                prior = None
        created = prior is None
        if prior:
            same = (
                operation == prior["operation"]
                or service == "secretsmanager"
                and prior.get("service") == service
                and prior.get("submission") == "UNCERTAIN"
            ) and (
                service == "cloudformation"
                and (
                    operation in {"create_change_set", "execute_change_set"}
                    and arguments.get("ChangeSetName") == prior["changeSetId"]
                    and (
                        operation != "create_change_set"
                        or arguments.get("ClientToken") == prior["token"]
                    )
                    or operation in {"delete_stack", "continue_update_rollback"}
                )
                or service == "secretsmanager"
                and arguments.get("SecretId") == prior.get("resourceId")
                and arguments.get(TOKENS[operation]) == prior["token"]
            )
            if not same:
                raise Blocked("current request is unresolved for Stack: " + name)
            if prior["operation"] != operation:
                prior.update(operation=operation, submission="SENDING")
                atomic_replace_file(path, json.dumps(prior), fsync=True, mode=0o600)
            arguments[TOKENS[operation]] = prior["token"]
            if operation in {"delete_stack", "continue_update_rollback"} and prior.get(
                "stackId"
            ):
                arguments["StackName"] = prior["stackId"]
        else:
            if current_state.category(current) in {"RUNNING", "UNKNOWN"}:
                raise Blocked("current Stack cannot accept a new request: " + name)
            token = arguments.setdefault(TOKENS[operation], uuid.uuid4().hex)
            prior = {
                "operation": operation,
                "service": service,
                "resourceId": arguments.get("SecretId"),
                "name": name,
                "stackId": current.get("StackId"),
                "changeSetId": arguments.get("ChangeSetName"),
                "token": token,
                "submission": "SENDING",
                "before": current_state.identity(current),
            }
            atomic_replace_file(path, json.dumps(prior), fsync=True, mode=0o600)
        try:
            response = transport(runtime, service, operation, arguments)
        except AwsError as error:
            if created and error.code in {
                "AccessDenied",
                "AccessDeniedException",
                "ValidationError",
                "InsufficientCapabilitiesException",
                "InvalidRequestException",
                "InvalidParameterException",
                "InvalidChangeSetStatus",
                "ChangeSetNotFound",
                "ResourceNotFoundException",
            }:
                # Structured rejection proves this call was not accepted; unknown transport retains intent.
                path.unlink()
            raise
        if service == "secretsmanager":
            path.unlink()
            return response
        prior.update(submission="SENT")
        if operation == "create_change_set":
            prior.update(
                stackId=response.get("StackId"),
                changeSetId=response.get("Id", prior["changeSetId"]),
            )
        atomic_replace_file(path, json.dumps(prior), fsync=True, mode=0o600)
        return response


def cutover(backend, path):
    """One-time legacy conversion under the old controller lock; keep raw originals."""
    if not path.exists():
        atomic_replace_file(
            path, json.dumps({"protocol": "current-request-v2"}), fsync=True, mode=0o600
        )
        return
    journal.private_path(path)
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeError):
        document = {}
    if document == {"protocol": "current-request-v2"}:
        return
    backup = path.with_name("legacy-" + fingerprint(raw.hex()) + ".bin")
    if backup.exists():
        journal.private_path(backup)
        if backup.read_bytes() != raw:
            raise Blocked("legacy original backup changed")
    atomic_replace_file(backup, raw, fsync=True, mode=0o600)
    payload = document.get("payload", {}) if isinstance(document, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    peers = payload.get("peers", [])
    for record in [payload, *(peers if isinstance(peers, list) else [])]:
        if not isinstance(record, dict) or not isinstance(
            record.get("operations", {}), dict
        ):
            continue
        for name, operation in record.get("operations", {}).items():
            if not isinstance(operation, dict) or not isinstance(
                operation.get("state", {}), dict
            ):
                continue
            state = operation.get("state", {})
            bootstrap = state.get("bootstrap", {})
            if (
                isinstance(bootstrap, dict)
                and bootstrap.get("stage") == "PUT_SUBMITTED"
                and isinstance(bootstrap.get("owner"), dict)
            ):
                owner = bootstrap["owner"].get("stack")
                if isinstance(owner, str) and owner:
                    destination = location(backend.target, owner)
                    if not destination.exists():
                        atomic_replace_file(
                            destination,
                            json.dumps(
                                {
                                    "operation": "update_secret_version_stage",
                                    "service": "secretsmanager",
                                    "resourceId": bootstrap.get("secretId"),
                                    "name": owner,
                                    "stackId": bootstrap["owner"].get("stackId"),
                                    "changeSetId": None,
                                    "token": bootstrap.get("clientRequestToken", ""),
                                    "submission": "UNCERTAIN",
                                    "before": {},
                                }
                            ),
                            fsync=True,
                            mode=0o600,
                        )

            kind = (
                "delete_stack"
                if state.get("cleanupStatus") == "DELETE_INTENT"
                else "execute_change_set"
                if state.get("status") == "RUNNING"
                else "create_change_set"
                if state.get("status") == "CHANGESET_CREATING"
                else None
            )
            if kind is None:
                continue
            destination = location(backend.target, name)
            if destination.exists():
                continue
            request = {
                "operation": kind,
                "name": name,
                "stackId": state.get("stackId"),
                "changeSetId": state.get("changeSetId"),
                "token": state.get("clientToken") or state.get("preparationId") or "",
                "submission": "UNCERTAIN",
                "before": {},
            }
            atomic_replace_file(
                destination, json.dumps(request), fsync=True, mode=0o600
            )
    # Older controllers reject this format before mutation; no parallel protocol remains.
    atomic_replace_file(
        path, json.dumps({"protocol": "current-request-v2"}), fsync=True, mode=0o600
    )
