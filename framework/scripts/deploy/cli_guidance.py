"""Presentation only: existing CLI routes and conservative next actions, never execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

from contracts.model import REFERENCE_PENDING_DEPLOY, REFERENCE_UNRESOLVED
from model.core import ReferenceDiagnosticError
from utils.aws.identity import IdentityError
from utils.project_targets import DeployContextError
from utils.reference_contracts import ARN_ATTRIBUTES, REF_ATTRIBUTES

from deploy.failures import AUTH_CODES, dependency_wait

PREPARATION_HELP = """Examples (replace example target, StackNames and paths with reviewed values):
  python3 -B framework/scripts/deploy_preparation.py --environment dev --alias app --stack app-network --stack app-worker --service ec2 --service iam --task-file tasks/deploy-app.md
  python3 -B framework/scripts/deploy_preparation.py --environment dev --alias app --order-from 30 --order-to 50 --task-file tasks/deploy-range.md
  python3 -B framework/scripts/deploy_preparation.py --register /tmp/blueprint-deploy-prepare-example/preparation.json
  python3 -B framework/scripts/deploy_preparation.py --run-controller /tmp/blueprint-deploy-prepare-example/preparation.json

Offline Preparation performs no AWS calls or deployment. Use a new task-file;
choose --stack repeatedly or an inclusive numeric --order-from/--order-to range.
--stack and Order bounds cannot be combined. Preparation discovers owning services
from explicit cfn-logicalId mappings; --service optionally checks that exact set.
No selected Stacks or invalid bounds stop before Task registration. The resolved
StackNames and Resource ownership are fixed in the Task; resume uses that complete
StackName scope, never the original Order range. Out-of-range Stack definition errors
remain errors and identify StackName, DeployOrder and the invalid field. External
producers remain read-only dependencies. Out-of-scope consumer services are recorded
as deferredConsumers and their Model/Views are not synchronized. Read the
contract and target summary before --register; read applicable Rules from the Deploy
prompt. Registration rechecks input bytes, identities, file sets
and the candidate; a change stops registration and requires a reviewed new preparation.
--run-controller requires the registered, unchanged Task and the same repository,
Python, PATH/PYTHONPATH. It launches exactly one controller, with current AWS checks.
Use --aws-account-id instead of --alias for targets without an alias; --profile
must agree with project.json. --sequential caps concurrency at one; otherwise the
Model's MaxConcurrentStacks applies within each DeployOrder group. The optional
--allow-external-repair authorizes a separate evidence-backed Implement handoff,
never automatic IaC editing. Existing Tasks use cloudformation-deploy.py directly.
For omitted owner services, suspend the same Task and use task_contract.py
--correct-deploy-contract with a reviewed external candidate adding only proven
Validation services and exact outputs. Same-target deferred reference consumers
also require explicit Human consent and --approve-deferred-consumer env/target/service.
Other Targets gain no authority. Verified pending Intents are retained; unknown
bytes, active requests and unfinished failure evidence stop for review.
Then check-resume-scope, resume and use needed sync/checkpoint without AWS replay.
Do not relaunch the old preparation.json through --run-controller after correction.
Failures return stage/cause/nextAction; command=null means stop for review.
"""

CONTROLLER_HELP = """Examples (use the current Task, target and exact Deployment scope):
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action advance
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action sync --sync-stack app-network
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action checkpoint --sync-stack app-network
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action sync --final
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action advance --profile app-dev
  env BLUEPRINT_TASK_FILE=tasks/update-app.md python3 -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --sequential --action advance
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --action status

Existing Task: running infrastructure deploy/update, explicit AWS/Deploy permission,
matching environment/account/alias and exact StackName scope are required.
Deploy uses the current checkout and fixed authorized inputs.
advance advances one bounded AWS turn; status reads latest scoped AWS.
sync --sync-stack saves current facts (success/failure/rollback/partial/unexecuted/
running/unknown), generates available services, validates and saves locally.
sync --final validates the local Model/View and Task Acceptance, then completes the Task
locally; Git integration is separate.
Omit --sync-stack when all needed observations are already saved.
checkpoint resumes a saved local sync, not a Git checkpoint; omitted --sync-stack
uses its saved scope and preserves its final intent.
The LLM chooses sync timing and explicit scope; no background writer or Sub Agents.
Deploy result, Model save, Validation and Task status are independent.
A consistent failed Snapshot can complete its Task with Deploy FAIL unchanged.
Intermediate saves keep Task running and fixed IaC/parameters/artifacts unchanged.
Current Task identity and saved candidate integrity determine the next action.
Keep this execution’s IDs and token when reporting an uncertain response;
a new Deploy invocation starts a new Task based on current AWS state.
Choose an explicit --action for every invocation.
Same-Order independent peers can continue after a failure; later Order still requires
prior success. --sequential only lowers the configured MaxConcurrentStacks to one.

Delete/replacement waits for Human approval of the entire current ChangeSet.
After consent, select the same Task/target/stacks and add, for example:
  --approve-change-set arn:aws:cloudformation:ap-northeast-1:123456789012:changeSet/reviewed-change/00000000-0000-0000-0000-000000000000
This illustrative ID is not an approval. Use only the actual returned ID; repeat
for each approved ChangeSet. Runtime rechecks ID, Stack, full content and input
fingerprints, CREATE_COMPLETE/AVAILABLE. Interrupted or changed approval is invalid.

--action status inspects this Task without starting a new AWS Execute.
It may recover and save previously persisted unfinished work, including pending Observed
values, generated artifacts and progress. It never implicitly starts a new Deploy
or automatically grants Human approval. Use explicit sync and checkpoint for their
current observations and saved local recovery.
Unconfirmed submissions block overlapping new requests in the checkout. Authentication,
Task/target/input mismatches and unresolved dependencies stop new starts; peers drain.
PENDING_DEPLOY is a dependency wait, not proof of an IaC defect. Task completion
requires a settled attempt, saved observations, required generation and a validated
final candidate. A failed attempt retains Deploy FAIL when its Task completes.
Failure JSON adds stage/cause/nextAction; unknown or unapproved actions have no command.
For a proven IaC defect with current external repair authority, inspect current
safe evidence and use deploy_handoff.py --help. repairFailure alone is insufficient.
"""

HANDOFF_HELP = """Examples (paths must identify current evidence and reviewed diagnosis):
  python3 -B framework/scripts/deploy_handoff.py --failure /tmp/deploy-failure-example.json --diagnosis /tmp/deploy-diagnosis.json --path infra/cloudformation/templates/worker.yaml
  python3 -B framework/scripts/deploy_handoff.py --failure /tmp/deploy-failure-example.json --discard-failure

Request creation requires current Task External IaC repair: allowed, a proven IaC
cause, settled scoped AWS/publication and exact current input/Model evidence.
Repeat --path only for the exact IaC files to repair. Diagnosis JSON maps every
failed StackName to {reason, inputRefs: [{path, sha256}], modelRefs: [{path, sha256,
key}]}; key is an existing desired Model entry. Never include secrets or guess a cause.
The CLI verifies current inputs and returns a local request.json for review.
Suspend the named Deploy Task before separate, authorized Implement work. The
request is evidence for review and identifies the exact IaC inputs; it does not
create or integrate another checkout. Retain the original Task's AWS evidence.
"""

CONTEXT_HELP = """Terraform preflight example (repository root, approved target/profile):
  python3 -B framework/scripts/check-deploy-context.py --environment dev --alias app --profile app-dev
Use --aws-account-id instead of --alias when no alias exists. This existing entry
checks target/account/Region/profile and AWS credentials, requiring Terraform for a
Terraform target. --read-only omits the IaC command requirement, not authentication.
It does not run Terraform or grant Task permission. Stop on any mismatch or failure;
never switch credentials to evade a failure.

Existing Terraform workflow, from the approved environment Root, with its reviewed
workspace/backend/variable inputs and the same process-local AWS_PROFILE/Region:
  terraform fmt -check
  terraform init
  terraform validate
  terraform plan -out=/tmp/app-dev.tfplan
  terraform show /tmp/app-dev.tfplan
  terraform apply /tmp/app-dev.tfplan
Select the existing designed workspace; do not guess a workspace/backend or invent
variable arguments. Use its existing approved input mechanism. Keep plan binaries
outside the repository. Only an authorized infrastructure deploy/update Task may
plan/apply; implement uses init -backend=false and a fresh TF_DATA_DIR, never plan/apply.
For unapproved destroy/replacement, stop for Human consent to the entire saved plan.
Apply only that identical plan with matching addresses/types/actions after consent;
a changed/lost/recreated plan requires a new review. A failed apply may be partial:
inspect state/AWS read-only and stop, never blindly reapply. After success collect
non-sensitive outputs, or read-only state attributes if outputs are absent; require
agreement if both exist. Synchronize only authorized observations/generated views.
See framework/rules/terraform.md#validation-and-execution for authoritative boundaries.
"""


class DeployStepBlocked(ValueError):
    """Framework-authored step precondition; never wrap raw AWS/parameter errors."""


class PreparationError(ValueError):
    """Known preparation conditions, separate from arbitrary exception prose."""

    def __init__(self, message, *, code, target=None, missing=()):
        super().__init__(message)
        self.code, self.target, self.missing = code, target, missing


class InputChanged(PreparationError):
    """Preparation snapshot revalidation failed; keep the existing ValueError boundary."""

    def __init__(self, message, *, target=None, condition=None):
        super().__init__(message, code="PREPARATION_INPUT_CHANGED", target=target)
        self.condition = condition


REFERENCE_CATEGORIES = {
    "MODEL_NEEDS_FIX",
    "FRAMEWORK_UNSUPPORTED",
    REFERENCE_PENDING_DEPLOY,
    REFERENCE_UNRESOLVED,
}
REFERENCE_CODES = REFERENCE_CATEGORIES | {
    "reference.unresolved",
    "codebuild.plaintext-reference",
    "MODEL_REF_INVALID_ATTRIBUTE",
    "MODEL_REF_INVALID_VALUE",
    "MODEL_REF_VALUE_CONFLICT",
    "MODEL_REF_INVALID_PENDING_STATE",
    "MODEL_REF_INVALID_SYNTAX",
    "MODEL_REF_TARGET_AMBIGUOUS",
}


def safe_model_path(value):
    """Only authored Model paths, never arbitrary filenames or parameter values."""
    if not isinstance(value, str):
        return None
    parts = Path(value).parts
    if "model" not in parts or ".." in parts:
        return None
    relative = Path(*parts[parts.index("model") :]).as_posix()
    return (
        relative
        if re.fullmatch(
            r"model/[a-z0-9_-]+/[a-z0-9_-]+/[a-z0-9-]+(?:/part-[0-9]{3,})?\.properties",
            relative,
        )
        else None
    )


def safe_diagnostic(diagnostic):
    result = {}
    for field, allowed in (
        ("category", REFERENCE_CATEGORIES),
        ("code", REFERENCE_CODES),
        ("status", {"FAIL", "NOT_RUN", "WARNING"}),
        ("attribute", {"Arn", *ARN_ATTRIBUTES.values(), *REF_ATTRIBUTES.values()}),
    ):
        value = diagnostic.get(field)
        if isinstance(value, str) and value in allowed:
            result[field] = value
    for field in ("model", "producerModel"):
        value = safe_model_path(diagnostic.get(field))
        if value:
            result[field] = value
    for field, pattern in (
        ("targetLogicalId", r"[A-Za-z][A-Za-z0-9]*_[A-Za-z][A-Za-z0-9]*_[0-9]{3,}"),
        ("resourceLogicalId", r"[A-Za-z][A-Za-z0-9]*_[A-Za-z][A-Za-z0-9]*_[0-9]{3,}"),
        (
            "modelKey",
            r"(?:desired|observed)\.(?:resource|row)\.[0-9]+(?:-[0-9]+)?\.(?:logicalId|value|property)",
        ),
        (
            "producerModelKey",
            r"(?:desired|observed)\.(?:resource|row)\.[0-9]+(?:-[0-9]+)?\.(?:logicalId|value|property)",
        ),
    ):
        value = diagnostic.get(field)
        if isinstance(value, str) and re.fullmatch(pattern, value):
            result[field] = value
    return result


def guidance(stage, cause, kind, reason, command=None):
    return {
        "stage": stage,
        "cause": cause,
        "nextAction": {"type": kind, "reason": reason, "command": command},
    }


def safe_error(error):
    """Accept typed conditions and allowlisted diagnostic fields, never exception prose."""
    code = getattr(error, "code", None)
    diagnostics = (
        [safe_diagnostic(d) for d in error.diagnostics if isinstance(d, dict)]
        if isinstance(error, ReferenceDiagnosticError)
        else []
    )
    result = {
        "diagnosticCategories": sorted(
            {d["category"] for d in diagnostics if "category" in d}
        )
        if isinstance(error, ReferenceDiagnosticError)
        else [],
        "errorType": type(error).__name__,
        "code": code
        if isinstance(code, str)
        and code
        in AUTH_CODES | {"InvalidIdentity", "AccountMismatch", "InputDecodeError"}
        else None,
        "detailDigest": hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
    }
    if diagnostics:
        result["diagnostics"] = diagnostics
    if isinstance(error, DeployStepBlocked):
        reason = str(error)
        safe_reasons = {
            "base advanced; review retained commit",
            "local Deploy save belongs to different fixed inputs",
            "fixed execution inputs changed without verified implement authority",
            "local publication Task/target authority changed",
            "local publication belongs to different fixed inputs",
            "sync needs distinct --sync-stack names within Deployment scope",
            "--final requires managed CloudFormation Deploy sync",
            "sync requires clean inputs or its own retained publication",
            "resume the saved checkpoint without changing its final intent or Stack scope",
            "synchronized candidate changed before next sync",
            "finish the saved Observed Stack scope before another sync",
            "generationError has no recoverable generation candidate",
            "locally completed candidate still needs --action checkpoint; advance is unavailable",
            "--final requires managed CloudFormation Deploy --action sync",
            "step operations require CloudFormation",
            "resume the saved sync before advance",
            "final sync requires settled AWS requests; continue the current Task",
            "completed Deploy permits status only",
            "no local sync to resume; use --action sync",
            "--final requires CloudFormation Deploy sync",
            "--final requires CloudFormation Deploy --action sync",
            "resume the saved sync without changing its final intent or Stack scope",
        }
        result.update(
            code="DEPLOY_STEP_BLOCKED",
            reason=reason
            if reason in safe_reasons
            else "Deploy step blocked; inspect its safe diagnostic evidence.",
        )
    elif isinstance(error, PreparationError):
        if error.code in {
            "PREPARATION_INPUT_CHANGED",
            "PREPARATION_ENVIRONMENT_INCOMPLETE",
        }:
            result["code"] = error.code
        target = safe_model_path(error.target)
        if target:
            result["target"] = target
        result["missingConditions"] = [
            item
            for item in error.missing
            if isinstance(item, str)
            and item in {"boto3", "botocore", "PyYAML", "git", "pip-check"}
        ]
        if isinstance(error, InputChanged) and error.condition in {
            "repository-or-python",
            "runtime-environment",
            "preparation-clock",
            "command-paths",
            "input-file",
            "deferred-inputs",
            "model-file-set",
            "contract-candidate",
        }:
            result["condition"] = error.condition
    elif isinstance(error, FileNotFoundError):
        result["code"] = "FILE_NOT_FOUND"
        target = safe_model_path(error.filename)
        if target:
            result["target"] = target
    elif isinstance(error, json.JSONDecodeError):
        result.update(code="InputDecodeError", line=error.lineno, column=error.colno)
    return result


def command_environment(root):
    if os.name != "posix" or not (Path(root) / ".git").exists():
        return None
    if "PYTHONHOME" in os.environ or not os.environ.get("PATH"):
        return None
    return ["env", "-u", "PYTHONHOME"]


def python_command(root, script, arguments, *, task_file=None):
    root = Path(root).resolve()
    scripts = Path(__file__).resolve().parents[1]
    env = command_environment(root)
    if env is None or not (scripts / script).is_file():
        return None
    if task_file:
        env.append("BLUEPRINT_TASK_FILE=" + task_file)
    argv = env + [
        sys.executable,
        "-B",
        str(scripts / script),
        *arguments,
    ]
    if any(not isinstance(value, str) or "\0" in value for value in argv):
        return None
    return "cd " + shlex.quote(str(root)) + " && " + shlex.join(argv)


def stopped(stage, error, *, template_paths=()):
    cause = safe_error(error)
    if isinstance(error, FileNotFoundError) and error.filename in template_paths:
        operations = {
            "read_text": "read",
            "write_text": "write",
            "stat": "stat",
            "open": "open",
        }
        trace, operation = error.__traceback__, "access"
        while trace:
            if trace.tb_frame.f_code.co_name in operations:
                operation = operations[trace.tb_frame.f_code.co_name]
            trace = trace.tb_next
        cause.update(operation=operation, path=error.filename, errno=error.errno)
    if isinstance(error, InputChanged):
        return guidance(
            "INPUT_REVALIDATION",
            cause,
            "PREPARE_AGAIN",
            "Frozen preparation inputs changed; review the changes and prepare again before registration. No old plan may be run.",
        )
    kind = (
        "DEPENDENCY_WAIT"
        if dependency_wait(error)
        else "CONTEXT_REVIEW"
        if isinstance(error, (IdentityError, DeployContextError))
        or cause["code"] in AUTH_CODES
        or stage in {"TARGET_SELECTION", "TASK_AUTHORITY", "AUTHENTICATION"}
        else "HUMAN_REVIEW"
    )
    return guidance(
        stage,
        cause,
        kind,
        "Execution stopped at this stage. Review the current cause, Task authority and inputs; no safe automatic command is established.",
    )


def preparation_result(root, plan_path, registered):
    if registered:
        return guidance(
            "REGISTRATION",
            None,
            "START_CONTROLLER",
            "Reviewed preparation registered; explicitly start one authorized controller.",
            python_command(
                root,
                "deploy_preparation.py",
                [
                    "--repository-root",
                    str(root),
                    "--run-controller",
                    str(plan_path),
                ],
            ),
        )
    return guidance(
        "PREPARATION",
        None,
        "REVIEW_PREPARATION",
        "Review the contract and target summary and read applicable Rules before registration.",
    )


def handoff_result(request=None, *, discarded=False):
    if discarded:
        return guidance(
            "HANDOFF",
            None,
            "REVIEW_CURRENT_INPUTS",
            "Unconsumed failure proof discarded; no repair or Deploy was started.",
        )
    return guidance(
        "HANDOFF",
        {"requestId": request["requestId"]},
        "SUSPEND_PARENT",
        "Local repair request issued. Review the diagnosis and suspend the named Task before separately authorized IaC repair.",
        python_command(
            Path(request["repository"]),
            "task_contract.py",
            [
                "--repository-root",
                request["repository"],
                "--task-file",
                request["taskFile"],
                "--suspend-reason",
                "one-shot implement repair " + request["requestId"],
            ],
            task_file=request["taskFile"],
        ),
    )
