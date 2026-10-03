#!/usr/bin/env python3
"""Runnable checks for desired-only, four-pair environment comparison."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import hashlib
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


def logical_id_checks():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        targets = [{"environment": env, "alias": "cde"} for env in ("dev", "stg")]
        (root / "project.json").write_text(json.dumps({"targets": targets}), encoding="utf-8")
        paths = [root / "model" / env / "cde/logs.properties" for env in ("dev", "stg")]
        for env, path in zip(("dev", "stg"), paths):
            text = ""
            for number, suffix in (("001", "A"), ("002", "B")):
                logical_id = f"{env.title()}Flow{suffix}"
                anchor = f"logs-{env}-{suffix.lower()}"
                body = model(number).replace("FlowLogs", logical_id).replace("logs-flow", anchor)
                if text:
                    body = body.replace("desired.service.logs.serviceId=logs\n", "")
                # Self, same-service, cross-service and grouped-parent references.
                body += f"desired.row.{number}-005.property=Logs.LogGroup.Arn\n"
                body += f"desired.row.{number}-005.value=[{logical_id}](#{anchor})\n"
                body += f"desired.row.{number}-006.property=Logs.LogGroup.LinkedLog\n"
                body += f"desired.row.{number}-006.value=[other](logs.md#logs-{env}-b)\n"
                body += f"desired.row.{number}-007.property=Logs.LogGroup.Role\n"
                body += f"desired.row.{number}-007.value=[{env}-role](iam.md#iam-{env}-a)\n"
                body += f"desired.resource.{number}.parentReference=[role](iam.md#iam-{env}-a)\n"
                document = json.dumps({"Target": f"[{logical_id}](#{anchor})", "Literal": "unchanged"})
                body = body.replace(DOCUMENT, document)
                digest = hashlib.sha256(json.dumps(json.loads(document), ensure_ascii=False,
                                                   sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                body += f"desired.row.{number}-002.artifactSha256={digest}\n"
                text += body
            save(path, text)
            role_text = "desired.service.iam.serviceId=iam\n"
            for number, suffix in (("001", "A"), ("002", "B")):
                role_text += (f"desired.resource.{number}.resourceType=IAM.Role\n"
                              f"desired.resource.{number}.logicalId=Role{suffix}\n"
                              f"desired.resource.{number}.anchor=iam-{env}-{suffix.lower()}\n"
                              f"desired.row.{number}-001.property=IAM.Role.RoleName\n"
                              f"desired.row.{number}-001.value=common-role-{suffix}\n")
            save(path.with_name("iam.properties"), role_text)
        args = ("--pair", "dev-stg", "--target", "cde")
        expected = [("dev", "stg", "cde")]
        code, pairs = cli(root, *args, expected=expected)
        assert code == 1 and pairs[0]["status"] == "unconfirmed"
        assert len(pairs[0]["unconfirmed"]) == 4
        assert not any(item["identity"][0] in {"resource", "row"} for item in pairs[0]["differences"])
        field = pairs[0]["unconfirmed"][0]["fields"][0]
        assert (root / field["path"]).read_text(encoding="utf-8").splitlines()[field["line"] - 1] == field["key"] + "=" + field["value"]

        mapping = {"left": "dev", "right": "stg", "target": "cde", "resources": [
            {"service": "logs", "resourceType": "Logs.LogGroup", "left": f"DevFlow{suffix}",
             "right": f"StgFlow{suffix}", "reason": "fixture confirms the same log purpose"}
            for suffix in ("A", "B")]}
        mapping_path = root / "mapping.json"
        mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
        mapped_args = (*args, "--resource-map", str(mapping_path))
        snapshot = {file: file.read_bytes() for file in root.rglob("*") if file.is_file()}
        code, pairs = cli(root, *mapped_args, expected=expected)
        assert code == 0 and pairs[0]["status"] == "complete" and not pairs[0]["differences"]
        assert len(pairs[0]["resource_matches"]) == 4 and not pairs[0]["unconfirmed"]
        assert {file: file.read_bytes() for file in root.rglob("*") if file.is_file()} == snapshot

        original = paths[1].read_text(encoding="utf-8")
        for before, after, expected_fields in (
            (".value=30", ".value=90", {"value"}),
            ("logs.md#logs-stg-b", "logs.md#logs-stg-a", {"value"}),
            ("iam.md#iam-stg-a", "iam.md#iam-stg-b", {"value", "parentReference"}),
            ('"Literal": "unchanged"', '"Literal": "StgFlowA"', {"document"}),
            (".value=Team", ".value=StgFlowA", {"value"}),
            ("logs/policy.json", "logs/another-policy.json", {"value"}),
        ):
            modified = original.replace(before, after)
            # Regenerate derived digests when the fixture document changes.
            lines = modified.splitlines()
            docs = {line.partition("=")[0].removesuffix("document"): json.loads(line.partition("=")[2])
                    for line in lines if ".document=" in line}
            for index, line in enumerate(lines):
                if ".artifactSha256=" in line:
                    key = line.partition("=")[0]
                    digest = hashlib.sha256(json.dumps(docs[key.removesuffix("artifactSha256")],
                        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                    lines[index] = key + "=" + digest
            paths[1].write_text("\n".join(lines) + "\n", encoding="utf-8")
            code, pairs = cli(root, *mapped_args, expected=expected)
            assert code == 0 and pairs[0]["differences"], (before, pairs)
            assert {item["identity"][-1] for item in pairs[0]["differences"]} == expected_fields
        paths[1].write_text(original, encoding="utf-8")
        paths[1].write_text(original.replace(".artifactSha256=", ".artifactSha256=stale-"), encoding="utf-8")
        code, pairs = cli(root, *mapped_args, expected=expected)
        assert code == 1 and pairs[0]["status"] == "incomplete"
        assert any("artifactSha256" in item["message"] for item in pairs[0]["errors"])
        paths[1].write_text(original, encoding="utf-8")
        role_path = paths[1].with_name("iam.properties")
        role = role_path.read_text(encoding="utf-8")
        role_path.write_text(role.replace("common-role-A", "different-role-A"), encoding="utf-8")
        code, pairs = cli(root, *mapped_args, expected=expected)
        assert code == 0 and len(pairs[0]["differences"]) == 1
        assert pairs[0]["differences"][0]["identity"][3] == "IAM.Role.RoleName"
        role_path.write_text(role, encoding="utf-8")

        # Explicitly confirmed absence is needed to classify same-type unmatched resources.
        mapping["resources"] = [mapping["resources"][0],
            {"service": "logs", "resourceType": "Logs.LogGroup", "left": "DevFlowB",
             "right": None, "reason": "left purpose confirmed absent on right"},
            {"service": "logs", "resourceType": "Logs.LogGroup", "left": None,
             "right": "StgFlowB", "reason": "right purpose confirmed absent on left"}]
        mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
        code, pairs = cli(root, *mapped_args, expected=expected)
        assert code == 0 and not pairs[0]["unconfirmed"]
        assert {item["kind"] for item in pairs[0]["differences"]} >= {"only_left", "only_right"}

        valid = json.loads(snapshot[mapping_path])
        for invalid in (
            {**valid, "target": "non-cde"},
            {**valid, "resources": [*valid["resources"], valid["resources"][0]]},
            {**valid, "resources": [{**valid["resources"][0], "right": "Unknown"}]},
            {**valid, "resources": [{**valid["resources"][0], "service": "unselected"}]},
            {**valid, "resources": [{**valid["resources"][0], "reason": ""}]},
            {**valid, "resources": [{**valid["resources"][0], "left": None, "right": None}]},
        ):
            mapping_path.write_text(json.dumps(invalid), encoding="utf-8")
            code, pairs = cli(root, *mapped_args, expected=expected)
            assert code == 1 and pairs[0]["status"] == "incomplete" and pairs[0]["errors"], invalid
        for extra in ((), ("--pair", "dev-stg"), ("--target", "cde")):
            invalid = subprocess.run([sys.executable, "-B", str(SCRIPT), "--resource-map", str(mapping_path), *extra],
                                     capture_output=True)
            assert invalid.returncode == 2 and not invalid.stdout


def import_mode_checks():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "project.json").write_text(json.dumps({"targets": [
            {"environment": env, "alias": "cde"} for env in ("dev", "stg")]}), encoding="utf-8")
        paths = [root / "model" / env / "cde/logs.properties" for env in ("dev", "stg")]
        args = ("--pair", "dev-stg", "--target", "cde", "--service", "logs")
        expected = [("dev", "stg", "cde")]

        def imported(number="001", logical_id="FlowLogs", anchor="logs-flow", retention="30"):
            return (model(number, retention).replace("FlowLogs", logical_id).replace("logs-flow", anchor)
                    + f"desired.resource.{number}.resourceMode=IMPORT\n")

        for left_mode, right_mode in (("IMPORT", "IMPORT"), ("IMPORT", "CREATE"), ("CREATE", "IMPORT")):
            save(paths[0], model("001") + f"desired.resource.001.resourceMode={left_mode}\n")
            save(paths[1], model("007", "90") + f"desired.resource.007.resourceMode={right_mode}\n")
            snapshot = {file: file.read_bytes() for file in root.rglob("*") if file.is_file()}
            code, pairs = cli(root, *args, expected=expected)
            pair = pairs[0]
            assert code == 0 and pair["status"] == "complete" and not pair["differences"] and not pair["unconfirmed"]
            assert len(pair["excluded"]) == 2 and pair["resource_matches"][0]["excluded"]
            for item in pair["excluded"]:
                field = item["evidence"]
                assert (root / field["path"]).read_text(encoding="utf-8").splitlines()[field["line"] - 1] == field["key"] + "=" + field["value"]
            assert {file: file.read_bytes() for file in root.rglob("*") if file.is_file()} == snapshot

        # Unmatched IMPORTs are excluded independently, without an identity heuristic.
        save(paths[0], imported(logical_id="DevExternal"))
        save(paths[1], imported("007", "StgExternal", retention="90"))
        code, pairs = cli(root, *args, expected=expected)
        assert code == 0 and not pairs[0]["differences"] and not pairs[0]["unconfirmed"]
        assert len(pairs[0]["excluded"]) == 2
        save(paths[1], model("007", "90").replace("FlowLogs", "StgExternal"))
        code, pairs = cli(root, *args, expected=expected)
        assert code == 1 and len(pairs[0]["excluded"]) == 1 and len(pairs[0]["unconfirmed"]) == 1
        mapping = root / "mapping.json"
        mapping.write_text(json.dumps({"left": "dev", "right": "stg", "target": "cde", "resources": [
            {"service": "logs", "resourceType": "Logs.LogGroup", "left": "DevExternal",
             "right": "StgExternal", "reason": "confirmed imported external log destination"}]}), encoding="utf-8")
        code, pairs = cli(root, *args, "--resource-map", str(mapping), expected=expected)
        assert code == 0 and not pairs[0]["differences"] and len(pairs[0]["excluded"]) == 2

        # IMPORT-only service on one side must not become an addition/removal.
        for present, absent in ((0, 1), (1, 0)):
            save(paths[present], imported())
            paths[absent].unlink()
            save(paths[absent].with_name("placeholder.properties"), "desired.service.placeholder.serviceId=placeholder\n")
            code, pairs = cli(root, *args, expected=expected)
            assert code == 0 and not pairs[0]["differences"] and len(pairs[0]["excluded"]) == 1
        save(paths[0], model("001"))
        save(paths[1], model("007") + "desired.resource.007.resourceMode=CREATE\n")
        code, pairs = cli(root, *args, expected=expected)
        assert code == 0 and not pairs[0]["differences"] and not pairs[0]["excluded"]
        save(paths[1], model("007", "90"))
        assert len(cli(root, *args, expected=expected)[1][0]["differences"]) == 1

        for mode in ("", "REFERENCE", "import", "UNSET"):
            save(paths[1], model("007") + f"desired.resource.007.resourceMode={mode}\n")
            code, pairs = cli(root, *args, expected=expected)
            assert code == 1 and pairs[0]["status"] == "incomplete" and pairs[0]["errors"]

        # Excluded resources stay available as destinations of CREATE references.
        for index, env in enumerate(("dev", "stg")):
            body = model("001")
            body += "desired.service.logs.ownedCatalogResourceTypes=Logs.LogGroup" + (",KMS.Key" if index else "") + "\n"
            body += "desired.row.001-005.property=Logs.LogGroup.ExternalTarget\n"
            body += f"desired.row.001-005.value=[{env} external](#logs-{env}-a)\n"
            body += f"desired.resource.001.parentReference=[parent](#logs-{env}-a)\n"
            for number, suffix in (("002", "a"), ("003", "b")):
                body += imported(number, f"External{suffix}", f"logs-{env}-{suffix}", "90" if index else "30").replace(
                    "desired.service.logs.serviceId=logs\n", "")
            # A stale derived digest on IMPORT does not enter the comparison.
            body += "desired.row.002-002.artifactSha256=excluded-digest\n"
            save(paths[index], body)
        original = paths[1].read_text(encoding="utf-8")
        code, pairs = cli(root, *args, expected=expected)
        assert code == 0 and not pairs[0]["differences"] and len(pairs[0]["excluded"]) == 4
        paths[1].write_text(original.replace(".value=30", ".value=60"), encoding="utf-8")
        code, pairs = cli(root, *args, expected=expected)
        assert code == 0 and len(pairs[0]["differences"]) == 1
        assert "RetentionInDays" in pairs[0]["differences"][0]["identity"][-3]
        paths[1].write_text(original.replace(
            "desired.row.001-005.value=[stg external](#logs-stg-a)",
            "desired.row.001-005.value=[other](#logs-stg-b)"), encoding="utf-8")
        code, pairs = cli(root, *args, expected=expected)
        assert code == 0 and len(pairs[0]["differences"]) == 1
        assert "ExternalTarget" in pairs[0]["differences"][0]["identity"][-3]


def main():
    import_mode_checks()
    logical_id_checks()
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
    print("Environment desired comparison checks: PASS (IMPORT exclusions, CREATE defaults/references, logical ID mapping, unconfirmed resources, actual settings, invalid maps/modes, four pairs, scope, desired-only, indexed models, evidence, read-only)")


if __name__ == "__main__":
    main()
