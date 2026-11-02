#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import shutil
import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import io
import venv
from contextlib import redirect_stderr
from unittest import TestCase

import import_guard as _imports_import_guard
import support.import_model_fixtures as _imports_support_import_model_fixtures
import task_contract_runtime
import validation.loop as _imports_validation_loop
import worktree_pr as pr
from import_guard import require_import_changes
from model.adapters.task import edit_write_context
from model.sources import load_model
from support import blueprint_loop_fixtures as loop_checks
from support.import_model_fixtures import (
    dependency_fixture,
)
from support.it_case_receipt import it_case
from support.model_sources import write_model
from support.worktree_task_fixtures import (
    SCRIPT,
    Path,
    cli,
    finish_contract,
    fixture,
    git,
    json,
    os,
    patch,
    retained,
    start,
    subprocess,
    sys,
    tasks,
    tempfile,
    wt,
)
from support.worktree_task_fixtures import (
    contract as contract,
)
from utils import sealed_evidence
from utils.aws_mappings import mapping_alias
from validation import loop

from model import prepare_edit, publish_edit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def check_implement_rebases_on_latest_base():
    check = TestCase()
    with fixture() as root:
        target, state = start(root)
        contract_path = target / state["task_file"]
        text = (
            contract_path.read_text(encoding="utf-8")
            .replace("`governance`", "`infrastructure`")
            .replace(
                "- Task status:", "- Infrastructure phase: `implement`\n- Task status:"
            )
            .replace("`framework`", "`dev/team/iam`")
        )
        contract_path.write_text(text, encoding="utf-8")
        (target / "file.txt").write_text("task change\n", encoding="utf-8")
        (root / "upstream.txt").write_text("latest base\n", encoding="utf-8")
        git(root, "add", "upstream.txt")
        git(root, "commit", "-qm", "independent base change")
        latest = git(root, "rev-parse", "HEAD")
        _, _, path, state = wt.load(root, "example")
        check.assertEqual(wt._prepare_commit(root, path, state, target, None), latest)
        git(root, "merge", "--ff-only", state["branch"])
        check.assertEqual((root / "file.txt").read_text(), "task change\n")
        check.assertEqual((root / "upstream.txt").read_text(), "latest base\n")
        check.assertEqual(git(root, "rev-list", "--count", latest + "..HEAD"), "1")


@it_case
def check_sync_base_preserves_candidate():
    with fixture() as root:
        target, state = start(root, files=("file.txt",))
        old = state["start"]
        (root / "file.txt").write_text("upstream\n")
        (root / "upstream.txt").write_text("inherited\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "reviewed upstream")
        latest = git(root, "rev-parse", "HEAD")
        (target / "file.txt").write_text("upstream\nreviewed candidate\n")
        saved = wt.sync_base(target, "example", latest)
        assert (
            saved["start"] == old and saved["tip"] == saved["validation_base"] == latest
        )
        assert saved["commit"] is None and git(target, "rev-parse", "HEAD") == latest
        assert (target / "file.txt").read_text() == "upstream\nreviewed candidate\n"
        assert (target / "upstream.txt").read_text() == "inherited\n"
        assert tasks.status((target / state["task_file"]).read_text()) == "running"
        finish_contract(target, state)
        assert cli(root, "finalize")["cleaned"]


@it_case
def check_old_workflow_registry_is_ignored():
    with fixture() as primary:
        directory = wt.metadata_directory(primary) / "deploy-workflows"
        directory.mkdir(parents=True)
        retained = directory / "old.json"
        retained.write_text('{"workflowId":"old","status":"unfinished"}')
        target, state = start(primary, task_id="new-deploy", files=("file.txt",))
        assert target.is_dir() and state["task_id"] == "new-deploy"
        assert retained.read_text() == '{"workflowId":"old","status":"unfinished"}'


@it_case
def check_success_and_empty():
    for empty in (False, True):
        with fixture() as root:
            before = git(root, "rev-parse", "HEAD")
            target, state = start(root, files=("file.txt", "追加 file.txt"))
            if not empty:
                (target / "file.txt").write_text("task\n", encoding="utf-8")
                (target / "追加 file.txt").write_text("new\n", encoding="utf-8")
            else:
                (target / "file.txt").write_text("staged, then canceled\n")
                git(target, "add", "file.txt")
                (target / "file.txt").write_text("original\n")
            finish_contract(target, state)
            wt.integration_task(target, state)
            result = cli(
                target, "finalize"
            )  # CLI uses the task cwd, not the helper's location.
            assert result["cleaned"]
            assert not wt.branch_exists(root, state["branch"])
            assert git(root, "status", "--porcelain") == ""
            assert git(root, "rev-list", "--count", "HEAD") == ("1" if empty else "2")
            assert bool(result["commit"]) != empty
            if empty:
                assert git(root, "rev-parse", "HEAD") == before
            else:
                assert (root / "file.txt").read_text() == "task\n"
                assert (root / "追加 file.txt").read_text() == "new\n"
                assert (
                    git(root, "log", "-1", "--format=%s")
                    == "task(example): completed task"
                )
                assert not wt.paths(root, "ls-files", "-z", "tasks")
    print("Normal/zero-change lifecycle: PASS")


@it_case
def check_finalize_line_endings():
    check = TestCase()
    content = b"task\r\n"
    with fixture() as root:
        rules = "blank-at-eol,blank-at-eof,space-before-tab"
        git(root, "config", "core.whitespace", rules)
        target, state = start(root)
        (target / "file.txt").write_bytes(content)
        finish_contract(target, state)
        result = cli(root, "finalize")
        check.assertTrue(result["cleaned"])
        check.assertEqual((root / "file.txt").read_bytes(), content)
        check.assertEqual(git(root, "config", "core.whitespace"), rules)


@it_case
def check_metadata_storage():
    with fixture() as root:
        target, first = start(root, "one")
        other, second = start(target, "two")
        directory = root / ".worktrees/.blueprint"
        path = directory / "tasks/one.json"
        sibling = directory / "tasks/two.json"
        assert wt.load(target, "one")[2] == path
        assert wt.load(other, "one")[2] == path
        assert json.loads(path.read_text(encoding="utf-8"))["worktree"] == str(target)
        assert sibling.is_file()
        with wt.lifecycle_lock(root):
            lock = directory / "lifecycle.lock"
            assert lock.is_dir()
            assert lock.is_dir()
        # Old metadata and locks neither authorize a task nor block the new lifecycle.
        old = root / ".git/blueprint-worktree-tasks/one.json"
        old.parent.mkdir()
        old.write_text("invalid old state", encoding="utf-8")
        (root / ".git/blueprint-worktree-lifecycle.lock").mkdir()
        cli(other, "setup", "one")
        sibling_before = sibling.read_bytes()
        finish_contract(target, first)
        assert cli(target, "finalize", "one")["cleaned"]
        assert sibling.read_bytes() == sibling_before and other.is_dir()
        assert old.read_text(encoding="utf-8") == "invalid old state"
        cli(root, "setup", "two")
        finish_contract(other, second)
        assert cli(root, "finalize", "two")["cleaned"]
        assert directory.is_dir()


@it_case
def check_human_approved_validation_failure():
    check = TestCase()
    approval = (
        "Human approves Git integration of the fixture's retained validation failure"
    )
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n", encoding="utf-8")
        tasks.suspend(
            target,
            state["task_file"],
            "Previously reviewed synthetic validation failure",
        )
        result = cli(root, "finalize", approval=approval)
        check.assertTrue(result["cleaned"] and result["merged"])
        check.assertEqual(result["validation_failure_approval"], approval)
        check.assertEqual((root / "file.txt").read_text(), "task\n")
        check.assertEqual(
            git(root, "log", "-1", "--format=%s"),
            "task(example): human-approved validation failure",
        )
        check.assertIn(approval, git(root, "log", "-1", "--format=%b"))


@it_case
def check_normal_model_final_candidate():
    _check_normal_model_final_candidate()


def _callback_normal_model_candidate(root, options, *, final_candidate):
    assert tasks.status((root / final_candidate.task_file).read_text()) == "running"
    with tasks.selected_task(root, final_candidate.task_file):
        require_import_changes(
            root, final_candidate.changed_paths, final_candidate=final_candidate
        )
    return 0


def _check_normal_model_final_candidate():
    relative = "model/stg/cde/service-a.properties"
    with fixture() as root:
        dependency_fixture(root)
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "Model fixture")
        target, state = start(root, files=(relative,))
        task = target / state["task_file"]
        text = (
            task.read_text()
            .replace("`governance`", "`design`")
            .replace(
                "- Task status:",
                "- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n- Task status:",
            )
            .replace("- `framework`", "- `stg/cde/service-a`\n- `stg/cde/service-b`")
        )
        task.write_text(text)
        source = target / relative
        source.write_text(source.read_text() + "\n# ordinary correction\n")
        (root / "upstream.txt").write_text("latest\n")
        git(root, "add", "upstream.txt")
        git(root, "commit", "-qm", "advance base")
        latest = git(root, "rev-parse", "HEAD")
        with mapping_alias(SCRIPT.parents[2], target):
            candidate = wt.prepare_integration(root, "example")
            assert candidate.base_commit == latest
            assert wt.task_start_commit(target, state["task_file"]) == latest
            assert wt.committed_task_paths(target, state["task_file"]) == {relative}
            assert tasks.final_model_task(
                text, wt.integration_changed_paths(target, state["task_file"])
            )
            validate = _callback_normal_model_candidate
            with patch.object(loop, "run_loop", side_effect=validate) as checked:
                result = wt.validate_final_candidate(candidate)
                checked.assert_called_once()
            assert (
                wt.merge_validated_candidate(result)["merged"]
                == candidate.candidate_head
            )
            assert tasks.status(task.read_text()) == "completed"
            assert git(root, "rev-parse", "HEAD") == candidate.candidate_head
            assert wt.cleanup(root, "example")["cleaned"]


@it_case
def check_registered_normal_model_guard():
    relative = "model/stg/cde/service-a.properties"
    with fixture() as root:
        dependency_fixture(root)
        # Requirements select local definitions, so provision the complete Framework.
        shutil.copytree(
            Path(wt.__file__).resolve().parents[1],
            root / "framework",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        requirements = root / wt.python_env.REQUIREMENTS
        requirements.write_text("", encoding="utf-8")
        (root / ".gitignore").write_text((root / ".gitignore").read_text() + ".venv/\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "synthetic runtime fixture")
        target, state = start(root, files=(relative,))
        contract_path = target / state["task_file"]
        text = (
            contract_path.read_text()
            .replace("`governance`", "`design`")
            .replace("- `framework`", "- `stg/cde/service-a`\n- `stg/cde/service-b`")
        )
        contract_path.write_text(text)
        directory = wt.python_env.shared_directory(root)
        directory.mkdir()
        (directory / ".blueprint-owner").write_text(str(directory))
        venv.EnvBuilder(with_pip=False).create(directory)
        interpreter = wt.python_env.python_path(directory)
        site = subprocess.run(
            [
                str(interpreter),
                "-c",
                'import sysconfig; print(sysconfig.get_path("purelib"))',
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        # Reuse installed test dependencies offline; the fixture never invokes pip/setup.
        Path(site, "fixture-dependencies.pth").write_text(
            "\n".join(p for p in sys.path if p.endswith("site-packages")) + "\n"
        )
        probe = root.parent / "guard-probe.json"
        Path(site, "guard_probe.py").write_text(
            """import sys, json, atexit, os
from pathlib import Path
counts = {}
def profile(frame, event, arg):
    if event != 'call': return
    name, file = frame.f_code.co_name, Path(frame.f_code.co_filename).name
    if file == 'worktree_task.py' and name in ('lifecycle_lock', 'finalize', 'prepare_integration', 'cleanup'):
        raise AssertionError('guard child entered lifecycle')
    if file in ('references.py', 'sources.py') and name in ('usages', '_read_model', 'raw_model'):
        assert sys.modules['utils.input_cache'].memo_table() is not None
        counts[name] = counts.get(name, 0) + 1
sys.setprofile(profile)
atexit.register(lambda: Path(os.environ['GUARD_PROBE']).write_text(json.dumps(counts)))
""",
            encoding="utf-8",
        )
        Path(site, "guard-probe.pth").write_text(
            "import guard_probe\n", encoding="utf-8"
        )
        (directory / ".blueprint-ready").write_text(str(directory))
        (directory / wt.python_env.APPLIED).write_text(
            wt.python_env.hashlib.sha256(requirements.read_bytes()).hexdigest(),
            encoding="utf-8",
        )
        state["python_setup"] = dict(
            status="ready",
            kind="shared",
            installed=False,
            interpreter=str(interpreter),
            bin=str(interpreter.parent),
        )
        _, _, state_path, _ = wt.load(root, "example")
        wt.save(state_path, state)
        (target / relative).write_text(
            (target / relative).read_text() + "\n# ordinary save\n"
        )
        finish_contract(target, state)
        environment = {
            **os.environ,
            "BLUEPRINT_TASK_FILE": "tasks/foreign.md",
            "GUARD_PROBE": str(probe),
        }
        parent = [
            sys.executable,
            "-S",
            "-B",
            "-c",
            "import sys, importlib.util; "
            'assert importlib.util.find_spec("pystache") is None; '
            "sys.path.insert(0, sys.argv.pop(1)); "
            "import worktree_task; raise SystemExit(worktree_task.main())",
            str(SCRIPT.parent),
            "finalize",
            "--repository-root",
            str(root),
            "--task-id",
            "example",
        ]
        result = subprocess.run(
            parent,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        response = json.loads(result.stdout)
        assert result.returncode == 0, response
        assert response["cleaned"] and response["merged"]
        counts = json.loads(probe.read_text())
        assert counts.get("usages", 0) == 0 and counts["raw_model"] >= 1, counts
        assert not target.exists()
        assert wt.python_env.shared_ready(directory)
        assert (root / relative).read_text().endswith("# ordinary save\n")
    print(
        "Ordinary Model guard in registered shared venv with dependency-free parent: PASS"
    )


class PRGitHub:
    """Offline gh responses, with real Git publication to a private bare repository."""

    url = "https://github.com/fixture/repository.git"

    def __init__(self, root, state):
        self.root, self.state = root, state
        self.remote = root.parent / "remote.git"
        git(
            root,
            "clone",
            "--bare",
            "--quiet",
            "--single-branch",
            "--branch",
            state["base"],
            str(root),
            str(self.remote),
        )
        git(root, "remote", "add", "origin", self.url)
        git(Path(state["worktree"]), "remote", "get-url", "origin")
        self.real_git, self.real_run = wt.git, subprocess.run
        self.pr, self.created = None, 0
        self.validations = []

    def git(self, root, *args, **kwargs):
        if "push" in args:
            assert not any(str(arg).startswith("--force") for arg in args)
        return self.real_git(
            root,
            *(str(self.remote) if arg == self.url else arg for arg in args),
            **kwargs,
        )

    def child(self, command, **kwargs):
        if (
            command[0] == str(sys.executable)
            and "-c" in command
            and (
                "from worktree_task import _integrate_model"
                in command[command.index("-c") + 1]
                or "from worktree_pr import validate_update"
                in command[command.index("-c") + 1]
            )
        ):
            if (
                "from worktree_pr import validate_update"
                in command[command.index("-c") + 1]
            ):
                try:
                    pr.validate_update(self.root, self.state["task_id"])
                except wt.Blocked as error:
                    return subprocess.CompletedProcess(command, 1, "", str(error))
            else:
                wt._integrate_model(self.root, self.state["task_id"])
            return subprocess.CompletedProcess(command, 0, "", "")
        return self.real_run(command, **kwargs)

    def validate_update_snapshot(
        self, interpreter, environment, snapshot, task_file, base, head
    ):
        assert git(snapshot, "rev-parse", head + "^1") == base
        self.validations.append(git(snapshot, "rev-parse", head + "^2"))
        return subprocess.CompletedProcess([], 0, "", "")

    def validate(self, root, options, *, final_candidate):
        assert not (self.root / ".worktrees/.blueprint/lifecycle.lock").exists()
        self.validations.append(final_candidate.candidate_head)
        return 0

    def gh(self, target, host, *args):
        assert not (self.root / ".worktrees/.blueprint/lifecycle.lock").exists()
        assert (self.root / ".worktrees/.blueprint/tasks/example.pr-lock").is_file()
        assert host == "github.com"
        if args[:2] == ("auth", "status"):
            return ""
        if args[:2] == ("repo", "view"):
            return json.dumps(
                dict(
                    url="https://github.com/fixture/repository",
                    nameWithOwner="fixture/repository",
                    viewerPermission="WRITE",
                )
            )
        if args[0] == "api":
            return json.dumps(
                {
                    "commit": {
                        "sha": git(
                            self.remote, "rev-parse", "refs/heads/" + self.state["base"]
                        )
                    }
                }
            )
        if args[:2] == ("pr", "list"):
            return json.dumps([self.pr] if self.pr else [])
        if args[:2] == ("pr", "view"):
            if self.pr and self.pr["state"] != "MERGED":
                self.pr["headRefOid"] = git(
                    self.remote, "rev-parse", "refs/heads/" + self.state["branch"]
                )
            return json.dumps(self.pr)
        if args[:2] == ("pr", "ready"):
            self.pr["isDraft"] = "--undo" in args
            return ""
        if args[:2] == ("pr", "close"):
            self.pr["state"] = "CLOSED"
            return ""
        if args[:2] == ("pr", "merge"):
            assert "--delete-branch" not in args
            assert args[args.index("--match-head-commit") + 1] == self.pr["headRefOid"]
            self.pr["state"] = "MERGED"
            # Squash/rebase merge result deliberately differs from the public candidate.
            self.pr["mergeCommit"] = {"oid": "a" * 40}
            return ""
        assert args[:2] == ("pr", "create"), args
        body = Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8")
        assert "example" in body and "Required changes" in body
        self.created += 1
        assert self.created == 1
        self.pr = dict(
            number=7,
            url="https://github.com/fixture/repository/pull/7",
            state="OPEN",
            baseRefName=self.state["base"],
            headRefName=self.state["branch"],
            headRefOid=git(
                self.remote, "rev-parse", "refs/heads/" + self.state["branch"]
            ),
            isCrossRepository=False,
            isDraft="--draft" in args,
        )
        return self.pr["url"] + "\n"


@it_case
def check_pr_publication_recovery():
    for framework in (False, True):
        with fixture(branch="release") as root:
            git(root, "config", "blueprint.baseBranch", "release")
            relative = "framework/scripts/candidate.txt" if framework else "file.txt"
            target, state = start(root, files=(relative,))
            source = target / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("PR candidate\n", encoding="utf-8")
            approval = None
            if not framework:
                finish_contract(target, state)
            base = git(root, "rev-parse", "HEAD")
            remote = PRGitHub(root, state)
            with (
                patch.object(wt, "git", side_effect=remote.git),
                patch.object(pr, "gh", side_effect=remote.gh),
                patch.object(
                    wt.python_env,
                    "runtime",
                    return_value=(
                        Path(sys.executable),
                        wt.python_env.environment(Path(sys.prefix)),
                    ),
                ),
                patch.object(subprocess, "run", side_effect=remote.child),
                patch.object(loop, "run_loop", side_effect=remote.validate),
            ):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "worktree_task.py",
                        "finalize",
                        "--repository-root",
                        str(root),
                        "--task-id",
                        "example",
                        "--create-pr",
                        *(
                            ["--human-approved-validation-failure", approval]
                            if approval
                            else []
                        ),
                    ],
                ):
                    with patch("sys.stdout", new_callable=io.StringIO) as output:
                        code = wt.main()
                        assert code == 0, output.getvalue()
                    published = json.loads(output.getvalue())
                assert (
                    published["status"] == "ok"
                    and published["prPublication"]["prState"] == "OPEN"
                )
                assert (
                    published["merged"] is None
                    and published["prPublication"]["number"] == 7
                )
                assert remote.created == 1
                assert published.get("validation_failure_approval") == approval
                assert len(remote.validations) == int(framework)
                assert tasks.status((target / state["task_file"]).read_text()) == (
                    "suspend" if approval else "completed"
                )
                assert (
                    wt.finalize(root, "example", create_pr=True)["prPublication"]["url"]
                    == remote.pr["url"]
                )
                assert remote.created == 1 and len(remote.validations) == int(framework)
                retained(root, target, state, base)
                assert (
                    git(remote.remote, "rev-parse", "refs/heads/" + state["base"])
                    == base
                )
                assert (
                    git(remote.remote, "rev-parse", "refs/heads/" + state["branch"])
                    == published["tip"]
                )
                assert git(root, "status", "--porcelain") == ""


@it_case
def check_explicit_disposal_and_orphans():
    for status in ("running", "suspend", "completed"):
        with fixture() as root:
            target, state = start(root)
            peer, peer_state = start(root, "other")
            peer_path = wt.load(root, "other")[2]
            peer_before = peer_path.read_bytes()
            (target / "file.txt").write_text("unmerged commit\n", encoding="utf-8")
            git(target, "add", "file.txt")
            git(target, "commit", "-qm", "review change")
            if status == "suspend":
                tasks.suspend(target, state["task_file"], "unfinished Task")
            elif status == "completed":
                finish_contract(target, state)
            (target / "file.txt").write_text("dirty\n", encoding="utf-8")
            (target / "untracked.txt").write_text("discard\n", encoding="utf-8")
            (target / "secret.bin").write_bytes(b"ignored discard")
            proof = sealed_evidence.evidence_store(target) / "example.json"
            sealed_evidence.write_sealed(target, proof, {"task": state["task_file"]})
            shared_marker = wt.python_env.shared_directory(root) / "keep.txt"
            shared_marker.parent.mkdir(parents=True, exist_ok=True)
            shared_marker.write_text("shared environment", encoding="utf-8")
            before = git(root, "rev-parse", "HEAD")
            result = cli(root, "cleanup")
            assert result["cleaned"] and not any(
                result["cleanup"]["remaining"].values()
            )
            assert proof.exists() and str(proof) in result["retained_external_evidence"]
            assert peer.exists() and peer_path.read_bytes() == peer_before
            assert shared_marker.read_text(encoding="utf-8") == "shared environment"
            assert git(root, "rev-parse", "HEAD") == before
            git(root, "branch", "codex/worktree/orphan")
            listing = wt.branches(root)["branches"]
            assert next(b for b in listing if b["branch"].endswith("/orphan"))["orphan"]
            assert not wt.delete_branch(root, "codex/worktree/orphan")[
                "remaining_branch"
            ]
            proof.unlink()


@it_case
def check_pr_update_and_operations():
    for ending in (
        "close",
        "cleanup-first",
        "external",
        "merge",
        "squash",
        "rebase",
    ):
        with fixture() as root:
            target, state = start(root, files=("framework/scripts/candidate.txt",))
            source = target / "framework/scripts/candidate.txt"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("initial\n", encoding="utf-8")
            remote = PRGitHub(root, state)
            with (
                patch.object(wt, "git", side_effect=remote.git),
                patch.object(pr, "gh", side_effect=remote.gh),
                patch.object(
                    wt.python_env,
                    "runtime",
                    return_value=(
                        Path(sys.executable),
                        wt.python_env.environment(Path(sys.prefix)),
                    ),
                ),
                patch.object(subprocess, "run", side_effect=remote.child),
                patch.object(loop, "run_loop", side_effect=remote.validate),
                patch.object(
                    pr, "validate_snapshot", side_effect=remote.validate_update_snapshot
                ),
            ):
                published = wt.finalize(root, "example", create_pr=True, draft=True)
                old = published["tip"]
                assert published["prPublication"]["isDraft"] and target.exists()
                assert wt.finalize(root, "example", create_pr=True)["prPublication"][
                    "isDraft"
                ]
                assert not pr.operate(root, "example", "pr-ready")["prPublication"][
                    "isDraft"
                ]
                assert pr.operate(root, "example", "pr-draft")["prPublication"][
                    "isDraft"
                ]
                source.write_text("review revision\n", encoding="utf-8")
                updated = pr.update(root, "example")
                assert updated["prPublication"]["number"] == 7 and remote.created == 1
                assert (
                    updated["tip"] != old
                    and target.exists()
                    and updated["merged"] is None
                )
                assert git(target, "merge-base", old, updated["tip"]) == old
                assert remote.validations == [old, updated["tip"]]
                assert git(root, "rev-parse", "HEAD") == state["start"]
                if ending == "close":
                    assert (
                        pr.operate(root, "example", "pr-close")["prPublication"][
                            "prState"
                        ]
                        == "CLOSED"
                    )
                    assert target.exists()
                    assert wt.cleanup(root, "example")["cleaned"]
                    assert (
                        pr.close_existing(root, "7")["prPublication"]["state"]
                        == "CLOSED"
                    )
                elif ending == "cleanup-first":
                    assert wt.cleanup(root, "example")["cleaned"]
                    assert (
                        pr.close_existing(root, remote.pr["url"])["prPublication"][
                            "state"
                        ]
                        == "CLOSED"
                    )
                elif ending == "external":
                    remote.pr.update(state="MERGED", mergeCommit={"oid": "b" * 40})
                    assert pr.operate(root, "example", "pr-status")["cleaned"]
                else:
                    assert pr.operate(root, "example", "pr-merge", method=ending)[
                        "cleaned"
                    ]
                assert wt.branch_exists(remote.remote, state["branch"])
                assert (
                    git(remote.remote, "rev-parse", "refs/heads/" + state["base"])
                    == state["start"]
                )

    _check_pr_update_recovery_and_base()


def _check_pr_update_recovery_and_base():
    for mode in (
        "repair",
        "retry",
        "remote",
        "local",
        "conflict",
        "stale",
        "interrupted",
        "rewrite",
        "foreign",
        "postpush",
        "push-old",
        "push-foreign",
    ):
        _check_pr_update_scenario(mode)

    # Exercise the actual snapshot validator using tracked, synthetic project inputs.
    with fixture() as root:
        source = SCRIPT.parents[2]
        shutil.copytree(
            source / "framework",
            root / "framework",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(source / ".agents", root / ".agents")
        for name in ("AGENTS.md", "README.md"):
            shutil.copyfile(source / name, root / name)
        for name in ("docs/designs", "infra", "tests/scenarios", "tests/results"):
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / ".gitkeep").touch()
        (root / "docs/system-overview.md").write_text("# Fixture\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-qm", "synthetic framework")
        git(root, "checkout", "-qb", "candidate")
        marker = "framework/scripts/pr-validator-fixture.txt"
        (root / marker).write_text("candidate\n", encoding="utf-8")
        git(root, "add", marker)
        git(root, "commit", "-qm", "candidate")
        candidate = git(root, "rev-parse", "HEAD")
        git(root, "checkout", "-q", "main")
        (root / "base-only.txt").write_text("base\n", encoding="utf-8")
        git(root, "add", "base-only.txt")
        git(root, "commit", "-qm", "base advance")
        base = git(root, "rev-parse", "HEAD")
        tree = git(root, "merge-tree", "--write-tree", base, candidate).splitlines()[0]
        merged = git(
            root,
            "commit-tree",
            tree,
            "-p",
            base,
            "-p",
            candidate,
            "-m",
            "temporary integration",
        )
        git(root, "checkout", "--quiet", "--detach", merged)
        (root / "tasks").mkdir(exist_ok=True)
        (root / "tasks/example.md").write_text(
            contract("example", [marker]), encoding="utf-8"
        )
        assert git(root, "diff", "--name-only", base, merged) == marker
        result = pr.validate_snapshot(
            Path(sys.executable),
            wt.python_env.environment(Path(sys.prefix)),
            root,
            "tasks/example.md",
            base,
            merged,
        )
        assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]


class PRUpdateScenario:
    def __init__(self, root, state, remote, mode):
        self.root, self.state, self.remote, self.mode = root, state, remote, mode
        self.failures = []
        self.real_push = pr.push_candidate

    def advance(self, path, content):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        git(self.root, "add", path)
        git(self.root, "commit", "-qm", "base advance")
        git(self.root, "push", str(self.remote.remote), "HEAD:refs/heads/" + self.state["base"])

    def validate(self, interpreter, environment, snapshot, task_file, base, head):
        result = self.remote.validate_update_snapshot(
            interpreter, environment, snapshot, task_file, base, head
        )
        assert git(snapshot, "diff", "--name-only", base, head) == "framework/scripts/candidate.txt"
        if self.mode == "remote":
            assert (snapshot / "base.txt").read_text(encoding="utf-8") == "remote-only content\n"
        if self.mode in {"repair", "retry"} and not self.failures:
            self.failures.append(True)
            return subprocess.CompletedProcess([], 1, "", "validation failed")
        if self.mode == "stale" and not self.failures:
            self.failures.append(True)
            self.advance("base.txt", "later base\n")
        return result

    def push_then_interrupt(self, target, publication):
        self.real_push(target, publication)
        self.failures.append(True)
        raise wt.Blocked("simulated interruption after push")

    def failed_push(self, target, publication):
        if self.mode == "push-foreign":
            tree = git(self.root, "rev-parse", "HEAD^{tree}")
            foreign = git(self.root, "commit-tree", tree, "-m", "foreign")
            git(self.root, "push", str(self.remote.remote), foreign + ":refs/heads/test-third")
            git(self.remote.remote, "update-ref", "refs/heads/" + self.state["branch"], foreign)
        raise wt.Blocked("push outcome unknown")

    def push_then_advance(self, target, publication):
        self.real_push(target, publication)
        self.advance("after-push.txt", "later base\n")


def _check_pr_update_scenario(mode):
    with fixture() as root:
        target, state = start(root, files=("framework/scripts/candidate.txt",))
        source = target / "framework/scripts/candidate.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("published\n", encoding="utf-8")
        remote = PRGitHub(root, state)
        scenario = PRUpdateScenario(root, state, remote, mode)

        with (
            patch.object(wt, "git", side_effect=remote.git),
            patch.object(pr, "gh", side_effect=remote.gh),
            patch.object(
                wt.python_env,
                "runtime",
                return_value=(
                    Path(sys.executable),
                    wt.python_env.environment(Path(sys.prefix)),
                ),
            ),
            patch.object(subprocess, "run", side_effect=remote.child),
            patch.object(loop, "run_loop", side_effect=remote.validate),
            patch.object(pr, "validate_snapshot", side_effect=scenario.validate),
        ):
            published = wt.finalize(root, "example", create_pr=True)
            old = published["tip"]
            source.write_text("candidate\n", encoding="utf-8")
            if mode == "remote":
                scenario.advance("base.txt", "remote-only content\n")
                assert (
                    git(remote.remote, "rev-parse", "refs/heads/" + state["base"])
                    != state["start"]
                )
            elif mode == "local":
                (root / "local.txt").write_text("local only\n", encoding="utf-8")
                git(root, "add", "local.txt")
                git(root, "commit", "-qm", "local advance")
            elif mode == "conflict":
                scenario.advance("framework/scripts/candidate.txt", "conflicting base\n")
            elif mode == "rewrite":
                tree = git(root, "rev-parse", "HEAD^{tree}")
                unrelated = git(root, "commit-tree", tree, "-m", "unrelated base")
                git(
                    root,
                    "push",
                    str(remote.remote),
                    unrelated + ":refs/heads/test-rewrite",
                )
                git(
                    remote.remote,
                    "update-ref",
                    "refs/heads/" + state["base"],
                    unrelated,
                )
            elif mode == "foreign":
                scenario.advance("foreign.txt", "foreign head\n")
                foreign = git(root, "rev-parse", "HEAD")
                git(
                    root,
                    "push",
                    str(remote.remote),
                    foreign + ":refs/heads/test-foreign",
                )
                git(
                    remote.remote,
                    "update-ref",
                    "refs/heads/" + state["branch"],
                    foreign,
                )
            if mode in {"push-old", "push-foreign"}:

                with patch.object(pr, "push_candidate", side_effect=scenario.failed_push):
                    with TestCase().assertRaises(wt.Blocked):
                        pr.update(root, "example")
                if mode == "push-foreign":
                    with patch.object(pr, "push_candidate") as retry_push:
                        with TestCase().assertRaises(wt.Blocked):
                            pr.update(root, "example")
                        retry_push.assert_not_called()
                    return
            elif mode == "postpush":

                with patch.object(pr, "push_candidate", side_effect=scenario.push_then_advance):
                    with TestCase().assertRaises(wt.Blocked):
                        pr.update(root, "example")
                retained_state = wt.load(root, "example")[3]
                assert retained_state["prUpdate"]["validation"] == "STALE"
                assert retained_state["prPublication"]["candidate"] != old
            elif mode == "interrupted":
                with patch.object(
                    pr, "push_candidate", side_effect=scenario.push_then_interrupt
                ):
                    with TestCase().assertRaises(wt.Blocked):
                        pr.update(root, "example")
                assert (
                    git(remote.remote, "rev-parse", "refs/heads/" + state["branch"])
                    != old
                )
            elif mode in {
                "repair",
                "retry",
                "conflict",
                "stale",
                "rewrite",
                "foreign",
            }:
                with TestCase().assertRaises(wt.Blocked):
                    pr.update(root, "example")
                if mode != "foreign":
                    assert (
                        git(
                            remote.remote,
                            "rev-parse",
                            "refs/heads/" + state["branch"],
                        )
                        == old
                    )
                if mode == "repair":
                    source.write_text("fixed candidate\n", encoding="utf-8")
                if mode in {"conflict", "rewrite", "foreign"}:
                    if mode != "foreign":
                        assert (
                            wt.load(root, "example")[3]["prUpdate"]["status"]
                            == "PREPARED"
                        )
                    return
                if mode == "stale":
                    with TestCase().assertRaises(wt.Blocked):
                        pr.update(root, "example")
            updated = pr.update(root, "example")
            assert updated["prPublication"]["number"] == 7 and remote.created == 1
            assert "prUpdate" not in updated
            assert (
                git(remote.remote, "rev-parse", "refs/heads/" + state["branch"])
                == updated["tip"]
            )
            assert git(target, "merge-base", old, updated["tip"]) == old
            assert target.exists() and updated["merged"] is None
            if mode == "remote":
                assert updated["prPublication"]["baseCommit"] == git(
                    remote.remote, "rev-parse", "refs/heads/" + state["base"]
                )
            if mode == "retry":
                assert remote.validations[-1] == remote.validations[-2]
            if mode == "repair":
                assert remote.validations[-1] != remote.validations[-2]


def main():
    for check in (
        check_implement_rebases_on_latest_base,
        check_sync_base_preserves_candidate,
        check_old_workflow_registry_is_ignored,
        check_success_and_empty,
        check_finalize_line_endings,
        check_metadata_storage,
        check_human_approved_validation_failure,
        check_normal_model_final_candidate,
        check_registered_normal_model_guard,
        check_model_operation_integration,
        check_model_refactor_integration,
        check_framework_final_candidate,
        check_pr_publication_recovery,
        check_explicit_disposal_and_orphans,
        check_pr_update_and_operations,
    ):
        check()
    print("worktree-task: PASS (normal Git/CLI/candidate/PR integration)")


@it_case
def check_framework_final_candidate():
    relative = ".github/workflows/framework-it.yml"
    with fixture() as root:
        loop_checks.make_project_fixture(SCRIPT.parents[2], root)
        shutil.copytree(
            SCRIPT.parents[1],
            root / "framework",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        for directory in (
            "docs/designs",
            "infra",
            "tests/scenarios",
            "tests/results",
        ):
            (root / directory / ".gitkeep").touch()
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("name: Framework IT\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "synthetic Framework fixture")
        target, state = start(root, files=(relative,))
        source = target / relative
        source.write_text(source.read_text() + "\nTask correction\n")
        # Advance the base with a path outside the Task's declarations.
        (root / "upstream.txt").write_text("inherited base\n")
        git(root, "add", "upstream.txt")
        git(root, "commit", "-qm", "advance Framework base")
        latest = git(root, "rev-parse", "HEAD")
        candidate = wt.prepare_integration(root, "example")
        TestCase().assertEqual(candidate.base_commit, latest)
        assert candidate.scope == frozenset() and candidate.changed_paths == {relative}
        assert not (target / "project.json").exists()
        assert tasks.status((target / state["task_file"]).read_text()) == "running"
        with patch(
            "model.sources.raw_model",
            side_effect=AssertionError("Framework must not load Models"),
        ):
            result = wt.validate_final_candidate(candidate)
        assert result.returncode == 0
        merged = wt.merge_validated_candidate(result)
        assert (
            merged["merged"]
            == candidate.candidate_head
            == git(root, "rev-parse", "HEAD")
        )
        assert tasks.status((target / state["task_file"]).read_text()) == "completed"
        assert wt.cleanup(root, "example")["cleaned"]
        assert not target.exists()


def _callback_check_model_operation_integration_validate(
    require_import_changes, /, root, options, *, final_candidate
):
    assert not (root.parent / ".blueprint/lifecycle.lock").exists()
    with tasks.selected_task(root, final_candidate.task_file):
        require_import_changes(
            root, final_candidate.changed_paths, final_candidate=final_candidate
        )
    return 0


@it_case
def check_model_operation_integration():
    operation_candidate = _imports_support_import_model_fixtures.operation_candidate
    operation_contract = _imports_support_import_model_fixtures.operation_contract
    operation_fixture = _imports_support_import_model_fixtures.operation_fixture
    action = "import-merge"
    for create_pr in (False, True):
        with fixture() as root:
            operation_fixture(root)
            git(root, "add", "model", "project.json")
            git(root, "commit", "-qm", "model fixture")
            with tempfile.TemporaryDirectory() as directory:
                candidate = Path(directory) / "candidate"
                sources = operation_candidate(root, candidate, action)
                target, state = start(root, files=tuple(sorted(sources)))
                text = (
                    operation_contract(action)
                    + "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n"
                )
                for heading in ("Modified files", "Allowed paths"):
                    text += (
                        "\n## "
                        + heading
                        + "\n"
                        + "".join(
                            "- `" + name + "`\n"
                            for name in sorted(sources | {state["task_file"]})
                        )
                    )
                text += "\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n"
                (target / state["task_file"]).write_text(text)
                task_contract_runtime.refresh(target, state["task_file"])
                for name in sources:
                    shutil.copyfile(candidate / name, target / name)
                with (
                    mapping_alias(SCRIPT.parents[2], target),
                    patch.object(
                        wt.python_env,
                        "runtime",
                        return_value=(
                            Path(sys.executable),
                            wt.python_env.environment(Path(sys.prefix)),
                        ),
                    ),
                ):
                    finish_contract(target, state)
                    require_import_changes = (
                        _imports_import_guard.require_import_changes
                    )
                    loop = _imports_validation_loop
                    validate = _bind_framework_callback(
                        _callback_check_model_operation_integration_validate,
                        require_import_changes,
                    )
                    with patch.object(
                        loop, "run_loop", side_effect=validate
                    ) as checked:
                        if create_pr:
                            base = git(root, "rev-parse", "HEAD")
                            remote = PRGitHub(root, state)
                            with (
                                patch.object(wt, "git", side_effect=remote.git),
                                patch.object(pr, "gh", side_effect=remote.gh),
                                patch.object(
                                    subprocess, "run", side_effect=remote.child
                                ),
                            ):
                                published = wt.finalize(root, "example", create_pr=True)
                                assert (
                                    published["merged"] is None and remote.created == 1
                                )
                                assert (
                                    wt.finalize(root, "example", create_pr=True)[
                                        "prPublication"
                                    ]["number"]
                                    == 7
                                )
                            retained(root, target, state, base)
                        else:
                            final = wt.prepare_integration(root, "example")
                            result = wt.validate_final_candidate(final)
                            assert (
                                wt.merge_validated_candidate(result)["merged"]
                                == final.candidate_head
                            )
                            assert wt.cleanup(root, "example")["cleaned"]
                            assert not target.exists()
                        checked.assert_called_once()
    print("Model-only merge final-candidate integration: PASS")


def _callback_check_model_refactor_integration_validate(
    calls, /, root, options, *, final_candidate
):
    calls.append(final_candidate.candidate_head)
    assert not (root.parent / ".blueprint/lifecycle.lock").exists()
    with tasks.selected_task(root, final_candidate.task_file):
        require_import_changes(
            root, final_candidate.changed_paths, final_candidate=final_candidate
        )
    return 0


@it_case
def check_model_refactor_integration():
    dependency_contract = _imports_support_import_model_fixtures.dependency_contract
    dependency_fixture = _imports_support_import_model_fixtures.dependency_fixture
    dependency_refactor = _imports_support_import_model_fixtures.dependency_refactor

    with fixture() as root, tempfile.TemporaryDirectory() as directory:
        dependency_fixture(root)
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "generic Model fixture")
        candidate = Path(directory) / "candidate"
        sources = dependency_refactor(root, candidate)
        target, state = start(root, files=tuple(sorted(sources)))
        text = (
            dependency_contract()
            + "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        )
        for heading in ("Modified files", "Allowed paths"):
            text += (
                "\n## "
                + heading
                + "\n"
                + "".join(
                    "- `" + name + "`\n"
                    for name in sorted(sources | {state["task_file"]})
                )
            )
        text += "\n## Validation scope\n- `dev/cde/service-a`\n- `dev/cde/service-b`\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n"
        (target / state["task_file"]).write_text(text)
        task_contract_runtime.refresh(target, state["task_file"])
        with (
            mapping_alias(SCRIPT.parents[2], target),
            tasks.selected_task(target, state["task_file"]),
        ):
            output = {target / name: (candidate / name).read_text() for name in sources}
            scope = {("stg", "cde", "service-b")}
            with edit_write_context(target, scope, state["task_file"]) as context:
                path = next(iter(output))
                publish_edit(
                    prepare_edit(load_model(path, context.snapshot), output, context),
                    context,
                )
            require_import_changes(target)
            assert (
                load_model(target / "model/stg/cde/service-b.properties").values[
                    "desired.row.002-001.value"
                ]
                == "same-name-stg"
            )
            file = root / "model/stg/cde/service-a.properties"
            producer = dict(load_model(file).authoritative)
            producer["desired.row.001-001.value"] = "advanced-name"
            write_model(file, producer)
            git(root, "add", file)
            git(root, "commit", "-qm", "advance producer on base")
            latest = git(root, "rev-parse", "HEAD")
            final = wt.prepare_integration(root, "example")
            assert final.base_commit == latest
            calls = []
            validate = _bind_framework_callback(
                _callback_check_model_refactor_integration_validate, calls
            )
            with patch.object(loop, "run_loop", side_effect=validate):
                with redirect_stderr(io.StringIO()) as warnings:
                    result = wt.validate_final_candidate(final)
                assert (
                    "producer name/identifier differs from saved text"
                    not in warnings.getvalue()
                )
                assert (
                    wt.merge_validated_candidate(result)["merged"]
                    == final.candidate_head
                )
                assert wt.cleanup(root, "example")["cleaned"]
            assert calls == [final.candidate_head]


if __name__ == "__main__":
    main()
