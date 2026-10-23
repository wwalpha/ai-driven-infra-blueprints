"""Schema, required names, CIDR and catalog row order."""


from __future__ import annotations

from functools import partial as _bind_framework_callback

from support.it_case_receipt import it_case
from support.validator import (
    MODULE,
    SCRIPT,
    diagnostics,
    project,
    schema_validator,
    write,
)
from support.validator import (
    load as load,
)

_CALLBACK_DEFAULT = object()



def _callback_check_description_design_constraints_validate_82(catalog, iam, metadata, root, sg, _default_role_text, _default_group_text, /, role_text=_CALLBACK_DEFAULT, group_text=_CALLBACK_DEFAULT):
    if role_text is _CALLBACK_DEFAULT:
        role_text = _default_role_text
    if group_text is _CALLBACK_DEFAULT:
        group_text = _default_group_text
    write(iam, role_text)
    write(sg, group_text)
    validator = schema_validator(root)
    validator.check_design_tables(metadata, *catalog, paths=[iam, sg])
    validator.check_design_overviews(paths=[iam, sg])
    return validator


@it_case
def check_description_design_constraints() -> None:
    repository = SCRIPT.parents[2]
    catalog = MODULE.Validator(repository).catalog_design_properties()
    with project() as root:
        target = root / "docs/designs/dev/123456789012"
        target.mkdir(parents=True)
        iam = target / "iam.md"
        sg = target / "security-group.md"
        iam_text = """# IAM 詳細設計

- Design service ID: `iam`
- Owned catalog resource types: `IAM.Role`

## リソース一覧

### IAM.Role

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-role](#iam-app-role) | アプリケーションの権限 |

## リソース詳細

<!-- resource-logical-id: RoleOne -->
<a id="iam-app-role"></a>
### IAM.Role: app-role

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RoleName | `app-role` | ロール名 |
| 2 | AssumeRolePolicyDocument | [Trust](iam/role-one-trust-policy.json) | 信頼ポリシー |
| 3 | Description | `Application role` | 用途の説明 |
"""
        sg_text = """# Security Group 詳細設計

- Design service ID: `security-group`
- Owned catalog resource types: `EC2.SecurityGroup`

## リソース一覧

### EC2.SecurityGroup

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-sg](#security-group-app-sg) | アプリケーションの通信制御 |

## リソース詳細

<!-- resource-logical-id: GroupOne -->
<a id="security-group-app-sg"></a>
### EC2.SecurityGroup: app-sg

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | `PENDING_DEPLOY` | 一意に識別するID |
| 2 | GroupDescription | `Application access` | 用途の説明 |
| 3 | GroupName | `app-sg` | 名前 |
| 4 | VpcId | [PENDING_DEPLOY](vpc.md#vpc-app-vpc) | 所属するVPCのID |
"""
        metadata = {iam: ("iam", ("IAM.Role",)), sg: ("security-group", ("EC2.SecurityGroup",))}

        validate = _bind_framework_callback(_callback_check_description_design_constraints_validate_82, catalog, iam, metadata, root, sg, iam_text, sg_text)

        # Both Japanese overview Comments and Source / Comments remain valid.
        assert not validate().errors, validate().errors
        for resource, prop, filename, role_text, group_text in (
            ("RoleOne", "IAM.Role.Description", "iam.md", iam_text.replace("Application role", "日本語の説明"), sg_text),
            ("GroupOne", "EC2.SecurityGroup.GroupDescription", "security-group.md", iam_text, sg_text.replace("Application access", "日本語の説明")),
            ("GroupOne", "EC2.SecurityGroup.GroupDescription", "security-group.md", iam_text, sg_text.replace("Application access", "Why?")),
        ):
            errors = validate(role_text, group_text).errors
            assert len(errors) == 1, errors
            assert all(text in errors[0] for text in (filename, resource, prop, "must match")), errors

        # Existing validators collect independent property and dependency failures.
        validator = validate(iam_text.replace("Application role", "日本語"), sg_text.replace("Application access", "日本語"))
        validator.check_design_links(catalog[2], paths=[iam, sg])
        assert any("RoleOne: IAM.Role.Description" in error for error in diagnostics(validator))
        assert any("GroupOne: EC2.SecurityGroup.GroupDescription" in error for error in diagnostics(validator))
        assert any("broken design link" in error and "vpc.md" in error for error in diagnostics(validator))
        assert any("broken design link" in error and "trust-policy.json" in error for error in diagnostics(validator))
        assert iam.read_text(encoding="utf-8") == iam_text.replace("Application role", "日本語")
        assert sg.read_text(encoding="utf-8") == sg_text.replace("Application access", "日本語")
