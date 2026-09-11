#!/usr/bin/env python3
"""Check service policy views, IAM regression and the unchanged model contract."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from policy_tables import IAM_END as END, IAM_START as START, policy_lines, rendered_design, resources_in, without_policy_tables

SCRIPTS = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load("validate-blueprint")
MODEL = load("sync-model")


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        path = root / "docs/designs/dev/123456789012/iam.md"
        path.parent.mkdir(parents=True)
        artifacts = path.parent / "iam"
        artifacts.mkdir()
        trust = {"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": {"Service": "vpc-flow-logs.amazonaws.com"},
            "Action": "sts:AssumeRole", "Condition": {
                "StringEquals": {"aws:SourceAccount": "123456789012"},
                "ArnLike": {"aws:SourceArn": "arn:aws:ec2:ap-northeast-1:123456789012:vpc-flow-log/*"},
            },
        }]}
        inline = {"Version": "2012-10-17", "Id": "Logging", "Statement": [
            {"Sid": "Write", "Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": ["arn:aws:logs:*:123456789012:log-group:example:*"]},
            {"Effect": "Deny", "NotAction": ["logs:DescribeLogGroups"], "NotResource": "arn:aws:logs:*:123456789012:log-group:other:*"},
        ]}
        text = """# IAM設計書

- Design service ID: `iam`
- Owned catalog resource types: `IAM.Role`, `IAM.InstanceProfile`

## リソース一覧

### IAM.Role

| RoleName | 信頼ポリシー | インラインポリシー |
| --- | --- | --- |

### IAM.InstanceProfile

| LogicalId | InstanceProfileName |
| --- | --- |
| [Profile](#iam-profile) | `example` |

## リソース詳細

"""
        for logical_id in ("RoleA", "RoleB"):
            file_id = VALIDATOR.artifact_id(logical_id)
            for suffix, document in (("trust-policy", trust), ("logging", inline), ("extra", inline)):
                (artifacts / f"{file_id}-{suffix}.json").write_text(json.dumps(document), encoding="utf-8")
            text += f'''<a id="iam-{logical_id.lower()}"></a>

### IAM.Role: {logical_id}

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | IAM.Role.RoleName | `role-{logical_id.lower()}` | ロールの名前 |
| 2 | IAM.Role.AssumeRolePolicyDocument | [FlowLogsTrust](iam/{file_id}-trust-policy.json) | 信頼ポリシー |
| 3 | IAM.Role.Policies[].PolicyName | `Logging` | ポリシーの名前 |
| 4 | IAM.Role.Policies[].PolicyDocument | [Logging](iam/{file_id}-logging.json) | 権限ポリシー |
| 5 | IAM.Role.Policies[].PolicyName | `Extra` | ポリシーの名前 |
| 6 | IAM.Role.Policies[].PolicyDocument | [Extra](iam/{file_id}-extra.json) | 追加の権限ポリシー |

'''
        text += '''<a id="iam-profile"></a>

### IAM.InstanceProfile: Profile

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | IAM.InstanceProfile.InstanceProfileName | `example` | インスタンスプロファイルの名前 |
'''
        path.write_text(text, encoding="utf-8")
        baseline_model = MODEL.model_for(path)
        rendered = rendered_design(path)
        path.write_text(rendered, encoding="utf-8")
        assert rendered_design(path) == rendered, "generation must be idempotent"
        assert MODEL.model_for(path) == baseline_model, "views must not alter the model"
        assert "desired.note." not in baseline_model
        assert rendered.count(START) == 2
        assert rendered.count("\n#### ") == 6
        assert rendered.count("\n## リソース詳細\n") == 1
        assert "[role-rolea](#iam-rolea)" in rendered
        assert "#iam-rolea-inline-logging" in rendered and "#iam-roleb-inline-logging" in rendered
        assert "| Statement | Sid | Effect | Action | NotAction | Resource | NotResource |" in rendered
        assert "`logs:CreateLogStream`<br>`logs:PutLogEvents`" in rendered
        condition_row = next(line for line in rendered.splitlines() if line.startswith("| 1 | Allow |"))
        assert "aws:SourceAccount" in condition_row and "aws:SourceArn" in condition_row

        def errors(content):
            path.write_text(content, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.accounts = {("dev", "123456789012"): {}}
            validator.check_policy_tables()
            validator.check_design_overviews()
            validator.check_design_links({})
            catalog_types, owners, outputs = VALIDATOR.Validator(SCRIPTS.parents[1]).catalog_design_properties()
            validator.check_design_tables({path: ("iam", ("IAM.Role", "IAM.InstanceProfile"))}, catalog_types, owners, outputs)
            validator.check_design_artifacts()
            return validator.errors

        assert not errors(rendered), errors(rendered)
        assert errors(text), "missing views must fail"
        assert errors(rendered.replace("[role-rolea](#iam-rolea)", "[Wrong](#iam-rolea)"))
        assert errors(rendered.replace("[Extra](#iam-roleb-inline-extra)", "[Extra](#iam-rolea-inline-extra)"))
        assert errors(rendered.replace("`logs:CreateLogStream`<br>`logs:PutLogEvents`", "`logs:CreateLogStream`", 1))
        assert errors(rendered.replace(START, "", 1))
        assert errors(rendered.replace(END, "", 1))
        assert errors(rendered.replace("### IAM.Role: RoleB", "### IAM.Role: RoleA"))
        path.write_text(rendered, encoding="utf-8")

        # JSON changes affect the existing hash and must invalidate the derived view.
        artifact = artifacts / "role-a-trust-policy.json"
        changed = json.loads(json.dumps(trust))
        changed["Statement"][0]["Condition"]["StringEquals"]["aws:SourceAccount"] = "222222222222"
        artifact.write_text(json.dumps(changed), encoding="utf-8")
        assert errors(rendered)
        assert MODEL.model_for(path) != baseline_model
        artifact.write_text(json.dumps(trust, indent=4, sort_keys=True), encoding="utf-8")
        assert not errors(rendered), "JSON formatting and object key order must not change views"
        assert MODEL.model_for(path) == baseline_model

        # A single Statement object, different principals, array conditions and escaping.
        special = {"Statement": {"Effect": "Deny", "NotPrincipal": {"AWS": ["arn:aws:iam::123456789012:root"], "Federated": "example"},
            "NotAction": "s3:*", "Resource": "*", "Condition": {"StringEquals": {"key": ["a|b", "<value>", "`value`"]}}}}
        artifact.write_text(json.dumps(special), encoding="utf-8")
        role = resources_in(without_policy_tables(rendered.splitlines()))[0]
        special_view = "\n".join(policy_lines(path, role.policies[0]))
        assert "NotPrincipal.AWS" in special_view and "NotPrincipal.Federated" in special_view
        assert "&#124;" in special_view and "&lt;value&gt;" in special_view
        assert "Version：" not in special_view, "do not invent absent Version"
        artifact.write_text(json.dumps({**trust, "Unknown": True}), encoding="utf-8")
        assert errors(rendered), "unknown policy elements must never be omitted"
        artifact.write_text('{"Statement":{"Effect":"Allow","Effect":"Deny"}}', encoding="utf-8")
        assert errors(rendered), "duplicate JSON keys must not be silently discarded"
        artifact.write_text(json.dumps({"Statement": [{"Effect": []}]}), encoding="utf-8")
        assert errors(rendered), "malformed Effect must report a validation error"
        artifact.write_text(json.dumps(trust), encoding="utf-8")
        assert errors(rendered.replace(START, START + "\n" + START, 1))
        assert errors(rendered.replace("iam/role-a-trust-policy.json", "../role-a-trust-policy.json"))

        # --write updates only derived Markdown and requires an explicit file.
        path.write_text(text, encoding="utf-8")
        check = subprocess.run([sys.executable, str(SCRIPTS / "policy_tables.py"), str(path)], capture_output=True)
        assert check.returncode == 1 and path.read_text(encoding="utf-8") == text
        write = subprocess.run([sys.executable, str(SCRIPTS / "policy_tables.py"), str(path), "--write"], capture_output=True)
        assert write.returncode == 0, write.stderr
        assert path.read_text(encoding="utf-8") == rendered

        # Optional RoleName and inline policies are not invented by the renderer.
        minimal = text[:text.index('<a id="iam-roleb"')]
        minimal = "\n".join(line for line in minimal.splitlines() if not any(prop in line for prop in ("IAM.Role.RoleName", "IAM.Role.Policies[]"))) + "\n"
        path.write_text(minimal, encoding="utf-8")
        view = rendered_design(path)
        assert "[（RoleName未指定）](#iam-rolea)" in view
        assert "#### インラインポリシー" not in view
        other_service = "# 他サービスの設計\n\n実装注記を維持する。\n"
        path.write_text(other_service, encoding="utf-8")
        assert rendered_design(path) == other_service
    print("IAM policy tables checks: PASS (generation, validation, model, CLI)")


def service_policy_checks():
    from cloudformation_schema import CloudFormationSchemaCatalog
    from policy_tables import POLICY_FORMATS, START, END

    repository = SCRIPTS.parents[1]
    schema = CloudFormationSchemaCatalog(repository)
    candidates = set()
    for catalog in (repository / "framework/materials/aws").glob("*.properties"):
        resource_type = catalog.stem.replace("_", ".", 1)
        for line in catalog.read_text().splitlines():
            prop = line.partition("=")[0]
            # Discover omissions for review; never infer their rendering mode.
            if "Policy" in prop.split(".")[-1] and "object" in schema.property_schema(resource_type, prop[len(resource_type) + 1:]).get("type", []):
                candidates.add(prop)
    assert candidates == set(POLICY_FORMATS), "catalog policy documents need an explicit display decision"
    statement = {"Version": "2012-10-17", "Statement": [
        {"Sid": "AllowRead", "Effect": "Allow", "Principal": "*", "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::example/*"]},
        {"Effect": "Deny", "NotPrincipal": {"AWS": ["arn:aws:iam::123456789012:root"]}, "NotAction": "s3:GetObject", "NotResource": "arn:aws:s3:::other/*", "Condition": {"Bool": {"aws:SecureTransport": "false"}}},
    ]}
    settings = {"Statement": [{"Operation": {"Audit": {}}, "DataIdentifier": ["example"]}], "filter": {"a/b~c": [False, None, 3, "a|<b>", {}, [], ""]}}
    for prop, style in POLICY_FORMATS.items():
        resource_type = ".".join(prop.split(".")[:2])
        catalog = repository / "framework/materials/aws" / (resource_type.replace(".", "_") + ".properties")
        assert prop in {line.partition("=")[0] for line in catalog.read_text().splitlines()}
        node = schema.property_schema(resource_type, prop[len(resource_type) + 1:])
        assert "object" in node["type"], (prop, node)
        assert VALIDATOR.Validator.is_policy_document_property(prop)
        if resource_type == "IAM.Role":
            continue  # The IAM regression above covers its exact existing output.
        if style == "wrapped-statement":
            document = {"PolicyDocument": statement}
        elif prop == "ECR.Repository.LifecyclePolicy":
            document = {"RegistryId": "123456789012", "LifecyclePolicyText": json.dumps({"rules": [{"rulePriority": 1, "selection": {"tagStatus": "untagged", "countNumber": 10}, "action": {"type": "expire"}}]})}
        else:
            document = settings if style == "settings" else statement
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            # S3 keeps the policy row inside its bucket, without a new resource.
            owner_type = "S3.Bucket" if resource_type == "S3.BucketPolicy" else resource_type
            service = {"EC2": "vpc", "SecretsManager": "secrets-manager"}.get(owner_type.split(".")[0], owner_type.split(".")[0].lower())
            path = root / f"docs/designs/dev/123456789012/{service}.md"
            artifacts = path.with_suffix("")
            artifacts.mkdir(parents=True)
            artifact = artifacts / "access.json"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            types = list(dict.fromkeys([owner_type, resource_type]))
            metadata = ", ".join(f"`{rt}`" for rt in types)
            original = f"# ポリシー設計\n\n- Design service ID: `{service}`\n- Owned catalog resource types: {metadata}\n\n## リソース一覧\n\n### {owner_type}\n\n| LogicalId | Label |\n| --- | --- |\n| [sample-a](#{service}-sample-a) | `一つ目` |\n| [sample-b](#{service}-sample-b) | `二つ目` |\n\n## リソース詳細\n\n"
            for name in ("sample-a", "sample-b"):
                original += f'<a id="{service}-{name}"></a>\n\n### {owner_type}: {name}\n\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n'
                rows = []
                if owner_type == "S3.Bucket":
                    rows = [("S3.Bucket.BucketName", f"`{name}`"), ("S3.Bucket.Region", "`us-east-1`")]
                rows.append((prop, f"[Access]({service}/access.json)"))
                for number, (key, value) in enumerate(rows, 1):
                    original += f"| {number} | {key} | {value} | 設定の値 |\n"
                original += "\n実装注記を維持する。\n\n"
            path.write_text(original, encoding="utf-8")
            baseline_model = MODEL.model_for(path)
            rendered = rendered_design(path)
            path.write_text(rendered, encoding="utf-8")
            assert rendered_design(path) == rendered, prop
            assert MODEL.model_for(path) == baseline_model, prop
            assert rendered.count(START) == 2 and rendered.count(END) == 2
            assert f"#{service}-sample-a-policy-access" in rendered and f"#{service}-sample-b-policy-access" in rendered
            assert f"Property：`{prop}`" in rendered
            assert rendered.count("実装注記を維持する。") == 2
            assert "| LogicalId | Label | Policies |" in rendered
            if style == "settings":
                assert "| Property | Type | Value |" in rendered and "| Statement |" not in rendered
                if prop == "ECR.Repository.LifecyclePolicy":
                    assert "LifecyclePolicyTextの内容：" in rendered
                    assert "`/rules/0/selection/countNumber` | number | `10`" in rendered
                else:
                    assert "`/filter/a~1b~0c/0` | boolean | `false`" in rendered
                    assert "`/filter/a~1b~0c/1` | null | `null`" in rendered
                    assert "| object | `{}` |" in rendered and "| array | `[]` |" in rendered
                    assert "&#124;" in rendered and "&lt;b&gt;" in rendered
            else:
                assert "| Statement | Sid | Effect | Principal | NotPrincipal.AWS | Action | NotAction | Resource | NotResource | Condition |" in rendered

            def errors(content):
                path.write_text(content, encoding="utf-8")
                validator = VALIDATOR.Validator(root)
                validator.check_policy_tables()
                validator.check_design_overviews()
                validator.check_design_links({})
                return validator.errors

            assert not errors(rendered), (prop, errors(rendered))
            assert errors(original), "missing views must fail"
            assert errors(rendered.replace(START, "", 1)), "missing marker must fail"
            assert errors(rendered.replace(END, "<!-- iam-policy-tables:end -->", 1)), "mixed markers must fail"
            assert errors(rendered.replace(f"[Access](#{service}-sample-b-policy-access)", f"[Access](#{service}-sample-a-policy-access)", 1)), "wrong owner link must fail"
            assert errors(rendered.replace(f"Property：`{prop}`", "Property：`Wrong`", 1)), "wrong source property must fail"
            assert errors(rendered.replace(START, START + "\n" + START, 1)), "nested markers must fail"
            # Same resource cannot silently collapse repeated policy documents.
            row = next(line for line in original.splitlines() if f" | {prop} | " in line)
            assert errors(original.replace(row, row + "\n" + row, 1)), "duplicate policy anchor must fail"
            path.write_text(rendered, encoding="utf-8")
            artifact.write_text(json.dumps(document, sort_keys=True, indent=4), encoding="utf-8")
            assert rendered_design(path) == rendered, "object order must not affect the view"
            assert MODEL.model_for(path) == baseline_model
            artifact.write_text('{"Statement":{},"Statement":{}}', encoding="utf-8")
            assert errors(rendered), "duplicate JSON keys must fail in every format"
            artifact.write_text('{"value":NaN}', encoding="utf-8")
            assert errors(rendered), "non-JSON constants must fail"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            path.write_text(original, encoding="utf-8")
            write = subprocess.run([sys.executable, str(SCRIPTS / "policy_tables.py"), str(path), "--write"], capture_output=True)
            assert write.returncode == 0 and path.read_text() == rendered, write.stderr
            assert json.loads(artifact.read_text()) == document, "generation must not modify policy JSON"

    # Scalar policies and names remain ordinary catalog property rows.
    for prop in ("ApiGateway.RestApi.SecurityPolicy", "ElasticLoadBalancingV2.Listener.SslPolicy", "NetworkFirewall.FirewallPolicy.FirewallPolicy.StatefulEngineOptions.StreamExceptionPolicy", "S3.Bucket.PublicAccessBlockConfiguration.BlockPublicPolicy", "SSO.PermissionSet.ManagedPolicies"):
        assert not VALIDATOR.Validator.is_policy_document_property(prop), prop
    print(f"Service policy tables checks: PASS ({len(POLICY_FORMATS)} registered properties, schema, generation, validation, model, CLI)")


def grouping_and_settings_checks():
    from policy_tables import START, END

    layout_fixture = load("design_layout.checks")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        path = root / "docs/designs/dev/123456789012/kms.md"
        artifacts = path.with_suffix("")
        artifacts.mkdir(parents=True)
        artifact = artifacts / "access.json"
        document = {"Statement": {"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::123456789012:root"}, "Action": "kms:*", "Resource": "*"}}
        artifact.write_text(json.dumps(document), encoding="utf-8")
        original = layout_fixture.KMS.replace('| 4 | KMS.Alias.AliasName', '| 5 | KMS.Alias.AliasName').replace('| 3 | KMS.Alias.AliasName', '| 3 | KMS.Key.KeyPolicy | [Access](kms/access.json) | アクセス権限 |\n| 4 | KMS.Alias.AliasName')
        path.write_text(original, encoding="utf-8")
        baseline_model = MODEL.model_for(path)
        rendered = rendered_design(path)
        path.write_text(rendered, encoding="utf-8")
        assert rendered_design(path) == rendered
        assert MODEL.model_for(path) == baseline_model
        assert rendered.count(START) == 1
        assert '| [KeyTwo](#kms-keytwo) | alias/three | — |' in rendered
        validator = VALIDATOR.Validator(root)
        validator.accounts = {("dev", "123456789012"): {}}
        validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(SCRIPTS.parents[1])
        validator.check_policy_tables()
        validator.check_design_overviews()
        validator.check_design_tables({path: ("kms", ("KMS.Key", "KMS.Alias"))}, *VALIDATOR.Validator(SCRIPTS.parents[1]).catalog_design_properties())
        validator.check_design_links({})
        validator.check_design_artifacts()
        assert not validator.errors, validator.errors
        # Removing a selected policy removes only its derived view and column.
        removed = rendered.replace('| 3 | KMS.Key.KeyPolicy | [Access](kms/access.json) | アクセス権限 |\n', '')
        path.write_text(removed, encoding="utf-8")
        assert 'Policies' not in rendered_design(path) and START not in rendered_design(path)
        assert 'logical-id: AliasTwo' in rendered_design(path)

        # Multiple policy formats in one owner, including a nested JSON string.
        path = path.with_name("ecr.md")
        artifacts = path.with_suffix("")
        artifacts.mkdir()
        (artifacts / "access.json").write_text(json.dumps(document), encoding="utf-8")
        lifecycle = artifacts / "lifecycle.json"
        lifecycle.write_text(json.dumps({"LifecyclePolicyText": '{"rules":[]}'}), encoding="utf-8")
        original = """# ECR設計書

- Design service ID: `ecr`
- Owned catalog resource types: `ECR.Repository`

## リソース一覧

### ECR.Repository

| LogicalId | Name | Encryption | Mutable | Scan | EmptyOnDelete |
| --- | --- | --- | --- | --- | --- |
| [Example](#ecr-example) | example | AES256 | MUTABLE | false | false |

## リソース詳細

<a id="ecr-example"></a>

### ECR.Repository: Example

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | ECR.Repository.RepositoryName | `example` | リポジトリの名前 |
| 2 | ECR.Repository.RepositoryPolicyText | [Policy](ecr/access.json) | アクセス権限 |
| 3 | ECR.Repository.LifecyclePolicy | [Policy](ecr/lifecycle.json) | 保持するイメージの条件 |
"""
        path.write_text(original, encoding="utf-8")
        baseline_model = MODEL.model_for(path)
        rendered = rendered_design(path)
        path.write_text(rendered, encoding="utf-8")
        assert rendered_design(path) == rendered
        assert MODEL.model_for(path) == baseline_model
        assert '[Policy](#ecr-example-policy-access)<br>[Policy](#ecr-example-policy-lifecycle)' in rendered
        validator = VALIDATOR.Validator(root)
        validator.check_design_overviews()
        assert not validator.errors, validator.errors
        for malformed in ({"LifecyclePolicyText": {}}, {"LifecyclePolicyText": "not-json"}, {"LifecyclePolicyText": "[]"}, {"LifecyclePolicyText": '{"rules":[],"rules":[]}'}):
            lifecycle.write_text(json.dumps(malformed), encoding="utf-8")
            try:
                rendered_design(path)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid embedded policy JSON must fail")
    print("Policy grouping/settings checks: PASS (KMS aliases, absent policy, multiple formats, nested JSON)")


if __name__ == "__main__":
    main()
    service_policy_checks()
    grouping_and_settings_checks()
