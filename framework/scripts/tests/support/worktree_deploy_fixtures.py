"""Managed parent setup for dedicated Worktree repair integration only."""

import os
import shutil
import sys
import sysconfig
import venv
from pathlib import Path

import worktree_task as wt
from deploy import progress as deploy_progress
from model.dependency_index import rebuild as rebuild_index
from support.deploy_controller_fixtures import invoke
from support.deploy_controller_fixtures import seed as seed_project
from support.repository_fixtures import git
from task_contract_core import start


def pin_progress(backend, identity):
    backend.progress_identity = identity
    backend.progress_root = backend.root.resolve()
    backend.progress_directory = backend.run_context.get("directory")
    backend.progress_destination = deploy_progress.progress_path(backend.root, create=True)
    backend.run_context["repository"] = str(backend.root)
    backend.run_context.setdefault("consumedInputs", {})
    backend.run_context.setdefault("stepUnits", [])
    backend.target = identity["target"]
    backend.run_context.update(
        {
            key: identity[key]
            for key in ("taskFile", "taskDigest", "target", "environment")
        }
    )


def seed(root, state_path, case="orders", **kwargs):
    seed_project(root, state_path, case, **kwargs)
    task = root / "tasks/deploy.md"
    ignore = root / ".gitignore"
    ignore.write_text(ignore.read_text() + "/.worktrees/\n")
    # A local requirements file makes this fixture its own Framework definition root.
    shutil.copytree(
        Path(wt.__file__).resolve().parents[1],
        root / "framework",
        ignore=shutil.ignore_patterns("__pycache__", "tests"),
    )
    skill = root / ".agents/skills/deploy/SKILL.md"
    skill.parent.mkdir(parents=True)
    shutil.copyfile(
        Path(wt.__file__).resolve().parents[2] / skill.relative_to(root), skill
    )
    requirements = root / wt.python_env.REQUIREMENTS
    requirements.write_text("", encoding="utf-8")
    git(root, "add", ".gitignore", "framework", skill.relative_to(root).as_posix())
    git(root, "commit", "-qm", "Managed fixture ignores")
    # Provision only the interpreter offline; dependencies come from this fixed test runtime.

    directory = root / ".worktrees/.blueprint/python-env"
    venv.EnvBuilder(with_pip=False).create(directory)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    packages = directory / "lib" / version / "site-packages"
    (packages / "fixture-runtime.pth").write_text(sysconfig.get_path("purelib") + "\n")
    for marker in (".blueprint-owner", ".blueprint-ready"):
        (directory / marker).write_text(str(directory))
    (directory / wt.python_env.APPLIED).write_text(
        wt.python_env.hashlib.sha256(requirements.read_bytes()).hexdigest(),
        encoding="utf-8",
    )
    saved_contract = (
        "\n".join(
            line
            for line in task.read_text().splitlines()
            if not line.startswith("- `infra/")
        )
        + "\n"
    )
    state = wt.create(root, "deploy")
    target = Path(state["worktree"])
    start(target, state["task_file"], saved_contract.replace("tasks/deploy.md", state["task_file"]))
    rebuild_index(target)
    return target


if __name__ == "__main__":
    root, state_path, aws_path = map(lambda arg: Path(arg).resolve(), sys.argv[1:4])
    os.chdir(root)
    raise SystemExit(
        invoke(
            root,
            state_path,
            aws_path,
            sys.argv[4:],
            fault=os.environ.get("BLUEPRINT_OBSERVED_FAULT"),
        )
    )
