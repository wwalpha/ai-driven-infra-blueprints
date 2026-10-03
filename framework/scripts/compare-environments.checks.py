#!/usr/bin/env python3
"""Runnable checks for desired-only, four-pair environment comparison."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from model_files import model_file_contents

SCRIPT = Path(__file__).with_name("compare-environments.py")
spec = importlib.util.spec_from_file_location("compare_environments", SCRIPT)
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)
DOCUMENT = '{"Version":"2012-10-17","Statement":[]}'
STACK = """desired.deployment.maxConcurrentStacks=1
desired.stack.001.name=cfn-stack-common
desired.stack.001.template=common.yaml
desired.stack.001.parameters=common.json
desired.stack.001.deployOrder=10
"""


def model(number, retention="30", document=DOCUMENT):
    return f"""desired.service.logs.serviceId=logs
desired.resource.{number}.resourceType=Logs.LogGroup
desired.resource.{number}.logicalId=FlowLogs
desired.resource.{number}.anchor=logs-flow
desired.row.{number}-001.property=Logs.LogGroup.RetentionInDays
desired.row.{number}-001.value={retention}
desired.row.{number}-001.comment=保持日数
desired.row.{number}-002.property=Logs.LogGroup.ResourcePolicyDocument
desired.row.{number}-002.value=[Policy](logs/policy.json)
desired.row.{number}-002.document={document}
desired.row.{number}-003.property=Logs.LogGroup.Tags[].Key
desired.row.{number}-003.value=Team
desired.row.{number}-004.property=Logs.LogGroup.Tags[].Key
desired.row.{number}-004.value=Purpose
observed.row.{number}-001.value=observed-{number}
display.resource.{number}.comment=表示-{number}
"""


def save(path, text):
    for file, content in model_file_contents(path, text).items():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")


def cli(root, *args, expected=None):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--repository-root", str(root), *args],
                            capture_output=True, text=True, encoding="utf-8")
    assert not result.stderr, result.stderr
    report = json.loads(result.stdout)
    assert report["namespace"] == "desired"
    assert [(item["left"], item["right"], item["target"]) for item in report["comparisons"]] == (
        compare.PAIRS if expected is None else expected)
    return result.returncode, report["comparisons"]


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        targets = [{"environment": environment, "alias": target, "awsAccountId": "123456789012",
                    "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
                   for environment in ("dev", "stg", "prod") for target in ("cde", "non-cde")]
        (root / "project.json").write_text(json.dumps({"targets": targets}), encoding="utf-8")
        for environment, number in (("dev", "001"), ("stg", "007"), ("prod", "009")):
            for target in ("cde", "non-cde"):
                path = root / "model" / environment / target / "logs.properties"
                document = '{ "Statement": [], "Version": "2012-10-17" }'
                text = model(number, document=document if environment == "stg" else DOCUMENT)
                save(path, "# padding\n" * 600 + text if environment == "stg" else text)
                save(path.with_name("cloudformation-stacks.properties"), STACK)
        snapshot = {file: file.read_bytes() for file in root.rglob("*") if file.is_file()}
        code, pairs = cli(root)
        assert code == 0 and all(item["status"] == "complete" and not item["differences"] for item in pairs)
        assert {file: file.read_bytes() for file in root.rglob("*") if file.is_file()} == snapshot
        assert cli(root, "--pair", "stg-prod", "--target", "non-cde",
                   expected=[("stg", "prod", "non-cde")])[0] == 0
        assert cli(root, "--target", "cde",
                   expected=[("dev", "stg", "cde"), ("stg", "prod", "cde")])[0] == 0
        # Unfinished prod must not be required or read during dev/stg comparison.
        (root / "project.json").write_text(json.dumps({"targets": targets[:4]}), encoding="utf-8")
        for file in snapshot:
            if file.relative_to(root).parts[:2] == ("model", "prod"):
                file.unlink()
        assert cli(root, "--pair", "dev-stg", "--target", "cde", "--service", "logs",
                   expected=[("dev", "stg", "cde")])[0] == 0
        assert cli(root, "--pair", "dev-stg",
                   expected=[("dev", "stg", "cde"), ("dev", "stg", "non-cde")])[0] == 0
        assert cli(root)[0] == 1  # Full comparison still reports unfinished prod.
        for file, data in snapshot.items():
            file.write_bytes(data)
        for arguments in (("--pair", "dev-prod"), ("--target", "unknown")):
            invalid = subprocess.run([sys.executable, "-B", str(SCRIPT), *arguments], capture_output=True)
            assert invalid.returncode == 2 and not invalid.stdout
        stack = root / "model/dev/cde/cloudformation-stacks.properties"
        stack.write_text(STACK.replace("maxConcurrentStacks=1", "maxConcurrentStacks=2"), encoding="utf-8")
        code, pairs = cli(root, "--service", "cloudformation-stacks")
        assert code == 0 and [len(item["differences"]) for item in pairs] == [1, 0, 0, 0]
        assert pairs[0]["differences"][0]["identity"] == ["desired.deployment.maxConcurrentStacks"]
        stack.write_text(STACK, encoding="utf-8")

        source = root / "model/stg/cde/logs.properties"
        # Update the part containing real keys and retain a source location in that part.
        part = source.with_suffix("") / "part-002.properties"
        part.write_text(part.read_text(encoding="utf-8").replace(".value=30", ".value=90"), encoding="utf-8")
        code, pairs = cli(root)
        assert code == 0 and [len(item["differences"]) for item in pairs] == [1, 1, 0, 0]
        difference = pairs[0]["differences"][0]
        assert difference["identity"] == ["row", "Logs.LogGroup", "FlowLogs", "Logs.LogGroup.RetentionInDays", "1", "value"]
        assert difference["left"]["value"] == "30" and difference["right"]["value"] == "90"
        evidence = difference["right"]
        assert evidence["path"].endswith("part-002.properties")
        assert (root / evidence["path"]).read_text(encoding="utf-8").splitlines()[evidence["line"] - 1] == evidence["key"] + "=90"

        path = root / "model/dev/non-cde/logs.properties"
        path.write_text(model("001", document='{"Version":"2012-10-17","Statement":["A","B"]}')
                        .replace(".value=Purpose", ".value=Other")
                        + "desired.note.001.text=環境差異の根拠を確認する\n", encoding="utf-8")
        _, pairs = cli(root)
        assert {item["identity"][-1] for item in pairs[2]["differences"]} == {"document", "value", "desired.note.001.text"}
        assert any(item["identity"][-2:] == ["2", "value"] for item in pairs[2]["differences"])
        array_path = root / "model/prod/non-cde/logs.properties"
        array_path.write_text(model("009", document='{"Version":"2012-10-17","Statement":["B","A"]}'), encoding="utf-8")
        before = compare.desired_fields(path, root)
        after = compare.desired_fields(array_path, root)
        document_key = ("row", "Logs.LogGroup", "FlowLogs", "Logs.LogGroup.ResourcePolicyDocument", "1", "document")
        assert before[document_key]["normalized"] != after[document_key]["normalized"]
        save(root / "model/prod/cde/extra.properties", "desired.service.extra.serviceId=extra\n")
        _, pairs = cli(root)
        assert any(item["service"] == "extra" and item["kind"] == "only_right" for item in pairs[1]["differences"])
        assert cli(root, "--service", "logs")[0] == 0
        assert cli(root, "--service", "unknown")[0] == 1

        # Duplicate identities, invalid JSON and orphan rows must fail, not appear equal.
        for invalid in (
            model("001") + "desired.resource.002.resourceType=Logs.LogGroup\ndesired.resource.002.logicalId=FlowLogs\n",
            model("001", document='{"A":1,"A":2}'),
            model("001", document='{"A":NaN}'),
            model("001") + "desired.row.002-001.property=Logs.LogGroup.RetentionInDays\ndesired.row.002-001.value=30\n",
        ):
            path.write_text(invalid, encoding="utf-8")
            code, pairs = cli(root)
            assert code == 1 and pairs[2]["status"] == "incomplete" and pairs[2]["errors"]
        part.unlink()
        code, pairs = cli(root)
        assert code == 1 and pairs[0]["status"] == pairs[1]["status"] == "incomplete"
        targets.pop()
        (root / "project.json").write_text(json.dumps({"targets": targets}), encoding="utf-8")
        assert cli(root)[1][3]["status"] == "incomplete"
        (root / "project.json").unlink()
        assert all(item["status"] == "incomplete" for item in cli(root)[1])
    print("Environment desired comparison checks: PASS (four pairs, selected pairs/targets, unfinished prod excluded, desired-only, indexed models, evidence, missing inputs, read-only)")


if __name__ == "__main__":
    main()
