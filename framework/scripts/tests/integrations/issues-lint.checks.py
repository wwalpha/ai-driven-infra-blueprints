#!/usr/bin/env python3
"""Real pinned lint/config/worker integration on temporary inputs and HOME only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import os
import select
import subprocess
from functools import partial
from unittest.mock import patch

import pytest
from cfnlint.helpers import get_cache_dir
from support.pytest_cli import run
from utils.cfn_lint import (
    Worker,
    lint_session,
    validate_template,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "project"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData/Local"))
    monkeypatch.chdir(cwd)
    return home, cwd


def args(template):
    return [
        "cfn-lint",
        "--regions",
        "ap-northeast-1",
        "--template",
        str(template.resolve()),
        "--format",
        "json",
    ]


def baseline(template):
    code = "from cfnlint.runner import main; main()"
    return subprocess.run(
        [sys.executable, "-B", "-c", code, *args(template)[1:]],
        capture_output=True,
        text=True,
        timeout=60,
    )


def signature(matches):
    return sorted(
        (
            m["Rule"]["Id"],
            m["Level"],
            json.dumps(m["Location"], sort_keys=True),
            m["Message"],
        )
        for m in matches
    )


@pytest.mark.parametrize(
    "body",
    [
        "Resources:\n  B:\n    Type: AWS::S3::Bucket\n",
        "Resources:\n  B:\n    Type: AWS::S3::Bucket\n    Properties:\n      Wrong: true\n",
    ],
)
def check_cli_equivalence(tmp_path, monkeypatch, body):
    home, cwd = isolated(tmp_path, monkeypatch)
    (home / ".cfnlintrc.yml").write_text("include_checks: [I]\n")
    template = cwd / "app.yaml"
    template.write_text(body)
    previous = baseline(template)
    assert previous.returncode in (0, 2, 4, 6, 8, 10, 12, 14), previous.stderr
    with lint_session(cwd) as session:
        execution = validate_template(session, template, "ap-northeast-1")
    assert execution["completed"] and not execution["processing_errors"], execution
    assert signature(execution["matches"]) == signature(
        json.loads(previous.stdout or "[]")
    )
    assert execution["requested_region"] == "ap-northeast-1"
    assert execution["effective_regions"] == ["ap-northeast-1"]


def parameter_signature(m):
    return (
        m["Rule"]["Id"],
        json.dumps(m["Location"], sort_keys=True),
        m["Message"],
    )


def check_parameter_file_cli_and_redaction(tmp_path, monkeypatch):
    _, cwd = isolated(tmp_path, monkeypatch)
    template = cwd / "network.yaml"
    parameters = cwd / "network.json"
    secret = "fixture-private-parameter-value"
    template.write_text(
        """Parameters:
  VpcCidrBlock:
    Type: String
    Default: ''
  Environment:
    Type: String
    Default: dev
  Password:
    Type: String
    NoEcho: true
Resources:
  Network:
    Type: AWS::EC2::VPC
    Properties:
      CidrBlock: !Ref VpcCidrBlock
      Tags:
        - Key: Environment
          Value: !Ref Environment
Outputs:
  Value:
    Value: !Ref Password
""",
        encoding="utf-8",
    )
    parameters.write_text(
        json.dumps(
            [
                {"ParameterKey": "VpcCidrBlock", "ParameterValue": "10.10.0.0/23"},
                {"ParameterKey": "Environment", "ParameterValue": "stg"},
                {"ParameterKey": "Password", "ParameterValue": secret},
            ]
        ),
        encoding="utf-8",
    )
    arguments = [
        "--regions",
        "ap-northeast-1",
        "--format",
        "json",
        "--parameter-files",
        str(parameters),
        "--",
        str(template),
    ]
    cli = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from cfnlint.runner import main; main()",
            *arguments,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    with lint_session(cwd) as session:
        result = validate_template(session, template, "ap-northeast-1", parameters)
    assert result["completed"]
    assert secret not in json.dumps(
        {k: v for k, v in result.items() if k != "sensitive_values"}
    )
    assert secret in result["sensitive_values"]
    with lint_session(cwd) as session:
        fallback = validate_template(session, template, "ap-northeast-1")
    assert any(m["Rule"]["Id"] == "W1030" for m in fallback["matches"])
    broken = cwd / "broken.yaml"
    broken.write_text("Resources: [", encoding="utf-8")
    with lint_session(cwd) as session:
        syntax = validate_template(session, broken, "ap-northeast-1")
    assert not syntax["decode_complete"]
    assert any(m["Rule"]["Id"] == "E0000" for m in syntax["matches"])
    assert "W1030" not in {item["Rule"]["Id"] for item in result["matches"]}, result[
        "matches"
    ]
    cli_matches = json.loads(cli.stdout or "[]")
    raw = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from cfnlint.runner import main; main()",
            "--regions",
            "ap-northeast-1",
            "--format",
            "json",
            "--template",
            str(template),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )

    applied = [parameter_signature(m) for m in cli_matches]
    for match in json.loads(raw.stdout or "[]"):
        applied.remove(parameter_signature(match))
    assert sorted(parameter_signature(m) for m in result["matches"]) == sorted(applied)
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            "    NoEcho: true", "    NoEcho: true\n    AllowedValues: [allowed]"
        ),
        encoding="utf-8",
    )
    with lint_session(cwd) as session:
        invalid = validate_template(session, template, "ap-northeast-1", parameters)
    assert any(m["Rule"]["Id"] == "E2900" for m in invalid["matches"])
    assert secret not in json.dumps(
        {k: v for k, v in invalid.items() if k != "sensitive_values"}
    )


def check_worker_config_isolation(tmp_path, monkeypatch):
    home, cwd = isolated(tmp_path, monkeypatch)
    (home / ".cfnlintrc.yml").write_text("include_checks: [I]\n")
    template = cwd / "app.yaml"
    secret = "fixture-super-private"
    template.write_text(
        "Parameters:\n  Input:\n    Type: String\n    NoEcho: true\n    Default: "
        + secret
        + "\n    AllowedValues: [other]\nResources:\n  B:\n    Type: AWS::S3::Bucket\n"
    )
    rules = cwd / "rules"
    rules.mkdir()
    (
        rules / "Stateful.py"
    ).write_text("""from cfnlint.rules import CloudFormationLintRule, RuleMatch
calls=0
class Stateful(CloudFormationLintRule):
    id='E9999'
    shortdesc='State isolation'
    description='Synthetic stateful rule'
    tags=['fixture']
    def match(self,cfn):
        global calls
        calls+=1
        return [RuleMatch(['Resources'],'invocation '+str(calls))]
""")
    registry = cwd / "registry"
    registry.mkdir()
    (registry / "bucket.json").write_text(
        json.dumps(
            {
                "typeName": "AWS::S3::Bucket",
                "description": "fixture",
                "properties": {"RequiredFixture": {"type": "string"}},
                "required": ["RequiredFixture"],
                "primaryIdentifier": ["/properties/RequiredFixture"],
                "additionalProperties": False,
            }
        )
    )
    override = cwd / "override.json"
    override.write_text(json.dumps({"IncludeResourceTypes": ["AWS::S3::Bucket"]}))
    config, output = cwd / ".cfnlintrc", cwd / "forbidden.json"
    with lint_session(cwd) as session:
        for settings in (
            {"append_rules": [str(rules)]},
            {"registry_schemas": [str(registry)]},
            {"override_spec": str(override)},
            {"append_rules": [str(rules)]},
        ):
            config.write_text(
                json.dumps(
                    dict(
                        settings,
                        output_file=str(output),
                        parameters=[{"Input": secret}],
                    )
                )
            )
            result = validate_template(session, template, "ap-northeast-1")
            assert result["completed"] and not result["processing_errors"], result
            assert set(result["configuration_sources"]) == {
                str(config),
                str(home / ".cfnlintrc.yml"),
            }
            messages = [m["Message"] for m in result["matches"]]
            assert ("invocation 1" in messages) == bool(settings.get("append_rules"))
            assert not any("invocation 2" in message for message in messages)
            assert any("RequiredFixture" in message for message in messages) == bool(
                settings.get("registry_schemas")
            )
            assert not output.exists()
            result.pop("sensitive_values", None)
            assert secret not in json.dumps(result)
        process = session.worker.process
    assert process.poll() is not None and process.stdin.closed and process.stdout.closed


def check_schema_failure_recovery(tmp_path, monkeypatch):
    _, cwd = isolated(tmp_path, monkeypatch)
    cache = Path(get_cache_dir())
    (cache / "providers").mkdir(parents=True)
    (cache / "resources").mkdir()
    version = cache / "version.json"
    version.write_text('{"schema_date":"9999-12-31"}')
    (cache / "providers/us-east-1.json").write_text(
        json.dumps(
            {
                "AWS::S3::Bucket": "broken-local-schema",
                "AWS::SQS::Queue": "valid-local-schema",
            }
        )
    )
    schema = cache / "resources/broken-local-schema.json"
    schema.write_text("{ broken json")
    (cache / "resources/valid-local-schema.json").write_text(
        json.dumps(
            {
                "typeName": "AWS::SQS::Queue",
                "description": "synthetic queue",
                "properties": {"QueueName": {"type": "string"}},
                "additionalProperties": False,
                "primaryIdentifier": ["/properties/QueueName"],
            }
        )
    )
    template = cwd / "app.yaml"
    template.write_text(
        "Resources:\n  Queue:\n    Type: AWS::SQS::Queue\n    Properties:\n      Wrong: true\n"
        "  Bucket:\n    Type: AWS::S3::Bucket\n  Unknown:\n    Type: AWS::Fixture::Absent\n"
    )
    with lint_session(cwd) as session:
        result = validate_template(session, template, "ap-northeast-1")
        assert (
            result["status"] == "processing_error"
            and not result["completed"]
            and result["unverified"]
        ), result
        assert any(
            e["code"] == "schema_unavailable"
            and e.get("resource_type") == "AWS::S3::Bucket"
            for e in result["processing_errors"]
        ), result
        assert {"E3002", "E3006"} <= {m["Rule"]["Id"] for m in result["matches"]}, (
            result
        )
        assert result["decode_complete"] and result["decode"]
        assert (
            result["fatal"]
            and validate_template(session, template, "ap-northeast-1")["status"]
            == "not_run"
        )
        process = session.worker.process
    assert process.poll() is not None
    assert not any(e["code"] == "child_execution" for e in result["processing_errors"])
    observed = {item["locator"]: item for item in result["dependencies"]["files"]}
    assert observed[str(schema)]["sha256"] and str(template) in observed
    assert (
        schema.read_text() == "{ broken json"
    )  # Offline execution did not repair/download a schema.
    version.unlink()
    with lint_session(cwd) as recovered:
        assert validate_template(recovered, template, "ap-northeast-1")["completed"]
        process = recovered.worker.process
    assert process.poll() is not None
    rules = cwd / "rules"
    rules.mkdir()
    (rules / "Crash.py").write_text("import os; os._exit(7)")
    config = cwd / ".cfnlintrc"
    config.write_text(json.dumps({"append_rules": [str(rules)]}))
    with lint_session(cwd) as crashed:
        broken = validate_template(crashed, template, "ap-northeast-1")
        assert broken["processing_errors"] and broken["fatal"]
        assert (
            validate_template(crashed, template, "ap-northeast-1")["status"]
            == "not_run"
        )
        process = crashed.worker.process
    assert process.poll() is not None


def launch_once_fixture(script, processes, launch, command, **kwargs):
    assert command[-1] == "--once"
    process = launch([sys.executable, "-B", str(script), "--once"], **kwargs)
    processes.append(process)
    return process


def check_timeout_reaping(tmp_path, monkeypatch):
    _, cwd = isolated(tmp_path, monkeypatch)
    script = cwd / "blocked.py"
    if sys.platform == "win32":
        # --once has no forked child; retain real Popen/communicate timeout and handle closure.
        script.write_text(
            "import sys\nimport threading\nsys.stdin.read()\nthreading.Event().wait()\n"
        )
        processes = []
        launch = partial(launch_once_fixture, script, processes, subprocess.Popen)
        with patch("utils.cfn_lint.subprocess.Popen", side_effect=launch):
            worker = Worker()
            result = worker.request({}, timeout=0.2)
        assert result["processing_errors"][0]["code"] == "timeout" and result["fatal"]
        assert worker.request({})["status"] == "not_run" and len(processes) == 1
        process = processes[0]
        assert (
            process.poll() is not None
            and process.stdin.closed
            and process.stdout.closed
        )
        return
    # Use real serve/fork/pipe/reaping, independent of lint import timing.
    script.write_text(
        """import os
import signal
import sys
sys.path.insert(0, """
        + repr(str(Path(__file__).resolve().parents[2]))
        + """)
from utils import cfn_lint_worker as worker
def blocked(request, emit):
    emit({'progress': {'state': {'fixture_pid': os.getpid()}}})
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.pause()
worker.execute = blocked
print('ready', flush=True)
worker.serve()
"""
    )
    worker = Worker()
    worker.process = subprocess.Popen(
        [sys.executable, "-B", str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    process = worker.process
    try:
        assert os.getpgrp() != process.pid
        assert select.select([process.stdout], [], [], 15)[0], "fixture startup failed"
        assert os.read(process.stdout.fileno(), 6) == b"ready\n"
        result = worker.request({}, timeout=0.2)
        assert (
            result["processing_errors"][0]["code"] == "timeout" and result["fatal"]
        ), result
        assert worker.process is None and worker.request({})["status"] == "not_run"
        assert (
            process.poll() is not None
            and process.stdin.closed
            and process.stdout.closed
        )
        with pytest.raises(ProcessLookupError):
            os.kill(result["fixture_pid"], 0)
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)
    finally:
        worker.close(force=True)
        process.stderr.close()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
