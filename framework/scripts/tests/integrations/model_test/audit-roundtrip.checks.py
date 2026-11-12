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
from datetime import datetime, timezone

from model.importing.cli import model_literal
from support.it_case_receipt import it_case
from support.model_test_references import ReferenceFixture
from support.model_test_runner import CLI, generated, load_fixture, prepare, snapshot
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
        runs = [run for run in expected["runs"] if run["code"] == 0]
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
            saved = log_directory / "vpc.log"
            assert saved.read_text(encoding="utf-8") == process.stdout
            actual_calls = [
                json.loads(line)
                for line in calls.read_text(encoding="utf-8").splitlines()
            ]
            assert actual_calls == run["calls"], actual_calls
        assert {path: path.read_bytes() for path in before} == before
        findings = Findings(root)
        check_results(root, {("dev", "cde"): {}}, False, {}, findings)
        assert not findings.errors, findings.errors


def _windows_cli(_command, **kwargs):
    program = (
        "import json, os, sys; "
        "value = json.dumps({'Description': 'ログキー'}, ensure_ascii=False); "
        "sys.stdout.buffer.write(value.encode(os.environ.get("
        "'AWS_CLI_OUTPUT_ENCODING', 'cp932')))"
    )
    return subprocess.run([sys.executable, "-c", program], **kwargs)


@it_case
def check_japanese_cli_output():
    inputs, _ = load_fixture("audit/base")
    with tempfile.TemporaryDirectory(prefix="audit-encoding-") as directory:
        root = Path(directory)
        standalone = generated(prepare(root, inputs), root)
        target = standalone["SNAPSHOT"]["target"]

        ctx = standalone["engine"](standalone["SNAPSHOT"]).Context(
            root, target, cli_runner=_windows_cli, services=[]
        )
        assert ctx.cli("kms", "describe_key", {}) == {"Description": "ログキー"}


@it_case
def check_macie_empty_scoping():
    inputs, _ = load_fixture("macie/lookup")
    prop = "Macie.ClassificationJob.s3JobDefinition"
    buckets = [{"accountId": "123456789012", "buckets": ["fixture-bucket"]}]
    design = {"bucketDefinitions": buckets}
    inputs["model"].update(
        {
            "desired.row.001-004.property": prop,
            "desired.row.001-004.value": model_literal(design),
            "desired.row.001-004.comment": "fixture",
        }
    )
    response = inputs["responses"][1]["response"]
    term = {"key": "OBJECT_EXTENSION", "comparator": "EQ", "values": ["pdf"]}
    cases = (
        ({}, []),
        ({"scoping": {}}, []),
        (
            {"scoping": {"includes": {"and": [{"simpleScopeTerm": term}]}}},
            ["$.scoping"],
        ),
        (
            {
                "bucketDefinitions": [{**buckets[0], "buckets": ["other-bucket"]}],
                "scoping": {},
            },
            ["$.bucketDefinitions[0].buckets[0]"],
        ),
    )
    with tempfile.TemporaryDirectory(prefix="audit-macie-scoping-") as directory:
        root = Path(directory)
        standalone = generated(prepare(root, inputs), root)
        responses = {tuple(item["api"]): item["response"] for item in inputs["responses"]}
        for changes, paths in cases:
            responses[("macie2", "describe-classification-job")] = {
                **response,
                "s3JobDefinition": {**design, **changes},
            }
            _, _, records = standalone["audit"](
                standalone["SNAPSHOT"], cli_runner=CLI(responses)
            )
            (item,) = (item for item in records if item["propertiesKey"] == prop)
            assert item["status"] == ("difference" if paths else "match"), item
            assert (
                standalone["different_paths"](item["designValue"], item["awsValue"])
                == paths
            )


@it_case
def check_lakeformation_list_identity():
    inputs, _ = load_fixture("lakeformation/federation")
    arn = "arn:aws:s3:::fixture-bucket"
    inputs["model"].update(
        {
            "desired.row.001-004.property": "LakeFormation.Resource.Id",
            "desired.row.001-004.value": '`{"$modelRef":{"logicalId":"LakeFormation_Resource_001","attribute":"Id"}}`',
            "desired.row.001-004.comment": "fixture",
            "observed.row.001-004.value": "`PENDING_DEPLOY`",
            "desired.row.001-005.property": "LakeFormation.Resource.RoleArn",
            "desired.row.001-005.value": "`arn:aws:iam::123456789012:role/expected`",
            "desired.row.001-005.comment": "fixture",
        }
    )
    with tempfile.TemporaryDirectory(prefix="audit-lakeformation-") as directory:
        root = Path(directory)
        standalone = generated(prepare(root, inputs), root)
        for entries, expected in (
            (
                [{"ResourceArn": arn, "WithFederation": True}],
                ("match", "excluded", "match"),
            ),
            (
                [{"ResourceArn": arn, "WithFederation": False}],
                ("match", "excluded", "difference"),
            ),
            ([{"ResourceArn": arn}], ("match", "excluded", "sdk_unavailable")),
            (
                [{"ResourceArn": arn + "-other", "WithFederation": True}],
                ("sdk_unavailable", "sdk_unavailable", "sdk_unavailable"),
            ),
            (
                [{"ResourceArn": arn}, {"ResourceArn": arn}],
                ("sdk_unavailable", "sdk_unavailable", "sdk_unavailable"),
            ),
            ([], ("sdk_unavailable", "sdk_unavailable", "sdk_unavailable")),
        ):
            runner = CLI(
                {
                    ("lakeformation", "describe-resource"): {
                        "ResourceInfo": {
                            "RoleArn": "arn:aws:iam::123456789012:role/fixture"
                        }
                    },
                    ("lakeformation", "list-resources"): {"ResourceInfoList": entries},
                }
            )
            _, _, records = standalone["audit"](
                standalone["SNAPSHOT"], cli_runner=runner
            )
            statuses = {
                item["propertiesKey"].rsplit(".", 1)[-1]: item["status"]
                for item in records
            }
            assert (
                tuple(
                    statuses[key]
                    for key in ("ResourceArn", "UseServiceLinkedRole", "WithFederation")
                )
                == expected
            )
            assert statuses["Id"] == (
                "excluded" if expected[0] == "match" else "sdk_unavailable"
            )
            assert runner.calls[-1][1] == {
                "FilterConditionList": [
                    {
                        "Field": "RESOURCE_ARN",
                        "ComparisonOperator": "EQ",
                        "StringValueList": [arn],
                    }
                ]
            }
        runner = CLI(
            {
                ("lakeformation", "describe-resource"): {
                    "ResourceInfo": {
                        "RoleArn": "arn:aws:iam::123456789012:role/fixture"
                    }
                }
            },
            fail=("lakeformation", "list-resources"),
        )
        _, _, records = standalone["audit"](standalone["SNAPSHOT"], cli_runner=runner)
        statuses = {
            item["propertiesKey"].rsplit(".", 1)[-1]: item["status"] for item in records
        }
        assert statuses["ResourceArn"] == "acquisition_failed"
        assert statuses["WithFederation"] == "acquisition_failed"
        assert statuses["RoleArn"] == "difference"
        assert statuses["UseServiceLinkedRole"] == "sdk_unavailable"
        assert statuses["Id"] == "sdk_unavailable"


@it_case
def check_eventbridge_target_audit():
    inputs, _ = load_fixture("audit/base")
    kind = "Events.Rule"
    target = {
        "Id": "fixture-target",
        "Arn": "arn:aws:codepipeline:ap-northeast-1:123456789012:fixture-pipeline",
        "RoleArn": "arn:aws:iam::123456789012:role/fixture",
        "InputTransformer": {"InputPathsMap": {"id": "$.id"}, "InputTemplate": "<id>"},
    }
    rows = {
        "Name": "fixture-rule",
        "Targets[].Id": target["Id"],
        "Targets[].Arn": target["Arn"],
        "Targets[].RoleArn": target["RoleArn"],
        "Targets[].InputTransformer.InputPathsMap": target["InputTransformer"][
            "InputPathsMap"
        ],
        "Targets[].InputTransformer.InputTemplate": target["InputTransformer"][
            "InputTemplate"
        ],
    }
    inputs["service"] = "eventbridge"
    inputs["models"] = {
        "dev/cde/codepipeline": ReferenceFixture.model(
            "CodePipeline.Pipeline",
            "CodePipeline_Pipeline_001",
            {"Name": "fixture-pipeline"},
        )
    }
    rows["Targets[].Arn"] = {
        "Fn::Sub": [
            "arn:aws:codepipeline:ap-northeast-1:123456789012:${PipelineName}",
            {"PipelineName": ReferenceFixture.ref("CodePipeline_Pipeline_001", "Name")},
        ]
    }
    inputs["model"] = {
        "desired.service.eventbridge.serviceId": "eventbridge",
        "desired.service.eventbridge.ownedCatalogResourceTypes": kind,
        "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
        "desired.resource.001.resourceType": kind,
        "desired.resource.001.resourceMode": "IMPORT",
        "desired.resource.001.logicalId": "Events_Rule_001",
    }
    for index, (prop, value) in enumerate(rows.items(), 1):
        key = f"desired.row.001-{index:03}."
        inputs["model"].update(
            {
                key + "property": kind + "." + prop,
                key + "value": model_literal(value),
                key + "comment": "fixture",
            }
        )
    targets_api = ("events", "list-targets-by-rule")
    with tempfile.TemporaryDirectory(prefix="audit-eventbridge-") as directory:
        root = Path(directory)
        standalone = generated(prepare(root, inputs), root)
        snap = standalone["SNAPSHOT"]
        for variant, expected_code in (("match", 0), ("different", 1), ("denied", 2)):
            actual = copy.deepcopy(target)
            if variant == "different":
                actual.update(
                    Arn=target["Arn"] + "-different",
                    RoleArn=target["RoleArn"] + "-different",
                    InputTransformer={
                        "InputPathsMap": {"id": "$.other"},
                        "InputTemplate": "<other>",
                    },
                )
            runner = CLI(
                {
                    ("events", "describe-rule"): {"Name": "fixture-rule"},
                    targets_api: {"Targets": [actual]},
                },
                fail=targets_api if variant == "denied" else None,
            )
            _, account, records = standalone["audit"](snap, cli_runner=runner)
            report, code = standalone["report"](
                snap, None, account, records, datetime.now(timezone.utc)
            )
            assert code == expected_code, report
            state = {0: "OK", 1: "NG", 2: "ERROR"}[expected_code]
            for field in ["Targets[].Arn", *list(rows)[-3:]]:
                assert f"[{state}] {kind} | fixture-rule | {field}" in report, report
            assert [
                (api, request) for api, request, _ in runner.calls if api == targets_api
            ] == [(targets_api, {"Rule": "fixture-rule", "EventBusName": "default"})]


@it_case
def check_hidden_secret_reference_audit():
    inputs, _ = load_fixture("audit/base")
    ref = ReferenceFixture.ref("SecretsManager_Secret_001", "Id")
    values = ReferenceFixture.model(
        "SecretsManager.Secret", "SecretsManager_Secret_001", {"Name": "fixture-secret"}
    )
    schedule = ReferenceFixture.model(
        "SecretsManager.RotationSchedule",
        "SecretsManager_RotationSchedule_001",
        {"SecretId": ref},
    )
    for key, value in schedule.items():
        if key.startswith(("desired.resource.001.", "desired.row.001-")):
            values[key.replace(".001", ".002", 1)] = value
    values["desired.service.identity.lastAllocated"] = json.dumps(
        {"SecretsManager.Secret": 1, "SecretsManager.RotationSchedule": 1}
    )
    values["desired.resource.002.parentReference"] = json.dumps(ref)
    values["desired.resource.002.parentProperty"] = (
        "SecretsManager.RotationSchedule.SecretId"
    )
    inputs.update(service="secrets-manager", model=values)
    inputs.pop("models", None)
    with tempfile.TemporaryDirectory(prefix="audit-secret-") as directory:
        root = Path(directory)
        standalone = generated(prepare(root, inputs), root)
        snap = standalone["SNAPSHOT"]
        for variant, expected in (
            ("match", "match"),
            ("wrong-name", "design_unresolved"),
            ("denied", "acquisition_failed"),
        ):
            response = {
                "Name": "other" if variant == "wrong-name" else "fixture-secret",
                "ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:fixture-secret-Ab12cd",
            }
            runner = CLI(
                {("secretsmanager", "describe-secret"): response},
                fail=("secretsmanager", "describe-secret")
                if variant == "denied"
                else None,
            )
            records = standalone["audit"](snap, cli_runner=runner)[2]
            item = next(
                item
                for item in records
                if item["propertiesKey"] == "SecretsManager.RotationSchedule.SecretId"
            )
            assert item["status"] == expected, item


@it_case
def check_iam_parallel_generated_audit():
    inputs, _ = load_fixture("iam/inline")
    model = inputs["model"]
    for key, value in list(model.items()):
        if key.startswith("desired.resource.001.") or key.startswith(
            "desired.row.001-"
        ):
            new_key = key.replace(".001.", ".002.").replace(".001-", ".002-")
            model[new_key] = value.replace("IAM_Role_001", "IAM_Role_002").replace(
                "test-role", "other-role"
            )
    model["desired.service.identity.lastAllocated"] = '{"IAM.Role": 2}'
    with tempfile.TemporaryDirectory(prefix="audit-iam-parallel-") as directory:
        root = Path(directory)
        standalone = generated(prepare(root, inputs), root)
        snap = standalone["SNAPSHOT"]
        cli = CLI(
            {
                ("iam", "get-role"): lambda request: {
                    "Role": {"RoleName": request["RoleName"]}
                },
                ("iam", "list-role-policies"): {"PolicyNames": ["policy"]},
                ("iam", "get-role-policy"): {"PolicyDocument": {}},
            }
        )
        _, account, records = standalone["audit"](snap, cli_runner=cli)
        assert account == "123456789012"
        assert len(records) == 4 and all(
            item["status"] == "match" for item in records
        ), records
        requests = [(api, request) for api, request, _ in cli.calls]
        for name in ("test-role", "other-role"):
            assert (
                requests.count((("iam", "list-role-policies"), {"RoleName": name})) == 2
            )
            assert (
                requests.count(
                    (
                        ("iam", "get-role-policy"),
                        {"RoleName": name, "PolicyName": "policy"},
                    )
                )
                == 1
            )


FAKE_AWS = 'import json, os, pathlib, sys\napi = sys.argv[1:3]\nrequest = json.loads(sys.argv[sys.argv.index("--cli-input-json") + 1])\nsettings = json.loads(pathlib.Path(os.environ["AUDIT_RESPONSES"]).read_text(encoding="utf-8"))\nwith pathlib.Path(os.environ["AUDIT_CALLS"]).open("a", encoding="utf-8") as handle:\n    handle.write(json.dumps([api, request]) + "\\n")\nif api == ["sts", "get-caller-identity"]:\n    assert request == {}\n    value = {"Account": settings.get("account", "123456789012"), "Arn": "arn:aws:iam::123456789012:user/offline"}\nelse:\n    route = next(item for item in settings["responses"] if item["api"] == api)\n    assert request == route["inputs"], (request, route)\n    value = route["response"]\nprint(json.dumps(value))\n'


if __name__ == "__main__":
    check_audit_roundtrip()
    check_japanese_cli_output()
    check_macie_empty_scoping()
    check_lakeformation_list_identity()
    check_eventbridge_target_audit()
    check_iam_parallel_generated_audit()
    check_hidden_secret_reference_audit()
