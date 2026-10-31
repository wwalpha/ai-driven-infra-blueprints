import ast
import json
import subprocess
import tempfile
from pathlib import Path

from model.audit import generate
from support.model_sources import write_model

from model import audit_runtime as audit


class ReferenceFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="audit-reference-unit-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "project.json").write_text(
            json.dumps(
                {
                    "projectName": "fixture",
                    "targets": [
                        {
                            "environment": "dev",
                            "alias": "cde",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.consumer = self.model(
            "EC2.FlowLog",
            "EC2_FlowLog_001",
            {
                "Id": "fl-fixture",
                "LogGroupName": self.ref("Logs_LogGroup_001", "LogGroupName"),
            },
        )
        self.producer = self.model(
            "Logs.LogGroup",
            "Logs_LogGroup_001",
            {"LogGroupName": "/aws/vpc/flowlogs/fixture"},
        )
        self.save()

    @staticmethod
    def ref(logical, attribute):
        return {"$modelRef": {"logicalId": logical, "attribute": attribute}}

    @staticmethod
    def model(kind, logical, rows):
        values = {
            "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
            "desired.resource.001.resourceType": kind,
            "desired.resource.001.logicalId": logical,
            "desired.resource.001.anchor": "fixture",
            "desired.resource.001.cfn-logicalId": "fixture-" + logical.replace("_", ""),
        }
        for index, (prop, value) in enumerate(rows.items(), 1):
            prefix = f"desired.row.001-{index:03d}."
            values.update(
                {
                    prefix + "property": kind + "." + prop,
                    prefix + "value": "`"
                    + (value if isinstance(value, str) else json.dumps(value))
                    + "`",
                    prefix + "comment": "fixture",
                }
            )
        return values

    def save(self):
        for service, values in [
            ("vpc", self.consumer),
            ("cloudwatch-logs", self.producer),
        ]:
            write_model(self.root / "model/dev/cde" / (service + ".properties"), values)

    def snapshot(self):
        source = generate(self.root, "dev", "cde", "vpc")[0]
        assignment = ast.parse(source).body[1]
        return json.loads(ast.literal_eval(assignment.value.args[0]))

    def cli(self, command, **kwargs):
        if command[1] == "sts":
            value = {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/offline",
            }
        else:
            value = {
                "FlowLogs": []
                if self.missing
                else [
                    {
                        "FlowLogId": "fl-fixture",
                        "LogGroupName": self.actual,
                        "Tags": [{"Key": "/aws/vpc/flowlogs/fixture"}],
                    }
                ]
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    def result(self, snapshot):
        self.actual, self.missing = ("/aws/vpc/flowlogs/fixture", False)
        return [
            item
            for item in audit.audit(snapshot, cli_runner=self.cli)[2]
            if item["propertiesKey"] == "EC2.FlowLog.LogGroupName"
        ][0]
