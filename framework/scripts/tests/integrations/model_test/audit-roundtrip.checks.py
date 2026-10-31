"""Offline Model audit integration; synthetic Models and a fake AWS executable."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import copy
import json
import os
import subprocess
import tempfile

from support.it_case_receipt import it_case
from support.model_test_runner import load_fixture, prepare, snapshot
from validation.findings import Findings
from validation.scenario import check_results

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def check_audit_roundtrip():
    inputs, expected = load_fixture("audit/base")
    with tempfile.TemporaryDirectory(prefix="audit-roundtrip-") as directory:
        root = Path(directory)
        source = prepare(root, inputs)
        assert prepare(root, inputs) == source
        assert expected["unrelatedValue"] not in source
        embedded = snapshot(source)
        assert "dev/cde/cloudwatch-logs" not in embedded["models"]
        assert (
            embedded["referenceRows"]["dev/cde/vpc"]["001-002"]["value"]
            == expected["referenceValue"]
        )
        before = {
            path: path.read_bytes() for path in (root / "model").rglob("*.properties")
        }
        script = root / "tests/dev/cde/vpc.py"
        script.parent.mkdir(parents=True)
        script.write_text(source, encoding="utf-8")
        fake = root / "aws"
        fake.write_text("#!" + sys.executable + "\n" + FAKE_AWS, encoding="utf-8")
        fake.chmod(0o700)
        settings = root / "responses.json"
        calls = root / "calls.jsonl"
        log_directory = root / "tests/results/dev/cde"
        runs = expected["runs"]
        for index, run in enumerate(runs):
            response = copy.deepcopy(inputs["responses"])
            if "actualName" in run:
                response[0]["response"]["FlowLogs"][0]["LogGroupName"] = run[
                    "actualName"
                ]
            configuration = {
                "responses": response,
                "account": run.get("account", "123456789012"),
            }
            settings.write_text(json.dumps(configuration), encoding="utf-8")
            calls.unlink(missing_ok=True)
            previous = set(log_directory.glob("vpc-*.log"))
            selected = script
            if run.get("flat"):
                selected = root / "vpc.py"
                selected.write_text(source, encoding="utf-8")
            process = subprocess.run(
                [sys.executable, "-I", "-B", str(selected)],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": str(root),
                    "AUDIT_RESPONSES": str(settings),
                    "AUDIT_CALLS": str(calls),
                },
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert process.returncode == run["code"], (
                index,
                process.stdout,
                process.stderr,
            )
            for text in run["contains"]:
                assert text in process.stdout, (index, text, process.stdout)
            for text in expected["absent"]:
                assert text not in process.stdout + process.stderr
            assert not process.stderr, process.stderr
            saved = set(log_directory.glob("vpc-*.log")) - previous
            assert len(saved) == 1, saved
            assert saved.pop().read_text(encoding="utf-8") == process.stdout
            actual_calls = [
                json.loads(line)
                for line in calls.read_text(encoding="utf-8").splitlines()
            ]
            assert actual_calls == run["calls"], actual_calls
        assert {path: path.read_bytes() for path in before} == before
        findings = Findings(root)
        check_results(root, {("dev", "cde"): {}}, False, {}, findings)
        assert not findings.errors, findings.errors
        log = next(log_directory.glob("vpc-*.log"))
        log.rename(log.with_name("vpc-invalid.log"))
        findings = Findings(root)
        check_results(root, {("dev", "cde"): {}}, False, {}, findings)
        assert any("invalid audit log" in error for error in findings.errors)


FAKE_AWS = 'import json, os, pathlib, sys\napi = sys.argv[1:3]\nrequest = json.loads(sys.argv[sys.argv.index("--cli-input-json") + 1])\nsettings = json.loads(pathlib.Path(os.environ["AUDIT_RESPONSES"]).read_text(encoding="utf-8"))\nwith pathlib.Path(os.environ["AUDIT_CALLS"]).open("a", encoding="utf-8") as handle:\n    handle.write(json.dumps([api, request]) + "\\n")\nif api == ["sts", "get-caller-identity"]:\n    assert request == {}\n    value = {"Account": settings.get("account", "123456789012"), "Arn": "arn:aws:iam::123456789012:user/offline"}\nelse:\n    route = next(item for item in settings["responses"] if item["api"] == api)\n    assert request == route["inputs"], (request, route)\n    value = route["response"]\nif "$error" in value:\n    print(value["$error"], file=sys.stderr)\n    sys.exit(254)\nprint(json.dumps(value))\n'


if __name__ == "__main__":
    check_audit_roundtrip()
