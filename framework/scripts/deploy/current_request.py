"""Only unresolved AWS submissions are shared across Tasks and Worktrees."""

import copy
import json
import uuid

from utils.aws.client import AwsError
from utils.aws_sdk import aws_runtime
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
    if not path.exists() and not path.is_symlink():
        return None
    journal.private_path(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(record, dict)
        or record.get("operation") not in TOKENS
        or not isinstance(record.get("token"), str)
        or not record["token"]
        or not isinstance(record.get("name"), str)
        or not record["name"]
        or record.get("stackId") is not None
        and not isinstance(record["stackId"], str)
        or record.get("service", "cloudformation")
        not in {"cloudformation", "secretsmanager"}
        or (
            record.get("operation")
            in {"put_secret_value", "update_secret_version_stage"}
        )
        != (record.get("service") == "secretsmanager")
        or record.get("operation") in {"create_change_set", "execute_change_set"}
        and not isinstance(record.get("changeSetId"), str)
        or record.get("service") == "secretsmanager"
        and not isinstance(record.get("resourceId"), str)
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
        and (
            operation != "execute_change_set"
            or state.get("executionEvidence", {}).get("StackId")
            and (
                not record.get("stackId")
                or state["executionEvidence"]["StackId"] == record["stackId"]
            )
        )
        and current_state.same_change_set(
            state.get("changeSetId"), record.get("changeSetId")
        )
        and (
            operation == "create_change_set"
            or not state.get("executionEvidence", {}).get("clientToken")
            or state["executionEvidence"]["clientToken"] == record.get("token")
        )
        and (
            operation == "create_change_set"
            or not state.get("executionEvidence", {}).get("ChangeSetId")
            or current_state.same_change_set(
                state["changeSetId"], state["executionEvidence"]["ChangeSetId"]
            )
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
    """Prove completion or loss of effect on the current target, never infer success."""
    operation = record["operation"]
    if record.get("service") == "secretsmanager":
        metadata = aws(
            "describe_secret", SecretId=record["resourceId"], service="secretsmanager"
        )
        versions = metadata.get("VersionIdsToStages")
        if not isinstance(versions, dict) or any(
            not isinstance(labels, list) for labels in versions.values()
        ):
            raise Blocked("Secret version evidence is incomplete")
        labels = versions.get(record["token"])
        confirmed = labels is not None and (
            operation == "put_secret_value"
            or "AWSCURRENT" in labels
            or any("AWSCURRENT" in stages for stages in versions.values())
        )
        if confirmed:
            record["trackingReason"] = "SECRET_VERSION_CONFIRMED"
        return confirmed
    pinned = operation in {
        "execute_change_set",
        "delete_stack",
        "continue_update_rollback",
    }
    identity = record.get("stackId")
    if pinned and identity:
        if (
            current.get("StackId")
            and current["StackId"] != identity
            and current_state.category(current) != "UNKNOWN"
        ):
            record.update(result="SETTLED", trackingReason="ORIGINAL_STACK_REPLACED")
            return True
        if current["StackStatus"] in {"ABSENT", "DELETE_COMPLETE"}:
            original = current_state.read(aws, identity)
            if original.get("StackId") not in {None, identity}:
                raise Blocked("original StackId observation differs")
            if original["StackStatus"] in {"ABSENT", "DELETE_COMPLETE"}:
                record.update(
                    result="SETTLED",
                    trackingReason="ORIGINAL_STACK_DELETED",
                    originalStack=current_state.observation(original),
                )
                return True
            return False
        if current_state.category(current) in {"UNKNOWN", "RUNNING"}:
            return False
    if operation == "execute_change_set" and current["StackStatus"] not in (
        current_state.SUCCESS | current_state.FAILED
    ) - {"CREATE_FAILED", "UPDATE_FAILED"}:
        return False
    if operation in {"create_change_set", "execute_change_set"}:
        try:
            change_set = aws(
                "describe_change_set",
                StackName=record["name"]
                if operation == "create_change_set"
                else identity or record["name"],
                ChangeSetName=record["changeSetId"],
            )
        except AwsError as error:
            if error.code != "ChangeSetNotFound":
                raise
            change_set = None
        if change_set is not None:
            if (
                not current_state.same_change_set(
                    record["changeSetId"], change_set.get("ChangeSetId")
                )
                or identity
                and change_set.get("StackId") != identity
            ):
                raise Blocked("current request ChangeSet/Stack identity differs")
            if operation == "create_change_set":
                confirmed = change_set.get("Status") in {
                    "CREATE_COMPLETE",
                    "FAILED",
                    "DELETE_COMPLETE",
                }
                if confirmed:
                    record["trackingReason"] = "CHANGESET_CREATION_ENDED"
                return confirmed
            execution = change_set.get("ExecutionStatus")
            if identity and execution in {
                "EXECUTE_COMPLETE",
                "EXECUTE_FAILED",
                "OBSOLETE",
            }:
                record.update(
                    result="SETTLED", trackingReason="CHANGESET_EXECUTION_ENDED"
                )
                return True
        if operation == "create_change_set":
            record["createUnconfirmed"] = True
            return False  # Recover only the original StackName/input/ChangeSet/token request.
    if not identity or current_state.category(current) in {
        "RUNNING",
        "UNKNOWN",
        "REVIEW",
    }:
        return False
    events = current_state.pages(
        aws, "describe_stack_events", "StackEvents", StackName=identity
    )
    matches = root_events(events, record["token"], identity)
    if matches:
        terminal = matches[0].get("ResourceStatus")
        if terminal in (current_state.SUCCESS | current_state.FAILED) - {
            "CREATE_FAILED",
            "UPDATE_FAILED",
        }:
            record.update(
                result="FAIL" if terminal in current_state.FAILED else "SUCCESS",
                attemptStatus=terminal,
                trackingReason="TOKEN_ROOT_EVENT",
            )
            return True
    return False


def saved_request(name, state):
    evidence = state.get("executionEvidence", {})
    if (
        state.get("clientToken")
        and state.get("changeSetId")
        and evidence.get("StackId")
    ):
        return {
            "operation": "execute_change_set",
            "service": "cloudformation",
            "resourceId": None,
            "name": name,
            "stackId": evidence["StackId"],
            "changeSetId": state["changeSetId"],
            "token": state["clientToken"],
        }
    return None


def end_tracking(state, record):
    """The caller saves this evidence before releasing only the matching shared request."""
    if not record.get("settled") or not record.get("trackingReason"):
        raise Blocked("request tracking has no completion evidence")
    owned = owns(state, record)
    if owned and record["operation"] == "execute_change_set":
        result = record.get("result", "SETTLED")
        current_state.record_attempt(
            state,
            {"SUCCESS": "ATTEMPT_SUCCESS", "FAIL": "ATTEMPT_FAIL"}.get(
                result, "ATTEMPT_SETTLED"
            ),
        )
        state["endedRequest"] = {
            "request": copy.deepcopy(record),
            "executionEvidence": copy.deepcopy(state.get("executionEvidence", {})),
            "result": state.get(
                "attemptResult", "SUCCESS" if state["status"] == "SUCCESS" else "FAIL"
            ),
        }
        for key in (
            "clientToken",
            "changeSetId",
            "preparationId",
            "executionEvidence",
            "settledRequest",
            "executionStarted",
        ):
            state.pop(key, None)
    else:
        if not state.get("endedRequest"):
            state["endedRequest"] = {
                "request": copy.deepcopy(record),
                "result": "UNKNOWN",
            }
    state["requestPending"] = bool(record.get("otherPending"))
    state.pop("requestError", None)


def reconcile(backend, unit, state=None):
    name = unit["name"]
    path = location(backend.target, name)
    state = backend.states[name] if state is None else state
    with journal.locked(path):
        record = None
        try:
            record = read(path)
            if record:
                record.pop("settled", None)
            if record and record.get("name") != name:
                raise Blocked("current request belongs to another Stack")
            original = saved_request(name, state)
            if original and (not record or not owns(state, record)):
                if settled(backend.aws, original, state["currentStack"]):
                    original.update(settled=True, otherPending=bool(record))
                    state.pop("requestError", None)
                    return original
                if record:
                    raise Blocked(
                        "original execution is unconfirmed and another current request exists"
                    )
                record = original
            if record:
                shared = dict(record)
                evidence = dict(record)
                if (
                    record["operation"] == "execute_change_set"
                    and not record.get("stackId")
                    and owns(state, record)
                ):
                    evidence["stackId"] = state["executionEvidence"]["StackId"]
                confirmed = settled(backend.aws, evidence, state["currentStack"])
                record = evidence
                if confirmed:
                    record["settled"] = True
                    if evidence.get("stackId") != shared.get("stackId"):
                        record["releaseIdentity"] = shared
            if record and record.get("createUnconfirmed"):
                state["createUnconfirmed"] = True
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


def release(backend, record):
    path = location(backend.target, record["name"])
    with journal.locked(path):
        current = read(path)
        keys = (
            "name",
            "operation",
            "service",
            "resourceId",
            "stackId",
            "changeSetId",
            "token",
        )
        identity = record.get("releaseIdentity", record)
        if current and all(
            current.get(key, "cloudformation" if key == "service" else None)
            == identity.get(key, "cloudformation" if key == "service" else None)
            for key in keys
        ):
            path.unlink()


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
                prior["settled"] = True
                if name not in runtime.states:
                    raise Blocked(
                        "settled request needs durable progress before release"
                    )
                state = runtime.states[name]
                transition = False
                if (
                    operation == "execute_change_set"
                    and prior["operation"] == "create_change_set"
                ):
                    change_set = runtime.aws(
                        "describe_change_set",
                        StackName=name,
                        ChangeSetName=prior["changeSetId"],
                    )
                    evidence = state.get("executionEvidence", {})
                    stack_arn = str(state.get("stackId") or "").split(":", 5)
                    change_arn = str(state.get("changeSetId") or "").split(":", 5)
                    region = runtime.target.get("awsRegion")
                    account = runtime.target.get(
                        "awsExecutionAccountId"
                    ) or runtime.target.get("awsAccountId")
                    partition = (
                        aws_runtime().sdk_session().get_partition_for_region(region)
                        if region
                        else None
                    )
                    transition = bool(
                        partition
                        and account
                        and len(stack_arn) == len(change_arn) == 6
                        and stack_arn[:5]
                        == change_arn[:5]
                        == ["arn", partition, "cloudformation", region, account]
                        and stack_arn[5].startswith("stack/" + name + "/")
                        and len(stack_arn[5].split("/")) == 3
                        and bool(stack_arn[5].split("/")[2])
                        and change_arn[5].startswith("changeSet/")
                        and len(change_arn[5].split("/")) == 3
                        and all(change_arn[5].split("/")[1:])
                        and prior["token"] == state.get("preparationId")
                        and current_state.same_change_set(
                            prior["changeSetId"], state.get("changeSetId")
                        )
                        and change_set.get("ChangeSetId") == state.get("changeSetId")
                        and change_set.get("StackId") == state.get("stackId")
                        and current.get("StackId") == state.get("stackId")
                        and (
                            not prior.get("stackId")
                            or prior["stackId"] == state.get("stackId")
                        )
                        and change_set.get("Status") == "CREATE_COMPLETE"
                        and change_set.get("ExecutionStatus") == "AVAILABLE"
                        and state.get("approvedChangeDigest")
                        and state["approvedChangeDigest"] == state.get("changeDigest")
                        and fingerprint(change_set.get("Changes", []))
                        == state["changeDigest"]
                        and evidence.get("StackId")
                        == arguments.get("StackName")
                        == state.get("stackId")
                        and evidence.get("ChangeSetId")
                        == arguments.get("ChangeSetName")
                        == state.get("changeSetId")
                        and evidence.get("clientToken")
                        and evidence.get("clientToken")
                        == arguments.get("ClientRequestToken")
                        == state.get("clientToken")
                        and evidence.get("clientToken") != prior["token"]
                        and evidence.get("changeDigest") == state["changeDigest"]
                        and evidence.get("inputDigest")
                    )
                ended = state.get("endedRequest")
                previous = ended.get("request", {}) if ended else {}
                previous_evidence = ended.get("executionEvidence", {}) if ended else {}
                completed_execution = (
                    previous.get("operation") == "execute_change_set"
                    and previous.get("settled")
                    and previous.get("trackingReason")
                    and ended.get("result") in {"SUCCESS", "FAIL"}
                    and previous.get("result") == ended["result"]
                    and previous.get("stackId")
                    and previous.get("stackId") == previous_evidence.get("StackId")
                    and previous.get("changeSetId")
                    and previous.get("changeSetId")
                    == previous_evidence.get("ChangeSetId")
                    and previous.get("token")
                    and previous.get("token") == previous_evidence.get("clientToken")
                    and previous_evidence.get("inputDigest")
                )
                completed_cleanup = (
                    previous.get("operation") == "delete_stack"
                    and previous.get("settled") is True
                    and previous.get("trackingReason") == "ORIGINAL_STACK_DELETED"
                    and previous.get("result") == "SETTLED"
                    and previous.get("name") == name
                    and previous.get("stackId")
                    and previous["stackId"] != state.get("stackId")
                    and previous.get("token")
                    and previous.get("originalStack", {}).get("StackStatus")
                    in {"ABSENT", "DELETE_COMPLETE"}
                )
                if (
                    transition
                    and ended
                    and ended.get("request") != prior
                    and not (completed_execution or completed_cleanup)
                ):
                    raise Blocked(
                        "cannot preserve both existing and current Create completion evidence"
                    )
                end_tracking(state, prior)
                runtime.save()
                if not transition:
                    path.unlink()
                    if operation == "execute_change_set":
                        raise Blocked(
                            "execution tracking ended; prepare a fresh current ChangeSet before executing"
                        )
                prior = None
        created = prior is None
        if prior:
            if operation == "execute_change_set":
                raise Blocked(
                    "original Execute is still unconfirmed; reconcile its identity before a new execution"
                )
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
                "stackId": current.get("StackId")
                or (
                    arguments.get("StackName")
                    if operation == "execute_change_set"
                    and ":stack/" in arguments.get("StackName", "")
                    else None
                ),
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
