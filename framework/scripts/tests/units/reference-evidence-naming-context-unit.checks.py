"""Offline reference proof through the shared evaluator and comparison pipeline."""

import json
import sys
from functools import partial
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.methods import ORDERED, compare_values
from comparison.registry import rules
from issues.materials import naming_materials
from issues.publication import save_scan
from support.comparison_cases import projected
from support.issues_scan_fixtures import (
    review_for,
    snapshot_artifact,
    stamp_naming_scan,
    task,
)
from support.model_reference_fixtures import reference as model_ref
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    same,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    ATHENA_KMS,
    _portable_synthetic_root,
    codebuild_batch,
    fixture,
    policy_reference,
    reference_for,
    resource,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="unknown-property-")
)
def test_unknown_reference_property_never_infers_from_name(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_unknown_property)


def _execute_unknown_property(case):
    field, context = case["data"]["field"], case["data"]["context"]
    comparison = fixture()
    resource(comparison, "iam", "001", "IAM.ManagedPolicy", "Policy", [])
    kind = (
        "CodeBuild.Project"
        if field.startswith("Environment")
        else "Route53.RecordSet"
        if field.startswith("ResourceRecords")
        else "IAM.User"
        if field == "Groups[]"
        else "IAM.Role"
    )
    with pytest.raises(Blocked) as failure:
        comparison.desired_reference(
            "iam", "[policy](iam.md#policy)", kind, field, context=context
        )
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)}
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-secret-")
)
def test_codebuild_secret_context(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_secret)


def _execute_codebuild_secret(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "secrets-manager",
        "001",
        "SecretsManager.Secret",
        "Secret",
        [],
        properties={"Name": "app/secret"},
    )
    link = model_ref("SecretsManager_Secret_001", "Id")
    try:
        symbol = comparison.desired_reference(
            "secrets-manager",
            link,
            "CodeBuild.Project",
            "Environment.EnvironmentVariables[].Value",
            context=data["context"],
        )
    except Blocked as failure:
        return {"error": {"type": type(failure).__name__, "message": str(failure)}}
    desired = {"Name": "SECRET", "Type": data["context"]["Type"], "Value": symbol}
    callback = partial(reference_for, comparison, "CodeBuild.Project")
    same_value = same(
        desired,
        dict(desired, Value="app/secret"),
        path="Environment.EnvironmentVariables[]",
        reference=callback,
    )
    suffix_value = same(
        desired,
        dict(desired, Value="app/secret:key:AWSPREVIOUS"),
        path="Environment.EnvironmentVariables[]",
        reference=callback,
    )
    TestCase().assertIs(same_value, True)
    TestCase().assertIs(suffix_value, False)
    return {"same": same_value, "suffix": suffix_value}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="policy-bijection-")
)
def test_policy_statement_bijection(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_policy_bijection)


def _execute_policy_bijection(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Key", "Key", [])
    left, right, path = data["left"], data["right"], data["path"]
    if data["reference_left"]:
        left[0]["Resource"] = comparison.evaluate(
            "producer", {"Fn::GetAtt": ["Key", "Arn"]}
        )
    declared = {path: ORDERED} if data["ordered"] else rules("IAM.Role")
    outcome = compare_values(
        left,
        right,
        path,
        rules=declared,
        whole=True,
        reference=partial(policy_reference, comparison),
    )
    if outcome.equal is not None:
        TestCase().assertIs(type(outcome.equal), bool)
    return {"equal": outcome.equal}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="incomplete-codebuild-")
)
def test_incomplete_codebuild_missing_structure(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_incomplete_codebuild)


def _execute_incomplete_codebuild(case):
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Alias", "Alias", [])
    rows = [
        ("Environment.EnvironmentVariables[1].Name", "RELEASE_BUCKET_KMS_KEY_ID", None),
        ("Environment.EnvironmentVariables[1].Type", "PLAINTEXT", None),
        (
            "Environment.EnvironmentVariables[1].Value",
            model_ref("KMS_Alias_001", "Arn"),
            None,
        ),
    ]
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        rows,
        properties=case["data"]["properties"],
    )
    document = comparison.stack_inputs["producer"][0]
    result = codebuild_batch(comparison, document)
    check = TestCase()
    check.assertIsNone(result.failure)
    differences = [item for item in result.records if item["category"] == "difference"]
    unresolved = [item for item in result.records if item["category"] == "uncompared"]
    check.assertEqual(len(differences), 1)
    check.assertEqual(len(unresolved), 1)
    check.assertIn("PLAINTEXTではResource linkは禁止", unresolved[0]["reason"])
    check.assertFalse(
        any(item["category"] in {"error", "matched"} for item in result.records)
    )
    shown = json.dumps(result.display_differences)
    check.assertIn("RELEASE_BUCKET_KMS_KEY_ID", shown)
    check.assertIn("Environment", shown)
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="nested-diagnostic-")
)
def test_nested_diagnostics_retain_format_and_failures(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_nested_diagnostic)


def _execute_nested_diagnostic(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Key", "Key", [])
    resource(
        comparison,
        "athena",
        "001",
        "Athena.WorkGroup",
        "WorkGroup",
        data["rows"],
        properties=data["properties"],
    )
    comparison.sensitive_values.add("private")
    _portable_synthetic_root(comparison)
    document = comparison.stack_inputs["producer"][0]
    result = comparison.compare_rows(
        "athena",
        "001",
        comparison.resources["athena"]["001"],
        "producer",
        "WorkGroup",
        comparison.root / "synthetic.yaml",
        document["Resources"]["WorkGroup"],
        document,
    ).records
    record = next(
        item
        for item in result
        if item["property"] == "Athena.WorkGroup.WorkGroupConfiguration"
    )
    check = TestCase()
    check.assertEqual(record["category"], "difference")
    diagnostic = record["reference_diagnostics"][0]
    check.assertEqual(diagnostic["path"], "Athena.WorkGroup." + ATHENA_KMS)
    check.assertEqual(diagnostic["identity"], "same")
    check.assertEqual(diagnostic["allowed_forms"], ["KeyArn"])
    check.assertEqual(diagnostic["model"]["$attribute"], "Arn")
    check.assertEqual(diagnostic["iac"]["$attribute"], "KeyId")
    if data["deferred"]:
        children = [
            child
            for child in result
            if child["property"]
            in {
                "Athena.WorkGroup.WorkGroupConfiguration#/ExecutionRole",
                "Athena.WorkGroup.WorkGroupConfiguration#/ResultConfiguration/ExpectedBucketOwner",
            }
        ]
        check.assertEqual(len(children), 2)
        check.assertEqual({child["category"] for child in children}, {"uncompared"})
        check.assertTrue(all(child["reason"] for child in children))
    check.assertNotIn("private", json.dumps(result))
    return {"records": projected(result)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="incomplete-setting-")
)
def test_incomplete_setting_presence_and_siblings(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_incomplete_setting)


def _execute_incomplete_setting(case):
    data = case["data"]
    comparison = fixture()
    comparison.stack_inputs["producer"][2]["AWS::NoValue"] = {"$noValue": True}
    comparison.stack_inputs["producer"][0]["Conditions"] = data["conditions"]
    resource(comparison, "kms", "001", "KMS.Alias", "Alias", [])
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        data["rows"],
        properties={"Environment": data["environment"]},
    )
    document = comparison.stack_inputs["producer"][0]
    batch = codebuild_batch(comparison, document)
    check = TestCase()
    check.assertIsNone(batch.failure)
    check.assertFalse(
        any(item["category"] in {"matched", "error"} for item in batch.records)
    )
    children = [
        item for item in batch.records if item["property"].endswith("[1].Value")
    ]
    check.assertEqual(len(children), 1)
    check.assertEqual(children[0]["category"], "uncompared")
    check.assertIn("PLAINTEXTではResource linkは禁止", children[0]["reason"])
    check.assertEqual(children[0]["iac"]["path"], "synthetic.yaml")
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="children-failed-")
)
def test_all_children_failed_preserve_parent_and_categories(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_children_failed)


def _execute_children_failed(case):
    data = case["data"]
    comparison = fixture()
    rows = [
        ("Environment.Image", model_ref("KMS_Key_999", "Arn"), None),
        ("Environment.PrivilegedMode", "invalid-json", None),
    ]
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        rows,
        properties=data["properties"],
    )
    _portable_synthetic_root(comparison)
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        comparison.root / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )
    TestCase().assertIsNone(batch.failure)
    TestCase().assertEqual(
        sorted(item["category"] for item in batch.records),
        ["error", "uncompared"]
        if data["present"]
        else ["difference", "error", "uncompared"],
    )
    if not data["present"]:
        parent = next(
            item for item in batch.records if item["category"] == "difference"
        )
        TestCase().assertEqual(parent["property"], "CodeBuild.Project.Environment")
        TestCase().assertEqual(parent["reason"], "property missing")
        TestCase().assertEqual(
            {
                item["category"]
                for item in batch.records
                if item["property"] != parent["property"]
            },
            {"error", "uncompared"},
        )
    return {"records": projected(batch.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="incomplete-json-")
)
def test_incomplete_json_preserves_declared_children(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_incomplete_json)


def _execute_incomplete_json(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Alias", "Alias", [])
    rows = resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("Environment", json.dumps(data["desired"]), None)],
        properties={"Environment": data["actual"]},
    )
    if data["document_row"]:
        rows[0][1]["document"] = json.dumps(data["desired"])
    prepared_value = comparison.prepare_value(
        "codebuild", rows[0][1], "CodeBuild.Project", stack="producer", row_id="001-001"
    )
    with pytest.raises(Blocked, match="PLAINTEXTではResource linkは禁止"):
        prepared_value.require_value()
    document = comparison.stack_inputs["producer"][0]
    batch = codebuild_batch(comparison, document)
    TestCase().assertIsNone(batch.failure)
    unresolved = next(
        item for item in batch.records if item["category"] == "uncompared"
    )
    TestCase().assertTrue(
        unresolved["property"].endswith("EnvironmentVariables[].Value")
    )
    TestCase().assertEqual(
        unresolved["model"]["pointer"], "/EnvironmentVariables/0/Value"
    )
    TestCase().assertIn("PLAINTEXTではResource linkは禁止", unresolved["reason"])
    return {"records": projected(batch.records)}


def fail_image_preparation(error, original, service, row, kind, **kwargs):
    if row["property"].endswith(".Image"):
        raise error("synthetic preparation failure")
    return original(service, row, kind, **kwargs)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="preparation-error-")
)
def test_preparation_error_retains_confirmed_difference(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_preparation_error)


def _execute_preparation_error(case):
    error = {
        "ValueError": ValueError,
        "TypeError": TypeError,
        "OSError": OSError,
        "ImportError": ImportError,
        "IndexError": IndexError,
    }[case["data"]["error_type"]]
    comparison = fixture()
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [
            ("Environment.Image", "image", None),
            ("Environment.Type", "LINUX_CONTAINER", None),
        ],
        properties={"Environment": {}},
    )
    comparison.prepare_value = partial(
        fail_image_preparation, error, comparison.prepare_value
    )
    document = comparison.stack_inputs["producer"][0]
    batch = codebuild_batch(comparison, document)
    check = TestCase()
    check.assertIsNone(batch.failure)
    check.assertEqual(
        sorted(item["category"] for item in batch.records), ["difference", "error"]
    )
    check.assertTrue(
        any(item["reason"] == "synthetic preparation failure" for item in batch.records)
    )
    return {"records": projected(batch.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="naming-targets-")
)
def test_naming_materials_mode_and_root_targets(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_naming_targets)


def _execute_naming_targets(case):
    comparison = fixture()
    comparison.services = ["vpc", "codebuild", "codepipeline", "glue", "kms"]
    for identity, mode, rows in [
        ("001", "CREATE", []),
        ("002", "IMPORT", []),
        ("003", "CREATE", [("Name", case["data"]["value"], None)]),
    ]:
        parsed = resource(
            comparison, "vpc", identity, "EC2.VPC", "Vpc" + identity, rows
        )
        comparison.resources["vpc"][identity]["resourceMode"] = mode
        for _, row in parsed:
            row["comment"] = "component evidence unconfirmed"
    specs = [
        (
            "codebuild",
            "CodeBuild.Project",
            ["Environment.EnvironmentVariables[].Name", "Artifacts.Name"],
        ),
        (
            "codepipeline",
            "CodePipeline.Pipeline",
            ["Stages[].Name", "Stages[].Actions[].Name"],
        ),
        ("glue", "Glue.Job", ["Command.Name"]),
    ]
    for service, kind, nested in specs:
        rows = resource(
            comparison,
            service,
            "001",
            kind,
            service.title(),
            [
                ("Name", "invalid_root_name", None),
                *[(prop, "nested", None) for prop in nested],
            ],
        )
        for _, row in rows:
            row["comment"] = "fixture name"
    alias_rows = resource(
        comparison,
        "kms",
        "001",
        "KMS.Alias",
        "Alias",
        [("AliasName", "alias/HumanActual", None)],
    )
    comparison.resources["kms"]["001"]["resourceMode"] = "IMPORT"
    alias_rows[0][1]["comment"] = "human exception"
    material, _ = naming_materials(comparison)
    names = material["names"]
    TestCase().assertTrue(
        next(
            (
                item
                for item in names
                if item["service"] == "vpc" and item["resource"] == "001"
            )
        )["required_missing"]
    )
    TestCase().assertTrue(
        not next(
            (
                item
                for item in names
                if item["service"] == "vpc" and item["resource"] == "002"
            )
        )["required_missing"]
    )
    selected = next(
        (
            item
            for item in names
            if item["service"] == "vpc" and item["resource"] == "003"
        )
    )
    TestCase().assertTrue(
        selected["pattern_review"] == "Scan mandatory-constraint decision"
        and selected["value"] == "`bad_pattern_value`"
    )
    TestCase().assertTrue(
        "未確認componentを名前から推測せず" in material["review_policy"]
    )
    TestCase().assertTrue(
        "その不足だけでIssueや未検証にしない" in material["review_policy"]
    )
    alias = next((item for item in names if item["service"] == "kms"))
    TestCase().assertTrue(
        alias["resourceMode"] == "IMPORT"
        and alias["value"] == "`alias/HumanActual`"
        and (not alias["required_missing"])
    )
    TestCase().assertTrue(
        {
            (item["service"], item["property"])
            for item in names
            if item["service"] not in {"vpc", "kms"}
        }
        == {("codebuild", "Name"), ("codepipeline", "Name"), ("glue", "Name")}
    )
    return {"names": names, "review_policy": material["review_policy"]}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="naming-review-")
)
def test_naming_materials_review_save(tmp_path, case_runner, case_id):
    case_runner.run(
        "reference_evidence", case_id, partial(_execute_naming_review, tmp_path)
    )


def _execute_naming_review(tmp_path, case):
    value = case["data"]["value"]
    violation = case["data"]["violation"]
    expected = case["data"]["issue_expected"]
    actual = case["data"]["issue_actual"]
    comparison = fixture()
    comparison.services = ["vpc"]
    comparison.target["environment"] = "dev"
    rows = resource(
        comparison,
        "vpc",
        "001",
        "EC2.VPC",
        "Vpc",
        [] if value is None else [("Name", value, None)],
    )
    for _, row in rows:
        row["comment"] = ""
    material, judgments = naming_materials(comparison)
    data = snapshot_artifact(tmp_path, services=["vpc"])
    data["naming_context"] = {
        key: val for key, val in material.items() if key != "names"
    }
    data["naming"]["names"] = material["names"]
    stamp_naming_scan(data)
    data["judgments"] = judgments
    item = next(
        (item for item in data["naming"]["names"] if item["property"] == "Name")
    )
    review = review_for(data)
    pattern = "vpc-{{application}}-{{environment}}"
    issue = dict(
        service="vpc",
        resource="001",
        property="Name",
        rule="review.naming",
        naming_item_id=item["id"],
        applied_rule=pattern,
        violation=violation or "format",
        evidence="Reviewed the recorded name and rule",
        message="Naming finding",
    )
    if expected:
        issue.update(expected=expected, actual=actual)
    if violation:
        review["issues"] = [issue]
    with task(tmp_path, ["vpc"]):
        _, snapshot, _ = save_scan(tmp_path, data, review)
    result = json.loads(snapshot.data)
    TestCase().assertTrue(len(result["ordinary"]) == bool(violation))
    TestCase().assertTrue(result["unverified"] == [])
    for invalid in (
        dict(issue, applied_rule="not-a-rule"),
        dict(issue, rule="naming"),
        dict(issue, resource="002"),
        dict(issue, property="Other"),
    ):
        review["issues"] = [invalid]
        with pytest.raises(ValueError):
            save_scan(tmp_path, data, review)
    if not violation:
        review["issues"] = [issue]
        with pytest.raises(ValueError, match="format"):
            save_scan(tmp_path, data, review)
        review["issues"] = [
            dict(
                service="vpc",
                resource="001",
                property="Name",
                rule="naming",
                message="Unknown component",
            )
        ]
        with pytest.raises(ValueError, match="naming_item_id"):
            save_scan(tmp_path, data, review)
        review["unverified"] = [
            dict(
                service="vpc",
                check="naming",
                reason="Unknown component",
                failure_kind="read_failure",
            )
        ]
        review["issues"] = []
        with pytest.raises(ValueError, match="recorded scan failure"):
            save_scan(tmp_path, data, review)
    if violation == "confirmed_mismatch":
        for invalid in (
            dict(issue, expected="unknown"),
            dict(issue, actual="invented"),
        ):
            review["issues"] = [invalid]
            with pytest.raises(ValueError, match="mismatch"):
                save_scan(tmp_path, data, review)
    return {"ordinary": result["ordinary"], "unverified": result["unverified"]}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
