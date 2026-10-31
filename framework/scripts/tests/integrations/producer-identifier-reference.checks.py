#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import shutil as _imports_shutil

import support.producer_identifier_reference_fixtures as _exports_support_producer_identifier_reference_fixtures
from model.projection import identifier_outputs
from model.render import generate_files
from support.import_model_fixtures import service_values
from support.it_case_receipt import it_case
from support.model_reference_fixtures import FRAMEWORK
from support.producer_identifier_reference_fixtures import (
    Path,
    affected,
    dependency_hashes,
    design_source_digest,
    json,
    load_model,
    reference,
    resource,
    setup,
    source_inputs,
    tempfile,
    trace_model,
    write_model,
)
from sync_files import save_files
from utils.aws_mappings import mapping_alias
from validation.design_links import check_design_links
from validation.findings import Findings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

# Preserve shared fixtures and compatibility exports under their historical names.
shutil = _exports_support_producer_identifier_reference_fixtures.shutil


@it_case
def check(root):
    setup(root, ["vpc", "vpc-endpoint"], ["EC2.VPC", "EC2.VPCEndpoint"])
    producer = root / "model/preview/team/vpc.properties"
    original = resource(
        "001",
        "EC2.VPC",
        "vpc-one",
        [
            ("Name", "`vpc-one`"),
            (
                "VpcId",
                '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
            ),
        ],
    )
    original["observed.row.001-002.value"] = "`vpc-fixture-one`"
    write_model(producer, original)
    path = producer.with_name("vpc-endpoint.properties")
    key = "desired.row.008-001.document"
    values = resource(
        "008",
        "EC2.VPCEndpoint",
        "endpoint-008",
        [("PolicyDocument", "[policy](vpc-endpoint/policy.json)")],
    )
    values[key] = json.dumps(
        {
            "Condition": {"StringEquals": {"aws:SourceVpc": "vpc-fixture-one"}},
            "Enabled": True,
        }
    )
    values.update(
        reference(
            "vpc-id",
            key,
            "vpc-fixture-one",
            "vpc",
            "001",
            "EC2.VPC",
            mode="identifier",
            prop="EC2.VPC.VpcId",
            pointer="/Condition/StringEquals/aws:SourceVpc",
        )
    )
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert json.loads(snapshot.authoritative[key]) == {
        "Condition": {"StringEquals": {"aws:SourceVpc": "vpc-fixture-one"}},
        "Enabled": True,
    }
    assert producer in source_inputs(path)
    trace = trace_model(path, key)
    assert trace["references"]["vpc-id"]["format"] == "identifier"
    assert affected(root, [producer.relative_to(root)]) == {
        ("preview", "team", "vpc"),
        ("preview", "team", "vpc-endpoint"),
    }
    digest = design_source_digest(path)
    dependencies = dependency_hashes(path)
    for raw in ("`vpc-fixture-two`", "`PENDING_DEPLOY`"):
        write_model(producer, {**original, "observed.row.001-002.value": raw})
        changed = load_model(path)
        assert changed.warnings and changed.authoritative == snapshot.authoritative
        assert (
            design_source_digest(path) == digest
            and dependency_hashes(path) != dependencies
        )
    shutil = _imports_shutil

    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        shutil.copytree(root / "model", stage / "model")
        shutil.copyfile(root / "project.json", stage / "project.json")
        staged_producer = stage / producer.relative_to(root)
        write_model(
            staged_producer,
            {**original, "observed.row.001-002.value": "`vpc-stage-only`"},
        )
        with mapping_alias(root, stage):
            assert not (stage / "framework").exists()
            staged = load_model(stage / path.relative_to(root))
            assert staged.authoritative == snapshot.authoritative and staged.warnings
            assert (
                staged_producer in staged.dependencies
                and producer not in staged.dependencies
            )
    assert load_model(path).authoritative == snapshot.authoritative
    print(
        "Producer identifiers: PASS (saved observed authority, pending/empty/absent distinctions, exact JSON, stage dependencies, warnings, schema rejection)"
    )


@it_case
def check_reference_views(root):
    setup(root, ["lambda", "security-group"], ["Lambda.Function", "EC2.SecurityGroup"])
    producer = root / "model/preview/team/security-group.properties"
    target = service_values("security-group", ["EC2.SecurityGroup"])
    target.update(
        resource(
            "001",
            "EC2.SecurityGroup",
            "sg-one",
            [
                (
                    "Id",
                    '`{"$modelRef":{"logicalId":"EC2_SecurityGroup_001","attribute":"GroupId"}}`',
                ),
                ("GroupDescription", "`fixture`"),
                ("GroupName", "`sg-one`"),
                ("VpcId", "`vpc-001`"),
            ],
        )
    )
    target["desired.resource.001.resourceMode"] = "CREATE"
    target["observed.row.001-001.value"] = "`PENDING_DEPLOY`"
    write_model(producer, target)
    consumer = root / "model/preview/team/lambda.properties"
    source = service_values("lambda", ["Lambda.Function"])
    source.update(
        resource(
            "001",
            "Lambda.Function",
            "lambda-one",
            [
                ("FunctionName", "`lambda-one`"),
                (
                    "VpcConfig.SecurityGroupIds",
                    '`[{"$modelRef":{"logicalId":"EC2_SecurityGroup_001","attribute":"GroupId"}}]`',
                ),
            ],
        )
    )
    source["desired.resource.001.resourceMode"] = "CREATE"
    write_model(consumer, source)
    policy_path = root / "model/preview/team/iam.properties"
    policy = service_values("iam", ["IAM.ManagedPolicy"])
    policy.update(
        resource(
            "001",
            "IAM.ManagedPolicy",
            "policy-one",
            [
                ("ManagedPolicyName", "`policy-one`"),
                ("PolicyDocument", "[policy](iam/policy.json)"),
            ],
        )
    )
    policy["desired.row.001-002.document"] = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "s3:GetObject",
                    "Resource": {
                        "Fn::Select": [0, ["arn:aws:s3:::example/*", "PENDING_DEPLOY"]]
                    },
                }
            ],
        }
    )
    write_model(policy_path, policy)
    paths = [
        root / "docs/designs/preview/team/security-group.md",
        root / "docs/designs/preview/team/lambda.md",
    ]
    before = (consumer.read_bytes(), producer.read_bytes())
    with mapping_alias(FRAMEWORK, root):
        policy_view = root / "docs/designs/preview/team/iam.md"
        save_files(generate_files(policy_view, load_model(policy_path).values, root))
        assert (
            json.loads(
                (policy_view.with_suffix("") / "policy.json").read_text(
                    encoding="utf-8"
                )
            )["Statement"][0]["Resource"]
            == "arn:aws:s3:::example/*"
        )
        for path, model in zip(paths, (producer, consumer), strict=True):
            save_files(generate_files(path, load_model(model).values, root))
        assert "[sg-one](security-group.md#sg-one)" in paths[1].read_text(
            encoding="utf-8"
        )
        findings = Findings(root)
        check_design_links(
            identifier_outputs(FRAMEWORK),
            paths,
            findings=findings,
            root=root,
            scope=None,
            definitions_root=FRAMEWORK,
        )
        assert not findings.errors and not findings.unverified, (
            findings.errors,
            findings.unverified,
        )
        assert not any(
            "identifier reference does not match observed target" in str(item)
            for item in findings.warnings
        ), findings.warnings
        assert (consumer.read_bytes(), producer.read_bytes()) == before
        paths[1].write_text(
            paths[1]
            .read_text()
            .replace(
                "[sg-one](security-group.md#sg-one)",
                "[sg-different](security-group.md#sg-one)",
            )
        )
        findings = Findings(root)
        check_design_links(
            identifier_outputs(FRAMEWORK),
            paths,
            findings=findings,
            root=root,
            scope=None,
            definitions_root=FRAMEWORK,
        )
        assert findings.errors and findings.unverified, (
            findings.errors,
            findings.unverified,
        )
        assert any(
            "design.display.mismatch" in str(item) for item in findings.errors
        ), findings.warnings
    assert producer.read_bytes() == before[1]


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
    with tempfile.TemporaryDirectory() as directory:
        check_reference_views(Path(directory).resolve())
