#!/usr/bin/env python3
"""Check IAM view generation, failure detection, and the unchanged model contract."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from iam_policy_tables import END, START, policy_lines, rendered_design, roles_in, without_policy_tables

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

"""
        for logical_id in ("RoleA", "RoleB"):
            file_id = VALIDATOR.artifact_id(logical_id)
            for suffix, document in (("trust-policy", trust), ("logging", inline), ("extra", inline)):
                (artifacts / f"{file_id}-{suffix}.json").write_text(json.dumps(document), encoding="utf-8")
            text += f'''<a id="iam-{logical_id.lower()}"></a>

## IAM.Role: {logical_id}

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

## IAM.InstanceProfile: Profile

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
            validator.check_iam_policy_tables()
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
        assert errors(rendered.replace("## IAM.Role: RoleB", "## IAM.Role: RoleA"))
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
        role = roles_in(without_policy_tables(rendered.splitlines()))[0]
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
        check = subprocess.run([sys.executable, str(SCRIPTS / "iam_policy_tables.py"), str(path)], capture_output=True)
        assert check.returncode == 1 and path.read_text(encoding="utf-8") == text
        write = subprocess.run([sys.executable, str(SCRIPTS / "iam_policy_tables.py"), str(path), "--write"], capture_output=True)
        assert write.returncode == 0, write.stderr
        assert path.read_text(encoding="utf-8") == rendered

        # Optional RoleName and inline policies are not invented by the renderer.
        minimal = text[:text.index('<a id="iam-roleb"')]
        minimal = "\n".join(line for line in minimal.splitlines() if not any(prop in line for prop in ("IAM.Role.RoleName", "IAM.Role.Policies[]"))) + "\n"
        path.write_text(minimal, encoding="utf-8")
        view = rendered_design(path)
        assert "[（RoleName未指定）](#iam-rolea)" in view
        assert "### インラインポリシー" not in view
        other_service = "# 他サービスの設計\n\n実装注記を維持する。\n"
        path.write_text(other_service, encoding="utf-8")
        assert rendered_design(path) == other_service
    print("IAM policy tables checks: PASS (generation, validation, model, CLI)")


if __name__ == "__main__":
    main()
