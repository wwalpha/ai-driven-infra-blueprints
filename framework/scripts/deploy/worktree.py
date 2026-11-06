"""Deploy selection and fixed managed-worktree authority, independent of local base."""

import copy
from pathlib import Path

import task_contract_core as tasks
import worktree_state as ws
import worktree_task as wt
from contracts.target import IAC_ENGINE_KEY
from utils.project_targets import load_target_directory


def is_deploy(text):
    lines = tasks.section(text, "## Task contract")
    return (
        "- Task type: `infrastructure`" in lines
        and "- Infrastructure phase: `deploy`" in lines
    )


def require(root, snapshot=None):
    snapshot = snapshot or tasks.task_snapshot(root, executable=False, live=True)
    if not is_deploy(snapshot.text):
        return None
    _, state = ws.deploy_task_state(root, snapshot.name, required=True)
    if Path(state["worktree"]) != root:
        raise ws.Blocked("source write requires its managed worktree")
    if state.get("python_setup", {}).get("status") != "ready":
        raise ws.Blocked("Deploy requires successful managed Python setup")
    if state.get("deployContractUpdate"):
        raise ws.Blocked(
            "unfinished Deploy contract correction; retry --correct-deploy-contract"
        )
    if (
        state.get("deployIdentity", {}).get("taskDigest", snapshot.task_digest)
        != snapshot.task_digest
    ):
        raise ws.Blocked("Deploy contract differs from its fixed snapshot authority")
    return state


def bind(root, task, target, environment, stacks):
    state = require(root, task)
    if state is None:
        return
    identity = dict(
        taskFile=task.name,
        taskDigest=task.task_digest,
        target=target,
        environment=environment,
        stacks=sorted(stacks),
        snapshot=state["start"],
    )
    primary, _, path, _ = ws.load(root, state["task_id"])
    with wt.lifecycle_lock(primary):
        state = require(root, task)
        if state.get("deployIdentity", identity) != identity:
            raise ws.Blocked("Deploy Task/Target/Stack/snapshot identity changed")
        state["deployIdentity"] = identity
        state.setdefault("deployContract", task.text)
        wt.save(path, state)
        return copy.deepcopy(identity)


def prepare_complete(root, task):
    require_complete(root, task)


def require_complete(root, task):
    if not is_deploy(task.text):
        return
    state = require(root, task)
    if not state.get("deployIdentity"):
        targets = {
            (environment, directory) for environment, directory, _ in task.scope or ()
        }
        if (
            len(targets) == 1
            and load_target_directory(root, *next(iter(targets)))[IAC_ENGINE_KEY]
            == "terraform"
        ):
            return
        raise ws.Blocked("managed Deploy has no fixed identity")
    progress = wt.module("deploy/progress.py", "deploy.progress")
    completion = wt.module("deploy/completion.py", "deploy.completion")
    saved = progress.read_progress(root, state)
    if completion.candidate_incomplete(
        task, state, saved, lambda: wt.output(root, "rev-parse", state["tip"] + "^{tree}")
    ):
        raise ws.Blocked(
            "Deploy final candidate is incomplete; use sync --final or resume the saved checkpoint"
        )
