#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_design_fixtures import *

def check_design_naming_rules():
    for kind in ("S3.Bucket", "EC2.Instance", "EC2.VPCEndpoint", "EC2.VPC", "IAM.Role",
                 "SecurityHub.Hub", "SecretsManager.Secret", "Macie.ClassificationJob", "SSM.Association", "CloudFormation.Stack"):
        assert not design_naming_errors(ROOT, kind), kind
    assert design_naming_errors(ROOT, "CloudFront.CachePolicy") == ["naming rule missing: CloudFront.CachePolicy: CachePolicyConfig.Name"]
    assert not design_naming_errors(ROOT, "CloudFront.CachePolicy", "IMPORT")
    assert design_naming_errors(ROOT, "SecretsManager.Secret", name_tag=True) == ["naming rule missing: SecretsManager.Secret: Name tag"]



def check_subnet_list_display():
    # Catalog coverage is explicit: single IDs and arrays of objects keep their format.
    catalog = {line.partition("=")[0] for path in (ROOT / "framework/materials/aws").glob("*.properties")
               for line in path.read_text(encoding="utf-8").splitlines() if "=" in line}
    subnet_lists = {prop for prop in catalog if prop.rsplit(".", 1)[-1].removesuffix("[]") in {"SubnetIds", "Subnets", "VpcSubnetIds"}}
    assert SUBNET_LIST_PROPERTIES == subnet_lists
    assert len(subnet_lists) == 16  # 15 arrays and Secrets Manager's string list.
    for prop in sorted(subnet_lists):
        kind = ".".join(prop.split(".")[:2])
        field = prop.removeprefix(kind + ".").removesuffix("[]")
        links = ["[subnet-a](vpc.md#subnet-a)", "[PENDING_DEPLOY](vpc.md#subnet-b)"]
        inputs = [[["1", prop, value, "配置先Subnet"] for value in links]]
        if prop not in CODEBUILD_VPC_PROPERTIES:
            raw = "`subnet-a, subnet-b`" if kind == "SecretsManager.RotationSchedule" else '`[ "subnet-a" , "subnet-b" ]`'
            inputs += [[["1", prop, raw, "配置先Subnet"]]]
            if prop.endswith("[]"):
                inputs += [[["1", prop, "`subnet-a`", "配置先Subnet"], ["2", prop, "`subnet-b`", "配置先Subnet"]]]
            if kind != "SecretsManager.RotationSchedule":
                inputs += [[["1", prop, json.dumps(links), "参照先Subnet"]]]
        for rows in inputs:
            shown = display_rows(kind, rows)
            assert [row[1] for row in shown] == [field + "[1]", field + "[2]"], (prop, shown)
            document = [f"### {kind}: list-owner", "", *row_table(shown)]
            restored = expanded_display_rows(document)
            formal = [line for line in restored if line.startswith("|") and line not in {HEADER, ALIGNMENT}]
            assert formal == ["| " + " | ".join([str(number), *row[1:]]) + " |" for number, row in enumerate(rows, 1)], (prop, formal)
            assert display_rows(kind, rows) == shown  # Counts reset for every resource.
            for bad in (
                document[:-1],  # Missing second list element.
                [line.replace(field + "[2]", field + "[3]") for line in document],
                [line.replace(field + "[2]", field + "[1]") for line in document],
                [line.replace(field + "[1]", field + "[0]") for line in document],
                [line.replace(field + "[1]", field) for line in document],
            ):
                # A shortened link-only list is valid; saved-array markers require all elements.
                if bad == document[:-1] and len(rows) == 2:
                    continue
                with pytest.raises(ValueError):
                    expanded_display_rows(bad)
            if len(rows) == 1:
                for bad in (
                    [line.replace("| " + shown[0][2] + " |", "| `subnet-other` |") for line in document],
                    [*document[:-1], document[-1].replace(shown[-1][3], "別の説明")],
                ):
                    with pytest.raises(ValueError):
                        expanded_display_rows(bad)
        if prop not in CODEBUILD_VPC_PROPERTIES:
            bad_values = ["`subnet-a,,subnet-b`", "` `"] if kind == "SecretsManager.RotationSchedule" else ["[]", "[1]", '[null]', '[""]', '{}', '["a|b"]']
            for value in bad_values:
                with pytest.raises(ValueError):
                    display_rows(kind, [["1", prop, value, "配置先Subnet"]])


def check_security_naming():
    from design_catalog import DesignSchemaCatalog
    schema = DesignSchemaCatalog(ROOT)
    text = "\n".join(path.read_text(encoding="utf-8") for path in naming_rule_files(ROOT))
    patterns = {}
    for line in text.splitlines():
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) == 5 and cells[2] and cells[4].startswith(("waf", "nfw", "scp", "fmsp", "sspb", "ssma", "ssmw", "mwtg", "mwts", "cfgr", "vbpe")):
            patterns[cells[2]] = (cells[3], cells[4])
    assert len(patterns) == 15
    for kind, (field, pattern) in patterns.items():
        if kind.startswith("WAFv2."):
            assert pattern.startswith("waf")
        for shared in (False, True) if kind == "Organizations.Policy" else (False,):
            name = pattern.replace("[-{{environment}}]", "" if shared else "-dev")
            for key, value in (("application", "app"), ("environment", "dev"), ("purpose", "patching")):
                name = name.replace("{{" + key + "}}", value)
            assert "{{" not in name
            fields = [("Tags[].Key", "Name"), ("Tags[].Value", name)] if field == "Name tag" else [(field, name)]
            rows = [[str(number), prop, f"`{value}`", "名称"] for number, (prop, value) in enumerate(fields, 1)]
            assert not naming_errors(ROOT, kind, rows), kind
            assert not naming_errors(ROOT, kind, [[row[0], kind + "." + row[1], *row[2:]] for row in rows]), kind
            for prop, value in fields:
                assert schema.literal_errors(kind, prop, value) == [], (kind, prop)
                selected = (ROOT / 'framework/materials/aws' / (kind.replace('.', '_', 1) + '.properties')).read_text(encoding="utf-8")
                assert f"{kind}.{prop}=" in selected
    for kind in ("EC2.TransitGateway", "EC2.TransitGatewayVpcAttachment", "EC2.TransitGatewayRouteTable"):
        assert not naming_errors(ROOT, kind, [["1", "Tags[].Key", "`Name`", "タグ"], ["2", "Tags[].Value", "`tgw-app-dev-patching-01`", "名称"]])
    assert not naming_errors(ROOT, "SSM.Association", [["1", "Name", "`AWS-RunPatchBaseline`", "参照document"]])
    assert not naming_errors(ROOT, "EC2.VPCBlockPublicAccessOptions", [["1", "InternetGatewayBlockMode", "`block-ingress`", "遮断設定"]])
    assert not naming_errors(ROOT, "EC2.VPCBlockPublicAccessExclusion", [["1", "InternetGatewayExclusionMode", "`allow-egress`", "除外設定"]])
    print("Security naming: PASS (15 patterns, catalog/schema, formal/short properties, TGW and optional names)")


def check_service_scoped_naming(tmp_path):
    datazone_targets = naming_targets(ROOT, "DataZone")
    for kind in ("DataZone.Domain", "DataZone.Project", "DataZone.DataSource"):
        assert datazone_targets[kind] == {"Name"}, kind
        assert not design_naming_errors(ROOT, kind), kind
    selected = naming_rule_files(ROOT, "S3")
    assert [path.name for path in selected] == ["aws-resource-naming.md", "S3.md"]
    read_text = Path.read_text

    def scoped_read(path, *args, **kwargs):
        if path.parent.name == "aws-resource-naming":
            assert path.name == "S3.md", f"unselected naming rule read: {path}"
        return read_text(path, *args, **kwargs)

    with patch.object(Path, "read_text", scoped_read):
        assert not naming_errors(ROOT, "S3.Bucket", [["1", "BucketName", "`app-dev-data-123456789012`", "名前"]])
        assert set(naming_targets(ROOT, "S3")) == {"S3.Bucket"}

    root = tmp_path
    rules = root / "framework/rules"
    rules.mkdir(parents=True)
    entrance = rules / "aws-resource-naming.md"
    entrance.write_text("| `S3` | [S3](aws-resource-naming/S3.md) |\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        naming_targets(root, "S3")
    entrance.write_text("| Fixture | Bucket | `S3.Bucket` | `BucketName` | `{{purpose}}` |\n", encoding="utf-8")
    assert naming_targets(root, "S3") == {"S3.Bucket": {"BucketName"}}
    assert naming_targets(root, "CloudFront") == {"S3.Bucket": {"BucketName"}}
    print("Service-scoped naming: PASS (selected service only, missing file rejected, legacy fixture)")


def check_naming_target_paths():
    targets = naming_targets(ROOT, "CodeBuild")["CodeBuild.Project"]
    assert naming_target_matches("Name", targets, "CodeBuild.Project")
    assert not naming_target_matches("Environment.EnvironmentVariables[].Name", targets, "CodeBuild.Project")
    assert not naming_target_matches("Artifacts.Name", targets, "CodeBuild.Project")
    pipeline = naming_targets(ROOT, "CodePipeline")["CodePipeline.Pipeline"]
    assert naming_target_matches("Name", pipeline, "CodePipeline.Pipeline")
    for field in ("Stages[].Name", "Stages[].Actions[].Name", "Variables[].Name"):
        assert not naming_target_matches(field, pipeline, "CodePipeline.Pipeline"), field
    glue = naming_targets(ROOT, "Glue")["Glue.Job"]
    assert naming_target_matches("Name", glue, "Glue.Job")
    assert not naming_target_matches("Command.Name", glue, "Glue.Job")
    # An explicitly declared nested target remains exact and valid.
    s3 = naming_targets(ROOT, "S3")["S3.Bucket"]
    assert naming_target_matches("LifecycleConfiguration.Rules[].Id", s3, "S3.Bucket")
    assert not naming_target_matches("Other.Rules[].Id", s3, "S3.Bucket")
    print("Naming Target paths: PASS (root-only implicit match, exact nested target)")


def check_security_group_and_glue_catalog_naming():
    text = "\n".join(path.read_text(encoding="utf-8") for path in naming_rule_files(ROOT))
    group_pattern = "{{application}}-{{environment}}-{{service}}-{{purpose}}[-{{number}}]-sg"
    assert f"| `EC2.SecurityGroup` | `GroupName` | `{group_pattern}` |" in text
    assert f"| `EC2.SecurityGroup` | Name tag | `{group_pattern}` |" in text
    assert "| `Glue.Catalog` | `Name` | `glct-{{application}}-{{environment}}-{{purpose}}` |" in text
    for kind, fields in (
        ("EC2.SecurityGroup", [("GroupName", "app-dev-glue-data-sg")]),
        ("EC2.SecurityGroup", [("GroupName", "app-dev-glue-data-01-sg")]),
        ("EC2.SecurityGroup", [("Tags[].Key", "Name"), ("Tags[].Value", "app-dev-glue-data-sg")]),
        ("EC2.SecurityGroup", [("Tags[].Key", "Name"), ("Tags[].Value", "app-dev-glue-data-01-sg")]),
        ("Glue.Catalog", [("Name", "glct-app-dev-data")]),
    ):
        for prefix in ("", kind + "."):
            rows = [[str(number), prefix + field, f"`{value}`", "名称"]
                    for number, (field, value) in enumerate(fields, 1)]
            assert not naming_errors(ROOT, kind, rows), kind
    assert not naming_errors(ROOT, "EC2.SecurityGroup", [])
    print("Security Group and Glue Catalog naming: PASS (exact patterns, optional number, formal/short properties, optional Name tag)")


@pytest.mark.parametrize("kind, field", [
    ("Logs.LogGroup", "LogGroupName"), ("Scheduler.Schedule", "Name"), ("EC2.VPC", "Name"),
    ("Athena.WorkGroup", "Name"), ("CloudTrail.Trail", "TrailName"),
])
def check_naming_coverage(kind, field):
    assert not naming_errors(ROOT, kind, [["1", field, "`example`", "名前"]])


def check_naming_edges():
    assert naming_errors(ROOT, "CloudFront.CachePolicy", [["1", "CachePolicyConfig.Name", "`example`", "名前"]])
    assert not naming_errors(ROOT, "Glue.Connection", [["1", "Name", "`PENDING_DEPLOY`", "生成される名前"]])
    assert not naming_errors(ROOT, "Glue.Connection", [["1", "ConnectionInput.Name", "`example`", "作成する接続の名前"]])
    assert not naming_errors(ROOT, "Scheduler.Schedule", [["1", "GroupName", "`default`", "所属先"]])
    assert not naming_errors(ROOT, "SecurityHub.Hub", [["1", "EnableDefaultStandards", "`true`", "標準を有効化"]])
    assert not naming_errors(ROOT, "SecurityHub.Hub", [["1", "Tags[].Key", '"purpose"', "タグ"], ["2", "Tags[].Value", '"security"', "用途"]])
    assert naming_errors(ROOT, "SecurityHub.Hub", [["1", "Tags[].Key", '"Name"', "タグ"], ["2", "Tags[].Value", '"security"', "名前"]])
    assert not naming_errors(ROOT, "EC2.Instance", [["1", "Tags[].Key", '"Name"', "タグ"], ["2", "Tags[].Value", '"app"', "名前"]])


@pytest.mark.parametrize("invalid", ["x=1\nx=2\n", "missing-separator\n"])
def check_invalid_model(invalid):
    with pytest.raises(ValueError):
        properties(invalid)


def check_temporary_roots(tmp_path):
    configure = load("conftest").pytest_configure
    cleanup = []
    configs = [SimpleNamespace(option=SimpleNamespace(basetemp=None), add_cleanup=cleanup.append) for _ in range(2)]
    try:
        for config in configs:
            configure(config)
        paths = [Path(config.option.basetemp) for config in configs]
        assert paths[0] != paths[1] and all(path.is_dir() for path in paths)
    finally:
        for callback in cleanup:
            callback()
    explicit = SimpleNamespace(option=SimpleNamespace(basetemp=tmp_path), add_cleanup=lambda _: pytest.fail("explicit temporary root replaced"))
    configure(explicit)
    assert explicit.option.basetemp == tmp_path and tmp_path.is_dir()


@pytest.mark.parametrize("result", [0, 1, 2])
def check_cli_result(result, monkeypatch, capsys):
    monkeypatch.setattr(pytest, "main", lambda *args, **kwargs: result)
    assert main() == int(result != 0)
    assert ("model_design: PASS" in capsys.readouterr().out) == (result == 0)
    report = SimpleNamespace(failed=result != 0, longrepr="pytest failure")
    Diagnostics().pytest_runtest_logreport(report)
    Diagnostics().pytest_collectreport(report)
    assert capsys.readouterr().err == ("pytest failure\n" * 2 if result else "")


def check_one_way_model_contract():
    from model.core import validate_model_keys
    from model.validation import validate_required_properties
    from design_layout import is_import_role_arn
    from types import SimpleNamespace
    import sync_runtime
    import inspect

    prop = 'Config.ConfigurationRecorder.RoleARN'
    arn = 'arn:aws:iam::123456789012:role/service-role/path/ConfigRecorderRole'
    values = {
        'desired.resource.001.resourceType': 'Config.ConfigurationRecorder',
        'desired.resource.001.logicalId': 'Config_ConfigurationRecorder_001',
        'desired.service.identity.lastAllocated': '{"Config.ConfigurationRecorder":1}',
        'desired.resource.001.resourceMode': 'IMPORT',
        'desired.row.001-001.property': prop,
        'desired.row.001-001.value': '`' + arn + '`',
        'desired.row.001-001.comment': '記録用IAM Role',
    }
    validate_required_properties(values, ROOT)
    with pytest.raises(ValueError, match='unknown Model field'):
        validate_required_properties(values | {'desired.extra': 'stale'}, ROOT)
    assert validate_required_properties(values | {'desired.resource.001.resourceMode': 'CREATE'}, ROOT)
    for invalid in ('arn:aws:iam::123:role/test', 'arn:aws:iam::123456789012:user/test',
                    'arn:aws:iam::123456789012:role/', 'arn:aws:iam::123456789012:role/a b', '`' + arn, arn + '`'):
        assert not is_import_role_arn(prop, invalid, 'IMPORT')
        assert validate_required_properties(values | {'desired.row.001-001.value': invalid}, ROOT)
    assert is_import_role_arn(prop, 'arn:aws:iam::123456789012:role/path!special/Role', 'IMPORT')
    shown = display_rows('Config.ConfigurationRecorder', [['001-001', prop, '`' + arn + '`', '記録用IAM Role']], mode='IMPORT')
    assert shown == [['001-001', 'RoleARN', '`' + arn + '`', '記録用IAM Role']]
    for value in ('[role](iam.md#iam-role)', '`AWSServiceRoleForConfig`'):
        assert display_rows('Config.ConfigurationRecorder', [['001-001', prop, value, '記録用IAM Role']], mode='IMPORT')[0][1] == 'RoleName'
    validate_model_keys(values | {'observed.row.001-001.value': 'current',
                                'display.resource.001.label': '表示名',
                                'desired.resource.001.cfn-logicalId': 'stack-Recorder'})
    assert 'design.projection' not in inspect.getsource(sync_runtime.validate_generation)
    from model.format import parse, serialize
    for value in ('value', '`value`', '010', '  quoted \"text\" '):
        assert parse(serialize({'desired.row.001-001.value': value})).values['desired.row.001-001.value'] == value




def check_pending_reference_is_required_input():
    from model.validation import validate_required_properties
    values = {
        'desired.resource.001.resourceType': 'EC2.Subnet',
        'desired.resource.001.logicalId': 'EC2_Subnet_001',
        'desired.resource.001.resourceMode': 'IMPORT',
        'desired.service.identity.lastAllocated': '{"EC2.Subnet":1}',
        'desired.row.001-001.property': 'EC2.Subnet.VpcId',
        'desired.row.001-001.value': 'resource://preview/team/vpc/EC2_VPC_001',
        'desired.row.001-001.comment': '所属するVPC',
        'desired.row.001-002.property': 'EC2.Subnet.CidrBlock',
        'desired.row.001-002.value': '`10.0.0.0/24`',
        'desired.row.001-002.comment': 'Subnet範囲',
    }
    for observation in ('PENDING_DEPLOY', '`PENDING_DEPLOY`', '`vpc-current`'):
        candidate = {**values, 'observed.row.001-001.value': observation}
        before = dict(candidate)
        assert validate_required_properties(candidate, ROOT) == []
        assert candidate == before
    for missing in ('', '`PENDING_DEPLOY`'):
        with pytest.raises(ValueError, match='required provider schema property missing: EC2.Subnet.VpcId'):
            validate_required_properties({**values, 'desired.row.001-001.value': missing}, ROOT)


def check_selected_model_row_consumption(monkeypatch):
    import model.render as model_design
    resource = {'resourceType': 'Config.ConfigurationRecorder', 'resourceMode': 'IMPORT'}
    rows = [['001-001', 'Config.ConfigurationRecorder.RoleARN', '`AWSServiceRoleForConfig`', '記録用IAM Role']]
    output = model_design.resource_table_lines(resource, 'default', rows, [], ROOT)
    assert any('| RoleName | `AWSServiceRoleForConfig` |' in line for line in output)
    with pytest.raises(ValueError, match='duplicate selected'):
        model_design.resource_table_lines(resource, 'default', rows * 2, [], ROOT)
    monkeypatch.setattr(model_design, 'display_rows', lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match='omitted or consumed more than once'):
        model_design.resource_table_lines(resource, 'default', rows, [], ROOT)
    def duplicated(*args, **kwargs):
        kwargs['consumed'].extend(['001-001', '001-001'])
        return [['001-001', 'RoleName', '`AWSServiceRoleForConfig`', '記録用IAM Role']]
    monkeypatch.setattr(model_design, 'display_rows', duplicated)
    with pytest.raises(ValueError, match='omitted or consumed more than once'):
        model_design.resource_table_lines(resource, 'default', rows, [], ROOT)



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
