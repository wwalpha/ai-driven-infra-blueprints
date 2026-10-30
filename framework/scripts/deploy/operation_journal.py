"""Current request storage, locks and ownership checks; no operation replay store."""

import errno
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

import worktree_state
from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# No approvals, failure archives, repair histories, workflow bindings or completed records.
OPERATION_FIELDS = {
    "failureDetected",
    "attemptResult",
    "unexecutedReason",
    "needsCurrentReview",
    "status",
    "stackId",
    "stackStatus",
    "changeSetId",
    "changeDigest",
    "changes",
    "clientToken",
    "executionStarted",
    "executionEvidence",
    "endedRequest",
    "operationType",
    "absentBeforeCreate",
    "operationStackId",
    "externalOperation",
    "observedSynced",
    "cleanupStatus",
    "cleanupStackId",
    "failureTemplateSafety",
    "bootstrap",
    "bootstrapAttempted",
    "emptyStackRecreated",
    "failureEvents",
    "preparationId",
    "changeSetStarted",
    "changeSetCreateSeconds",
    "expectedOutputs",
    "noChangeEvidence",
    "preExecutionRecovery",
    "delivery",
    "checkpointRequired",
    "observedCoverage",
    "observedServices",
    "failure",
    "schedulerError",
    "pollReadFailures",
    "unconfirmedPolls",
}


def location(target):
    identity = [
        target.get("awsExecutionAccountId", target["awsAccountId"]),
        target["awsRegion"],
    ]
    return (
        Path(tempfile.gettempdir()).resolve()
        / ("blueprint-cfn-current-v3-" + fingerprint(identity))
        / "journal.json"
    )


def safe_path(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise Blocked("operation journal path must be absolute and not redirected")
    return path


def private_path(path, *, directory=False, permissions=0o077):
    path = safe_path(path)
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not kind(info.st_mode)
        or os.name != "nt"
        and (info.st_uid != os.getuid() or info.st_mode & permissions)
        or not directory
        and info.st_nlink != 1
    ):
        raise Blocked("operation journal path must be private and owned: " + str(path))
    return info


@contextmanager
def locked(path):
    path = safe_path(path)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    private_path(path.parent, directory=True)
    lock = safe_path(path.with_suffix(".lock"))
    flags = os.O_CREAT | os.O_RDWR
    if os.name != "nt":
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock, flags, 0o600)
    try:
        info = private_path(lock, permissions=0o022)
        opened = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise Blocked("operation lock identity changed")
        try:
            if os.name == "nt":
                if opened.st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            raise Blocked(
                "controller active; operation lock busy: " + str(lock)
            ) from error
        yield
    finally:
        os.close(descriptor)


def target_identity(target):
    return (
        target.get("awsExecutionAccountId", target["awsAccountId"]),
        target["awsRegion"],
    )


def same_repository(root, owner):
    owner = safe_path(Path(owner))
    if root == owner:
        return True
    try:
        return (
            Path(
                worktree_state.output(
                    root, "rev-parse", "--path-format=absolute", "--git-common-dir"
                )
            ).resolve()
            == Path(
                worktree_state.output(
                    owner, "rev-parse", "--path-format=absolute", "--git-common-dir"
                )
            ).resolve()
        )
    except (OSError, ValueError):
        return False


def publication_paths(context):
    paths = set(context.get("pendingObserved", {}).get("beforeManifest", {}))
    plans = [*context.get("pendingGeneration", {}).values()]
    if context.get("pendingObserved"):
        plans.append(context["pendingObserved"])
    for plan in plans:
        paths.update(plan.get("generated", {}).get("originals", {}))
        paths.update(plan.get("waitingModelManifest", {}))
        paths.update(plan.get("candidateManifest") or {})
    return paths
