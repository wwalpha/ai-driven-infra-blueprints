"""Explicit, recoverable PR publication of an already validated worktree candidate."""

import copy
import errno
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import task_contract_core as tasks
import worktree_task as wt

if os.name == "nt":
    import msvcrt
else:
    import fcntl

PR_FIELDS = "number,url,state,baseRefName,headRefName,headRefOid,isCrossRepository,isDraft,mergeCommit"


@contextmanager
def publication_lock(path):
    # Lock order: task publication, then short lifecycle sections; never network under lifecycle.
    lock = path.with_suffix(".pr-lock")
    if any(p.is_symlink() for p in (path, path.with_suffix(".tmp"), *path.parents)):
        raise wt.Blocked("PR metadata must not be redirected")
    if os.name != "nt" and (
        path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o022
    ):
        raise wt.Blocked("PR metadata directory must belong to the current user")
    flags = os.O_CREAT | os.O_RDWR
    if os.name != "nt":
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock, flags, 0o600)
    try:
        opened, current = os.fstat(descriptor), lock.lstat()
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
            or os.name != "nt"
            and (current.st_uid != os.getuid() or current.st_mode & 0o022)
        ):
            raise wt.Blocked("PR publication lock must be owned and not redirected")
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
            raise wt.Blocked(
                "PR publication busy; retain worktree and retry"
            ) from error
        yield
    finally:
        # Keep the same inode; the OS releases ownership even after process death.
        os.close(descriptor)


def finalize(where, task_id, approval, *, draft=False):
    root, _, path, state = wt.load(where, task_id)
    with wt.lifecycle_lock(root):
        root, _, path, state = wt.load(root, task_id)
        if state.get("deployIdentity") or state.get("deployRepair") or state["merged"]:
            raise wt.Blocked("PR publication requires an ordinary unmerged task")
        if (
            path.with_suffix(".setup-lock").exists()
            or state.get("python_setup", {}).get("status") != "ready"
        ):
            raise wt.Blocked("Python setup must finish before PR intent selection")
        if state.get("integrationMode") not in (None, "pr"):
            raise wt.Blocked("Task integration mode changed; review required")
        if "draftRequested" not in state:
            state["draftRequested"] = draft
        state["integrationMode"] = "pr"
        wt.save(path, state)
    if not state.get("prPublication"):
        state = wt._finalize(root, task_id, approval)
    elif approval is not None and approval != state.get("validation_failure_approval"):
        raise wt.Blocked("PR candidate approval changed; review required")
    return publish(root, path, state)


def prepare(root, path, state, base_commit, candidate):
    """Called only at the existing validated integration exit, under lifecycle_lock."""
    target = wt.task_worktree(root, state)
    wt.integration_task(target, state)
    if not wt.paths(target, "diff", "--name-only", "-z", base_commit, candidate):
        raise wt.Blocked("no PR diff; empty PR publication refused")
    if (
        state.get("prPublication")
        or state["merged"]
        or candidate != state["tip"]
        or not state["verified"]
        or wt.output(target, "rev-parse", "HEAD") != candidate
        or wt.changed_paths(target)
        or wt.output(wt.base_worktree(root, state), "rev-parse", "HEAD") != base_commit
    ):
        raise wt.Blocked("PR candidate changed or is unverified; retain worktree")
    text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
    state["prPublication"] = dict(
        status="PREPARED",
        base=state["base"],
        head=state["branch"],
        baseCommit=base_commit,
        candidate=candidate,
        taskHash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        draftRequested=state.get("draftRequested", False),
    )
    wt.save(path, state)
    return state


def check_candidate(root, path, state):
    current, records = wt.worktree_state.load_with_records(root, state["task_id"])
    publication = state["prPublication"]
    target = wt.task_worktree(root, state, records=records)
    text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
    if (
        current[2] != path
        or current[3] != state
        or state.get("integrationMode") != "pr"
        or state["merged"]
        or not state["verified"]
        or state["tip"] != state["commit"]
        or state["tip"] != publication["candidate"]
        or publication["head"] != state["branch"]
        or publication["base"] != state["base"]
        or wt.output(target, "rev-parse", "HEAD") != publication["candidate"]
        or wt.changed_paths(target)
        or wt.output(
            wt.base_worktree(root, state, records=records), "rev-parse", "HEAD"
        )
        != publication["baseCommit"]
        or hashlib.sha256(text.encode("utf-8")).hexdigest() != publication["taskHash"]
    ):
        raise wt.Blocked(
            "PR candidate, Task, lifecycle or local base changed; review required"
        )
    wt.integration_task(target, state, records=records, expected_common=current[1])
    return target, text


def record(root, path, state, *, finish_update=False, progress_only=False, **values):
    with wt.lifecycle_lock(root):
        if progress_only:
            current = wt.load(root, state["task_id"])
            if current[2] != path or current[3] != state:
                raise wt.Blocked("PR lifecycle changed; retain worktree for review")
        else:
            check_candidate(root, path, state)
        state["prPublication"].update(values)
        if finish_update:
            state["prPublication"].pop("previousCandidate", None)
            state.pop("prUpdate", None)
        wt.save(path, state)


def repository_identity(url):
    match = re.fullmatch(
        r"(?:https://|ssh://git@|git@)([A-Za-z0-9.-]+)[/:]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?",
        url,
    )
    if not match:
        raise wt.Blocked(
            "origin must be an unambiguous GitHub HTTPS/SSH URL without credentials"
        )
    return match[1].lower(), match[2]


def gh(target, host, *arguments):
    environment = {
        **os.environ,
        "GH_HOST": host,
        "GH_PROMPT_DISABLED": "1",
        "GH_PAGER": "cat",
        "GH_NO_UPDATE_NOTIFIER": "1",
    }
    try:
        result = subprocess.run(
            ["gh", *arguments],
            cwd=target,
            env=environment,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise wt.Blocked(
            "GitHub CLI unavailable or timed out; retain PR intent and retry"
        ) from error
    if result.returncode:
        # gh/Git stderr can contain credential-bearing transport URLs.
        raise wt.Blocked(
            "GitHub CLI request failed; check authentication/permissions and retry"
        )
    return result.stdout


def remote_identity(target):
    urls = [
        wt.output(target, "remote", "get-url", *kind, "--all", "origin").splitlines()
        for kind in ((), ("--push",))
    ]
    if any(len(value) != 1 for value in urls) or urls[0] != urls[1]:
        raise wt.Blocked(
            "origin fetch/push URLs must identify one identical repository"
        )
    url = urls[0][0]
    host, repository = repository_identity(url)
    rewrites = wt.git(
        target,
        "config",
        "--get-regexp",
        r"^(url\..*\.(insteadof|pushinsteadof)|remote\.origin\.(mirror|receivepack))$",
        check=False,
    )
    if rewrites.returncode != 1:
        raise wt.Blocked(
            "Git URL rewrites/mirror/custom receivepack are not supported for PR publication"
        )
    gh(target, host, "auth", "status", "--hostname", host)
    info = json.loads(
        gh(
            target,
            host,
            "repo",
            "view",
            url,
            "--json",
            "nameWithOwner,url,viewerPermission",
        )
    )
    if (
        repository_identity(info["url"]) != (host, repository)
        or info["nameWithOwner"] != repository
        or info["viewerPermission"] not in {"ADMIN", "MAINTAIN", "WRITE"}
    ):
        raise wt.Blocked("GitHub repository identity or write permission mismatch")
    return dict(remote="origin", remoteUrl=url, repository=repository, host=host)


def remote_heads(target, publication):
    try:
        result = wt.git(
            target,
            "-c",
            "core.sshCommand=ssh -o BatchMode=yes",
            "ls-remote",
            "--heads",
            publication["remoteUrl"],
            f"refs/heads/{publication['base']}",
            f"refs/heads/{publication['head']}",
            timeout=60,
        )
    except (wt.Blocked, subprocess.TimeoutExpired):
        raise wt.Blocked(
            "cannot read PR remote refs; check transport access and retry"
        ) from None
    refs = {}
    for line in result.stdout.splitlines():
        sha, ref = line.split("\t")
        if not re.fullmatch(r"[0-9a-f]{40,64}", sha) or ref in refs:
            raise wt.Blocked("ambiguous remote refs; review required")
        refs[ref] = sha
    return refs


def remote_base(target, publication):
    branch = quote(publication["base"], safe="")
    result = json.loads(
        gh(
            target,
            publication["host"],
            "api",
            "--hostname",
            publication["host"],
            f"repos/{publication['repository']}/branches/{branch}",
        )
    )
    if result["commit"]["sha"] != publication["baseCommit"]:
        raise wt.Blocked(
            "GitHub base differs from validated local base; review required"
        )
    refs = remote_heads(target, publication)
    if refs.get(f"refs/heads/{publication['base']}") != publication["baseCommit"]:
        raise wt.Blocked(
            "remote base differs from validated local base; review required"
        )
    return refs.get(f"refs/heads/{publication['head']}")


def existing_pr(target, publication, *, states=("OPEN",), heads=None):
    repo = publication["host"] + "/" + publication["repository"]
    matches = json.loads(
        gh(
            target,
            publication["host"],
            "pr",
            "list",
            "--repo",
            repo,
            "--head",
            publication["head"],
            "--state",
            "all",
            "--limit",
            "100",
            "--json",
            PR_FIELDS,
        )
    )
    if len(matches) > 1:
        raise wt.Blocked("multiple PRs for this head; human review required")
    if not matches:
        if publication.get("number"):
            raise wt.Blocked("recorded PR is missing or retargeted; review required")
        return None
    # Re-read the selected PR rather than trusting a stale list response.
    result = json.loads(
        gh(
            target,
            publication["host"],
            "pr",
            "view",
            str(matches[0]["number"]),
            "--repo",
            repo,
            "--json",
            PR_FIELDS,
        )
    )
    if (
        result["state"] not in states
        or result["isCrossRepository"]
        or result["baseRefName"] != publication["base"]
        or result["headRefName"] != publication["head"]
        or result["headRefOid"] not in (heads or {publication["candidate"]})
        or publication.get("number", result["number"]) != result["number"]
        or publication.get("url", result["url"]) != result["url"]
        or result["url"]
        != f"https://{publication['host']}/{publication['repository']}/pull/{result['number']}"
    ):
        raise wt.Blocked(
            "PR closed/merged or identity differs from validated candidate; review required"
        )
    return result


def push_candidate(target, publication):
    hook = Path(
        wt.output(
            target,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "hooks/pre-push",
        )
    )
    if hook.exists() or hook.is_symlink():
        raise wt.Blocked(
            "existing pre-push hook needs review; PR publication never replaces it"
        )
    with tempfile.TemporaryDirectory(prefix="blueprint-pr-hooks-") as directory:
        guard = Path(directory) / "pre-push"
        # Git checks the advertised old OID again on receive, closing the query→push creation race.
        guard.write_text(
            "#!/bin/sh\nwhile read -r local_ref local_sha remote_ref remote_sha; do\n"
            + (
                f'  test "$remote_sha" = "{publication["previousCandidate"]}" || exit 1\n'
                if publication.get("previousCandidate")
                else '  case "$remote_sha" in ""|*[!0]*) exit 1 ;; esac\n'
            )
            + "done\n",
            encoding="utf-8",
        )
        guard.chmod(0o700)
        try:
            wt.git(
                target,
                "-c",
                "core.sshCommand=ssh -o BatchMode=yes",
                "-c",
                "push.followTags=false",
                "-c",
                "push.recurseSubmodules=no",
                "-c",
                "core.hooksPath=" + directory,
                "push",
                "--porcelain",
                publication["remoteUrl"],
                f"{publication['candidate']}:refs/heads/{publication['head']}",
                timeout=60,
            )
        except (wt.Blocked, subprocess.TimeoutExpired):
            raise wt.Blocked(
                "PR push failed; intent/worktree retained; retry to reconcile remote refs"
            ) from None


def publish(root, path, state):
    with wt.lifecycle_lock(root):
        target, text = check_candidate(root, path, state)
    publication = state["prPublication"]
    identity = remote_identity(target)
    if any(publication.get(key, value) != value for key, value in identity.items()):
        raise wt.Blocked("recorded PR repository/remote changed; review required")
    record(root, path, state, **identity)
    head = remote_base(target, publication)
    previous = publication.get("previousCandidate")
    if head is not None and (
        not publication.get("pushIntent")
        or head not in {publication["candidate"], previous}
    ):
        raise wt.Blocked("remote branch collision; no push performed")
    if head is None and publication.get("status") in {"PUSHED", "OPEN"}:
        raise wt.Blocked("published remote branch disappeared; review required")
    pr = existing_pr(target, publication, heads={publication["candidate"], previous})
    if pr and not publication.get("pushIntent"):
        raise wt.Blocked("unknown PR for this head; review required")
    if pr and head is None:
        raise wt.Blocked("PR branch disappeared; review required")
    if head is None or previous and head == previous:
        record(root, path, state, pushIntent=True)
        # Recheck remote/local boundaries immediately before the single non-force ref push.
        if remote_base(target, publication) != previous:
            raise wt.Blocked("remote branch changed before push; review required")
        with wt.lifecycle_lock(root):
            check_candidate(root, path, state)
        push_candidate(target, publication)

    if remote_base(target, publication) != publication["candidate"]:
        raise wt.Blocked("remote head differs after push; retain candidate")
    record(
        root,
        path,
        state,
        progress_only=True,
        status="OPEN" if publication["status"] == "OPEN" else "PUSHED",
    )
    pr = existing_pr(target, publication)
    if pr is None:
        if publication.get("createIntent"):
            raise wt.Blocked(
                "previous PR creation outcome is unconfirmed; retain intent for human review"
            )
        record(root, path, state, createIntent=True)
        with tempfile.TemporaryDirectory(prefix="blueprint-pr-") as directory:
            body = Path(directory) / "body.md"
            body.write_text(
                f"Task `{state['task_id']}`\n\n"
                + "\n".join(tasks.section(text, "## Task contract"))
                + "\n\nRequired changes\n"
                + "\n".join(tasks.section(text, "## Required changes"))
                + "\n\nAcceptance checks\n"
                + "\n".join(tasks.section(text, "## Acceptance checks"))
                + (
                    "\n\nValidation FAIL retained; Human Git integration approval: "
                    + state["validation_failure_approval"]
                    if state.get("validation_failure_approval")
                    else "\n\nRequired Task validation completed before publication."
                )
                + "\n",
                encoding="utf-8",
            )
            # No shared lifecycle lock is held across gh or Git network calls.
            if remote_base(target, publication) != publication["candidate"]:
                raise wt.Blocked("remote head changed before PR creation")
            with wt.lifecycle_lock(root):
                check_candidate(root, path, state)
            gh(
                target,
                publication["host"],
                "pr",
                "create",
                *(["--draft"] if publication.get("draftRequested") else []),
                "--repo",
                publication["host"] + "/" + publication["repository"],
                "--base",
                publication["base"],
                "--head",
                publication["head"],
                "--title",
                f"task({state['task_id']}): "
                + (
                    "human-approved validation failure"
                    if state.get("validation_failure_approval")
                    else "completed task"
                ),
                "--body-file",
                str(body),
            )
        pr = existing_pr(target, publication)
        if pr is None:
            raise wt.Blocked(
                "PR creation outcome unconfirmed; retry to reconcile existing PR"
            )
    if remote_base(target, publication) != publication["candidate"]:
        raise wt.Blocked("remote changed during PR publication; retain worktree")
    record(
        root,
        path,
        state,
        finish_update=bool(previous),
        status="OPEN",
        url=pr["url"],
        number=pr["number"],
        prState=pr["state"],
        isDraft=pr.get("isDraft", False),
        publishedHead=publication["candidate"],
    )
    return state


def update_refs(target, publication):
    """Read both providers and require an identical target-base reference."""
    branch = quote(publication["base"], safe="")
    result = json.loads(
        gh(
            target,
            publication["host"],
            "api",
            "--hostname",
            publication["host"],
            f"repos/{publication['repository']}/branches/{branch}",
        )
    )
    base = result["commit"]["sha"]
    refs = remote_heads(target, publication)
    if (
        not re.fullmatch(r"[0-9a-f]{40,64}", base)
        or refs.get("refs/heads/" + publication["base"]) != base
    ):
        raise wt.Blocked("GitHub and Git remote base references differ")
    return base, refs.get("refs/heads/" + publication["head"])


def update_snapshot(root, state, *, clean=True):
    target = wt.task_worktree(root, state)
    text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
    if tasks.status(text) not in {"running", "completed"}:
        raise wt.Blocked("PR update requires a running/completed Task; resume it first")
    if clean and (
        wt.changed_paths(target)
        or wt.output(target, "rev-parse", "HEAD") != state["prUpdate"]["candidate"]
        or state["tip"] != state["prUpdate"]["candidate"]
        or state["commit"] != state["prUpdate"]["candidate"]
        or not state["verified"]
    ):
        raise wt.Blocked("PR update candidate changed; validation cannot be reused")
    return target, text


def save_update(root, path, state, expected):
    with wt.lifecycle_lock(root):
        if wt.load(root, state["task_id"])[3] != expected:
            raise wt.Blocked("PR update lifecycle changed; retain intent")
        wt.save(path, state)


def validate_snapshot(interpreter, environment, snapshot, task_file, base, head):
    script = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, str(Path(sys.argv[1]) / 'framework/scripts')); "
        "import worktree_task as wt, task_contract_core as tasks; "
        "root=Path(sys.argv[1]).resolve(); name,base,head=sys.argv[2:]; "
        "text=tasks.read_task_snapshot(root,name,live=True).text; "
        "changed=wt.paths(root,'diff','--no-renames','--name-only','-z',base,head); "
        "scope=frozenset() if tasks.final_framework_task(text,changed) else "
        "frozenset(tasks.active_scope(root,task_file=name)); "
        "candidate=wt.FinalCandidate(root,root,name,text,base,head,frozenset(changed),scope); "
        "raise SystemExit(wt.validate_final_candidate(candidate).returncode)"
    )
    return subprocess.run(
        [str(interpreter), "-B", "-c", script, str(snapshot), task_file, base, head],
        cwd=snapshot,
        env=environment,
        capture_output=True,
        encoding="utf-8",
    )


def validate_update(where, task_id):
    """Validate a temporary integration without touching any registered worktree."""
    root, _, path, state = wt.load(Path(where), task_id)
    intent = state["prUpdate"]
    target, text = update_snapshot(root, state)
    if intent["status"] != "PREPARED":
        raise wt.Blocked("PR update intent changed before validation")
    task_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if task_hash != intent["taskHash"]:
        raise wt.Blocked("PR update Task changed before validation")
    publication = state["prPublication"]
    base, remote_head = update_refs(target, publication)
    expected_head = (
        intent["candidate"]
        if intent.get("pushConfirmed")
        else intent["previousCandidate"]
    )
    if remote_head != expected_head:
        raise wt.Blocked("remote HEAD differs from the expected published HEAD")
    existing_pr(target, publication, heads={expected_head})
    interpreter, environment = wt.python_env.runtime(target)
    # Independent clones create no registrations in the source repository; interrupted
    # clones can be removed by ordinary temporary-directory maintenance.
    with tempfile.TemporaryDirectory(prefix="blueprint-pr-validation-") as directory:
        snapshot = Path(directory) / "repository"
        wt.git(
            target,
            "clone",
            "--quiet",
            "--no-hardlinks",
            "--no-checkout",
            "--",
            str(target),
            str(snapshot),
        )
        wt.git(
            snapshot,
            "-c",
            "core.sshCommand=ssh -o BatchMode=yes",
            "fetch",
            "--no-tags",
            "--",
            publication["remoteUrl"],
            "refs/heads/" + publication["base"],
            timeout=60,
        )
        if wt.output(snapshot, "rev-parse", "FETCH_HEAD") != base:
            raise wt.Blocked("remote base changed during fetch; retry validation")
        if wt.git(
            snapshot,
            "merge-base",
            "--is-ancestor",
            intent.get("baselineBase", publication["baseCommit"]),
            base,
            check=False,
        ).returncode:
            raise wt.Blocked("remote base history was rewritten; review required")
        merged = wt.git(
            snapshot,
            "merge-tree",
            "--write-tree",
            base,
            intent["candidate"],
            check=False,
        )
        if merged.returncode:
            raise wt.Blocked("remote base and PR candidate conflict; no push")
        tree = merged.stdout.splitlines()[0]
        if not re.fullmatch(r"[0-9a-f]{40,64}", tree):
            raise wt.Blocked("cannot determine integration tree")
        commit = wt.output(
            snapshot,
            "-c",
            "user.name=Blueprint validation",
            "-c",
            "user.email=validation@invalid",
            "commit-tree",
            tree,
            "-p",
            base,
            "-p",
            intent["candidate"],
            "-m",
            "temporary PR integration validation",
        )
        wt.git(snapshot, "checkout", "--quiet", "--detach", commit)
        contract = snapshot / state["task_file"]
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text(text, encoding="utf-8")
        result = validate_snapshot(
            interpreter, environment, snapshot, state["task_file"], base, commit
        )
        if result.returncode:
            error = wt.Blocked("PR update integration validation failed; no push")
            error.diagnostics = dict(
                returncode=result.returncode, stdout=result.stdout, stderr=result.stderr
            )
            raise error
        if (
            wt.output(snapshot, "rev-parse", "HEAD") != commit
            or wt.output(snapshot, "rev-parse", "HEAD^{tree}") != tree
            or wt.changed_paths(snapshot)
            or tasks.read_task_snapshot(snapshot, state["task_file"], live=True).text
            != text
        ):
            raise wt.Blocked("integration snapshot changed during validation")
    with wt.lifecycle_lock(root):
        if wt.load(root, task_id)[3] != state:
            raise wt.Blocked("PR update intent changed during validation")
        _, current_text = update_snapshot(root, state)
        if current_text != text:
            raise wt.Blocked("PR update Task changed during validation")
        intent.update(
            status="VALIDATED",
            baseCommit=base,
            baselineBase=base,
            integrationTree=tree,
            taskHash=task_hash,
            validation="PASS",
        )
        wt.save(path, state)


def update(where, task_id):
    root, _, path, state = wt.load(where, task_id)
    with publication_lock(path):
        root, _, path, state = wt.load(root, task_id)
        publication = state.get("prPublication", {})
        if (
            state.get("integrationMode") != "pr"
            or not publication.get("number")
            or state["merged"]
        ):
            raise wt.Blocked("PR update requires this Task's published open PR")
        identity = remote_identity(root)
        if any(publication.get(k) != v for k, v in identity.items()):
            raise wt.Blocked("recorded PR repository/remote changed")
        intent = state.get("prUpdate")
        if intent and intent.get("pushIntent"):
            head = remote_heads(root, publication).get(
                "refs/heads/" + publication["head"]
            )
            base = None
        else:
            base, head = update_refs(root, publication)
        if (
            intent
            and not intent.get("pushConfirmed")
            and publication.get("candidate") != intent["previousCandidate"]
        ):
            raise wt.Blocked("published HEAD does not match the retained update intent")
        if intent and intent.get("pushIntent"):
            if head not in {intent["previousCandidate"], intent["candidate"]}:
                raise wt.Blocked("remote HEAD changed unexpectedly after push intent")
            existing_pr(root, publication, heads={head})
            if head == intent["candidate"]:
                if (
                    intent.get("status")
                    not in {"VALIDATED", "PUBLISHED_REVIEW", "PREPARED"}
                    or (
                        intent.get("validation") != "PASS"
                        and not (
                            intent.get("pushConfirmed")
                            and intent.get("validation") == "STALE"
                        )
                    )
                    or not re.fullmatch(r"[0-9a-f]{40,64}", intent.get("candidate", ""))
                    or not re.fullmatch(
                        r"[0-9a-f]{40,64}", intent.get("baseCommit", "")
                    )
                    or not re.fullmatch(
                        r"[0-9a-f]{40,64}", intent.get("integrationTree", "")
                    )
                    or not re.fullmatch(r"[0-9a-f]{64}", intent.get("taskHash", ""))
                    or publication.get("candidate")
                    not in {intent["previousCandidate"], head}
                ):
                    raise wt.Blocked("published candidate lacks validated push intent")
                with wt.lifecycle_lock(root):
                    if wt.load(root, task_id)[3] != state:
                        raise wt.Blocked("PR lifecycle changed after push")
                    publication.update(
                        candidate=head,
                        publishedHead=head,
                        taskHash=intent["taskHash"],
                        baseCommit=intent["baseCommit"],
                    )
                    state.pop("prUpdate")
                    wt.save(path, state)
                return state
            if intent.get("pushConfirmed"):
                raise wt.Blocked("confirmed published HEAD changed; retain intent")
            base, head = update_refs(root, publication)
        if not intent:
            existing_pr(root, publication, heads={publication["candidate"]})
            if head != publication["candidate"]:
                raise wt.Blocked(
                    "remote HEAD differs from the published HEAD; no update"
                )
            with wt.lifecycle_lock(root):
                if wt.load(root, task_id)[3] != state:
                    raise wt.Blocked("PR lifecycle changed before update")
                target = wt.task_worktree(root, state)
                if wt.output(target, "rev-parse", "HEAD") == publication[
                    "candidate"
                ] and not wt.changed_paths(target):
                    raise wt.Blocked("PR update requires a new descendant candidate")
                if path.with_suffix(".setup-lock").exists() or state.get(
                    "validation_failure_approval"
                ):
                    raise wt.Blocked(
                        "PR update requires ready setup and successful new validation"
                    )
                intent = state["prUpdate"] = dict(
                    previousCandidate=publication["candidate"], status="PREPARING"
                )
                wt.save(path, state)
        if intent["status"] == "VALIDATED":
            target, text = update_snapshot(root, state)
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != intent["taskHash"]:
                raise wt.Blocked("validated Task changed; validation cannot be reused")
            if base != intent["baseCommit"]:
                prior = copy.deepcopy(state)
                intent.update(status="PREPARED", validation="STALE")
                save_update(root, path, state, prior)
                raise wt.Blocked(
                    "remote base advanced after validation; retry to revalidate"
                )
        if intent["status"] in {"PREPARING", "PREPARED"}:
            with wt.lifecycle_lock(root):
                if wt.load(root, task_id)[3] != state:
                    raise wt.Blocked("PR update lifecycle changed before preparation")
                target = wt.task_worktree(root, state)
                text = tasks.read_task_snapshot(
                    target, state["task_file"], live=True
                ).text
                if tasks.status(text) not in {"running", "completed"}:
                    raise wt.Blocked(
                        "PR update requires a running/completed Task; resume it first"
                    )
                head_now = wt.output(target, "rev-parse", "HEAD")
                changed = wt.changed_paths(target)
                if (
                    intent["status"] == "PREPARING"
                    or changed
                    or head_now != intent["candidate"]
                ):
                    if intent.get("pushConfirmed"):
                        raise wt.Blocked("published candidate changed during recovery")
                    wt._prepare_commit(root, path, state, target, None, pr_update=True)
                    if state["tip"] == intent["previousCandidate"]:
                        raise wt.Blocked(
                            "PR update requires a new descendant candidate"
                        )
                    intent.update(candidate=state["tip"], validation="PENDING")
                    intent.pop("pushIntent", None)
                intent.update(
                    status="PREPARED",
                    taskHash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
                for key in ("baseCommit", "integrationTree"):
                    intent.pop(key, None)
                wt.save(path, state)
            target = wt.task_worktree(root, state)
            interpreter, environment = wt.python_env.runtime(target)
            result = subprocess.run(
                [
                    str(interpreter),
                    "-B",
                    "-c",
                    f"import sys, json; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); from worktree_pr import validate_update; import worktree_task as wt\ntry: validate_update(sys.argv[1], sys.argv[2])\nexcept wt.Blocked as error:\n print('PR_VALIDATOR_DIAGNOSTICS=' + json.dumps(getattr(error, 'diagnostics', None)), file=sys.stderr); print(str(error), file=sys.stderr); sys.exit(1)",
                    str(root),
                    task_id,
                ],
                cwd=target,
                env=environment,
                capture_output=True,
                encoding="utf-8",
            )
            if result.returncode:
                error = wt.Blocked(
                    "PR update candidate validation failed; intent retained"
                )
                error.diagnostics = dict(
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
                for line in result.stderr.splitlines():
                    if line.startswith("PR_VALIDATOR_DIAGNOSTICS="):
                        details = json.loads(line.partition("=")[2])
                        if isinstance(details, dict):
                            error.diagnostics = details
                        break
                raise error
            state = wt.load(root, task_id)[3]
            publication = state["prPublication"]
            intent = state["prUpdate"]
        target, text = update_snapshot(root, state)
        if (
            intent["status"] != "VALIDATED"
            or intent.get("validation") != "PASS"
            or not re.fullmatch(r"[0-9a-f]{40,64}", intent.get("integrationTree", ""))
            or hashlib.sha256(text.encode("utf-8")).hexdigest() != intent["taskHash"]
        ):
            raise wt.Blocked("PR update validation is missing or stale")
        if not intent.get("pushConfirmed"):
            prior = copy.deepcopy(state)
            intent["pushIntent"] = True
            save_update(root, path, state, prior)
            base, head = update_refs(target, publication)
            existing_pr(target, publication, heads={intent["previousCandidate"]})
            with wt.lifecycle_lock(root):
                if wt.load(root, task_id)[3] != state:
                    raise wt.Blocked("PR lifecycle changed before push")
                _, current = update_snapshot(root, state)
                if (
                    hashlib.sha256(current.encode("utf-8")).hexdigest()
                    != intent["taskHash"]
                ):
                    raise wt.Blocked("PR Task changed before push")
            if base != intent["baseCommit"] or head != intent["previousCandidate"]:
                raise wt.Blocked("PR base or head changed before push")
            push_candidate(
                target,
                dict(
                    publication,
                    candidate=intent["candidate"],
                    previousCandidate=intent["previousCandidate"],
                ),
            )
        head = remote_heads(target, publication).get(
            "refs/heads/" + publication["head"]
        )
        if head != intent["candidate"]:
            raise wt.Blocked("remote HEAD differs after push; retain intent")
        existing_pr(target, publication, heads={intent["candidate"]})
        with wt.lifecycle_lock(root):
            if wt.load(root, task_id)[3] != state:
                raise wt.Blocked("PR lifecycle changed after push")
            publication.update(
                candidate=head,
                publishedHead=head,
                taskHash=intent["taskHash"],
                baseCommit=intent["baseCommit"],
            )
            state.pop("prUpdate")
            wt.save(path, state)
        return state


def operate(where, task_id, action, *, method="merge"):
    root, _, path, state = wt.load(where, task_id)
    with publication_lock(path):
        root, _, path, state = wt.load(root, task_id)
        publication = state.get("prPublication", {})
        if state.get("integrationMode") != "pr" or not publication.get("number"):
            raise wt.Blocked("PR operation requires this Task's published PR")
        if state.get("prUpdate"):
            raise wt.Blocked("finish the pending PR update before another PR operation")
        identity = remote_identity(root)
        if any(publication.get(k) != v for k, v in identity.items()):
            raise wt.Blocked("recorded PR repository/remote changed")
        pr = existing_pr(root, publication, states=("OPEN", "CLOSED", "MERGED"))
        repo = publication["host"] + "/" + publication["repository"]
        if action != "pr-status" and pr["state"] == "OPEN":
            if action == "pr-merge":
                with wt.lifecycle_lock(root):
                    if wt.load(root, task_id)[3] != state:
                        raise wt.Blocked("PR lifecycle changed before merge")
                    publication["mergeIntent"] = True
                    wt.save(path, state)
                gh(
                    root,
                    publication["host"],
                    "pr",
                    "merge",
                    str(pr["number"]),
                    "--repo",
                    repo,
                    "--" + method,
                    "--match-head-commit",
                    publication["candidate"],
                )
            elif action == "pr-close":
                gh(
                    root,
                    publication["host"],
                    "pr",
                    "close",
                    str(pr["number"]),
                    "--repo",
                    repo,
                )
            elif action in {"pr-draft", "pr-ready"}:
                gh(
                    root,
                    publication["host"],
                    "pr",
                    "ready",
                    str(pr["number"]),
                    "--repo",
                    repo,
                    *(["--undo"] if action == "pr-draft" else []),
                )
            pr = existing_pr(root, publication, states=("OPEN", "CLOSED", "MERGED"))
        with wt.lifecycle_lock(root):
            if wt.load(root, task_id)[3] != state:
                raise wt.Blocked("PR lifecycle changed during GitHub operation")
            publication.update(
                status=pr["state"],
                prState=pr["state"],
                isDraft=pr.get("isDraft", False),
            )
            if pr["state"] == "MERGED":
                merged = (pr.get("mergeCommit") or {}).get("oid")
                if not merged or not re.fullmatch(r"[0-9a-f]{40,64}", merged):
                    raise wt.Blocked(
                        "PR merge result is unknown; retain state and reconcile"
                    )
                state["githubMerged"] = dict(
                    number=pr["number"],
                    repository=repo,
                    candidate=publication["candidate"],
                    mergeCommit=merged,
                )
                state["merged"] = merged
            wt.save(path, state)
            if pr["state"] == "MERGED" and action in {"pr-merge", "pr-status"}:
                return wt.cleanup_state(root, path, state)
        return state


def close_existing(where, reference):
    """Close by explicit number/URL after local lifecycle cleanup; never delete a branch."""
    root = wt.repository(where)[2]
    identity = remote_identity(root)
    repo = identity["host"] + "/" + identity["repository"]
    if not re.fullmatch(r"[1-9][0-9]*", reference):
        match = re.fullmatch(
            r"https://" + re.escape(repo) + r"/pull/([1-9][0-9]*)", reference
        )
        if not match:
            raise wt.Blocked("PR URL must match this repository")
        reference = match[1]
    pr = json.loads(
        gh(
            root,
            identity["host"],
            "pr",
            "view",
            reference,
            "--repo",
            repo,
            "--json",
            PR_FIELDS,
        )
    )
    if (
        str(pr["number"]) != reference
        or pr["url"] != f"https://{repo}/pull/{reference}"
    ):
        raise wt.Blocked("PR identity mismatch")
    if pr["state"] == "OPEN":
        gh(root, identity["host"], "pr", "close", reference, "--repo", repo)
        pr = json.loads(
            gh(
                root,
                identity["host"],
                "pr",
                "view",
                reference,
                "--repo",
                repo,
                "--json",
                PR_FIELDS,
            )
        )
    return {"prPublication": pr}
