#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

import design.policy_tables as _imports_policy_tables
import support.policy_tables_fixtures as _retained_fixture_policy_mapping_cache
from design.layout import expanded_design
from design.policy_tables import Policy, policy_document_lines, validate_policy_document
from support import design_layout_fixtures as layout_fixture
from support.policy_tables_fixtures import (
    ALIGNMENT,
    END,
    HEADER,
    SCRIPTS,
    START,
    VALIDATOR,
    Path,
    iam_fixture,
    iam_role_policy_artifact_filename,
    indexed_rows,
    json,
    mapping_cache_checks,
    model_projection,
    policy_cli,
    policy_lines,
    pytest,
    rendered_design,
    resources_in,
    run,
    sys,
    tempfile,
    without_policy_tables,
)
from support.policy_tables_fixtures import pytestmark as pytestmark
from support.validator import diagnostics
from utils.cloudformation.schema import CloudFormationSchemaCatalog

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

policy_mapping_cache = _retained_fixture_policy_mapping_cache.policy_mapping_cache


@pytest.mark.parametrize(
    ("logical_id", "role_id"),
    [
        ("cde-stg-example-role", "stg-example-role"),
        ("CDEIFINBOUNDGLUEROLE01", "ifinboundgluerole01"),
        ("cdemwaaexecutionrole01", "mwaaexecutionrole01"),
        ("RoleA", "role-a"),
        ("non-cde-role", "non-cde-role"),
        ("VPCFlowLogsToCloudWatchLogs", "vpc-flow-logs-to-cloud-watch-logs"),
    ],
)
def check_iam_artifact_names(logical_id, role_id):
    assert (
        iam_role_policy_artifact_filename(logical_id) == f"{role_id}-trust-policy.json"
    )
    assert (
        iam_role_policy_artifact_filename(logical_id, "CDEAccess")
        == f"{role_id}-cde-access.json"
    )


@pytest.mark.parametrize(
    "property_name", ["KMS.Key.KeyPolicy", "S3.BucketPolicy.PolicyDocument"]
)
@pytest.mark.parametrize("version", ["2012-10-17", "2008-10-17"])
def check_statement_metadata(property_name, version):
    document = {
        "Id": "key-default",
        "Version": version,
        "Statement": [
            {"Effect": "Allow", "Action": "kms:DescribeKey", "Resource": "*"}
        ],
    }
    original = json.dumps(document)
    policy = Policy("ResourcePolicy", "Policy", "policy.json", "policy", property_name)
    rendered = "\n".join(policy_document_lines(document, policy))
    assert "| Id |" not in rendered and "| Version |" not in rendered
    assert "| No. | Effect | Action | Resource |" in rendered
    assert "`kms:DescribeKey`" in rendered
    assert json.dumps(document) == original


def check_lossless_generation():
    policy = Policy(
        "ResourcePolicy",
        "Policy",
        "policy.json",
        "policy",
        "Logs.ResourcePolicy.PolicyDocument",
    )
    document = {
        "PolicyDocument": {"Statement": [{"Effect": "Unknown", "Extra": {"keep": 1}}]}
    }
    rendered = "\n".join(policy_document_lines(document, policy))
    assert json.dumps(document, ensure_ascii=False, indent=2) in rendered
    with pytest.raises(ValueError):
        validate_policy_document(document, policy)


@pytest.mark.parametrize("key", ["Resource", "NotResource"])
@pytest.mark.parametrize(
    "value", [{"unexpected": "*"}, [{"unexpected": "*"}], ["*", 1], None, 3, True]
)
def check_resource_types(key, value):
    policy = Policy(
        "test", "policy.json", "test", "policy", "IAM.ManagedPolicy.PolicyDocument"
    )
    with pytest.raises(ValueError, match=key + " must be a string or string array"):
        validate_policy_document(
            {"Statement": [{"Effect": "Allow", "Action": "*", key: value}]}, policy
        )


@pytest.mark.parametrize("key", ["Resource", "NotResource"])
@pytest.mark.parametrize("value", ["*", ["arn:aws:s3:::bucket/${aws:username}", "*"]])
def check_valid_resource_types(key, value):
    policy = Policy(
        "test", "policy.json", "test", "policy", "IAM.ManagedPolicy.PolicyDocument"
    )
    document = {
        "Statement": {
            "Effect": "Allow",
            "NotAction": ["s3:DeleteObject"],
            key: value,
            "Principal": {"AWS": ["111111111111"]},
            "Condition": {"StringEquals": {"aws:username": "${aws:username}"}},
        }
    }
    validate_policy_document(document, policy)


def _callback_check_iam_errors(path, root, /, content):
    path.write_text(content, encoding="utf-8")
    validator = VALIDATOR.Validator(root)
    validator.accounts = {("dev", "123456789012"): {}}
    validator.check_policy_tables()
    validator.check_design_overviews()
    validator.check_design_links({})
    catalog_types, owners, outputs = VALIDATOR.Validator(
        SCRIPTS.parents[1]
    ).catalog_design_properties()
    validator.check_design_tables(
        {path: ("iam", ("IAM.Role", "IAM.InstanceProfile"))},
        catalog_types,
        owners,
        outputs,
    )
    validator.check_design_artifacts()
    return diagnostics(validator)


def check_iam(tmp_path):
    path, artifacts, trust, inline, text = iam_fixture(tmp_path)
    root = tmp_path
    baseline_model = expanded_design(
        without_policy_tables(path.read_text(encoding="utf-8").splitlines())
    )[0]
    rendered = rendered_design(path)
    path.write_text(rendered, encoding="utf-8")
    assert rendered_design(path) == rendered, "generation must be idempotent"
    assert (
        expanded_design(
            without_policy_tables(path.read_text(encoding="utf-8").splitlines())
        )[0]
        == baseline_model
    ), "views must not alter the model"
    assert not any("ポリシー：" in line for line in baseline_model)
    assert rendered.count("| Version |\n| --- |\n| `2012-10-17` |") == 2
    assert rendered.count(START) == 2
    assert rendered.count("\n#### ") == 6
    assert rendered.count("\n## リソース詳細\n") == 1
    assert "[RoleA](#iam-rolea)" in rendered
    assert (
        "Flow Logsに使用するRole" in rendered and "追加ログを記録するRole" in rendered
    )
    assert (
        'id="iam-rolea-inline-logging"' in rendered
        and 'id="iam-roleb-inline-logging"' in rendered
    )
    assert (
        "| No. | Sid | Effect | Action | NotAction | Resource | NotResource |"
        in rendered
    )
    assert "`logs:CreateLogStream`<br>`logs:PutLogEvents`" in rendered
    condition_row = next(
        line for line in rendered.splitlines() if line.startswith("| 1 | Allow |")
    )
    assert "aws:SourceAccount" in condition_row and "aws:SourceArn" in condition_row

    errors = _bind_framework_callback(_callback_check_iam_errors, path, root)

    assert not errors(rendered), errors(rendered)
    for metadata in ("Property：", "JSON：", "Version：", "Id："):
        assert metadata not in rendered
        assert errors(
            rendered.replace(START, START + "\n\n" + metadata + "`legacy`", 1)
        )
    assert errors(rendered.replace("| `2012-10-17` |", "| `2008-10-17` |", 1)), (
        "wrong trust Version must fail"
    )
    assert errors(text), "missing views must fail"
    assert errors(rendered.replace("[RoleA](#iam-rolea)", "[Wrong](#iam-rolea)"))
    assert errors(
        rendered.replace('id="iam-roleb-inline-extra"', 'id="iam-rolea-inline-extra"')
    )
    assert errors(
        rendered.replace(
            "`logs:CreateLogStream`<br>`logs:PutLogEvents`", "`logs:CreateLogStream`", 1
        )
    )
    assert errors(rendered.replace(START, "", 1))
    assert errors(rendered.replace(END, "", 1))
    assert errors(rendered.replace("### IAM.Role: RoleB", "### IAM.Role: RoleA"))

    # Generated one-based rows retain both inline policies for every Role.
    indexed_lines = text.splitlines()
    for resource in reversed(resources_in(indexed_lines)):
        start = resource.table_end
        while indexed_lines[start - 1].startswith("|") and indexed_lines[
            start - 1
        ] not in {HEADER, ALIGNMENT}:
            start -= 1
        rows = [
            [cell.strip() for cell in line.strip("|").split("|")]
            for line in indexed_lines[start : resource.table_end]
        ]
        shown = indexed_rows(rows, resource.resource_type)
        indexed_lines[start : resource.table_end] = [
            "| " + " | ".join(row) + " |" for row in shown
        ]
    indexed = "\n".join(indexed_lines) + "\n"
    assert (
        "Policies[1].PolicyDocument" in indexed
        and "Policies[2].PolicyDocument" in indexed
    )
    path.write_text(indexed, encoding="utf-8")
    indexed_rendered = rendered_design(path)
    assert indexed_rendered.count("#### インラインポリシー：Logging") == 2
    assert indexed_rendered.count("#### インラインポリシー：Extra") == 2
    assert indexed_rendered.count("\n#### ") == 6
    assert (
        "\n".join(without_policy_tables(indexed_rendered.splitlines())) + "\n"
        == indexed
    )
    assert not errors(indexed_rendered), errors(indexed_rendered)
    assert rendered_design(path) == indexed_rendered, (
        "indexed policy generation must be idempotent"
    )
    assert (
        expanded_design(
            without_policy_tables(path.read_text(encoding="utf-8").splitlines())
        )[0]
        == baseline_model
    ), "array display and policy views must preserve the model"
    path.write_text(rendered, encoding="utf-8")

    # JSON changes affect the existing hash and must invalidate the derived view.
    artifact = artifacts / "role-a-trust-policy.json"
    original_digest = model_projection.json_sha256(artifact)
    changed = json.loads(json.dumps(trust))
    changed["Statement"][0]["Condition"]["StringEquals"]["aws:SourceAccount"] = (
        "222222222222"
    )
    artifact.write_text(json.dumps(changed), encoding="utf-8")
    assert errors(rendered)
    assert model_projection.json_sha256(artifact) != original_digest
    artifact.write_text(json.dumps(trust, indent=4, sort_keys=True), encoding="utf-8")
    assert not errors(rendered), (
        "JSON formatting and object key order must not change views"
    )
    assert (
        expanded_design(
            without_policy_tables(path.read_text(encoding="utf-8").splitlines())
        )[0]
        == baseline_model
    )

    # A single Statement object, different principals, array conditions and escaping.
    special = {
        "Statement": {
            "Effect": "Deny",
            "NotPrincipal": {
                "AWS": ["arn:aws:iam::123456789012:root"],
                "Federated": "example",
            },
            "NotAction": "s3:*",
            "Resource": "*",
            "Condition": {"StringEquals": {"key": ["a|b", "<value>", "`value`"]}},
        }
    }
    artifact.write_text(json.dumps(special), encoding="utf-8")
    role = resources_in(without_policy_tables(rendered.splitlines()))[0]
    special_view = "\n".join(policy_lines(path, role.policies[0]))
    assert (
        "NotPrincipal.AWS" in special_view and "NotPrincipal.Federated" in special_view
    )
    assert "&#124;" in special_view and "&lt;value&gt;" in special_view
    assert "| Version |" not in special_view, "do not invent an absent Version table"
    assert "Version：" not in special_view, "do not invent absent Version"
    artifact.write_text(json.dumps({**trust, "Unknown": True}), encoding="utf-8")
    assert errors(rendered), "unknown policy elements must never be omitted"
    artifact.write_text(
        '{"Statement":{"Effect":"Allow","Effect":"Deny"}}', encoding="utf-8"
    )
    assert errors(rendered), "duplicate JSON keys must not be silently discarded"
    artifact.write_text(json.dumps({"Statement": [{"Effect": []}]}), encoding="utf-8")
    assert errors(rendered), "malformed Effect must report a validation error"
    artifact.write_text(json.dumps(trust), encoding="utf-8")
    assert errors(rendered.replace(START, START + "\n" + START, 1))
    assert errors(
        rendered.replace("iam/role-a-trust-policy.json", "../role-a-trust-policy.json")
    )

    # The 16-character limit belongs only to inline Statement.Sid.
    inline_artifact = artifacts / "role-a-logging.json"
    role = resources_in(without_policy_tables(rendered.splitlines()))[0]
    for sid, valid in (("S" * 16, True), ("S" * 17, False), (17, False)):
        document = json.loads(json.dumps(inline))
        document["Statement"][0]["Sid"] = sid
        inline_artifact.write_text(json.dumps(document), encoding="utf-8")
        try:
            view = "\n".join(policy_lines(path, role.policies[1]))
        except ValueError as error:
            assert not valid and "Sid must be a string of at most 16 characters" in str(
                error
            )
        else:
            assert valid and "S" * 16 in view
        assert json.loads(inline_artifact.read_text(encoding="utf-8")) == document
    assert any("Sid must be" in error for error in errors(rendered))
    inline_artifact.write_text(json.dumps(inline), encoding="utf-8")
    trust_with_sid = json.loads(json.dumps(trust))
    trust_with_sid["Statement"][0]["Sid"] = "T" * 17
    artifact.write_text(json.dumps(trust_with_sid), encoding="utf-8")
    assert "T" * 17 in "\n".join(policy_lines(path, role.policies[0]))
    artifact.write_text(json.dumps(trust), encoding="utf-8")

    # The policy-only renderer does not invent omitted Role settings.
    minimal = text[: text.index('<a id="iam-roleb"')]
    minimal = (
        "\n".join(
            line
            for line in minimal.splitlines()
            if not any(prop in line for prop in ("| RoleName |", "| Policies[]"))
        )
        + "\n"
    )
    path.write_text(minimal, encoding="utf-8")
    view = rendered_design(path)
    assert "[RoleA](#iam-rolea)" in view
    assert "#### インラインポリシー" not in view
    other_service = "# 他サービスの設計\n\n実装注記を維持する。\n"
    path.write_text(other_service, encoding="utf-8")
    assert rendered_design(path) == other_service
    print("IAM policy tables checks: PASS (generation, validation, model, CLI)")


def _callback_service_policy_checks_errors(path, root, /, content):
    path.write_text(content, encoding="utf-8")
    validator = VALIDATOR.Validator(root)
    validator.check_policy_tables()
    validator.check_design_overviews()
    validator.check_design_links({})
    return diagnostics(validator)


def check_service_policy_checks():
    END = _imports_policy_tables.END
    POLICY_FORMATS = _imports_policy_tables.POLICY_FORMATS
    START = _imports_policy_tables.START

    repository = SCRIPTS.parents[1]
    schema = CloudFormationSchemaCatalog(repository)
    assert POLICY_FORMATS["IAM.User.Policies[].PolicyDocument"] == "statement"
    candidates = {"Organizations.Policy.Content"}
    for catalog in (repository / "framework/materials/aws").glob("*.properties"):
        resource_type = catalog.stem.replace("_", ".", 1)
        for line in catalog.read_text(encoding="utf-8").splitlines():
            prop = line.partition("=")[0]
            # Discover omissions for review; never infer their rendering mode.
            if "Policy" in prop.split(".")[-1] and "object" in schema.property_schema(
                resource_type, prop[len(resource_type) + 1 :]
            ).get("type", []):
                candidates.add(prop)
    assert len(POLICY_FORMATS) == 31
    assert candidates == set(POLICY_FORMATS), (
        "catalog policy documents need an explicit display decision"
    )
    statement = {
        "Version": "2012-10-17",
        "Id": "access-policy",
        "Statement": [
            {
                "Sid": "AllowRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:GetObject"],
                "Resource": ["arn:aws:s3:::example/*"],
            },
            {
                "Effect": "Deny",
                "NotPrincipal": {"AWS": ["arn:aws:iam::123456789012:root"]},
                "NotAction": "s3:GetObject",
                "NotResource": "arn:aws:s3:::other/*",
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            },
        ],
    }
    settings = {
        "Version": "2026-09-12",
        "Id": "settings-id",
        "Statement": [{"Operation": {"Audit": {}}, "DataIdentifier": ["example"]}],
        "filter": {"a/b~c": [False, None, 3, "a|<b>", {}, [], ""]},
    }
    for prop, style in POLICY_FORMATS.items():
        resource_type = ".".join(prop.split(".")[:2])
        catalog = (
            repository
            / "framework/materials/aws"
            / (resource_type.replace(".", "_") + ".properties")
        )
        assert prop in {
            line.partition("=")[0]
            for line in catalog.read_text(encoding="utf-8").splitlines()
        }
        node = schema.property_schema(resource_type, prop[len(resource_type) + 1 :])
        assert "object" in node["type"], (prop, node)
        assert VALIDATOR.Validator.is_policy_document_property(prop)
        if resource_type == "IAM.Role":
            continue  # The IAM regression above covers its exact existing output.
        if style == "wrapped-statement":
            document = {"PolicyDocument": statement}
        elif prop == "ECR.Repository.LifecyclePolicy":
            document = {
                "RegistryId": "123456789012",
                "LifecyclePolicyText": json.dumps(
                    {
                        "rules": [
                            {
                                "rulePriority": 1,
                                "selection": {
                                    "tagStatus": "untagged",
                                    "countNumber": 10,
                                },
                                "action": {"type": "expire"},
                            }
                        ]
                    }
                ),
            }
        else:
            document = settings if style == "settings" else statement
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            # S3 keeps the policy row inside its bucket, without a new resource.
            owner_type = (
                "S3.Bucket" if resource_type == "S3.BucketPolicy" else resource_type
            )
            service = {"EC2": "vpc", "SecretsManager": "secrets-manager"}.get(
                owner_type.split(".")[0], owner_type.split(".")[0].lower()
            )
            path = root / f"docs/designs/dev/123456789012/{service}.md"
            artifacts = path.with_suffix("")
            artifacts.mkdir(parents=True)
            artifact = artifacts / "access.json"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            types = list(dict.fromkeys([owner_type, resource_type]))
            metadata = ", ".join(f"`{rt}`" for rt in types)
            summary = f"| No. | ResourceName | Comment |\n| ---: | --- | --- |\n| 1 | [sample-a](#{service}-sample-a) | 一つ目のresource |\n| 2 | [sample-b](#{service}-sample-b) | 二つ目のresource |"
            original = f"# ポリシー設計\n\n- Design service ID: `{service}`\n- Owned catalog resource types: {metadata}\n\n## リソース一覧\n\n### {owner_type}\n\n{summary}\n\n## リソース詳細\n\n"
            for name in ("sample-a", "sample-b"):
                original += f'<a id="{service}-{name}"></a>\n\n### {owner_type}: {name}\n\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n'
                rows = []
                if owner_type == "S3.Bucket":
                    rows = [
                        ("S3.Bucket.BucketName", f"`{name}`"),
                        ("S3.Bucket.Region", "`us-east-1`"),
                    ]
                if prop == "IAM.User.Policies[].PolicyDocument":
                    rows.append(("IAM.User.Policies[].PolicyName", "`Access`"))
                rows.append((prop, f"[Access]({service}/access.json)"))
                for number, (key, value) in enumerate(rows, 1):
                    original += f"| {number} | {key} | {value} | 設定の値 |\n"
                original += "\n実装注記を維持する。\n\n"
            path.write_text(original, encoding="utf-8")
            baseline_model = expanded_design(
                without_policy_tables(path.read_text(encoding="utf-8").splitlines())
            )[0]
            rendered = rendered_design(path)
            path.write_text(rendered, encoding="utf-8")
            assert rendered_design(path) == rendered, prop
            assert (
                expanded_design(
                    without_policy_tables(path.read_text(encoding="utf-8").splitlines())
                )[0]
                == baseline_model
            ), prop
            assert rendered.count(START) == 2 and rendered.count(END) == 2
            suffix = (
                "inline-access"
                if prop == "IAM.User.Policies[].PolicyDocument"
                else "policy-access"
            )
            assert (
                f'id="{service}-sample-a-{suffix}"' in rendered
                and f'id="{service}-sample-b-{suffix}"' in rendered
            )
            for duplicate in ("Property：", "JSON：", "Version：", "Id："):
                assert duplicate not in rendered, (prop, duplicate)
            assert rendered.count("実装注記を維持する。") == 2
            assert "| No. | ResourceName | Comment |" in rendered
            assert "| Policies |" not in rendered
            if style == "settings":
                assert (
                    "| Property | Type | Value |" in rendered
                    and "| No. | Sid |" not in rendered
                )
                if prop == "ECR.Repository.LifecyclePolicy":
                    assert "LifecyclePolicyTextの内容：" in rendered
                    assert (
                        "`/rules/0/selection/countNumber` | number | `10`" in rendered
                    )
                else:
                    assert "`/Version` | string | `2026-09-12`" in rendered
                    assert "`/Id` | string | `settings-id`" in rendered
                    assert "`/filter/a~1b~0c/0` | boolean | `false`" in rendered
                    assert "`/filter/a~1b~0c/1` | null | `null`" in rendered
                    assert (
                        "| object | `{}` |" in rendered
                        and "| array | `[]` |" in rendered
                    )
                    assert "&#124;" in rendered and "&lt;b&gt;" in rendered
            else:
                assert (
                    "| No. | Sid | Effect | Principal | NotPrincipal.AWS | Action | NotAction | Resource | NotResource | Condition |"
                    in rendered
                )
                if prop == "IAM.User.Policies[].PolicyDocument":
                    assert "#### インラインポリシー：Access" in rendered

            errors = _bind_framework_callback(
                _callback_service_policy_checks_errors, path, root
            )

            assert not errors(rendered), (prop, errors(rendered))
            assert errors(original), "missing views must fail"
            assert errors(rendered.replace(START, "", 1)), "missing marker must fail"
            assert errors(rendered.replace(END, "<!-- iam-policy-tables:end -->", 1)), (
                "mixed markers must fail"
            )
            assert errors(
                rendered.replace(
                    f'id="{service}-sample-b-{suffix}"',
                    f'id="{service}-sample-a-{suffix}"',
                    1,
                )
            ), "duplicate policy anchor must fail"
            for metadata in (
                f"Property：`{prop}`",
                f"JSON：[Access]({service}/access.json)",
                "Version：`2012-10-17`",
                "Id：`access-policy`",
            ):
                assert errors(rendered.replace(START, START + "\n\n" + metadata, 1)), (
                    prop,
                    metadata,
                )
            assert errors(rendered.replace(START, START + "\n" + START, 1)), (
                "nested markers must fail"
            )
            # Same resource cannot silently collapse repeated policy documents.
            row = next(
                line for line in original.splitlines() if f" | {prop} | " in line
            )
            assert errors(original.replace(row, row + "\n" + row, 1)), (
                "duplicate policy anchor must fail"
            )
            path.write_text(rendered, encoding="utf-8")
            artifact.write_text(
                json.dumps(document, sort_keys=True, indent=4), encoding="utf-8"
            )
            assert rendered_design(path) == rendered, (
                "object order must not affect the view"
            )
            assert (
                expanded_design(
                    without_policy_tables(path.read_text(encoding="utf-8").splitlines())
                )[0]
                == baseline_model
            )
            artifact.write_text('{"Statement":{},"Statement":{}}', encoding="utf-8")
            assert errors(rendered), "duplicate JSON keys must fail in every format"
            artifact.write_text('{"value":NaN}', encoding="utf-8")
            assert errors(rendered), "non-JSON constants must fail"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            path.write_text(original, encoding="utf-8")
            write = policy_cli([str(path), "--write"])
            assert (
                write.returncode == 0 and path.read_text(encoding="utf-8") == rendered
            ), write.stderr
            assert json.loads(artifact.read_text(encoding="utf-8")) == document, (
                "generation must not modify policy JSON"
            )

    # Scalar policies and names remain ordinary catalog property rows.
    for prop in (
        "ApiGateway.RestApi.SecurityPolicy",
        "ElasticLoadBalancingV2.Listener.SslPolicy",
        "NetworkFirewall.FirewallPolicy.FirewallPolicy.StatefulEngineOptions.StreamExceptionPolicy",
        "S3.Bucket.PublicAccessBlockConfiguration.BlockPublicPolicy",
        "SSO.PermissionSet.ManagedPolicies",
    ):
        assert not VALIDATOR.Validator.is_policy_document_property(prop), prop
    print(
        f"Service policy tables checks: PASS ({len(POLICY_FORMATS)} registered properties, schema, generation, validation, model, CLI)"
    )


def check_grouping_and_settings_checks():
    mapping_cache_checks()
    START = _imports_policy_tables.START
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        path = root / "docs/designs/dev/123456789012/kms.md"
        artifacts = path.with_suffix("")
        artifacts.mkdir(parents=True)
        artifact = artifacts / "access.json"
        document = {
            "Statement": {
                "Effect": "Allow",
                "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
                "Action": "kms:*",
                "Resource": "*",
            }
        }
        artifact.write_text(json.dumps(document), encoding="utf-8")
        original = layout_fixture.KMS.replace(
            "| 4 | KMS.Alias.AliasName", "| 5 | KMS.Alias.AliasName"
        ).replace(
            "| 3 | KMS.Alias.AliasName",
            "| 3 | KeyPolicy | [Access](kms/access.json) | アクセス権限 |\n| 4 | KMS.Alias.AliasName",
        )
        path.write_text(original, encoding="utf-8")
        baseline_model = expanded_design(
            without_policy_tables(path.read_text(encoding="utf-8").splitlines())
        )[0]
        rendered = rendered_design(path)
        path.write_text(rendered, encoding="utf-8")
        assert rendered_design(path) == rendered
        assert (
            expanded_design(
                without_policy_tables(path.read_text(encoding="utf-8").splitlines())
            )[0]
            == baseline_model
        )
        assert rendered.count(START) == 1
        assert "| 2 | [KeyTwo](#kms-keytwo) | データの暗号化に使うkey |" in rendered
        validator = VALIDATOR.Validator(root)
        validator.accounts = {("dev", "123456789012"): {}}
        validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(SCRIPTS.parents[1])
        validator.check_policy_tables()
        validator.check_design_overviews()
        validator.check_design_tables(
            {path: ("kms", ("KMS.Key", "KMS.Alias"))},
            *VALIDATOR.Validator(SCRIPTS.parents[1]).catalog_design_properties(),
        )
        validator.check_design_links({})
        validator.check_design_artifacts()
        assert not validator.errors, validator.errors
        # Removing a selected policy removes only its derived view.
        removed = rendered.replace(
            "| 3 | KeyPolicy | [Access](kms/access.json) | アクセス権限 |\n", ""
        )
        path.write_text(removed, encoding="utf-8")
        assert "Policies" not in rendered_design(path) and START not in rendered_design(
            path
        )
        assert "logical-id: AliasTwo" in rendered_design(path)

        # Multiple policy formats in one owner, including a nested JSON string.
        path = path.with_name("ecr.md")
        artifacts = path.with_suffix("")
        artifacts.mkdir()
        (artifacts / "access.json").write_text(json.dumps(document), encoding="utf-8")
        lifecycle = artifacts / "lifecycle.json"
        lifecycle.write_text(
            json.dumps({"LifecyclePolicyText": '{"rules":[]}'}), encoding="utf-8"
        )
        original = """# ECR設計書

- Design service ID: `ecr`
- Owned catalog resource types: `ECR.Repository`

## リソース一覧

### ECR.Repository

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [Example](#ecr-example) | コンテナimageを保管するrepository |

## リソース詳細

<a id="ecr-example"></a>

### ECR.Repository: Example

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RepositoryName | `example` | リポジトリの名前 |
| 2 | RepositoryPolicyText | [Policy](ecr/access.json) | アクセス権限 |
| 3 | LifecyclePolicy | [Policy](ecr/lifecycle.json) | 保持するイメージの条件 |
"""
        path.write_text(original, encoding="utf-8")
        baseline_model = expanded_design(
            without_policy_tables(path.read_text(encoding="utf-8").splitlines())
        )[0]
        rendered = rendered_design(path)
        path.write_text(rendered, encoding="utf-8")
        assert rendered_design(path) == rendered
        assert (
            expanded_design(
                without_policy_tables(path.read_text(encoding="utf-8").splitlines())
            )[0]
            == baseline_model
        )
        assert (
            'id="ecr-example-policy-access"' in rendered
            and 'id="ecr-example-policy-lifecycle"' in rendered
        )
        validator = VALIDATOR.Validator(root)
        validator.check_design_overviews()
        assert not validator.errors, validator.errors
        for malformed in (
            {"LifecyclePolicyText": {}},
            {"LifecyclePolicyText": "not-json"},
            {"LifecyclePolicyText": "[]"},
            {"LifecyclePolicyText": '{"rules":[],"rules":[]}'},
        ):
            lifecycle.write_text(json.dumps(malformed), encoding="utf-8")
            with pytest.raises(ValueError):
                rendered_design(path)
    print(
        "Policy grouping/settings checks: PASS (KMS aliases, absent policy, multiple formats, nested JSON)"
    )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
