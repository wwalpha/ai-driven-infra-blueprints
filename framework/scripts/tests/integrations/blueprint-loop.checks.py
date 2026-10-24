#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from model.render import markdown_for
from model.sources import load_model
from support.blueprint_loop_fixtures import (
    MODULE,
    SCRIPT,
    Path,
    events,
    io,
    json,
    make_loop_fixture,
    make_project_fixture,
    make_service_loop_fixture,
    os,
    pytest,
    redirect_stdout,
    run,
    subprocess,
    sys,
    tasks,
    write_model,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_running_and_interruption(tmp_path):
    root = tmp_path
    script = root / "slow.py"
    script.write_text("import time\nprint('before wait', flush=True)\ntime.sleep(0.15)\n", encoding="utf-8")
    logs = root / "logs"
    logs.mkdir()
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, str(script)]
    with redirect_stdout(io.StringIO()) as output:
        assert MODULE.run_commands(root, [command], environment, logs, heartbeat_seconds=0.03) == 0
    history = events(logs)
    assert history[0]["jobs"] == 1 and history[0]["python_version"] == sys.version
    assert history[0]["hash_seed"] == environment.get("PYTHONHASHSEED")
    assert next(event for event in history if event["event"] == "step_start")["command"] == command
    assert any(event["event"] == "heartbeat" for event in history)
    assert "RUNNING slow.py" in output.getvalue()
    assert "before wait" in (logs / "01-slow.py.log").read_text(encoding="utf-8")
    assert history[-1]["status"] == "pass"
    assert history[-1]["duration_seconds"] >= 0.15
    running = next(event for event in history if event["event"] == "step_running")
    assert running["pid"] > 0


def check_deploy_scope_isolation(tmp_path):
    """Exercise the real task loop and validation scopes with two environments."""
    root = tmp_path / "repository"
    make_project_fixture(SCRIPT.parents[2], root)
    target = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
    (root / "project.json").write_text(json.dumps({"projectName": "app", "targets": [
        {"environment": env, **target} for env in ("dev", "stg")]}) + "\n")
    template = root / "infra/cloudformation/templates/shared.yaml"
    template.parent.mkdir(parents=True)
    template.write_text("Resources: {}\n")
    parameters, models, designs, stack_values = {}, {}, {}, {}
    for env in ("dev", "stg"):
        models[env] = root / f"model/{env}/123456789012/cloudformation-stacks.properties"
        designs[env] = root / f"docs/designs/{env}/123456789012/cloudformation-stacks.md"
        parameters[env] = root / f"infra/cloudformation/parameters/{env}/123456789012/a.json"
        for path in (models[env], designs[env], parameters[env]):
            path.parent.mkdir(parents=True, exist_ok=True)
        values = {"desired.deployment.maxConcurrentStacks": "1", "desired.stack.001.name": f"cfn-stack-app-{env}-a",
                  "desired.stack.001.template": "shared.yaml", "desired.stack.001.parameters": "a.json",
                  "desired.stack.001.deployOrder": "1", "display.stack.001.comment": "アプリケーションを配置するstack"}
        stack_values[env] = values
        write_model(models[env], values)
        designs[env].write_text(markdown_for(designs[env], values, root))
        parameters[env].write_text("[]\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], cwd=root, check=True)
    for env, phase in (("dev", "deploy"), ("stg", "update")):
        name = f"tasks/{env}.md"
        files = [name, parameters[env].relative_to(root).as_posix()]
        files += [template.relative_to(root).as_posix()] if env == "dev" else [
            models[env].relative_to(root).as_posix(), designs[env].relative_to(root).as_posix()]
        listed = "\n".join(f"- `{path}`" for path in files)
        tasks.start(root, name, f"""# Task
## Task contract
- Task type: `infrastructure`
- Task status: `running`
- Infrastructure phase: `{phase}`
- Target environment: `{env}`
- Target AWS account: `123456789012`
- Deployment scope: `cfn-stack-app-{env}-a`
## Validation scope
- `{env}/123456789012/cloudformation-stacks`
## Required changes
- [R1] 対象stackを検証する。
## Acceptance checks
- [R1] `exists:{parameters[env].relative_to(root).as_posix()}`
## Modified files
{listed}
## Allowed paths
{listed}
""")
    values = stack_values["stg"] | {"display.stack.001.comment": "更新対象のstack"}
    write_model(models["stg"], values)
    designs["stg"].write_text(markdown_for(designs["stg"], values, root))
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONOPTIMIZE": "0"}

    command = [sys.executable, str(SCRIPT), "--mode", "task", "--task-file", "tasks/dev.md",
               "--log-dir", str(tmp_path / "logs")]

    parameters["stg"].write_text("invalid JSON\n")
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
    assert result.returncode != 0 and "outside Deployment scope" in result.stdout, result.stdout + result.stderr
    assert "invalid CloudFormation parameter JSON" not in result.stdout


def check_task_service_validation(tmp_path):
    root = tmp_path / 'repository'
    make_service_loop_fixture(root)
    result = subprocess.run([sys.executable, str(SCRIPT), '--mode', 'task', '--task-file', 'tasks/example.md',
                             '--log-dir', str(tmp_path / 'logs')], cwd=root,
                            env=MODULE.utf8_environment(), capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'START validate-blueprint.py' in result.stdout
    assert 'validation scope: dev/123456789012/iam' in result.stdout
    assert 'START git-diff-check' in result.stdout
    assert 'framework regression: skipped' in result.stdout
    assert 'PASS (0 framework regression scripts)' in result.stdout


def check_parallel_and_selection(tmp_path):
    root = tmp_path
    scripts = root / "framework/scripts"
    scripts.mkdir(parents=True)
    (scripts / "tests/units").mkdir(parents=True, exist_ok=True)
    logs = root / "logs"
    logs.mkdir()
    commands = []
    for name, other, code in (("a", "b", 1), ("b", "a", 0)):
        script = scripts / f"tests/units/{name}.checks.py"
        script.write_text(
            "from pathlib import Path\nimport time\n"
            f"Path('{name}').touch()\nend=time.monotonic()+5\n"
            f"while not Path('{other}').exists() and time.monotonic()<end: time.sleep(.01)\n"
            f"assert Path('{other}').exists(), 'workers did not overlap'\n"
            f"print('diagnostic-{name}')\nraise SystemExit({code})\n", encoding="utf-8")
        commands.append([sys.executable, str(script)])
    with redirect_stdout(io.StringIO()) as output:
        assert MODULE.run_commands(root, commands, MODULE.utf8_environment(), logs, jobs=2) == 1
    assert output.getvalue().index("diagnostic-a") < output.getvalue().index("diagnostic-b")
    assert events(logs)[-1]["failed_steps"] == ["a.checks.py"]


def check_staged_snapshot(tmp_path):
    root = tmp_path / "source"
    scripts = root / "checks"
    scripts.mkdir(parents=True)
    (scripts / "tests/units").mkdir(parents=True, exist_ok=True)
    make_loop_fixture(scripts)
    # These isolated runner fixtures exercise orchestration after authorization.
    (scripts / "tests/units/snapshot.checks.py").write_text(
        "print('snapshot regression assertion executed')\n", encoding="utf-8")
    (root / "tasks").mkdir()
    active = root / "tasks/snapshot.md"
    contract = ("## Task contract\n- Task type: `governance`\n- Task status: `running`\n"
                "## Validation scope\n- `framework`\n## Modified files\n- `tasks/snapshot.md`\n"
                "- `checks/validate-blueprint.py`\n## Allowed paths\n- `tasks/snapshot.md`\n"
                "- `checks/validate-blueprint.py`\n")
    MODULE.git(root, "init", "-q")
    active.write_text(contract, encoding="utf-8")
    validator = scripts / "validate-blueprint.py"
    validator.write_text("print('base')\n", encoding="utf-8")
    MODULE.git(root, "add", ".")
    MODULE.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base")
    (root / "historical.txt").write_text("old version", encoding="utf-8")
    MODULE.git(root, "add", ".")
    MODULE.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "history")
    base = MODULE.git(root, "rev-parse", "HEAD")
    validator.write_text(
        "from pathlib import Path\nimport subprocess\n"
        "assert not Path('untracked.txt').exists()\n"
        "text=Path('tasks/snapshot.md').read_text(encoding='utf-8')\n"
        f"assert text == {contract!r}\n"
        "assert subprocess.check_output(['git','rev-list','--count','HEAD'], text=True).strip() == '1'\n"
        "paths=subprocess.check_output(['git','diff','--cached','--name-only'], text=True)\n"
        "assert 'validate-blueprint.py' in paths\nprint('日本語 snapshot')\n", encoding="utf-8")
    MODULE.git(root, "add", ".")
    active.write_text("dirty workspace contract", encoding="utf-8")
    (root / "untracked.txt").write_text("not staged", encoding="utf-8")
    (root / ".lock").write_text('{"local":"fixture service_source"}\n', encoding="utf-8")
    validator.write_text(validator.read_text(encoding="utf-8") +
                        "assert __import__('json').loads(Path('.lock').read_text()) == {'local':'fixture service_source'}\n", encoding="utf-8")
    MODULE.git(root, "add", "checks/validate-blueprint.py")
    log_parent = tmp_path / "logs"
    command = [sys.executable, str(scripts / SCRIPT.name), "--mode", "task", "--staged", "--base", base,
               "--log-dir", str(log_parent)]
    environment = {**MODULE.utf8_environment(), "PYTHONUTF8": "0", "PYTHONIOENCODING": "ascii"}
    index = Path(MODULE.git(root, "rev-parse", "--git-path", "index"))
    if not index.is_absolute():
        index = root / index
    saved_index = index.read_bytes()
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
    assert result.returncode == 0 and "日本語 snapshot" in result.stdout, result.stdout + result.stderr
    assert "snapshot regression assertion executed" not in result.stdout
    assert "PASS (0 framework regression scripts)" in result.stdout
    assert index.read_bytes() == saved_index
    assert active.read_text(encoding="utf-8") == "dirty workspace contract"
    metadata = json.loads(next(log_parent.glob("*/snapshot.json")).read_text(encoding="utf-8"))
    assert metadata["base"] == base and metadata["source_unchanged"]
    # Changing the source password service_source makes a staged result stale.
    original_validator = validator.read_text(encoding="utf-8")
    validator.write_text(original_validator +
                        f"Path({str(root / '.lock')!r}).write_text('changed', encoding='utf-8')\n", encoding="utf-8")
    MODULE.git(root, "add", "checks/validate-blueprint.py")
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
    assert result.returncode == 1 and "HEAD/index/.lock changed" in result.stdout, result.stdout + result.stderr
    # write-tree must reject unresolved conflicts before any validation starts.
    blob = MODULE.git(root, "rev-parse", "HEAD:tasks/snapshot.md")
    conflict = "0 " + "0" * len(blob) + "\ttasks/snapshot.md\n"
    conflict += "".join(f"100644 {blob} {stage}\ttasks/snapshot.md\n" for stage in (1, 2, 3))
    subprocess.run(["git", "update-index", "--index-info"], cwd=root,
                   input=conflict, encoding="utf-8", check=True)
    with pytest.raises(subprocess.CalledProcessError):
        MODULE.index_tree(root, tmp_path)


def check_failure_suspension(tmp_path):
    root = tmp_path / 'repository'
    model = make_service_loop_fixture(root)
    other = 'tasks/other.md'
    tasks.start(root, other, '## Task contract\n- Task type: `governance`\n- Task status: `running`\n'
                '## Validation scope\n- `framework`\n## Modified files\n- `tasks/other.md`\n'
                '## Allowed paths\n- `tasks/other.md`\n')
    untouched = (root / other).read_bytes()
    with tasks.selected_task(root, 'tasks/example.md'):
        values = dict(load_model(model).authoritative)
        values['display.resource.001.comment'] = '保存済み設計と異なる説明'
        write_model(model, values)
    logs = tmp_path / 'logs'
    result = subprocess.run([sys.executable, str(SCRIPT), '--mode', 'task', '--task-file', 'tasks/example.md',
                             '--log-dir', str(logs)], cwd=root, env=MODULE.utf8_environment(),
                            capture_output=True, encoding='utf-8')
    assert result.returncode == 1 and 'Task suspended' in result.stdout, result.stdout + result.stderr
    text = (root / 'tasks/example.md').read_text(encoding='utf-8')
    assert tasks.status(text) == 'suspend' and 'generated Markdown is stale' in text
    assert (root / other).read_bytes() == untouched
    history = events(next(logs.glob('blueprint-loop-*')))
    ended = [row for row in history if row['event'] == 'step_end']
    assert [row['returncode'] for row in ended] == [1, 0, 0]
    assert history[-1]['failed_steps'] == ['validate-blueprint.py']


def check_workflow(tmp_path) -> None:
    root = tmp_path / "repository"
    log_parent = tmp_path / "logs"
    scripts = root / "checks"
    scripts.mkdir(parents=True)
    (scripts / "tests/units").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    make_loop_fixture(scripts)
    (scripts / "validate-blueprint.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    (scripts / "tests/units/a.checks.py").write_text("assert False, 'assertions must run'\n", encoding="utf-8")
    (scripts / "tests/units/b.checks.py").write_text(
        "from pathlib import Path\nPath('continued').write_text('yes', encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = [sys.executable, "-O", str(scripts / SCRIPT.name), "--mode", "local", "--all", "--jobs", "1", "--log-dir", str(log_parent)]
    environment = {**os.environ, "PYTHONOPTIMIZE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, encoding="utf-8")
    assert result.returncode != 0
    assert "AssertionError: assertions must run" in result.stdout
    assert "validate-blueprint.py, a.checks.py" in result.stdout
    assert (root / "continued").read_text(encoding="utf-8") == "yes"
    failed_directory = next(log_parent.glob("blueprint-loop-*"))
    startup = [json.loads(line) for line in (failed_directory / "startup.jsonl").read_text(encoding="utf-8").splitlines()]
    assert startup[0]["event"] == "directory_created"
    assert {"task.contract.read", "git.config", "commands.prepare", "utf8.subprocess", "utf8.output",
            "utf8.cleanup", "stdout.print", "stdout.flush", "timing.open"} <= {
                event["step"] for event in startup if event["event"] == "end"}
    history = events(failed_directory)
    assert history[0]["event"] == "loop_start" and history[0]["step_count"] == 5
    ended = [event for event in history if event["event"] == "step_end"]
    assert [event["returncode"] for event in ended] == [1, 1, 0, 0, 0]
    assert all(event["duration_seconds"] >= 0 for event in ended)
    assert history[-1]["event"] == "loop_end" and history[-1]["status"] == "fail"
    assert history[-1]["failed_steps"] == ["validate-blueprint.py", "a.checks.py"]
    assert all("timestamp" in event for event in history)
    assert "AssertionError" in (failed_directory / "02-a.checks.py.log").read_text(encoding="utf-8")



def main():
    return run(__file__, message='blueprint-loop: PASS')


if __name__ == "__main__":
    raise SystemExit(main())
