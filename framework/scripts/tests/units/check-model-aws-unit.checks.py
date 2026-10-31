#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import Mock

import support.check_model_aws_fixtures as _retained_fixture_offline_network
import support.model_reference_fixtures as reference_fixtures
from aws_mapping import Identity
from model.validations.schema import validate_required_properties
from support.aws_mapping_compare_fixtures import (
    ROOT,
    checks,
    comparison,
    input_scope,
    mapped_value,
    outcome,
)
from support.check_model_aws_fixtures import (
    ACCOUNT,
    PATCHES,
    STACK_MODEL,
    TARGET,
    FakeResource,
    Path,
    SchemaOffline,
    SimpleNamespace,
    _batch_checks_cli,
    boto3,
    check,
    copy,
    expect,
    json,
    m,
    model_text,
    patch,
    pytest,
    run,
    sys,
    write_model,
)
from utils.aws_mappings import mapping_alias

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

offline_network = _retained_fixture_offline_network.offline_network


def check_summary_exit_codes():
    check(m.summarize([{"status": "match"}])["exitCode"] == 0, "match exit")
    check(m.summarize([{"status": "difference"}])["exitCode"] == 1, "difference exit")
    check(
        m.summarize([{"status": "difference"}, {"status": "sdk_unavailable"}])[
            "exitCode"
        ]
        == 2,
        "incomplete takes precedence",
    )
    check(m.summarize([])["exitCode"] == 2, "empty scan incomplete")


@pytest.mark.parametrize("shape", ["leaf", "projection"])
def check_explicit_array_shape_comparison(tmp_path, shape):
    ctx = SchemaOffline(tmp_path)
    ctx.verified = True
    kind = "QuickSight.DataSource"
    prop = kind + ".Permissions[].Actions"
    actions = ["ActionA", "ActionB"]
    row = {
        "property": prop,
        "value": "`" + json.dumps(actions if shape == "leaf" else [actions]) + "`",
        "valueShape": shape,
    }
    model = SimpleNamespace(
        ctx=ctx,
        service="quicksight",
        values={},
        locations={},
        path=tmp_path / "model/dev" / ACCOUNT / "quicksight.properties",
    )
    selected = m.Resource(
        model,
        "001",
        {"resourceType": kind, "logicalId": "QuickSight_DataSource_001"},
        [("001-001", row)],
    )
    with patch.object(
        m._imports_aws_mapping_compare, "value", return_value=({}, [actions])
    ):
        records = m.compare_resource(ctx, selected)
    assert len(records) == 1 and records[0]["status"] == "match", records


@pytest.mark.parametrize("conflicting", [False, True])
def check_projection_sibling_comparison(tmp_path, conflicting):
    ctx = SchemaOffline(tmp_path)
    ctx.verified = True
    kind = "CodeBuild.Project"
    mapping, properties = ctx.comparison("codebuild")
    # The pinned catalog spells this terminal array without []; isolate row construction.
    ctx.comparisons["codebuild"] = (
        mapping,
        {
            **properties,
            kind + ".VpcConfig.Subnets[]": properties[kind + ".VpcConfig.Subnets"],
        },
    )
    rows = [
        ("001-001", {"property": kind + ".VpcConfig.VpcId", "value": "`vpc-123`"}),
        (
            "001-002",
            {
                "property": kind + ".VpcConfig.Subnets[]",
                "value": '`["subnet-2","subnet-1"]`',
                "valueShape": "projection",
            },
        ),
    ]
    if conflicting:
        rows.append(
            (
                "001-003",
                {"property": kind + ".VpcConfig.Subnets[]", "value": "`subnet-3`"},
            )
        )
    model = SimpleNamespace(
        ctx=ctx,
        service="codebuild",
        values={},
        locations={},
        path=tmp_path / "model/dev" / ACCOUNT / "codebuild.properties",
    )
    selected = m.Resource(
        model,
        "001",
        {"resourceType": kind, "logicalId": "CodeBuild_Project_001"},
        rows,
    )
    with patch.object(
        m._imports_aws_mapping_compare,
        "value",
        side_effect=[({}, "vpc-123"), ({}, ["subnet-2", "subnet-1"])],
    ):
        records = m.compare_resource(ctx, selected)
    assert {item["propertiesKey"]: item["status"] for item in records} == {
        kind + ".VpcConfig.VpcId": "match",
        kind + ".VpcConfig.Subnets[]": "design_unresolved" if conflicting else "match",
    }, records


@pytest.mark.parametrize(
    "actual,status", [(["ActionA"], "match"), (["ActionB"], "difference")]
)
def check_indexed_projection_aws_comparison(tmp_path, actual, status):
    ctx = SchemaOffline(tmp_path)
    ctx.verified = True
    kind = "QuickSight.DataSource"
    mapping, properties = ctx.comparison("quicksight")
    principal = kind + ".Permissions[1].Principal"
    actions = kind + ".Permissions[1].Actions[]"
    ctx.comparisons["quicksight"] = (
        mapping,
        {
            **properties,
            principal: properties[kind + ".Permissions[].Principal"],
            actions: properties[kind + ".Permissions[].Actions"],
        },
    )
    model = SimpleNamespace(
        ctx=ctx,
        service="quicksight",
        values={},
        locations={},
        path=tmp_path / "model/dev" / ACCOUNT / "quicksight.properties",
    )
    selected = m.Resource(
        model,
        "001",
        {"resourceType": kind, "logicalId": "QuickSight_DataSource_001"},
        [
            ("001-001", {"property": principal, "value": "`principal`"}),
            (
                "001-002",
                {
                    "property": actions,
                    "value": '`["ActionA"]`',
                    "valueShape": "projection",
                },
            ),
        ],
    )
    with patch.object(
        m._imports_aws_mapping_compare,
        "value",
        side_effect=[({}, "principal"), ({}, actual)],
    ):
        records = m.compare_resource(ctx, selected)
    assert {item["propertiesKey"]: item["status"] for item in records} == {
        principal: "match",
        actions: status,
    }, records
    assert (
        next(item for item in records if item["propertiesKey"] == actions)["awsValue"]
        == actual
    )


def check_value_normalization():
    tags = {"Tags": [{"Key": "b", "Value": "2"}, {"Key": "a", "Value": "1"}]}
    check(
        m.canonical(tags)["Tags"]
        == [{"Key": "a", "Value": "1"}, {"Key": "b", "Value": "2"}],
        "tag association",
    )
    check(m.canonical({"Stages": ["b", "a"]})["Stages"] == ["b", "a"], "stage order")
    check(
        m.canonical({"SubnetIds": ["b", "a"]})["SubnetIds"] == ["b", "a"],
        "placement order",
    )
    check(
        m.policy(
            {
                "Statement": {
                    "Effect": "Allow",
                    "Action": "s3:GetObject",
                    "Resource": "*",
                }
            }
        )
        == m.policy(
            {
                "Statement": [
                    {"Resource": ["*"], "Action": ["s3:GetObject"], "Effect": "Allow"}
                ]
            }
        ),
        "policy scalar/set/object normalization",
    )
    check(
        m.policy('{"Statement":[],"Id":"keep%2Fthis"}')["Id"] == "keep%2Fthis",
        "plain JSON policy preserves percent escapes",
    )


def check_secret_redaction():
    check(
        m.redacted({"password": "never print", "nested": {"Token": "never print"}})
        == {"password": "[REDACTED]", "nested": {"Token": "[REDACTED]"}},
        "secret output redaction",
    )


def check_identity_delegation_and_sts_reuse(tmp_path):
    target = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}
    runner = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout='{"Account":"123456789012"}', stderr=""
        )
    )
    ctx = m.Context(tmp_path, target, cli_runner=runner, services=(), import_mode=True)
    with patch.object(m, "verify_account", return_value="123456789012") as verify:
        assert ctx.verify() == ctx.verify() == "123456789012"
        assert verify.call_count == 2
        verify.assert_called_with(target, "123456789012")
    assert runner.call_count == 1
    rejected = m.Context(
        tmp_path, target, cli_runner=runner, services=(), import_mode=True
    )
    failure = m.IdentityError("identity rejected", "AccountMismatch")
    with patch.object(m, "verify_account", side_effect=failure):
        with pytest.raises(m.IdentityError, match="identity rejected") as caught:
            rejected.verify()
        assert caught.value is failure
    with pytest.raises(ValueError, match="account has not been verified"):
        rejected.call(
            "cloudcontrol", "list_resources", TypeName="AWS::DataZone::Domain"
        )
    assert runner.call_count == 2


def check_all_target_profiles_precede_aws(tmp_path):
    targets = [
        dict(awsAccountId="123456789012", awsRegion="ap-northeast-1", directory=name)
        for name in ("first", "second")
    ]
    items = [(target, tmp_path / "vpc.properties") for target in targets]
    factory = Mock()
    with (
        patch.object(
            m,
            "select_profile",
            side_effect=[None, m.IdentityError("identity rejected")],
        ) as select,
        patch.object(m.subprocess, "run") as process,
    ):
        with pytest.raises(m.IdentityError, match="identity rejected"):
            m.run(tmp_path, items, profile="explicit", session_factory=factory)
        assert [call.args for call in select.call_args_list] == [
            (target, "explicit") for target in targets
        ]
    factory.assert_not_called()
    process.assert_not_called()


@pytest.mark.parametrize(
    "service,operation,cli_service",
    [
        ("config", "describe_configuration_recorders", "configservice"),
        ("config", "describe_delivery_channels", "configservice"),
        ("s3", "list_buckets", "s3api"),
        ("logs", "describe_log_groups", "logs"),
    ],
)
@pytest.mark.parametrize("paginate", [False, True])
def check_cli_service_names(tmp_path, service, operation, cli_service, paginate):
    ctx = m.Context(tmp_path, TARGET)
    ctx.verified = True
    with patch.object(
        m.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""),
    ) as process:
        (ctx.pages if paginate else ctx.call)(service, operation)
    command = process.call_args.args[0]
    assert command[:3] == ["aws", cli_service, operation.replace("_", "-")]
    assert ("--no-paginate" not in command) == paginate


def check_stack_states(tmp_path):
    root = tmp_path
    (root / "project.json").write_text(json.dumps({"targets": [TARGET]}))
    path = root / "model/dev" / ACCOUNT / "cloudformation-stacks.properties"
    path.parent.mkdir(parents=True)
    write_model(path, STACK_MODEL)
    adapter = m.service_module("cloudformation-stacks")
    cases = [
        ({"Stacks": [{"StackName": "fixture", "StackStatus": state}]}, None, status)
        for state, status in [
            ("CREATE_COMPLETE", "match"),
            ("UPDATE_COMPLETE", "match"),
            ("IMPORT_COMPLETE", "match"),
            ("ROLLBACK_COMPLETE", "difference"),
        ]
    ]
    cases += [
        (payload, None, "resource_missing")
        for payload in (
            {"Stacks": []},
            {"Stacks": [{"StackName": "other", "StackStatus": "CREATE_COMPLETE"}]},
            {"Stacks": [{"StackName": "fixture"}, {"StackName": "fixture"}]},
        )
    ]
    cases += [
        ({}, message, status)
        for message, status in [
            ("Stack with id fixture does not exist", "resource_missing"),
            ("Invalid StackName", "acquisition_failed"),
        ]
    ]
    for payload, message, status in cases:
        response = SimpleNamespace(
            returncode=254 if message else 0,
            stdout=json.dumps(payload),
            stderr=(
                "An error occurred (ValidationError) when calling the DescribeStacks operation: "
                + message
            )
            if message
            else "",
        )
        with patch.object(m.subprocess, "run", return_value=response) as process:
            ctx = m.Context(root, TARGET, services=["cloudformation-stacks"])
            ctx.verified = True
            model = ctx.model(path)
            results = adapter.compare(ctx, model)
            check(
                results[0]["status"] == status,
                "dedicated Stack state/name/error: " + str((payload, message)),
            )
            check(
                results[0]["apis"]
                == [
                    {
                        "api": "cloudformation.describe_stacks",
                        "inputs": {"StackName": "fixture"},
                    }
                ],
                "Stack API trace",
            )
            check(
                sum(item["status"] == "local_metadata" for item in results) == 4,
                "Stack local metadata preserved",
            )
            check(
                adapter.compare(ctx, model) == results and process.call_count == 1,
                "Stack response/error cache and classification",
            )
            check(
                ctx.allowed
                == {
                    ("sts", "get_caller_identity"),
                    ("cloudformation", "describe_stacks"),
                },
                "Stack allowlist isolated",
            )


def _identity_registry_checks_forbidden(context, selected, getter):
    return context.call("ec2", "terminate_instances", InstanceIds=["unconfirmed"])


def check_identity_registry(tmp_path):
    root = tmp_path
    ctx = SchemaOffline(root)
    ctx.verified = True
    resource = FakeResource(ctx, "s3", "S3.Bucket")
    # Registry is the authority even when its response path differs from legacy Python.
    definition = SimpleNamespace(
        identities={
            "S3.Bucket": Identity("base", "CustomId", "BucketArn", "BucketName")
        }
    )
    with (
        patch.object(ctx, "comparison", return_value=(definition, {})),
        patch.object(ctx, "fetch", return_value={"CustomId": "registry-id"}),
    ):
        check(
            m.Resource.identity(resource) == "registry-id",
            "Registry identity path is used directly",
        )
        expect(m.Unresolved, lambda: m.Resource.identity(resource, "arn"))
        with patch.object(ctx, "fetch", return_value={"CustomId": None}):
            expect(m.Unresolved, lambda: m.Resource.identity(resource))
        with (
            patch.object(
                ctx, "fetch", side_effect=m.Unresolved("resource does not exist")
            ),
            patch.object(resource, "value") as selected_name,
        ):
            expect(m.Unresolved, lambda: m.Resource.identity(resource, "name"))
            check(
                not selected_name.called, "Name selection follows confirmed existence"
            )
        definition.identities = {}
        expect(m.Unresolved, lambda: m.Resource.identity(resource))
    allowed = set(ctx.allowed)
    definition.identities = {"S3.Bucket": Identity("new-getter", "Name", None, None)}
    forbidden = _identity_registry_checks_forbidden
    with (
        patch.object(ctx, "comparison", return_value=(definition, {})),
        patch.object(resource.module, "fetch", side_effect=forbidden),
    ):
        expect(ValueError, lambda: m.Resource.identity(resource))
    check(
        ctx.allowed == allowed and not ctx.trace,
        "new Mapping getter cannot grant or call an API",
    )
    stack = FakeResource(ctx, "cloudformation-stacks", "CloudFormation.Stack")
    expect(m.Unresolved, lambda: m.Resource.identity(stack))


def check_cli_errors(tmp_path):
    root = tmp_path
    (root / "project.json").write_text(json.dumps({"targets": [TARGET]}))
    path = root / "model/dev" / ACCOUNT / "s3.properties"
    path.parent.mkdir(parents=True)
    write_model(path, model_text("S3.Bucket", [("S3.Bucket.BucketName", "`fixture`")]))
    items = [(dict(TARGET, awsProfile="configured"), path)]
    with patch.object(
        m.subprocess,
        "run",
        return_value=SimpleNamespace(
            returncode=0, stdout='{"Account":"999999999999"}', stderr=""
        ),
    ) as process:
        assert m.run(root, items)["exitCode"] == 2 and process.call_count == 1
        process.reset_mock()
        expect(ValueError, lambda: m.run(root, items, profile="wrong"))
        assert not process.called
    for fault, reason in [
        (FileNotFoundError("secret"), "FileNotFoundError"),
        (
            SimpleNamespace(
                returncode=255, stdout="", stderr="secret credential failure"
            ),
            "AwsCliError",
        ),
        (
            SimpleNamespace(returncode=0, stdout="invalid secret", stderr=""),
            "JSONDecodeError",
        ),
        (SimpleNamespace(returncode=0, stdout="[]", stderr=""), "ValueError"),
    ]:
        with patch.object(
            m.subprocess,
            "run",
            side_effect=fault if isinstance(fault, Exception) else None,
            return_value=fault,
        ) as process:
            report = m.run(root, items)
            check(
                report["exitCode"] == 2 and report["results"][0]["reason"] == reason,
                "CLI failures remain incomplete",
            )
            check(
                "secret" not in json.dumps(report) and process.call_count == 1,
                "CLI error details hidden and no fallback",
            )

    for code, expected in [
        ("NoSuchBucket", "resource_missing"),
        ("AccessDenied", "acquisition_failed"),
    ]:
        ctx = m.Context(root, items[0][0])
        ctx.verified = True
        error = SimpleNamespace(
            returncode=254,
            stdout="",
            stderr=f"An error occurred ({code}) when calling the GetBucketVersioning operation: secret",
        )
        with patch.object(m.subprocess, "run", return_value=error) as process:
            for _ in range(2):
                with pytest.raises(m.AcquisitionError) as caught:
                    ctx.call("s3", "get_bucket_versioning", Bucket="fixture")
                check(
                    caught.value.status == expected and caught.value.code == code,
                    "CLI AWS error classification retained",
                )
                check("secret" not in str(caught.value), "CLI error message redacted")
            check(process.call_count == 1, "failed CLI request cached")

    ctx = m.Context(root, TARGET)
    with patch.object(m.subprocess, "run") as process:
        expect(ValueError, lambda: ctx.call("s3", "list_buckets"))
        ctx.verified = True
        expect(
            ValueError,
            lambda: ctx.call("secretsmanager", "get_secret_value", SecretId="fixture"),
        )
        expect(ValueError, lambda: ctx.call("s3", "delete_bucket", Bucket="fixture"))
        expect(ValueError, lambda: ctx.pages("s3", "delete_bucket", Bucket="fixture"))
        check(not process.called, "unverified, secret and mutating CLI calls blocked")
    merged = {"ResourceRecordSets": [{"Name": "first"}, {"Name": "second"}]}
    with patch.object(
        m.subprocess,
        "run",
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(merged), stderr=""
        ),
    ) as process:
        check(
            ctx.pages("route53", "list_resource_record_sets", HostedZoneId="fixture")
            == merged,
            "CLI merged pagination response preserved",
        )
        check(
            ctx.pages("route53", "list_resource_record_sets", HostedZoneId="fixture")
            == merged
            and process.call_count == 1,
            "CLI pagination cached",
        )
        check(
            "--no-paginate" not in process.call_args.args[0]
            and "--max-items" not in process.call_args.args[0],
            "CLI owns service-specific pagination tokens",
        )
    with patch.object(
        m.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""),
    ) as process:
        ctx.call("logs", "describe_log_groups", logGroupNamePrefix="日本語")
        check(
            json.loads(
                process.call_args.args[0][
                    process.call_args.args[0].index("--cli-input-json") + 1
                ]
            )
            == {"logGroupNamePrefix": "日本語"},
            "Unicode CLI input preserved",
        )
        check(
            "--profile" not in process.call_args.args[0],
            "unconfigured profile uses CLI credential chain",
        )
    ctx = m.Context(root, TARGET)
    ctx.verified = True
    with patch.object(
        m.subprocess,
        "run",
        return_value=SimpleNamespace(
            returncode=254,
            stdout=json.dumps(merged),
            stderr="An error occurred (AccessDenied) when calling the ListResourceRecordSets operation: later page",
        ),
    ):
        expect(
            m.AcquisitionError,
            lambda: ctx.pages(
                "route53", "list_resource_record_sets", HostedZoneId="fixture"
            ),
        )


def check_batch_selectors(tmp_path):
    root = tmp_path
    directory = root / "model/dev" / ACCOUNT
    directory.mkdir(parents=True)
    (root / "project.json").write_text(json.dumps({"targets": [TARGET]}))
    for service, kind, prop in [
        ("s3", "S3.Bucket", "BucketName"),
        ("iam", "IAM.Role", "RoleName"),
        ("athena", "Athena.WorkGroup", "Name"),
    ]:
        write_model(
            directory / (service + ".properties"),
            model_text(kind, [(kind + "." + prop, "`fixture`")]),
        )
    selected = m.targets(root, "dev", ACCOUNT)
    expect(ValueError, lambda: m.targets(root, "dev", "unknown"))
    base_args = ["--root", str(root), "--environment", "dev", "--target", ACCOUNT]
    cli = _batch_checks_cli
    single = (0, {"exitCode": 0})
    with patch.object(m, "run", return_value=single[1]) as compare:
        for services in (["s3"], ["s3", "s3"]):
            code, _, _ = cli(
                [
                    *base_args,
                    *(flag for name in services for flag in ("--service", name)),
                ]
            )
            assert code == 0 and len(compare.call_args.args[1]) == 1
    with patch.object(
        boto3, "Session", side_effect=AssertionError("coverage is offline")
    ):
        code, report, _ = cli(
            [*base_args, "--service", "s3", "--service", "iam", "--coverage"]
        )
        code2, duplicate, _ = cli(
            [
                *base_args,
                "--service",
                "s3",
                "--service",
                "iam",
                "--service",
                "s3",
                "--coverage",
            ]
        )
        assert code == code2 == 0 and report == duplicate
    assert m.inventory(root, selected, ["s3", "s3"]) == m.inventory(
        root, selected, ["s3"]
    )
    expect(ValueError, lambda: m.inventory(root, selected, ["s3", "iam", "kms"]))
    expect(ValueError, lambda: m.inventory(root, selected, ["kms"]))
    with patch.object(m, "run") as run, patch.object(m, "coverage") as coverage:
        for flags in ([], ["--coverage"]):
            code, report, _ = cli(
                [
                    *base_args,
                    "--service",
                    "s3",
                    "--service",
                    "iam",
                    "--service",
                    "kms",
                    *flags,
                ]
            )
            check(
                code == 2
                and report
                == {
                    "status": "incomplete",
                    "reason": "service entrance models are missing for target: kms",
                },
                "missing batch service fails closed in existing error schema",
            )
        check(
            not run.called and not coverage.called,
            "missing service rejected before comparison or coverage",
        )
    with patch.object(m, "targets") as targets:
        for flags in (
            [],
            ["--all", "--service", "s3"],
            ["--all", "--environment", "dev"],
            ["--all", "--target", ACCOUNT],
            ["--environment", "dev", "--target", ACCOUNT],
            ["--service", "s3"],
            ["--environment", "dev", "--service", "s3"],
            ["--target", ACCOUNT, "--service", "s3"],
        ):
            code, report, error = cli(["--root", str(root), *flags])
            check(
                code == 2 and report is None and "use --all alone" in error,
                "invalid selector rejected: " + repr(flags),
            )
        check(not targets.called, "invalid selectors rejected before inventory")
    with patch.object(m, "run", return_value=single[1]) as run:
        code, _, _ = cli(["--root", str(root), "--all"])
        check(
            code == 0
            and {path.stem for _, path in run.call_args.args[1]}
            == {"s3", "iam", "athena"},
            "explicit --all remains available",
        )


def _callback_common_checks_bad_factory(calls, /, **kw):
    calls.append(kw)
    raise RuntimeError("secret credential failure")


def check_context_branches(tmp_path):
    root = tmp_path
    directory = root / "model/dev" / ACCOUNT
    directory.mkdir(parents=True)
    (root / "project.json").write_text(json.dumps({"targets": [TARGET]}))
    path = directory / "athena.properties"
    write_model(
        path,
        model_text(
            "Athena.WorkGroup",
            [
                ("Athena.WorkGroup.Name", "`fixture`"),
                ("Athena.WorkGroup.State", "`ENABLED`"),
            ],
        ),
    )
    ctx = SchemaOffline(root)
    ctx.verify()
    model = ctx.model(path)
    resource = model.resources[0]
    resource.rows.append(
        (
            "001-003",
            {
                "property": "Athena.WorkGroup.Unknown",
                "value": "false",
                "comment": "fixture",
            },
        )
    )
    model.locations["desired.row.001-003.value"] = {"file": str(path), "line": 1}
    expect(
        ValueError, lambda: m.compare_resource(ctx, resource)
    )  # Missing Mapping is a validation error.
    resource.rows.pop()
    resource.rows[1][1]["value"] = "UNSET"
    check(
        any(
            item["status"] == "design_unresolved"
            for item in m.compare_resource(ctx, resource)
        ),
        "unresolved desired is not equality",
    )
    resource.rows[1][1]["value"] = "`ENABLED`"
    failed = SchemaOffline(root, "failed")
    failed.egress = False
    failed.verified = True
    failures = m.compare_resource(failed, failed.model(path).resources[0])
    check(
        len(failures) == 1 and len(failures[0]["affectedKeys"]) == 2,
        "one failure with affected-key scope",
    )
    expect(ValueError, lambda: ctx.call("s3", "delete_bucket", Bucket="fixture"))
    expect(
        ValueError,
        lambda: ctx.call("secretsmanager", "get_secret_value", SecretId="fixture"),
    )
    unverified = SchemaOffline(root)
    expect(ValueError, lambda: unverified.call("s3", "list_buckets"))
    bad = dict(TARGET, awsAccountId="999999999999")
    ctx2 = SchemaOffline(root, target=bad)
    expect(m.IdentityError, ctx2.verify)
    check(
        not ctx2.verified and set(ctx2.clients) == {"sts"},
        "account mismatch stops all service APIs",
    )
    split = SchemaOffline(
        root,
        target=dict(TARGET, awsAccountId="999999999999", awsExecutionAccountId=ACCOUNT),
    )
    split.verify()
    check(
        split.verified and split.target["awsAccountId"] == "999999999999",
        "execution account verification preserves resource account",
    )
    split_resource = split.model(path).resources[0]
    check(
        split_resource.resolve_json({"Fn::Sub": "account-${AWS::AccountId}"}, None)
        == "account-" + ACCOUNT,
        "live CFN pseudo account uses verified execution account",
    )
    check(
        split_resource.resolve_json({"Ref": "AWS::AccountId"}) == ACCOUNT,
        "live CFN Ref pseudo account uses verified execution account",
    )
    wrong_execution = SchemaOffline(
        root, target=dict(TARGET, awsExecutionAccountId="999999999999")
    )
    expect(m.IdentityError, wrong_execution.verify)
    check(
        not wrong_execution.verified and set(wrong_execution.clients) == {"sts"},
        "execution mismatch stops all service APIs",
    )
    # Implicit API account contexts use execution IDs; explicit model values stay untouched.
    execution = "999999999999"
    api_ctx = SimpleNamespace(target=dict(TARGET, awsExecutionAccountId=execution))
    resource_stub = SimpleNamespace(
        kind="SQS.Queue", value=lambda key: "fixture", current=lambda key: None
    )
    with patch.object(
        api_ctx, "call", create=True, return_value={"QueueUrl": "url"}
    ) as call:
        m.service_module("sqs").fetch(api_ctx, resource_stub, "base")
        check(
            call.call_args_list[0].kwargs["QueueOwnerAWSAccountId"] == execution,
            "SQS implicit owner is execution account",
        )
    with patch.object(api_ctx, "call", create=True, return_value={}) as call:
        m.service_module("s3").fetch(api_ctx, resource_stub, "versioning")
        check(
            call.call_args.kwargs["ExpectedBucketOwner"] == execution,
            "S3 implicit owner is execution account",
        )
        check(
            m.service_module("macie").fetch(api_ctx, resource_stub, "session")[
                "AwsAccountId"
            ]
            == execution,
            "Macie session actual account is execution account",
        )
    resource_stub.kind = "Glue.Catalog"
    with patch.object(
        api_ctx,
        "pages",
        create=True,
        return_value={"CatalogList": [{"Name": "fixture"}]},
    ) as pages:
        m.service_module("glue").fetch(api_ctx, resource_stub, "base")
        check(
            pages.call_args.kwargs["ParentCatalogId"] == execution,
            "Glue implicit parent catalog is execution account",
        )
    calls = []
    bad_factory = _bind_framework_callback(_callback_common_checks_bad_factory, calls)
    m.run(
        root,
        [(dict(TARGET, awsProfile="confirmed"), path)],
        session_factory=bad_factory,
    )
    check(
        len(calls) == 1 and calls[0]["profile_name"] == "confirmed",
        "no profile fallback",
    )
    check(
        m.normalize(ctx, "false", "boolean") is False
        and m.normalize(ctx, "60", "number") == 60,
        "typed SDK string values",
    )
    expect(m.Unresolved, lambda: m.normalize(ctx, "FALSE", "boolean"))
    sample_row = {
        "property": "GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.ObjectPrefixes[]",
        "value": '`["a/","b/"]`',
        "valueShape": "projection",
    }
    check(resource.parse(sample_row) == ["a/", "b/"], "terminal-array literal")
    check(
        resource.parse(
            {
                "property": "S3.Bucket.LifecycleConfiguration.Rules[].Prefix",
                "value": "``",
            }
        )
        == "",
        "explicit empty optional prefix",
    )
    # Stack presence/state and local metadata, without templates or parameters.
    stacks = directory / "cloudformation-stacks.properties"
    write_model(stacks, STACK_MODEL)
    for fault in (None, "missing", "failed"):
        stack_ctx = SchemaOffline(root, fault)
        stack_ctx.egress = False
        stack_ctx.verified = True
        results = m.service_module("cloudformation-stacks").compare(
            stack_ctx, stack_ctx.model(stacks)
        )
        check(
            results[0]["status"]
            == {
                None: "match",
                "missing": "resource_missing",
                "failed": "acquisition_failed",
            }[fault],
            "stack acquisition",
        )
        check(
            sum(item["status"] == "local_metadata" for item in results) == 4,
            "stack local metadata",
        )


def check_association_values(tmp_path):
    root = tmp_path
    directory = root / "model/dev" / ACCOUNT
    directory.mkdir(parents=True)
    (root / "project.json").write_text(json.dumps({"targets": [TARGET]}))
    # SDK responses and desired rows are authored separately. Moving a tag value
    # onto a different key must fail even when the multisets of values are equal.
    path = directory / "ec2.properties"
    text = model_text(
        "EC2.Instance",
        [
            (
                "EC2.Instance.InstanceId",
                '`{"$modelRef":{"logicalId":"EC2_Instance_001","attribute":"InstanceId"}}`',
            ),
            ("EC2.Instance.Tags[].Key", "`b`"),
            ("EC2.Instance.Tags[].Value", "`2`"),
            ("EC2.Instance.Tags[].Key", "`a`"),
            ("EC2.Instance.Tags[].Value", "`1`"),
        ],
    )
    text += "observed.row.001-001.value=fixture\n"
    write_model(path, text)
    for wrong in (False, True):
        patches = copy.deepcopy(PATCHES)
        patches[("ec2", "describe_instances")] = {
            "Reservations.Instances.Tags": [
                {"Key": "a", "Value": "2" if wrong else "1"},
                {"Key": "b", "Value": "1" if wrong else "2"},
            ]
        }
        with patch.dict(PATCHES, patches, clear=True):
            ctx = SchemaOffline(root)
            ctx.egress = False
            ctx.verified = True
            values = m.compare_resource(ctx, ctx.model(path).resources[0])
            check(
                any(v["status"] == "difference" for v in values) == wrong,
                "tag values belong to their keys",
            )
    pipeline = directory / "codepipeline.properties"
    write_model(
        pipeline,
        model_text(
            "CodePipeline.Pipeline",
            [
                ("CodePipeline.Pipeline.Name", "`fixture`"),
                (
                    "CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category",
                    "`Source`",
                ),
                ("CodePipeline.Pipeline.Stages[].Actions[].Name", "`source`"),
                ("CodePipeline.Pipeline.Stages[].Name", "`first`"),
                (
                    "CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category",
                    "`Build`",
                ),
                ("CodePipeline.Pipeline.Stages[].Actions[].Name", "`build-a`"),
                (
                    "CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category",
                    "`Build`",
                ),
                ("CodePipeline.Pipeline.Stages[].Actions[].Name", "`build-b`"),
                ("CodePipeline.Pipeline.Stages[].Name", "`second`"),
            ],
        ),
    )
    stages = [
        {
            "name": "first",
            "actions": [
                {
                    "name": "source",
                    "actionTypeId": {
                        "category": "Source",
                        "owner": "AWS",
                        "provider": "CodeCommit",
                        "version": "1",
                    },
                }
            ],
        },
        {
            "name": "second",
            "actions": [
                {
                    "name": "build-a",
                    "actionTypeId": {
                        "category": "Build",
                        "owner": "AWS",
                        "provider": "CodeBuild",
                        "version": "1",
                    },
                },
                {
                    "name": "build-b",
                    "actionTypeId": {
                        "category": "Build",
                        "owner": "AWS",
                        "provider": "CodeBuild",
                        "version": "1",
                    },
                },
            ],
        },
    ]
    for reversed_order in (False, True):
        patches = copy.deepcopy(PATCHES)
        patches[("codepipeline", "get_pipeline")]["pipeline.stages"] = (
            list(reversed(stages)) if reversed_order else stages
        )
        with patch.dict(PATCHES, patches, clear=True):
            ctx = SchemaOffline(root)
            ctx.verified = True
            ctx.egress = False
            values = m.compare_resource(ctx, ctx.model(pipeline).resources[0])
            stage_results = [v for v in values if ".Stages" in v["propertiesKey"]]
            check(
                stage_results
                and all(v["status"] == "design_unresolved" for v in stage_results),
                "ambiguous stages never compared",
            )
            check(
                all("element index" in v["reason"] for v in stage_results),
                "specific membership reason",
            )
            check(
                not any(v["status"] == "difference" for v in values),
                "no guessed Action difference",
            )
    trail = directory / "cloudtrail.properties"
    write_model(
        trail,
        model_text(
            "CloudTrail.Trail",
            [
                ("CloudTrail.Trail.TrailName", "`fixture`"),
                ("CloudTrail.Trail.IsLogging", "`true`"),
            ],
        ),
    )
    ctx = SchemaOffline(root, {("cloudtrail", "get_trail_status"): "failed"})
    ctx.egress = False
    ctx.verified = True
    values = m.compare_resource(ctx, ctx.model(trail).resources[0])
    check(
        {v["status"] for v in values} == {"match", "acquisition_failed"},
        "partial acquisition preserves successful comparisons",
    )
    failure = next(v for v in values if v["status"] == "acquisition_failed")
    report = m.summarize(
        [
            dict(failure, environment="dev", target=ACCOUNT, service="cloudtrail"),
            dict(
                failure,
                environment="dev",
                target=ACCOUNT,
                service="cloudtrail",
                resource="second",
            ),
        ]
    )
    check(
        len(report["results"]) == 1
        and len(report["results"][0]["affectedResources"]) == 2,
        "one shared failure retains all affected resources",
    )
    imported = directory / "mwaa.properties"
    write_model(
        imported,
        model_text(
            "MWAA.Environment",
            [("MWAA.Environment.Name", "`fixture`")],
            metadata="desired.resource.001.resourceMode=IMPORT\n",
        ),
    )
    ctx = SchemaOffline(root)
    ctx.verified = True
    ctx.egress = False
    check(
        m.compare_resource(ctx, ctx.model(imported).resources[0])[0]["status"]
        == "match",
        "IMPORT is compared",
    )


@input_scope
def check_mapping_transforms():
    # include=false remains in Compare, with real acquisition and typed transforms.
    cases = [
        ("config", "Config.DeliveryChannel", "S3KeyPrefix"),
        ("codebuild", "CodeBuild.Project", "Artifacts.ArtifactIdentifier"),
        (
            "data-firehose",
            "KinesisFirehose.DeliveryStream",
            "S3DestinationConfiguration.EncryptionConfiguration.NoEncryptionConfig",
        ),
        (
            "glue",
            "Glue.Connection",
            "ConnectionInput.AuthenticationConfiguration.KmsKeyArn",
        ),
        ("glue", "Glue.Table", "TableInput.Description"),
        ("lambda", "Lambda.Function", "Code.S3ObjectVersion"),
        ("macie", "Macie.ClassificationJob", "description"),
        ("s3", "S3.Bucket", "LifecycleConfiguration.Rules[].ExpiredObjectDeleteMarker"),
    ]
    for service, kind, suffix in cases:
        mapping, properties = comparison(ROOT, service)
        key = kind + "." + suffix
        definition = properties[key]
        assert (
            not definition.include and definition.field.classification == "supported"
        ), key
        ctx = checks.Offline(ROOT)
        ctx.verified = True
        resource = checks.FakeResource(ctx, service, kind, key)
        _, actual = mapped_value(ctx, resource, mapping, definition, key)
        assert checks.acquired(actual), key
        resource.desired = actual[0] if ".Rules[]." in key else actual
        result = m.compare_resource(ctx, resource)
        assert len(result) == 1 and result[0]["status"] == "match", (key, result)
        requests = ctx.request_count
        assert m.compare_resource(ctx, resource) == result
        assert ctx.request_count == requests, key + ": repeated API acquisition"
        ctx.finish()
    ctx = checks.Offline(ROOT)
    ctx.verified = True
    resource = checks.FakeResource(
        ctx,
        "codebuild",
        "CodeBuild.Project",
        "CodeBuild.Project.Triggers.Webhook",
        True,
    )
    assert m.compare_resource(ctx, resource)[0]["status"] == "match"
    assert ctx.request_count == 1
    # A legacy field and a new SDK field share exactly the same raw API response.
    resource.rows[0][1]["property"] = "CodeBuild.Project.Name"
    resource.desired = "fixture"
    assert (
        m.compare_resource(ctx, resource)[0]["status"] == "match"
        and ctx.request_count == 1
    )
    ctx.finish()
    blocked = checks.FakeResource(
        ctx,
        "s3",
        "S3.Bucket",
        "S3.Bucket.LifecycleConfiguration.Rules[].ExpirationDate",
    )
    result = m.compare_resource(ctx, blocked)
    assert result[0]["status"] == "sdk_unavailable" and not result[0]["apis"]
    assert (
        ctx.request_count == 1 and ("cloudcontrol", "get_resource") not in ctx.allowed
    )
    webhook = checks.FakeResource(
        ctx,
        "codebuild",
        "CodeBuild.Project",
        "CodeBuild.Project.Triggers.Webhook",
        False,
    )
    for response in ({"projects": [{}]}, {"projects": [{"webhook": None}]}):
        with patch.object(ctx, "fetch", return_value=response):
            assert m.compare_resource(ctx, webhook)[0]["status"] == "match"
    # Ambiguous resource collections are unresolved, never first-element selection.
    mapping, properties = comparison(ROOT, "codebuild")
    resource = checks.FakeResource(ctx, "codebuild", "CodeBuild.Project")
    with patch.object(
        ctx, "fetch", return_value={"projects": [{"name": "a"}, {"name": "b"}]}
    ):
        assert (
            outcome(
                lambda: mapped_value(
                    ctx,
                    resource,
                    mapping,
                    properties["CodeBuild.Project.Triggers.Webhook"],
                    "CodeBuild.Project.Triggers.Webhook",
                )
            )[0]
            == "error"
        )
    with (
        patch(
            "aws_mapping_compare.comparison", side_effect=ValueError("missing Mapping")
        ),
        patch.object(m, "Context") as context,
    ):
        assert (
            outcome(
                lambda: m.run(
                    ROOT, [(checks.TARGET, Path("/offline/config.properties"))]
                )
            )[0]
            == "error"
        )
        assert not context.called
    print(
        "P4 Mapping: PASS (include=false, transforms, SDK collections, shared cache, blocked APIs, missing definitions)"
    )


def check_lakeformation_resource_comparison(tmp_path):
    with mapping_alias(ROOT, tmp_path):
        reference_fixtures.project(tmp_path)
        glue_scope, glue = reference_fixtures.resource(
            tmp_path, "glue", "Glue.Connection", attribute="ConnectionInput.Name"
        )
        glue["desired.row.001-001.value"] = "`example-connection`"
        glue.update(
            {
                "desired.row.001-002.property": "Glue.Connection.CatalogId",
                "desired.row.001-002.value": "`123456789012`",
                "desired.row.001-002.comment": "catalog",
            }
        )
        reference_fixtures.save(glue_scope, glue)
        role_scope, role = reference_fixtures.resource(
            tmp_path, "roles", "IAM.Role", attribute="RoleName"
        )
        role["desired.row.001-001.value"] = "`lake-role`"
        reference_fixtures.save(role_scope, role)
        scope, values = reference_fixtures.resource(
            tmp_path,
            "lake-formation",
            "LakeFormation.Resource",
            attribute="ResourceArn",
        )
        values["desired.row.001-001.value"] = (
            "`"
            + json.dumps(reference_fixtures.reference("Glue_Connection_001", "Arn"))
            + "`"
        )
        for index, (name, value) in enumerate(
            (
                (
                    "RoleArn",
                    json.dumps(reference_fixtures.reference("IAM_Role_001", "Arn")),
                ),
                ("UseServiceLinkedRole", "false"),
                ("WithFederation", "true"),
                ("HybridAccessEnabled", "false"),
            ),
            2,
        ):
            prefix = f"desired.row.001-{index:03d}."
            values[prefix + "property"] = "LakeFormation.Resource." + name
            values[prefix + "value"] = "`" + value + "`"
            values[prefix + "comment"] = "fixture"
        reference_fixtures.save(scope, values)
        validate_required_properties(values, ROOT)
        for row in ("001-001", "001-003"):
            incomplete = {
                key: value
                for key, value in values.items()
                if not key.startswith("desired.row." + row + ".")
            }
            with pytest.raises(
                ValueError, match="required provider schema property missing"
            ):
                validate_required_properties(incomplete, ROOT)
        target = dict(TARGET, environment="qa", directory="team")
        arn = "arn:aws:glue:ap-northeast-1:123456789012:connection/example-connection"
        role_arn = "arn:aws:iam::123456789012:role/lake-role"
        response = {
            "ResourceInfo": {
                "ResourceArn": arn,
                "RoleArn": role_arn,
                "WithFederation": True,
                "HybridAccessEnabled": False,
            }
        }
        for expected, payload in (
            ("match", response),
            (
                "difference",
                {
                    "ResourceInfo": dict(
                        response["ResourceInfo"], RoleArn=role_arn + "-other"
                    )
                },
            ),
            ("sdk_unavailable", {"ResourceInfo": {"ResourceArn": arn}}),
        ):
            ctx = SchemaOffline(tmp_path, target=target)
            ctx.verified = True
            selected = m.Model(ctx, scope.path).resources[0]
            with patch.object(ctx, "call", return_value=payload) as call:
                result = {
                    item["propertiesKey"].rsplit(".", 1)[-1]: item["status"]
                    for item in m.compare_resource(ctx, selected)
                }
            assert result["ResourceArn"] == "match"
            assert result["RoleArn"] == expected
            assert result["UseServiceLinkedRole"] == "sdk_unavailable"
            assert result["WithFederation"] == (
                "sdk_unavailable" if expected == "sdk_unavailable" else "match"
            )
            call.assert_called_once_with(
                "lakeformation", "describe_resource", ResourceArn=arn
            )
        selected.rows[0][1]["value"] = (
            "`"
            + json.dumps(reference_fixtures.reference("Glue_Connection_001", "Name"))
            + "`"
        )
        with pytest.raises(ValueError):
            selected.value("ResourceArn", "arn")
        selected.rows[0][1]["value"] = (
            "`"
            + json.dumps(reference_fixtures.reference("Glue_Connection_999", "Arn"))
            + "`"
        )
        with pytest.raises(ValueError):
            selected.value("ResourceArn", "arn")


if __name__ == "__main__":
    raise SystemExit(run(__file__))


@pytest.mark.parametrize("getter", ["base", "permissions"])
@pytest.mark.parametrize(
    "accounts,execution,verified,identifier,works",
    [
        ([], ACCOUNT, True, "fixture", True),
        ([ACCOUNT], ACCOUNT, True, "fixture", True),
        (["999999999999"], ACCOUNT, True, "fixture", False),
        ([ACCOUNT, ACCOUNT], ACCOUNT, True, "fixture", False),
        (["PENDING_DEPLOY"], ACCOUNT, True, "fixture", False),
        (["UNSET"], ACCOUNT, True, "fixture", False),
        ([], "999999999999", True, "fixture", False),
        ([], ACCOUNT, False, "fixture", False),
        ([], ACCOUNT, True, None, False),
    ],
)
def test_quicksight_datasource_selector(
    tmp_path, accounts, execution, verified, identifier, works, getter
):
    ctx = SchemaOffline(tmp_path)
    ctx.target["awsExecutionAccountId"] = execution
    ctx.verified = verified
    kind = "QuickSight.DataSource"
    rows = [
        (str(i), {"property": kind + ".AwsAccountId", "value": f"`{value}`"})
        for i, value in enumerate(accounts)
    ]
    if identifier is not None:
        rows.append(
            ("id", {"property": kind + ".DataSourceId", "value": f"`{identifier}`"})
        )
    model = SimpleNamespace(
        ctx=ctx,
        service="quicksight",
        values={},
        locations={},
        path=tmp_path / "model/dev" / ACCOUNT / "quicksight.properties",
    )
    resource = m.Resource(
        model,
        "001",
        {"resourceType": kind, "logicalId": "QuickSight_DataSource_001"},
        rows,
    )
    with patch.object(
        ctx, "call", return_value={"DataSource": {"Type": "ATHENA"}, "Permissions": []}
    ) as call:
        if works:
            result = resource.module.fetch(ctx, resource, getter)
            check(
                result.get("Type") == "ATHENA"
                if getter == "base"
                else result["Permissions"] == [],
                "response retained",
            )
            check(
                bool(accounts) or "AwsAccountId" not in result,
                "omitted account is not response data",
            )
            call.assert_called_once_with(
                "quicksight",
                "describe_data_source"
                if getter == "base"
                else "describe_data_source_permissions",
                AwsAccountId=ACCOUNT,
                DataSourceId="fixture",
            )
        else:
            with pytest.raises(m.Unresolved):
                resource.module.fetch(ctx, resource, getter)
            call.assert_not_called()


def test_quicksight_other_getters_unchanged(tmp_path):
    ctx = SchemaOffline(tmp_path)
    ctx.verified = True
    module = m.service_module("quicksight")
    resource = Mock()
    resource.kind = "QuickSight.VPCConnection"
    resource.value.side_effect = lambda prop: {
        "AwsAccountId": ACCOUNT,
        "VPCConnectionId": "vpc-id",
        "Namespace": "default",
        "GroupName": "readers",
    }[prop]
    with patch.object(
        ctx, "call", return_value={"VPCConnection": {"Name": "vpc"}}
    ) as call:
        module.fetch(ctx, resource, "vpc")
        call.assert_called_once_with(
            "quicksight",
            "describe_vpc_connection",
            AwsAccountId=ACCOUNT,
            VPCConnectionId="vpc-id",
        )
    resource.kind = "QuickSight.DataSource"
    resource.rows_for.return_value = [object()]
    resource.value.side_effect = m.Unresolved("missing account")
    with patch.object(ctx, "call") as call:
        with pytest.raises(m.Unresolved):
            module.fetch(ctx, resource, "permissions")
        call.assert_not_called()
    resource.kind = "QuickSight.Group"
    resource.value.side_effect = lambda prop: {
        "AwsAccountId": ACCOUNT,
        "Namespace": "default",
        "GroupName": "readers",
    }[prop]
    with patch.object(ctx, "call", return_value={"Group": {}}) as call:
        module.fetch_sdk(ctx, resource, "describe_group")
        call.assert_called_once_with(
            "quicksight",
            "describe_group",
            AwsAccountId=ACCOUNT,
            Namespace="default",
            GroupName="readers",
        )
