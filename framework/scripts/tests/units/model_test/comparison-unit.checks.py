import ast
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import copy
from types import SimpleNamespace as _CallbackState
from unittest import TestCase

from design.layout import confirmed_display_name
from model.adapters.aws import AcquisitionError, Unresolved, sdk_error, service_module
from model.audit import (
    build_snapshot,
    generate,
    pipeline_indexed_rows,
)
from model.core import entries
from model.projection import validate_json_documents
from model.reference_values import confirmed
from model.sources import load_model
from support.model_sources import write_model
from support.model_test_references import ReferenceFixture
from support.model_test_runner import (
    CLI,
    assert_result,
    execute,
    fixture,
    generated,
    load_fixture,
    snapshot,
)
from support.model_test_runtime import runtime
from support.pytest_cli import run

from model import audit as generator
from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _sg_sdk_error(code):
    error = Exception()
    error.response = {"Error": {"Code": code}}
    return sdk_error("ec2.describe_security_group_rules", error, {})


class CloudTrailArrayTests(unittest.TestCase):
    setUp = ReferenceFixture.setUp
    model = staticmethod(ReferenceFixture.model)
    ref = staticmethod(ReferenceFixture.ref)
    save = ReferenceFixture.save

    @staticmethod
    def records(snapshot, response):
        cli = Mock(
            side_effect=[
                subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps(
                        {
                            "Account": "123456789012",
                            "Arn": "arn:aws:iam::123456789012:user/offline",
                        }
                    ),
                    "",
                ),
                subprocess.CompletedProcess(
                    [], 0, json.dumps({"Trail": {"Name": "fixture"}}), ""
                ),
                subprocess.CompletedProcess(
                    [], 0, json.dumps({"EventSelectors": response}), ""
                ),
            ]
        )
        return audit.audit(snapshot, cli_runner=cli)[2]

    def test_reference_array_membership(self):
        arn = "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture"
        producer = self.model(
            "Lambda.Function", "Lambda_Function_001", {"FunctionName": "fixture"}
        )
        write_model(self.root / "model/dev/cde/lambda.properties", producer)
        values = self.model("CloudTrail.Trail", "CloudTrail_Trail_001", {})
        fields = [
            ("TrailName", "`fixture`"),
            ("EventSelectors[].IncludeManagementEvents", "`true`"),
            ("EventSelectors[].ReadWriteType", "`All`"),
            ("EventSelectors[].DataResources[].Type", "`AWS::Lambda::Function`"),
            (
                "EventSelectors[].DataResources[].Values",
                "`" + json.dumps([self.ref("Lambda_Function_001", "Arn")]) + "`",
            ),
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3"]`'),
            ("EventSelectors[].IncludeManagementEvents", "`false`"),
            ("EventSelectors[].ReadWriteType", "`ReadOnly`"),
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3:::other/"]`'),
        ]
        for index, (prop, value) in enumerate(fields, 1):
            prefix = f"desired.row.001-{index:03d}."
            values.update(
                {
                    prefix + "property": "CloudTrail.Trail." + prop,
                    prefix + "value": value,
                    prefix + "comment": "fixture",
                }
            )
        path = self.root / "model/dev/cde/cloudtrail.properties"
        write_model(path, values)
        selectors = [
            {
                "IncludeManagementEvents": True,
                "ReadWriteType": "All",
                "DataResources": [
                    {"Type": "AWS::Lambda::Function", "Values": [arn]},
                    {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3"]},
                ],
            },
            {
                "IncludeManagementEvents": False,
                "ReadWriteType": "ReadOnly",
                "DataResources": [
                    {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3:::other/"]}
                ],
            },
        ]
        source = generate(self.root, "dev", "cde", "cloudtrail")[0]
        snapshot = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        self.assertEqual(
            snapshot["referenceRows"]["dev/cde/cloudtrail"]["001-005"]["status"],
            "resolved",
        )
        for response, prop, expected in [
            (selectors, "ReadWriteType", "match"),
            (
                [dict(selectors[0], ReadWriteType="WriteOnly"), selectors[1]],
                "ReadWriteType",
                "difference",
            ),
            (
                [
                    dict(
                        selectors[0],
                        DataResources=[
                            dict(
                                selectors[0]["DataResources"][0],
                                Values=[arn + "-other"],
                            ),
                            selectors[0]["DataResources"][1],
                        ],
                    ),
                    selectors[1],
                ],
                "DataResources[].Values",
                "difference",
            ),
            (
                [
                    dict(
                        selectors[0], DataResources=selectors[0]["DataResources"][::-1]
                    ),
                    selectors[1],
                ],
                "DataResources[].Values",
                "difference",
            ),
        ]:
            with self.subTest(prop=prop, expected=expected):
                result = next(
                    (
                        r
                        for r in self.records(snapshot, response)
                        if r["propertiesKey"].endswith(prop)
                    )
                )
                self.assertEqual(result["status"], expected, result)
        self.assertTrue(
            all(
                (
                    r["status"] == "match"
                    for r in self.records(snapshot, selectors)
                    if "EventSelectors[]" in r["propertiesKey"]
                )
            )
        )
        namespace = generated(source, self.root)
        cli = CLI(
            {
                ("cloudtrail", "get-trail"): {"Trail": {"Name": "fixture"}},
                ("cloudtrail", "get-event-selectors"): {"EventSelectors": selectors},
            }
        )
        _, account, records = namespace["audit"](namespace["SNAPSHOT"], None, cli)
        text, code = namespace["report"](
            namespace["SNAPSHOT"], None, account, records, datetime.now(timezone.utc)
        )
        self.assertEqual(code, 0, text)
        for missing in ("004", "005"):
            incomplete = dict(values)
            for field in ("property", "value", "comment"):
                incomplete.pop(f"desired.row.001-{missing}.{field}")
            write_model(path, incomplete)
            snapshot = build_snapshot(self.root, "dev", "cde", "cloudtrail")[0]
            result = next(
                (
                    r
                    for r in self.records(snapshot, selectors)
                    if r["propertiesKey"].endswith("ReadWriteType")
                )
            )
            self.assertEqual(result["status"], "design_unresolved", result)
        values["desired.row.001-005.value"] = (
            "`" + json.dumps([self.ref("Missing_001", "Arn")]) + "`"
        )
        write_model(path, values)
        snapshot = build_snapshot(self.root, "dev", "cde", "cloudtrail")[0]
        result = next(
            (
                r
                for r in self.records(snapshot, selectors)
                if r["propertiesKey"].endswith("DataResources[].Values")
            )
        )
        self.assertNotEqual(result["status"], "match", result)

    def test_event_selector_membership(self):
        fields = [
            ("TrailName", "`fixture`"),
            ("EventSelectors[].IncludeManagementEvents", "`true`"),
            ("EventSelectors[].ReadWriteType", "`All`"),
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3"]`'),
            ("EventSelectors[].DataResources[].Type", "`AWS::Lambda::Function`"),
            (
                "EventSelectors[].DataResources[].Values",
                '`["arn:aws:lambda:ap-northeast-1:123456789012:function:a"]`',
            ),
            ("EventSelectors[].IncludeManagementEvents", "`false`"),
            ("EventSelectors[].ReadWriteType", "`ReadOnly`"),
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3:::other/"]`'),
        ]
        values = self.model("CloudTrail.Trail", "CloudTrail_Trail_001", {})
        for index, (prop, value) in enumerate(fields, 1):
            prefix = f"desired.row.001-{index:03d}."
            values.update(
                {
                    prefix + "property": "CloudTrail.Trail." + prop,
                    prefix + "value": value,
                    prefix + "comment": "fixture",
                }
            )
        path = self.root / "model/dev/cde/cloudtrail.properties"
        write_model(path, values)
        selectors = [
            {
                "IncludeManagementEvents": True,
                "ReadWriteType": "All",
                "DataResources": [
                    {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3"]},
                    {
                        "Type": "AWS::Lambda::Function",
                        "Values": [
                            "arn:aws:lambda:ap-northeast-1:123456789012:function:a"
                        ],
                    },
                ],
            },
            {
                "IncludeManagementEvents": False,
                "ReadWriteType": "ReadOnly",
                "DataResources": [
                    {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3:::other/"]}
                ],
            },
        ]
        snapshot = build_snapshot(self.root, "dev", "cde", "cloudtrail")[0]
        for response, expected, data_expected in [
            (selectors, "match", "match"),
            (
                [dict(selectors[0], ReadWriteType="ReadOnly"), selectors[1]],
                "difference",
                "match",
            ),
            (selectors[::-1], "difference", "difference"),
            (
                [
                    dict(
                        selectors[0], DataResources=selectors[0]["DataResources"][::-1]
                    ),
                    selectors[1],
                ],
                "match",
                "difference",
            ),
        ]:
            with self.subTest(expected=expected, response=response):
                cli = Mock(
                    side_effect=[
                        subprocess.CompletedProcess(
                            [],
                            0,
                            json.dumps(
                                {
                                    "Account": "123456789012",
                                    "Arn": "arn:aws:iam::123456789012:user/offline",
                                }
                            ),
                            "",
                        ),
                        subprocess.CompletedProcess(
                            [], 0, json.dumps({"Trail": {"Name": "fixture"}}), ""
                        ),
                        subprocess.CompletedProcess(
                            [], 0, json.dumps({"EventSelectors": response}), ""
                        ),
                    ]
                )
                records = audit.audit(snapshot, cli_runner=cli)[2]
                result = next(
                    (
                        item
                        for item in records
                        if item["propertiesKey"]
                        == "CloudTrail.Trail.EventSelectors[].ReadWriteType"
                    )
                )
                self.assertEqual(result["status"], expected, result)
                data = next(
                    (
                        item
                        for item in records
                        if item["propertiesKey"]
                        == "CloudTrail.Trail.EventSelectors[].DataResources[].Type"
                    )
                )
                self.assertEqual(data["status"], data_expected, data)
                if expected == data_expected == "match":
                    self.assertTrue(
                        all(
                            (
                                item["status"] == "match"
                                for item in records
                                if "EventSelectors[]" in item["propertiesKey"]
                            )
                        ),
                        records,
                    )
        prepared = [
            (
                f"001-{index:03d}",
                {"property": "CloudTrail.Trail." + prop, "value": value},
            )
            for index, (prop, value) in enumerate(fields, 1)
        ]
        prepared[4][1]["property"] = (
            "CloudTrail.Trail.EventSelectors[1].DataResources[1].Values[1]"
        )
        with patch("model.audit.cloudtrail_rows", return_value=prepared):
            rejected = build_snapshot(self.root, "dev", "cde", "cloudtrail")[0]
        self.assertEqual(
            rejected["cloudtrailIndexedRows"]["001"]["001-005"],
            "CloudTrail.Trail.EventSelectors[].DataResources[].Values",
        )
        values.pop("desired.row.001-011.property")
        values.pop("desired.row.001-011.value")
        values.pop("desired.row.001-011.comment")
        write_model(path, values)
        snapshot = build_snapshot(self.root, "dev", "cde", "cloudtrail")[0]
        self.assertEqual(
            snapshot["cloudtrailIndexedRows"]["001"]["001-003"],
            "CloudTrail.Trail.EventSelectors[].ReadWriteType",
        )
        cli = Mock(
            side_effect=[
                subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps(
                        {
                            "Account": "123456789012",
                            "Arn": "arn:aws:iam::123456789012:user/offline",
                        }
                    ),
                    "",
                ),
                subprocess.CompletedProcess(
                    [], 0, json.dumps({"Trail": {"Name": "fixture"}}), ""
                ),
                subprocess.CompletedProcess(
                    [], 0, json.dumps({"EventSelectors": selectors}), ""
                ),
            ]
        )
        records = audit.audit(snapshot, cli_runner=cli)[2]
        result = next(
            (
                item
                for item in records
                if item["propertiesKey"]
                == "CloudTrail.Trail.EventSelectors[].ReadWriteType"
            )
        )
        self.assertEqual(result["status"], "design_unresolved", result)


class PipelineMembershipTests(unittest.TestCase):
    save = ReferenceFixture.save
    setUp = ReferenceFixture.setUp
    model = staticmethod(ReferenceFixture.model)
    ref = staticmethod(ReferenceFixture.ref)

    def build(
        self,
        stages=2,
        actions=2,
        reference=False,
        ambiguous=False,
        varied=False,
        order="last",
        run_order=False,
        standalone=False,
    ):
        values = self.model(
            "CodePipeline.Pipeline", "CodePipeline_Pipeline_001", {"Name": "fixture"}
        )
        rows = []
        response = []
        for stage in range(stages):
            aws_actions = []
            for action in range(actions):
                name = f"action-{stage}-{action}"
                category = "Build" if reference else f"category-{stage}-{action}"
                project = f"project-{stage}-{action}"
                config = {
                    "ProjectName": self.ref("CodeBuild_Project_001", "Name")
                    if reference and stage == action == 0
                    else project
                }
                if reference and stage == action == 0:
                    project = "build-project"
                rows.extend(
                    [
                        (
                            "Stages[].Actions[].ActionTypeId.Category",
                            category,
                            "fixture",
                        ),
                        ("Stages[].Actions[].ActionTypeId.Owner", "AWS", "fixture"),
                        (
                            "Stages[].Actions[].ActionTypeId.Provider",
                            "CodeBuild",
                            "fixture",
                        ),
                        ("Stages[].Actions[].ActionTypeId.Version", "1", "fixture"),
                        (
                            "Stages[].Actions[].Configuration",
                            json.dumps(config),
                            "ProjectName: project",
                        ),
                        ("Stages[].Actions[].Name", name, "fixture"),
                    ]
                )
                if order == "middle":
                    rows[-2], rows[-1] = (rows[-1], rows[-2])
                elif order == "first":
                    rows.insert(len(rows) - 6, rows.pop())
                if varied and stage == 1 and (action == 1):
                    rows.insert(
                        -1, ("Stages[].Actions[].Namespace", "optional", "fixture")
                    )
                if run_order:
                    rows.append(("Stages[].Actions[].RunOrder", "1", "fixture"))
                aws_actions.append(
                    {
                        "name": name,
                        "actionTypeId": {
                            "category": category,
                            "owner": "AWS",
                            "provider": "CodeBuild",
                            "version": "1",
                        },
                        "configuration": {"ProjectName": project},
                    }
                )
                if run_order:
                    aws_actions[-1]["runOrder"] = 1
            if varied and stage == 1:
                aws_actions[1]["namespace"] = "optional"
            rows.append(("Stages[].Name", f"stage-{stage}", "fixture"))
            response.append({"name": f"stage-{stage}", "actions": aws_actions})
        if ambiguous:
            rows.pop(5)
        for index, (prop, value, comment) in enumerate(rows, 2):
            prefix = f"desired.row.001-{index:03d}."
            values.update(
                {
                    prefix + "property": "CodePipeline.Pipeline." + prop,
                    prefix + "value": "`" + value + "`",
                    prefix + "comment": comment,
                }
            )
        write_model(self.root / "model/dev/cde/codepipeline.properties", values)
        if reference:
            producer = self.model(
                "CodeBuild.Project", "CodeBuild_Project_001", {"Name": "build-project"}
            )
            write_model(self.root / "model/dev/cde/codebuild.properties", producer)
        model_path = self.root / "model/dev/cde/codepipeline.properties"
        validate_json_documents(load_model(model_path).authoritative, model_path)
        if standalone:
            source = generate(self.root, "dev", "cde", "codepipeline")[0]
            snap = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        else:
            source = None
            snap = build_snapshot(self.root, "dev", "cde", "codepipeline")[0]
        return (snap, response, source)

    def records(self, snapshot, stages):
        cli = Mock(
            side_effect=[
                subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps(
                        {
                            "Account": "123456789012",
                            "Arn": "arn:aws:iam::123456789012:user/offline",
                        }
                    ),
                    "",
                ),
                subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps({"pipeline": {"name": "fixture", "stages": stages}}),
                    "",
                ),
            ]
        )
        return audit.audit(snapshot, cli_runner=cli)[2]

    def test_membership_and_difference(self):
        for stages, actions in [(1, 1), (2, 2)]:
            with self.subTest(stages=stages, actions=actions):
                snapshot, response, _ = self.build(stages, actions)
                records = self.records(snapshot, response)
                selected = [r for r in records if "Stages[]" in r["propertiesKey"]]
                self.assertTrue(selected)
                self.assertTrue(
                    all((r["status"] == "match" for r in selected)), selected
                )
                response[0]["actions"][0]["configuration"]["ProjectName"] = "wrong"
                records = self.records(snapshot, response)
                config = next(
                    (
                        r
                        for r in records
                        if r["propertiesKey"].endswith(".Configuration")
                    )
                )
                category = next(
                    (r for r in records if r["propertiesKey"].endswith(".Category"))
                )
                self.assertEqual(config["status"], "difference", config)
                self.assertEqual(category["status"], "match", category)

    def test_run_order_membership_four_actions(self):
        for order in ("first", "last", "middle"):
            with self.subTest(order=order):
                snapshot, response, _ = self.build(2, 4, order=order, run_order=True)
                paths = snapshot["pipelineIndexedRows"]["001"]
                run_paths = [
                    path for path in paths.values() if path.endswith(".RunOrder")
                ]
                self.assertEqual(len(run_paths), 8)
                self.assertEqual(len(set(run_paths)), 8)
                records = self.records(snapshot, response)
                run = next(
                    (r for r in records if r["propertiesKey"].endswith(".RunOrder"))
                )
                self.assertEqual(run["status"], "match", run)
                response[1]["actions"][2]["runOrder"] = 2
                run = next(
                    (
                        r
                        for r in self.records(snapshot, response)
                        if r["propertiesKey"].endswith(".RunOrder")
                    )
                )
                self.assertEqual(run["status"], "difference", run)

    def test_name_before_configuration(self):
        for stages, actions in [(1, 1), (2, 2)]:
            for order in ("first", "last", "middle"):
                with self.subTest(stages=stages, actions=actions, order=order):
                    snapshot, response, source = self.build(
                        stages, actions, reference=True, order=order, standalone=True
                    )
                    compile(source, "generated-audit.py", "exec")
                    records = self.records(snapshot, response)
                    selected = [r for r in records if "Stages[]" in r["propertiesKey"]]
                    self.assertTrue(
                        all((r["status"] == "match" for r in selected)), selected
                    )
                    response[-1]["actions"][-1]["configuration"]["ProjectName"] = (
                        "wrong"
                    )
                    records = self.records(snapshot, response)
                    self.assertEqual(
                        next(
                            (
                                r
                                for r in records
                                if r["propertiesKey"].endswith(".Configuration")
                            )
                        )["status"],
                        "difference",
                    )
                    self.assertEqual(
                        next(
                            (
                                r
                                for r in records
                                if r["propertiesKey"].endswith(".Category")
                            )
                        )["status"],
                        "match",
                    )

    def test_varied_optional_fields(self):
        snapshot, response, _ = self.build(varied=True)
        records = self.records(snapshot, response)
        selected = [
            r
            for r in records
            if "Stages[]" in r["propertiesKey"]
            and (not r["propertiesKey"].endswith(".Namespace"))
        ]
        self.assertTrue(all((r["status"] == "match" for r in selected)), selected)

    def test_unsafe_boundaries(self):
        prefix = "CodePipeline.Pipeline.Stages[].Actions[]."
        stage = "CodePipeline.Pipeline.Stages[].Name"
        category = prefix + "ActionTypeId.Category"
        name = prefix + "Name"
        config = prefix + "Configuration"
        cases = [
            [category, config, stage],
            [category, name, name, stage],
            [name, config, stage],
            [category, category, name, stage],
            [category, name, config, category, name, stage],
            [stage, category, name, stage, stage, category, name],
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                rows = [
                    (
                        f"001-{i:03d}",
                        {
                            "property": field,
                            "value": '`{"ProjectName":"p"}`'
                            if field == config
                            else "`x`",
                            "comment": "ProjectName: project"
                            if field == config
                            else "fixture",
                        },
                    )
                    for i, field in enumerate(fields, 1)
                ]
                self.assertFalse(pipeline_indexed_rows(rows))

    def test_fixed_ids_restore_membership_after_input_reordering(self):
        self.build(2, 4, run_order=True)
        rows = [
            (rid, row)
            for rid, row in entries(
                load_model(
                    self.root / "model/dev/cde/codepipeline.properties"
                ).authoritative,
                "desired.row.",
            )
            if rid.startswith("001-")
        ]
        paths = pipeline_indexed_rows(rows)
        self.assertTrue(paths)
        self.assertEqual(paths, pipeline_indexed_rows(list(reversed(rows))))

    def test_missing_action_identity_reports_row_ids(self):
        self.build(2, 4, run_order=True)
        path = self.root / "model/dev/cde/codepipeline.properties"
        values = dict(load_model(path).authoritative)
        values.pop("desired.row.001-002.property")
        values.pop("desired.row.001-002.value")
        values.pop("desired.row.001-002.comment")
        write_model(path, values)
        _, _, notices = generate(self.root, "dev", "cde", "codepipeline")
        self.assertTrue(
            any(
                (
                    "001-008" in key and "membership unresolved" in reason
                    for key, reason in notices
                )
            ),
            notices,
        )

    def test_configuration_keys_remain_with_their_action(self):
        self.build(reference=True)
        path = self.root / "model/dev/cde/codepipeline.properties"
        values = dict(load_model(path).authoritative)
        config_rows = [
            rid
            for rid, row in entries(values, "desired.row.")
            if row["property"].endswith(".Configuration")
        ]
        for index, rid in enumerate(config_rows):
            if index == 2:
                for field in ("property", "value", "comment"):
                    values.pop(f"desired.row.{rid}.{field}")
                continue
            config = {
                "ProjectName": self.ref("CodeBuild_Project_001", "Name")
                if index == 0
                else f"project-{index // 2}-{index % 2}"
            }
            config[f"Extra{index}"] = f"value-{index}"
            values[f"desired.row.{rid}.value"] = "`" + json.dumps(config) + "`"
            values[f"desired.row.{rid}.comment"] = (
                f"ProjectName: project / Extra{index}: extra"
            )
        write_model(path, values)
        source = generate(self.root, "dev", "cde", "codepipeline")[0]
        snapshot = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
        _, response, _ = self.build(reference=True)
        for index, action in enumerate(
            (a for stage in response for a in stage["actions"])
        ):
            if index == 2:
                action.pop("configuration")
            else:
                action["configuration"][f"Extra{index}"] = f"value-{index}"
        config = next(
            (
                r
                for r in self.records(snapshot, response)
                if r["propertiesKey"].endswith(".Configuration")
            )
        )
        self.assertEqual(config["status"], "match", config)
        response[1]["actions"][1]["configuration"]["Extra3"] = "wrong"
        config = next(
            (
                r
                for r in self.records(snapshot, response)
                if r["propertiesKey"].endswith(".Configuration")
            )
        )
        self.assertEqual(config["status"], "difference", config)
        failure = Mock(return_value=subprocess.CompletedProcess([], 1, "", "denied"))
        config = next(
            (
                r
                for r in audit.audit(snapshot, cli_runner=failure)[2]
                if r["propertiesKey"].endswith(".Configuration")
            )
        )
        self.assertNotIn("Design reference projection failed", config["reason"])

    def test_ambiguous_membership(self):
        snapshot, response, _ = self.build(2, 2, ambiguous=True)
        self.assertFalse(snapshot["pipelineIndexedRows"]["001"])
        records = self.records(snapshot, response)
        config = next(
            (r for r in records if r["propertiesKey"].endswith(".Configuration"))
        )
        self.assertIn("001-", config["reason"])
        self.assertIn(
            "Stage Name, Action Name and ActionTypeId.Category", config["reason"]
        )
        self.assertTrue(
            all(
                (
                    r["status"] == "design_unresolved"
                    for r in records
                    if "Stages[]" in r["propertiesKey"]
                )
            ),
            records,
        )

    def test_standalone(self):
        snapshot, response, source = self.build(
            reference=True, order="middle", standalone=True
        )
        namespace = generated(source, self.root)
        for status, code in (("match", 0), ("difference", 1)):
            if status == "difference":
                response[0]["actions"][0]["configuration"]["ProjectName"] = "wrong"
            cli = CLI(
                {
                    ("codepipeline", "get-pipeline"): {
                        "pipeline": {"name": "fixture", "stages": response}
                    }
                }
            )
            _, account, records = namespace["audit"](snapshot, None, cli)
            text, actual = namespace["report"](
                snapshot, None, account, records, datetime.now(timezone.utc)
            )
            self.assertEqual(actual, code, text)
            self.assertIn(
                ("[OK]" if status == "match" else "[NG]") + " CodePipeline.Pipeline",
                text,
            )
            self.assertNotIn("Design reference projection failed", text)

    def test_reference(self):
        snapshot, response, _ = self.build(reference=True)
        records = self.records(snapshot, response)
        config = next(
            (r for r in records if r["propertiesKey"].endswith(".Configuration"))
        )
        self.assertEqual(config["status"], "match", config)
        failure = Mock(return_value=subprocess.CompletedProcess([], 1, "", "denied"))
        records = audit.audit(snapshot, cli_runner=failure)[2]
        config = next(
            (r for r in records if r["propertiesKey"].endswith(".Configuration"))
        )
        self.assertEqual(config["status"], "acquisition_failed", config)
        self.assertNotIn("Design reference projection failed", config["reason"])
        resolution = next(
            iter(snapshot["referenceRows"]["dev/cde/codepipeline"].values())
        )
        resolution.update(status="unresolved", reason="missing producer")
        records = self.records(snapshot, response)
        config = next(
            (r for r in records if r["propertiesKey"].endswith(".Configuration"))
        )
        self.assertEqual(config["status"], "design_unresolved", config)
        self.assertIn("missing producer", config["reason"])


class SecurityGroupRuleRecoveryTests(unittest.TestCase):
    def test_rule_recovery(self):
        module = service_module("security-group")
        rule = {
            "SecurityGroupRuleId": "sgr-old",
            "GroupId": "sg-parent",
            "IsEgress": True,
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "CidrIpv4": "10.0.0.0/24",
        }
        resource = Mock()
        resource.kind = "EC2.SecurityGroupEgress"
        resource.parent.return_value.identity.return_value = "sg-parent"
        resource.current.return_value = "sgr-old"
        values = {
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "CidrIp": "10.0.0.0/24",
        }
        resource.rows = [
            (name, {"property": resource.kind + "." + name, "value": value})
            for name, value in values.items()
        ]
        resource.parse.side_effect = lambda row, norm: row["value"]
        sdk = _sg_sdk_error
        missing = sdk("InvalidSecurityGroupRuleId.NotFound")
        self.assertEqual(missing.status, "resource_missing")
        ctx = Mock()
        for name, responses, expected in (
            ("normal", [{"SecurityGroupRules": [rule]}], "sgr-old"),
            ("deleted", [{"SecurityGroupRules": []}], "missing"),
            (
                "recreated",
                [{"SecurityGroupRules": [{**rule, "SecurityGroupRuleId": "sgr-new"}]}],
                "sgr-new",
            ),
            ("ambiguous", [{"SecurityGroupRules": [rule, rule]}], "ambiguous"),
            (
                "parent",
                [{"SecurityGroupRules": [{**rule, "GroupId": "sg-other"}]}],
                "ambiguous",
            ),
            ("denied", [sdk("AccessDenied")], "denied"),
            (
                "different attributes",
                [{"SecurityGroupRules": [{**rule, "CidrIpv4": "10.1.0.0/24"}]}],
                "missing",
            ),
        ):
            with self.subTest(name=name):
                ctx.pages.side_effect = responses
                if expected in {"missing", "ambiguous", "denied"}:
                    with self.assertRaises(
                        AcquisitionError if expected != "ambiguous" else Unresolved
                    ) as caught:
                        module.fetch(ctx, resource, "rule")
                    if expected == "missing":
                        self.assertEqual(caught.exception.status, "resource_missing")
                    if expected == "denied":
                        self.assertEqual(caught.exception.status, "acquisition_failed")
                else:
                    self.assertEqual(
                        module.fetch(ctx, resource, "rule")["SecurityGroupRuleId"],
                        expected,
                    )
                self.assertEqual(
                    ctx.pages.call_args.kwargs,
                    {"Filters": [{"Name": "group-id", "Values": ["sg-parent"]}]},
                )

    def test_recreated_rule_id_is_reported_as_difference(self):
        engine = Mock()
        engine.ROOT = Path("/")
        engine.catalog_outputs.return_value = {"EC2.SecurityGroupEgress.Id"}
        engine.literal.return_value = "sgr-old"
        engine.confirmed_display_name.return_value = True
        engine.confirmed.return_value = True
        engine.normalize.side_effect = lambda ctx, value, norm: value
        engine.stable.side_effect = lambda value: value
        engine.redacted.side_effect = lambda value: value
        resource = Mock()
        resource.kind = "EC2.SecurityGroupEgress"
        resource.rows_for.return_value = [("001-001", {"value": "`sgr-old`"})]
        resource.model.values = {"observed.row.001-001.value": "`sgr-old`"}
        resource.parse.return_value = "sgr-old"
        resource.module.sensitive.return_value = False
        ctx = Mock()
        ctx.comparison.return_value = (
            None,
            {
                "EC2.SecurityGroupEgress.Id": SimpleNamespace(
                    field=SimpleNamespace(norm="typed")
                )
            },
        )
        result = audit.identifier_result(
            engine,
            ctx,
            resource,
            {
                "propertiesKey": "EC2.SecurityGroupEgress.Id",
                "status": "identifier",
                "awsValue": "sgr-new",
            },
        )
        self.assertEqual(result["status"], "difference")
        self.assertEqual(result["designValue"], "sgr-old")
        self.assertEqual(result["awsValue"], "sgr-new")


class IngressRuleTests(unittest.TestCase):
    def test_pending_recreation_and_direction(self):
        module = service_module("security-group")
        resource = Mock()
        resource.kind = "EC2.SecurityGroupIngress"
        resource.parent.return_value.identity.return_value = "sg-parent"
        resource.parse.side_effect = lambda row, norm: row["value"]
        resource.rows = [
            (key, {"property": resource.kind + "." + key, "value": value})
            for key, value in {
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "SourceSecurityGroupId": "sg-peer",
            }.items()
        ]
        rule = {
            "SecurityGroupRuleId": "sgr-new",
            "GroupId": "sg-parent",
            "IsEgress": False,
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "ReferencedGroupInfo": {"GroupId": "sg-peer"},
        }
        ctx = Mock()
        resource.current.return_value = None
        ctx.pages.return_value = {"SecurityGroupRules": [rule]}
        self.assertEqual(module.fetch(ctx, resource, "rule"), rule)
        ctx.pages.return_value = {"SecurityGroupRules": [{**rule, "IsEgress": True}]}
        with self.assertRaises(AcquisitionError):
            module.fetch(ctx, resource, "rule")
        ctx.pages.return_value = {"SecurityGroupRules": [rule, rule]}
        with self.assertRaises(Unresolved):
            module.fetch(ctx, resource, "rule")
        error = Exception()
        error.response = {"Error": {"Code": "InvalidSecurityGroupRuleId.NotFound"}}
        resource.current.return_value = "sgr-old"
        ctx.pages.side_effect = [
            sdk_error("ec2.describe_security_group_rules", error, {}),
            {"SecurityGroupRules": [rule]},
        ]
        self.assertEqual(module.fetch(ctx, resource, "rule"), rule)

    def test_pending_identifier_is_not_adopted(self):
        engine = SimpleNamespace(
            ROOT=Path("/"),
            catalog_outputs=lambda root, kind: {kind + ".Id"},
            literal=lambda raw: raw.strip("`"),
            confirmed_display_name=confirmed_display_name,
            confirmed=confirmed,
        )
        resource = SimpleNamespace(
            kind="EC2.SecurityGroupIngress",
            rows_for=lambda key: [("001", {})],
            model=SimpleNamespace(
                values={"observed.row.001.value": "`PENDING_DEPLOY`"}
            ),
        )
        result = audit.identifier_result(
            engine,
            None,
            resource,
            {
                "propertiesKey": resource.kind + ".Id",
                "status": "identifier",
                "awsValue": "sgr-new",
            },
        )
        self.assertEqual(result["status"], "pending_identifier")
        self.assertIsNone(result["designValue"])
        for aws_value in (None, "", []):
            with self.subTest(aws_value=aws_value):
                unresolved = audit.identifier_result(
                    engine,
                    None,
                    resource,
                    {
                        "propertiesKey": resource.kind + ".Id",
                        "status": "identifier",
                        "awsValue": aws_value,
                    },
                )
                self.assertEqual(unresolved["status"], "design_unresolved")


def _parse_pending_ingress(row, norm):
    if row["value"] == "PENDING_DEPLOY":
        raise Unresolved("Design reference unresolved: REFERENCE_PENDING_DEPLOY")
    return row["value"]


def test_pending_source_does_not_select_ingress_rule():
    module = service_module("security-group")
    resource = Mock()
    resource.kind = "EC2.SecurityGroupIngress"
    resource.parent.return_value.identity.return_value = "sg-parent"
    resource.current.return_value = None
    resource.rows = [
        (name, {"property": resource.kind + "." + name, "value": value})
        for name, value in {
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "SourceSecurityGroupId": "PENDING_DEPLOY",
        }.items()
    ]

    parse = _parse_pending_ingress

    resource.parse.side_effect = parse
    ctx = Mock()
    ctx.pages.return_value = {
        "SecurityGroupRules": [
            {
                "GroupId": "sg-parent",
                "IsEgress": False,
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "ReferencedGroupInfo": {"GroupId": "sg-peer"},
            }
        ]
    }
    with unittest.TestCase().assertRaisesRegex(Unresolved, "REFERENCE_PENDING_DEPLOY"):
        module.fetch(ctx, resource, "rule")


def test_quicksight_namespace_fixture():
    fixture = load_fixture("quicksight/namespace")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_quicksight_datasource_fixture():
    fixture = load_fixture("quicksight/datasource")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def _record_status(record, key):
    return next(
        row["status"] for row in record["records"] if row["propertiesKey"] == key
    )


def test_quicksight_group_reference_and_pending_principal_offline():
    inputs, _ = load_fixture("quicksight/datasource")
    model = inputs["model"]
    model["desired.service.identity.lastAllocated"] = json.dumps(
        {"QuickSight.DataSource": 1, "QuickSight.Group": 1}
    )
    model.update(
        {
            "desired.resource.002.resourceType": "QuickSight.Group",
            "desired.resource.002.logicalId": "QuickSight_Group_001",
            "desired.resource.002.anchor": "group",
            "desired.resource.002.cfn-logicalId": "fixture-Group",
        }
    )
    for index, (name, value) in enumerate(
        (
            ("AwsAccountId", "123456789012"),
            ("Namespace", "default"),
            ("GroupName", "team"),
            (
                "PrincipalId",
                {
                    "$modelRef": {
                        "logicalId": "QuickSight_Group_001",
                        "attribute": "PrincipalId",
                    }
                },
            ),
        ),
        1,
    ):
        prefix = f"desired.row.002-{index:03d}."
        model.update(
            {
                prefix + "property": "QuickSight.Group." + name,
                prefix + "value": "`"
                + (json.dumps(value) if isinstance(value, dict) else value)
                + "`",
                prefix + "comment": "fixture",
            }
        )
    model["observed.row.002-004.value"] = "`PENDING_DEPLOY`"
    model["desired.row.001-005.value"] = (
        "`"
        + json.dumps(
            {"$modelRef": {"logicalId": "QuickSight_Group_001", "attribute": "Arn"}}
        )
        + "`"
    )
    arn = "arn:aws:quicksight:ap-northeast-1:123456789012:group/default/team"
    inputs["responses"][1]["response"]["Permissions"][0]["Principal"] = arn
    inputs["responses"].append(
        {
            "api": ["quicksight", "describe-group"],
            "response": {
                "Group": {
                    "GroupName": "team",
                    "PrincipalId": "live-principal",
                    "Arn": arn,
                }
            },
        }
    )
    inputs["report"] = True
    inputs["scenarios"] = [
        {},
        {
            "responses": [
                {
                    "api": ["quicksight", "describe-data-source-permissions"],
                    "response": {
                        "Permissions": [
                            {"Principal": arn + "-other", "Actions": ["ActionA"]}
                        ]
                    },
                }
            ]
        },
        {"model": {"desired.row.002-003.value": "`UNSET`"}},
    ]
    results = execute((inputs, []))

    status = _record_status

    principal = "QuickSight.DataSource.Permissions[].Principal"
    assert [status(record, principal) for record in results] == [
        "match",
        "difference",
        "design_unresolved",
    ]
    assert status(results[0], "QuickSight.Group.PrincipalId") == "design_unresolved"
    assert "[ERROR] QuickSight.Group | team | PrincipalId" in results[0]["report"]
    assert status(results[0], "QuickSight.Group.AwsAccountId") == "match"


def test_glue_write_only_fixture():
    fixture = load_fixture("glue/write-only")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_lakeformation_federation_fixture():
    fixture = load_fixture("lakeformation/federation")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_lakeformation_generated_response_and_cache():
    fixture = load_fixture("lakeformation/federation")
    inputs, _ = fixture
    arn = "arn:aws:s3:::fixture-bucket"
    role = "arn:aws:iam::123456789012:role/lake-role"
    inputs["model"].update(
        {
            "desired.row.001-004.property": "LakeFormation.Resource.RoleArn",
            "desired.row.001-004.value": f"`{role}`",
            "desired.row.001-004.comment": "fixture",
            "desired.row.001-005.property": "LakeFormation.Resource.Id",
            "desired.row.001-005.value": '`{"$modelRef":{"logicalId":"LakeFormation_Resource_001","attribute":"Id"}}`',
            "desired.row.001-005.comment": "fixture",
            "observed.row.001-005.value": "`PENDING_DEPLOY`",
        }
    )
    cases = [
        (
            {"ResourceArn": arn, "RoleArn": role, "WithFederation": True},
            ("match", "match", "excluded", "match"),
        ),
        (
            {"RoleArn": role},
            ("sdk_unavailable", "match", "sdk_unavailable", "sdk_unavailable"),
        ),
        (
            {"ResourceArn": arn, "RoleArn": role},
            ("match", "match", "excluded", "excluded"),
        ),
        (
            {"ResourceArn": arn + "-other", "RoleArn": role},
            ("difference", "match", "sdk_unavailable", "sdk_unavailable"),
        ),
    ]
    inputs["scenarios"] = [
        {
            "responses": [
                {
                    "api": ["lakeformation", "describe-resource"],
                    "response": {"ResourceInfo": info},
                }
            ],
            "fields": ["propertiesKey", "status"],
        }
        for info, _ in cases
    ] + [
        {
            "fail": ["lakeformation", "describe-resource"],
            "fields": ["propertiesKey", "status"],
        }
    ]
    expected = [statuses for _, statuses in cases] + [
        (
            "acquisition_failed",
            "acquisition_failed",
            "sdk_unavailable",
            "acquisition_failed",
        )
    ]
    for result, statuses in zip(execute(fixture), expected, strict=True):
        records = {
            item["propertiesKey"].rsplit(".", 1)[-1]: item["status"]
            for item in result["records"]
        }
        assert (
            tuple(
                records[key]
                for key in (
                    "ResourceArn",
                    "RoleArn",
                    "UseServiceLinkedRole",
                    "WithFederation",
                )
            )
            == statuses
        )
        assert records["Id"] == "design_unresolved"
        assert "PENDING_DEPLOY" in result["report"]
        assert (
            "DescribeResource does not return the CloudFormation Id."
            in result["report"]
        )
        assert result["calls"] == [
            [["lakeformation", "describe-resource"], {"ResourceArn": arn}]
        ]


def test_lambda_comparison_fixture():
    fixture = load_fixture("lambda/comparison")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_macie_lookup_fixture():
    fixture = load_fixture("macie/lookup")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_references_flowlog_fixture():
    fixture = load_fixture("references/flowlog")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_iam_inline_fixture():
    fixture = load_fixture("iam/inline")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_glue_job_fixture():
    fixture = load_fixture("glue/job")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_route53_records_fixture():
    fixture = load_fixture("route53/records")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_sqs_policies_fixture():
    fixture = load_fixture("sqs/policies")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_runtime_policy_and_reference_boundaries():
    inputs, expected = load_fixture("audit/runtime")
    POLICY = inputs["policy"]
    _state_check_106 = _CallbackState()
    with tempfile.TemporaryDirectory(prefix="audit-boundaries-") as directory:
        root = Path(directory)
        (root / "project.json").write_text(
            json.dumps(inputs["project"]), encoding="utf-8"
        )
        iam = fixture({}, "iam", inputs["resources"]["base-iam"])
        vpc = fixture({}, "vpc", inputs["resources"]["base-vpc"])
        for service, data in [("vpc", vpc), ("iam", iam)]:
            write_model(
                root / "model/dev/cde" / (service + ".properties"),
                data["models"]["dev/cde/" + service],
            )
        sources = {
            service: generator.generate(root, "dev", "cde", service)[0]
            for service in ("vpc", "iam")
        }
        snapshots = {service: snapshot(source) for service, source in sources.items()}
        assert (
            snapshots["vpc"]["referenceRows"]["dev/cde/vpc"]["003-001"]["value"]
            == expected["referenceArn"]
        ), "VPC flow-log IAM reference is resolved during generation"
        assert set(snapshots["vpc"]["models"]) != set(
            generator.module("model/adapters/aws.py", "model.adapters.aws").SERVICES
        )
        vpc = fixture(snapshots["vpc"], "vpc", inputs["resources"]["observed-vpc"])
        vpc["models"]["dev/cde/vpc"]["observed.row.001-004.value"] = "`vpc-observed`"
        vpc["names"] = {"EC2_VPC_001": "test-vpc"}
        TestCase().assertEqual(snapshots["vpc"]["names"]["EC2_VPC_001"], "fixture-vpc")
        TestCase().assertEqual(
            snapshots["vpc"]["names"]["EC2_Subnet_002"], "fixture-subnet"
        )
        TestCase().assertEqual(
            snapshots["iam"]["names"]["IAM_Role_001"], "fixture-role"
        )
        responses = {
            tuple(item["api"]): item["response"]
            for item in inputs["responses"]["responses"]
        }
        rt = runtime(vpc)
        cli = CLI(responses)
        _, account, records = rt["audit"](vpc, "dev-profile", cli)
        assert (
            sum(api == ("sts", "get-caller-identity") for api, _, _ in cli.calls) == 1
        )
        status = {r["propertiesKey"]: r["status"] for r in records}
        assert status["EC2.VPC.CidrBlock"] == "match", records
        assert status["EC2.VPC.EnableDnsSupport"] == "difference", records
        TestCase().assertEqual(status["EC2.VPC.VpcId"], "match", records)
        subnet = fixture(
            snapshots["vpc"], "vpc", inputs["resources"]["observed-subnet"]
        )
        subnet["models"]["dev/cde/vpc"]["observed.row.002-002.value"] = "`subnet-01`"
        subnet["names"] = {"EC2_Subnet_002": "test-subnet"}
        subnet_response = {
            tuple(item["api"]): item["response"]
            for item in inputs["responses"]["subnet_response"]
        }
        subnet_records = runtime(subnet)["audit"](subnet, None, CLI(subnet_response))[2]
        selected = [
            item
            for item in subnet_records
            if item["propertiesKey"] == "EC2.Subnet.SubnetId"
        ]
        TestCase().assertEqual(selected[0]["status"], "match", selected)
        TestCase().assertEqual(selected[0]["designValue"], "subnet-01")
        stamp = datetime(2026, 10, 15, tzinfo=timezone.utc)
        _state_check_106.text, code = rt["report"](
            vpc, "dev-profile", account, records, stamp
        )
        TestCase().assertEqual(code, 1)
        TestCase().assertIn("[OK] EC2.VPC | test-vpc | VpcId", _state_check_106.text)
        TestCase().assertNotIn("  API:", _state_check_106.text)
        TestCase().assertIn("Diff paths: $", _state_check_106.text)
        assert (
            "Design SHA256:" in _state_check_106.text
            and "Executed:" in _state_check_106.text
        )
        ordinary = copy.deepcopy(records)
        assert rt["report"](vpc, None, account, ordinary, stamp)[1] == 1
        for r in ordinary:
            r["status"] = "match"
        assert rt["report"](vpc, None, account, ordinary, stamp)[1] == 0
        _, _, failed = rt["audit"](
            vpc, None, CLI(responses, fail=("ec2", "describe-vpcs"))
        )
        assert len(failed) == len(records), failed
        assert any(r["status"] == "acquisition_failed" for r in failed)
        failed_link = copy.deepcopy(vpc)
        failed_link["models"]["dev/cde/vpc"]["desired.row.001-004.value"] = (
            '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`'
        )
        failed_records = runtime(failed_link)["audit"](
            failed_link, None, CLI(responses, fail=("ec2", "describe-vpcs"))
        )[2]
        failed_id = [
            item for item in failed_records if item["propertiesKey"] == "EC2.VPC.VpcId"
        ][0]
        TestCase().assertEqual(failed_id["status"], "acquisition_failed")
        TestCase().assertEqual(failed_id["designValue"], "vpc-observed")
        TestCase().assertEqual(
            rt["report"](failed_link, None, account, failed_records, stamp)[1], 2
        )
        # Configured profile conflict and account/authentication errors stop before resource APIs.
        configured = copy.deepcopy(vpc)
        configured["target"]["awsProfile"] = "required"
        cli = CLI(responses)
        assert all(
            r["status"] == "acquisition_failed"
            for r in runtime(configured)["audit"](configured, "wrong", cli)[2]
        )
        assert not cli.calls
        cli = CLI(responses)
        assert all(
            r["status"] == "acquisition_failed" for r in rt["audit"](vpc, "", cli)[2]
        )
        assert not cli.calls
        cli = CLI(responses, account="999999999999")
        assert all(
            r["status"] == "acquisition_failed" for r in rt["audit"](vpc, None, cli)[2]
        )
        assert all(api == ("sts", "get-caller-identity") for api, _, _ in cli.calls)
        # Unresolved references remain visible, independent of the other attributes.
        unresolved = copy.deepcopy(vpc)
        unresolved["models"]["dev/cde/vpc"]["desired.row.001-002.value"] = (
            '`{"$modelRef":{"logicalId":"EC2_VPC_999","attribute":"VpcId"}}`'
        )
        result = runtime(unresolved)["audit"](unresolved, None, CLI(responses))[2]
        assert any(
            r["propertiesKey"] == "EC2.VPC.CidrBlock"
            and r["status"] == "design_unresolved"
            for r in result
        )
        # A valid parent reference uses the fetched identity, then checks membership.
        referenced = fixture(
            snapshots["vpc"], "vpc", inputs["resources"]["parent-membership"]
        )
        referenced["models"]["dev/cde/vpc"].update(
            {
                "desired.row.001-003.property": "EC2.VPC.VpcId",
                "desired.row.001-003.value": '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
                "desired.row.001-003.comment": "取得済み親識別子",
                "observed.row.001-003.value": "`vpc-observed`",
            }
        )
        membership = {
            **responses,
            ("ec2", "describe-subnets"): {
                "Subnets": [
                    {
                        "SubnetId": "subnet-01",
                        "VpcId": "vpc-wrong-parent",
                        "Tags": [{"Key": "Name", "Value": "test-subnet"}],
                    }
                ]
            },
        }
        resolved = runtime(referenced)["audit"](referenced, None, CLI(membership))[2]
        assert any(
            r["propertiesKey"] == "EC2.Subnet.VpcId"
            and r["status"] == "difference"
            and r["designValue"] == "vpc-observed"
            for r in resolved
        ), resolved
        # Trust, inline, managed, attached policies, and permissions boundary.
        iam = fixture(snapshots["iam"], "iam", inputs["resources"]["policy-set"])
        iam["schemas"]["IAM.Role.PermissionsBoundary"] = {"type": "string"}
        reordered = copy.deepcopy(POLICY)
        reordered["Statement"].reverse()
        reordered["Statement"][1]["Action"].reverse()
        reordered["Statement"][1]["Resource"].reverse()
        reordered["Statement"][1]["Condition"]["StringEquals"][
            "aws:PrincipalOrgID"
        ].reverse()
        iam_responses = {
            tuple(item["api"]): item["response"]
            for item in inputs["responses"]["iam_responses"]
        }
        irt = runtime(iam)
        _, account, result = irt["audit"](iam, None, CLI(iam_responses))
        assert all(r["status"] == "match" for r in result), result
        assert len(result) == 8
        for change in ("Action", "Condition"):
            altered = copy.deepcopy(iam_responses)
            statement = altered[("iam", "get-role")]["Role"][
                "AssumeRolePolicyDocument"
            ]["Statement"][1]
            if change == "Action":
                statement["Action"].append("s3:PutObject")
            else:
                statement["Condition"]["StringEquals"]["aws:PrincipalOrgID"] = [
                    "o-different"
                ]
            changed = irt["audit"](iam, None, CLI(altered))[2]
            assert any(
                r["propertiesKey"] == "IAM.Role.AssumeRolePolicyDocument"
                and r["status"] == "difference"
                for r in changed
            )
            assert "$.Statement" in irt["report"](iam, None, account, changed, stamp)[0]
        # The existing resolver assumes every GetAtt means Arn. Audits reject that guess.
        role_arn = "arn:aws:iam::123456789012:role/test-role"
        symbolic = copy.deepcopy(iam)
        symbolic_responses = copy.deepcopy(iam_responses)
        symbolic_responses[("iam", "get-role")]["Role"]["Arn"] = role_arn
        actual_policy = copy.deepcopy(POLICY)
        actual_policy["Statement"][0]["Resource"] = role_arn
        symbolic_responses[("iam", "get-role")]["Role"]["AssumeRolePolicyDocument"] = (
            actual_policy
        )
        for expression, expected in [
            ({"Fn::GetAtt": ["Role", "Arn"]}, "match"),
            ({"Fn::GetAtt": ["Role", "RoleId"]}, "design_unresolved"),
            ({"Fn::Sub": "${Role.RoleId}"}, "design_unresolved"),
        ]:
            document = copy.deepcopy(POLICY)
            document["Statement"][0]["Resource"] = expression
            symbolic["models"]["dev/cde/iam"]["desired.row.001-002.document"] = (
                json.dumps(document)
            )
            result = runtime(symbolic)["audit"](
                symbolic, None, CLI(symbolic_responses)
            )[2]
            (item,) = [
                r
                for r in result
                if r["propertiesKey"] == "IAM.Role.AssumeRolePolicyDocument"
            ]
            assert item["status"] == expected, item
            if expected == "design_unresolved":
                assert "unsupported GetAtt attribute" in item["reason"], item
        # Unsupported attributes are explicit errors, even when Mapping include=false.
        unsupported = copy.deepcopy(iam)
        for key, value in [
            ("property", "IAM.Role.MaxSessionDuration"),
            ("value", "`3600`"),
            ("comment", "fixture"),
        ]:
            unsupported["models"]["dev/cde/iam"]["desired.row.001-007." + key] = value
        result = runtime(unsupported)["audit"](unsupported, None, CLI(iam_responses))[2]
        assert any(
            r["propertiesKey"] == "IAM.Role.MaxSessionDuration"
            and r["status"] == "sdk_unavailable"
            and r["reason"]
            for r in result
        )
        assert irt["masked"](
            {
                "password": "never-print",
                "Tags": [{"Key": "token", "Value": "never-print"}],
            }
        ) == {"password": "[REDACTED]", "Tags": ["[REDACTED]"]}


def test_references_failures_fixture():
    fixture = load_fixture("references/failures")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


def test_iam_model_reference_fixture():
    fixture = load_fixture("iam/model-reference")
    actual = execute(fixture, snapshot_only=True)
    assert_result(actual, fixture)


if __name__ == "__main__":
    raise SystemExit(run(__file__))


def test_lambda_code_s3_properties_are_not_compared():
    inputs, expected = load_fixture("lambda/comparison")
    inputs["model"].update(
        {
            "desired.row.001-004.property": "Lambda.Function.Code.S3Key",
            "desired.row.001-004.value": "`handler.zip`",
            "desired.row.001-004.comment": "fixture",
        }
    )
    inputs["properties"] = [
        "Lambda.Function.Code.S3Bucket",
        "Lambda.Function.Code.S3Key",
    ]
    inputs["scenarios"] = [
        {"responses": [{"api": ["lambda", "get-function"], "response": response}]}
        for response in (
            {
                "Configuration": {"FunctionName": "fixture-function", "Timeout": 30},
                "Code": {"ResolvedS3Object": {"S3Bucket": "other", "S3Key": "other"}},
            },
            {
                "Configuration": {"FunctionName": "fixture-function", "Timeout": 30},
                "Code": {},
            },
            {"$error": json.dumps({"Code": "AccessDeniedException"})},
            {"$error": json.dumps({"Code": "ResourceNotFoundException"})},
        )
    ]
    results = execute((inputs, expected))
    assert all(result["records"] == [] for result in results)
    assert all(
        "Code.S3Bucket" not in result["report"] and "Code.S3Key" not in result["report"]
        for result in results
    )
    assert "[ERROR]" in results[2]["report"]
    assert "[NG]" in results[3]["report"]
