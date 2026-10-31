"""Offline Model audit fixture execution and exact expected-result comparison."""

import ast
import copy
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from model.audit import generate
from support.model_sources import write_model

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/model_test"


class CLI:
    def __init__(self, responses, account="123456789012", fail=None):
        self.indices = {}
        self.responses, self.account, self.fail, self.calls = (
            responses,
            account,
            fail,
            [],
        )

    def __call__(self, command, **kwargs):
        assert command[0] == "aws"
        api = tuple(command[1:3])
        inputs = json.loads(command[command.index("--cli-input-json") + 1])
        self.calls.append((api, inputs, command))
        assert (
            "--region" in command
            and command[command.index("--region") + 1] == "ap-northeast-1"
        )
        if api == self.fail:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "An error occurred (AccessDenied) when calling Mock: secret-not-for-output",
            )
        elif api == ("sts", "get-caller-identity") and api not in self.responses:
            value = {
                "Account": self.account,
                "Arn": "arn:aws:iam::" + self.account + ":user/offline",
            }
        else:
            assert api in self.responses, api
            value = self.responses[api]
            value = value(inputs) if callable(value) else value
        if isinstance(value, dict) and "$sequence" in value:
            index = self.indices.get(api, 0)
            self.indices[api] = index + 1
            step = value["$sequence"][index]
            assert inputs == step["inputs"], (api, inputs, step)
            value = step["response"]
        if isinstance(value, dict) and "$error" in value:
            return subprocess.CompletedProcess(command, 254, "", value["$error"])
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")


def load_fixture(name):
    inputs = json.loads((FIXTURES / (name + ".input.json")).read_text(encoding="utf-8"))
    if "projectFixture" in inputs:
        assert "project" not in inputs, "fixture has two project authorities"
        provider = inputs.pop("projectFixture")
        inputs["project"] = json.loads(
            (FIXTURES / (provider + ".input.json")).read_text(encoding="utf-8")
        )["project"]
    expected = json.loads(
        (FIXTURES / (name + ".expected.json")).read_text(encoding="utf-8")
    )
    return inputs, expected


def prepare(root, inputs, overrides=None):
    (root / "project.json").write_text(json.dumps(inputs["project"]), encoding="utf-8")
    model = dict(inputs["model"])
    for key, value in (overrides or {}).items():
        if value is None:
            model.pop(key, None)
        else:
            model[key] = value
    for address, values in inputs.get("models", {}).items():
        write_model(root / "model" / (address + ".properties"), values)
    write_model(root / ("model/dev/cde/" + inputs["service"] + ".properties"), model)
    return generate(root, "dev", "cde", inputs["service"])[0]


def generated(source, root):
    namespace = {"__name__": "audit_fixture", "__file__": str(root / "audit.py")}
    exec(compile(source, "<generated-audit>", "exec"), namespace)
    for adapter in namespace["SNAPSHOT"]["adapters"].values():
        assert "model.adapters.aws" not in adapter
        assert "model.importing.sdk_inventory" not in adapter
    return namespace


def path_value(value, path):
    for key in path:
        value = value[key]
    return value


def execute(fixture):
    inputs, _expected = fixture
    results, sources = [], {}
    with TemporaryDirectory(prefix="audit-unit-") as directory:
        root = Path(directory)
        for scenario in inputs["scenarios"]:
            identity = json.dumps(
                {
                    key: value
                    for key, value in {
                        **inputs["model"],
                        **scenario.get("model", {}),
                    }.items()
                    if value is not None
                },
                sort_keys=True,
            )
            if identity not in sources:
                sources[identity] = prepare(root, inputs, scenario.get("model"))
            namespace = generated(sources[identity], root)
            snap = namespace["SNAPSHOT"]
            for update in scenario.get("snapshotUpdates", []):
                path_value(snap, update["path"][:-1])[update["path"][-1]] = update[
                    "value"
                ]
            responses = {
                tuple(item["api"]): item["response"]
                for item in inputs.get("responses", [])
            }
            responses.update(
                {
                    tuple(item["api"]): item["response"]
                    for item in scenario.get("responses", [])
                }
            )
            cli = CLI(
                responses,
                account=scenario.get("account", "123456789012"),
                fail=tuple(scenario.get("fail", [])),
            )
            _, account, records = namespace["audit"](snap, None, cli)
            properties = inputs.get("properties")
            selected = [
                item
                for item in records
                if properties is None or item["propertiesKey"] in properties
            ]
            selected.sort(key=lambda item: item["propertiesKey"])
            actual = {
                "records": [
                    {key: item[key] for key in scenario.get("fields", inputs["fields"])}
                    for item in selected
                ],
                "calls": [
                    [list(api), args] for api, args, _ in cli.calls if api[0] != "sts"
                ],
            }
            if inputs.get("report"):
                report_records = records
                if "reportRecords" in scenario:
                    report_records = [
                        item
                        for item in records
                        if item["propertiesKey"] in scenario["reportRecords"]
                    ]
                actual["report"], actual["code"] = namespace["report"](
                    snap,
                    None,
                    account,
                    report_records,
                    datetime(2026, 10, 15, tzinfo=timezone.utc),
                )
            if "snapshotValues" in inputs:
                actual["snapshotValues"] = {
                    key: path_value(snap, path)
                    for key, path in scenario.get(
                        "snapshotValues", inputs["snapshotValues"]
                    ).items()
                }
            results.append(actual)
    return results


def assert_result(actual, fixture):
    expected = fixture[1]
    assert len(actual) == len(expected), (len(actual), len(expected))
    for result, wanted in zip(actual, expected, strict=True):
        result, wanted = dict(result), dict(wanted)
        if "report" in wanted:
            text = result.pop("report")
            checks = wanted.pop("report")
            assert set(checks) <= {"contains", "absent", "counts"}, checks
            for value in checks.get("contains", []):
                assert value in text, (value, text)
            for value in checks.get("absent", []):
                assert value not in text, (value, text)
            for value, count in checks.get("counts", []):
                assert text.count(value) == count, (value, count, text)
        assert json.dumps(result, sort_keys=True, allow_nan=False) == json.dumps(
            wanted, sort_keys=True, allow_nan=False
        ), (result, wanted)


def fixture(base, service, resources):
    data = copy.deepcopy(base)
    data["service"] = service
    data["target"] = {
        "environment": "dev",
        "directory": "cde",
        "awsAccountId": "111111111111",
        "awsExecutionAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
    }
    values = {}
    for number, kind, anchor, rows in resources:
        for key, value in {
            "resourceType": kind,
            "anchor": anchor,
            "cfn-logicalId": "fixture-" + anchor.replace("-", "").title(),
            "logicalId": kind.replace(".", "_") + "_" + str(number).zfill(3),
        }.items():
            values[f"desired.resource.{number}.{key}"] = value
        for index, (prop, value, document) in enumerate(rows, 1):
            prefix = f"desired.row.{number}-{index:03d}."
            values.update(
                {
                    prefix + "property": kind + "." + prop,
                    prefix + "value": value,
                    prefix + "comment": "fixture",
                }
            )
            if document is not None:
                values[prefix + "document"] = json.dumps(document)
    values["desired.service.identity.lastAllocated"] = json.dumps(
        {
            kind: max(
                int(number) for number, selected, _, _ in resources if selected == kind
            )
            for _, kind, _, _ in resources
        }
    )
    data["models"] = {"dev/cde/" + service: values}
    return data


def snapshot(source):
    node = ast.parse(source).body[1]
    assert isinstance(node, ast.Assign) and node.targets[0].id == "SNAPSHOT"
    return json.loads(ast.literal_eval(node.value.args[0]))
