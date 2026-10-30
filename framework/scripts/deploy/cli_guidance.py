"""Presentation only: existing CLI routes and conservative next actions, never execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

import worktree_python
import worktree_state
from model.core import ReferenceDiagnosticError
from utils.aws.identity import IdentityError
from utils.project_targets import DeployContextError
from utils.reference_contracts import ARN_ATTRIBUTES, REF_ATTRIBUTES

from deploy.failures import AUTH_CODES, dependency_wait

PREPARATION_HELP = """Examples (replace example target, StackNames and paths with reviewed values):
  python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --environment dev --alias app --stack app-network --stack app-worker --service ec2 --service iam --task-file tasks/deploy-app.md
  python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --register /tmp/blueprint-deploy-prepare-example/preparation.json
  python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --run-controller /tmp/blueprint-deploy-prepare-example/preparation.json

Offline Preparation performs no AWS calls or deployment. Use a new task-file;
repeat --service for all explicitly reviewed owning/referencing services. Read the
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
Failures return stage/cause/nextAction; command=null means stop for review.
"""

CONTROLLER_HELP = """Examples (use the current Task, target and exact Deployment scope):
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action advance
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action sync --sync-stack app-network
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action checkpoint --sync-stack app-network
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --action advance --profile app-dev
  env BLUEPRINT_TASK_FILE=tasks/update-app.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --stack app-worker --sequential --action advance
  env BLUEPRINT_TASK_FILE=tasks/deploy-app.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment dev --alias app --stack app-network --action status

Existing Task: running infrastructure deploy/update, explicit AWS/Deploy permission,
matching environment/account/alias and exact StackName scope are required.
Managed Worktree operations use current AWS and fixed authorized inputs.
advance advances one bounded AWS turn; status reads latest scoped AWS.
sync --sync-stack saves current facts (success/failure/rollback/partial/unexecuted/
running/unknown), generates available services, validates and commits/publishes.
checkpoint resumes local validation/commit/publication; omitted --sync-stack uses the saved candidate scope.
The LLM chooses sync timing and explicit scope; no background writer or Sub Agents.
Deploy result, Model save, Snapshot validation and Git publication are independent.
A consistent failed Snapshot can complete its Task with Deploy FAIL unchanged.
Intermediate saves keep Task running and fixed IaC/parameters/artifacts unchanged.
Old Task/Journal/Fence/Output/checkpoint history never gates current-state adoption.
Current Stack requests retain original IDs/tokens across lost replies and Worktrees;
a stale COMPLETE alone never settles an uncertain Execute. No automatic Reset.
Choose an explicit --action for every invocation.
Retry saved Git commits with worktree_task.py deploy-publish, without AWS or recollection.
Same-Order independent peers can continue after a failure; later Order still requires
prior success. --sequential only lowers the configured MaxConcurrentStacks to one.

Delete/replacement waits for Human approval of the entire current ChangeSet.
After consent, select the same Task/target/stacks and add, for example:
  --approve-change-set arn:aws:cloudformation:ap-northeast-1:123456789012:changeSet/reviewed-change/00000000-0000-0000-0000-000000000000
This illustrative ID is not an approval. Use only the actual returned ID; repeat
for each approved ChangeSet. Runtime rechecks ID, Stack, full content and input
fingerprints, CREATE_COMPLETE/AVAILABLE. Interrupted or changed approval is invalid.

--action status inspects and reconciles existing requests without starting a new AWS Execute.
It may recover and save previously persisted unfinished work, including pending Observed
values, generated artifacts and progress. It never implicitly starts a new Deploy
or automatically grants Human approval. Use explicit sync and checkpoint for their
respective current-snapshot and Git publication operations.
Do not run normal Deploy while submission/publication is unconfirmed. Authentication,
Task/target/input mismatches and unresolved dependencies stop new starts; peers drain.
PENDING_DEPLOY is a dependency wait, not proof of an IaC defect. AWS success,
Observed sync and Markdown/JSON generation are separate; all are needed for COMPLETE.
Failure JSON adds stage/cause/nextAction; unknown or unapproved actions have no command.
For a proven IaC defect with current external repair authority, inspect current
safe evidence and use deploy_handoff.py --help. repairFailure alone is insufficient.
"""

HANDOFF_HELP = """Examples (paths must identify current evidence and reviewed diagnosis):
  python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_handoff.py --failure /tmp/deploy-failure-example.json --diagnosis /tmp/deploy-diagnosis.json --path infra/cloudformation/templates/worker.yaml
  python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_handoff.py --failure /tmp/deploy-failure-example.json --discard-failure

Request creation requires current Task External IaC repair: allowed, a proven IaC
cause, settled scoped AWS/publication and exact current input/Model evidence.
Repeat --path only for the exact IaC files to repair. Diagnosis JSON maps every
failed StackName to {reason, inputRefs: [{path, sha256}], modelRefs: [{path, sha256,
key}]}; key is an existing desired Model entry. Never include secrets or guess a cause.
The CLI verifies and checkpoints the parent, then returns a pinned request.json.
Suspend only that parent with task_contract.py --task-file ... --suspend-reason ...;
create a separate child using worktree_task.py create --task-id ... --repair-request ... .
The child is infrastructure/implement with identical Validation scope, only request
IaC paths plus its contract, and AWS API execution/AWS mutation/Deploy/apply forbidden.
Use worktree_task.py repair-validate --task-id ... --repair-request ... for at most
three static cycles in that child, complete its Task, then finalize and cleanup.
Exact verified commit/paths/bytes integrate ff-only into the suspended parent.
Resume that named parent explicitly with task_contract.py --task-file ... --resume;
start an independent cloudformation-deploy.py run with current target/stacks and fresh
Human ChangeSet approval. Never automatically chain unlimited Deploy attempts.
These lifecycle commands require real Task IDs/request paths; omitted values above
are descriptions, not runnable commands. The Worktree skill defines the lifecycle.

Approval wait, authentication/Task/target failure, PENDING_DEPLOY, missing design,
unknown submission or unproven cause do not authorize repair. --discard-failure
explicitly abandons an unconsumed proof; referenced/unknown evidence is retained.
Blocked JSON adds stage/cause/nextAction and never grants authority or auto-retries.
"""

CONTEXT_HELP = """Terraform preflight example (repository root, approved target/profile):
  python3 -B framework/scripts/run-python.py -B framework/scripts/check-deploy-context.py --environment dev --alias app --profile app-dev
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
    "REFERENCE_PENDING_DEPLOY",
    "REFERENCE_UNRESOLVED",
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
        result.update(code="DEPLOY_STEP_BLOCKED", reason=str(error))
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
            "legacy-plan",
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
    """Re-enter the registered wrapper without adding its bin to PATH a second time."""
    if os.name != "posix":
        return None
    root = Path(root).resolve()
    if not (root / ".git").exists():
        return None
    if "PYTHONHOME" in os.environ or not os.environ.get("PATH"):
        return None
    env = ["env", "-u", "PYTHONHOME", "-u", "PYTHONPATH"]
    path = os.environ["PATH"]
    try:
        repository, _, primary = worktree_state.repository(root)
        if repository != root:
            return None
        if root.parent == primary / ".worktrees":
            _, _, _, state = worktree_state.load(root, root.name)
            setup = state.get("python_setup", {})
            directory = worktree_python.shared_directory(root)
            interpreter = worktree_python.python_path(directory)
            prefix = str(interpreter.parent) + os.pathsep
            if (
                state.get("worktree") != str(root)
                or setup.get("status") != "ready"
                or setup.get("kind") != "shared"
                or setup.get("interpreter") != str(interpreter)
                or setup.get("bin") != str(interpreter.parent)
                or sys.executable != str(interpreter)
                or not os.environ.get("PATH", "").startswith(prefix)
                or "PYTHONPATH" in os.environ
                or "PYTHONHOME" in os.environ
                or not worktree_python.shared_ready(directory)
                or directory.with_name("python-env.setup-lock").exists()
                or not worktree_python.applied(
                    directory, worktree_python.requirements_snapshot(root, primary)[1]
                )
            ):
                return None
            path = path[len(prefix) :]
    except (OSError, ValueError, KeyError):
        return None
    env.append("PATH=" + path)
    if "PYTHONPATH" in os.environ:
        env.append("PYTHONPATH=" + os.environ["PYTHONPATH"])
    return env


def python_command(root, script, arguments, *, task_file=None):
    root = Path(root).resolve()
    scripts = Path(__file__).resolve().parents[1]
    env = command_environment(root)
    if env is None or not all(
        (scripts / name).is_file() for name in ("run-python.py", script)
    ):
        return None
    if task_file:
        env.append("BLUEPRINT_TASK_FILE=" + task_file)
    argv = env + [
        sys.executable,
        "-B",
        str(scripts / "run-python.py"),
        "-B",
        str(scripts / script),
        *arguments,
    ]
    if any(not isinstance(value, str) or "\0" in value for value in argv):
        return None
    return "cd " + shlex.quote(str(root)) + " && " + shlex.join(argv)


def stopped(stage, error):
    cause = safe_error(error)
    if isinstance(error, InputChanged) and error.condition == "legacy-plan":
        return guidance(
            "INPUT_REVALIDATION",
            cause,
            "PREPARE_AGAIN",
            "This legacy preparation contains documents; prepare again before registration or controller launch.",
        )
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


def recovery_command(args, root, task_file):
    """Only called after Task/context checks; never reconstruct an approval or normal retry."""
    if (
        not task_file
        or not args.environment
        or not args.stack
        or not (args.alias or args.aws_account_id)
    ):
        return None
    argv = [
        "--environment",
        args.environment,
    ]
    argv += (
        ["--alias", args.alias]
        if args.alias
        else ["--aws-account-id", args.aws_account_id]
    )
    for name in args.stack:
        argv += ["--stack", name]
    if args.profile:
        argv += ["--profile", args.profile]
    if args.sequential:
        argv.append("--sequential")
    argv.extend(["--action", "status"])
    return python_command(root, "cloudformation-deploy.py", argv, task_file=task_file)


def controller_result(
    result, run_context, args, root, *, repair_failure=None, task_text=""
):
    states = run_context.get("states", {})
    failures = [s.get("failure", {}) for s in states.values() if s.get("failure")]
    diagnostics = {
        "gitPublication": run_context.get("gitPublication"),
        "stackFailures": {
            name: s["failure"] for name, s in states.items() if s.get("failure")
        },
        "observedError": run_context.get("observedFailure")
        or (
            safe_error(RuntimeError(run_context["observedError"]))
            if run_context.get("observedError")
            else None
        ),
        "generationError": run_context.get("generationFailure")
        or (
            safe_error(RuntimeError(run_context["generationError"]))
            if run_context.get("generationError")
            else None
        ),
        "changeSetFailures": {
            name: state["changeSetFailure"]
            for name, state in states.items()
            if state.get("changeSetFailure")
        },
        "observedStage": run_context.get("pendingObserved", {}).get("stage")
        if run_context.get("pendingObserved", {}).get("stage")
        in {"PREPARED", "MODEL_PUBLISHED"}
        else None,
        "generationReportError": safe_error(
            RuntimeError(run_context["generationReportError"])
        )
        if run_context.get("generationReportError")
        else None,
        "stackEvents": {
            name: s["failureEvents"]
            for name, s in states.items()
            if s.get("failureEvents")
        },
        "pendingGeneration": {
            path: {
                "reason": "REFERENCE_PENDING_DEPLOY"
                if r.get("reason") == "REFERENCE_PENDING_DEPLOY"
                else "PUBLICATION_PENDING"
            }
            for path, r in run_context.get("pendingGeneration", {}).items()
        },
    }
    command = None
    if any(s.get("status") == "RUNNING" for s in states.values()) or any(
        f.get("executionState") == "UNKNOWN" for f in failures
    ):
        stage, kind, reason = (
            "AWS_OPERATION",
            "RECOVER_OPERATIONS",
            "Submission/completion is unconfirmed. Settle only the original operation; never resend as a normal Deploy.",
        )
        command = recovery_command(args, root, run_context.get("taskFile"))
    elif run_context.get("observedError") or run_context.get("pendingObserved"):
        stage, kind, reason = (
            "OBSERVED",
            "HUMAN_REVIEW",
            "AWS success does not prove Observed publication. Resolve the synchronization blocker before guarded recovery; do not Execute again.",
        )
    elif (
        run_context.get("generationError")
        or run_context.get("pendingGeneration")
        or run_context.get("generationReportError")
    ):
        stage = "GENERATION"
        waiting = bool(run_context.get("pendingGeneration")) and all(
            r.get("reason") == "REFERENCE_PENDING_DEPLOY"
            for r in run_context["pendingGeneration"].values()
        )
        kind = "DEPENDENCY_WAIT" if waiting else "HUMAN_REVIEW"
        reason = "Markdown/JSON generation remains incomplete. Review producer dependencies or publication failure; Observed success alone is not COMPLETE."
    elif any(f.get("classification") == "AUTHORIZATION" for f in failures):
        stage, kind, reason = (
            "AWS_AUTHORIZATION",
            "CONTEXT_REVIEW",
            "Resolve the current AWS authorization failure without changing target or inheriting another credential.",
        )
    elif any(f.get("classification") == "APPROVAL" for f in failures):
        stage, kind, reason = (
            "CHANGESET_REVIEW",
            "HUMAN_APPROVAL",
            "The whole destructive ChangeSet requires explicit current Human approval; no approval command is authorized yet.",
        )
    elif any(f.get("dependencyWait") for f in failures):
        stage, kind, reason = (
            "PREPARATION",
            "DEPENDENCY_WAIT",
            "PENDING_DEPLOY requires producer evidence; it is not proof of an IaC defect.",
        )
    elif result == "PUBLICATION_PENDING":
        stage, kind, reason = (
            "GIT_PUBLICATION",
            "HUMAN_REVIEW",
            "AWS, Observed and generation succeeded. Review Git publication separately with worktree_task.py deploy-publish; never redeploy successful Stacks to resolve Git conflicts.",
        )
    elif result == "COMPLETE":
        stage, kind, reason = (
            "COMPLETE",
            "VERIFY_TASK",
            "Controller AWS, Observed and generation barriers completed; perform the Task's required final validation.",
        )
    elif (
        repair_failure
        and "- External IaC repair: `allowed`" in task_text.splitlines()
        and failures
        and all(
            f.get("classification") in {"IAC_CANDIDATE", "INPUT_CANDIDATE"}
            for f in failures
        )
        and all(
            s.get("failure", {}).get("classification")
            in {"IAC_CANDIDATE", "INPUT_CANDIDATE"}
            for s in states.values()
            if s.get("status") in {"FAILED", "BLOCKED"}
        )
        and not any(s.get("schedulerError") for s in states.values())
    ):
        stage, kind, reason = (
            "DIAGNOSIS",
            "INVESTIGATE_IAC",
            "Current structured failure is a repair candidate. Prove the exact IaC cause against approved Model before deploy_handoff; repairFailure alone grants no repair authority.",
        )
    else:
        stage = (
            failures[0].get("stage", "CONTROLLER")
            if failures
            else (
                "AWS_EXECUTION"
                if any(s.get("status") == "FAILED" for s in states.values())
                else "CHANGESET_REVIEW"
                if any(s.get("changeSetFailure") for s in states.values())
                else "CONTROLLER"
            )
        )
        kind, reason = (
            "HUMAN_REVIEW",
            "Inspect the current structured failure. Cause or safe next operation is not established; stop without retrying.",
        )
    return {
        **guidance(stage, diagnostics, kind, reason, command),
        "awsStatus": "SUCCESS"
        if states and all(s.get("status") == "SUCCESS" for s in states.values())
        else "FAILED"
        if any(s.get("status") == "FAILED" for s in states.values())
        else "PENDING",
        "observedStatus": "SUCCESS"
        if states
        and all(
            s.get("status") == "SUCCESS" and s.get("observedSynced")
            for s in states.values()
        )
        and not run_context.get("pendingObserved")
        and not run_context.get("observedError")
        else "PENDING",
        "generationStatus": "PENDING"
        if run_context.get("pendingGeneration") or run_context.get("generationError")
        else "SUCCESS"
        if states and all(s.get("observedSynced") for s in states.values())
        else "PENDING",
        "gitPublication": run_context.get("gitPublication"),
    }


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
        "Pinned request issued. Suspend only the named parent, then follow the Worktree repair lifecycle with a separately named child; do not start Deploy.",
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
