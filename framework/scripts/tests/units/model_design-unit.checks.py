#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import model.render as model_design
import support.model_design_fixtures as _exports_support_model_design_fixtures
import sync_runtime
import validation.design as design_validation
import validation.design_tables as design_tables
from array_display import indexed_rows
from design_catalog import DesignSchemaCatalog
from design_document import DesignIndex
from design_layout import (
    catalog_order_errors,
    formal_property,
    is_import_pending_reference,
    is_import_role_arn,
    resource_display_name,
    resource_display_selection,
    stack_deployment_policy,
    stack_design,
)
from iac_values import cfn_resource_identity
from model.core import entries, stack_model, validate_model_keys
from model.format import parse, serialize
from model.identity import resource_index
from model.projection import resource_rows
from model.validation import (
    validate_kms_policy_accounts,
    validate_required_properties,
    validate_resource_identities,
)
from support.model_design_fixtures import (
    ALIGNMENT,
    CODEBUILD_VPC_PROPERTIES,
    HEADER,
    ROOT,
    SUBNET_LIST_PROPERTIES,
    Diagnostics,
    Path,
    SimpleNamespace,
    catalog_display_rows,
    design_naming_errors,
    display_rows,
    expanded_display_rows,
    json,
    load,
    main,
    model,
    naming_errors,
    naming_rule_files,
    naming_target_matches,
    naming_targets,
    patch,
    properties,
    pytest,
    row_table,
    run,
    sys,
)
from support.model_design_fixtures import pytestmark as pytestmark
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from validation.design_links import check_design_links as validate_design_links
from validation.findings import Findings

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

# Preserve shared fixtures and compatibility exports under their historical names.
text = _exports_support_model_design_fixtures.text



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
            raw = '`[ "subnet-a" , "subnet-b" ]`'
            if kind == "SecretsManager.RotationSchedule":
                raw = "`subnet-a, subnet-b`"
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
            bad_values = ["[]", "[1]", '[null]', '[""]', '{}', '["a|b"]']
            if kind == "SecretsManager.RotationSchedule":
                bad_values = ["`subnet-a,,subnet-b`", "` `"]
            for value in bad_values:
                with pytest.raises(ValueError):
                    display_rows(kind, [["1", prop, value, "配置先Subnet"]])


def check_security_naming():
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
        variants = (False,)
        if kind == "Organizations.Policy":
            variants = (False, True)
        for shared in variants:
            environment = "-dev"
            if shared:
                environment = ""
            name = pattern.replace("[-{{environment}}]", environment)
            for key, value in (("application", "app"), ("environment", "dev"), ("purpose", "patching")):
                name = name.replace("{{" + key + "}}", value)
            assert "{{" not in name
            fields = [(field, name)]
            if field == "Name tag":
                fields = [("Tags[].Key", "Name"), ("Tags[].Value", name)]
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


def _callback_check_service_scoped_naming_scoped_read(read_text, /, path, *args, **kwargs):
    if path.parent.name == "aws-resource-naming":
        assert path.name == "S3.md", f"unselected naming rule read: {path}"
    return read_text(path, *args, **kwargs)


def check_service_scoped_naming(tmp_path):
    datazone_targets = naming_targets(ROOT, "DataZone")
    for kind in ("DataZone.Domain", "DataZone.Project", "DataZone.DataSource"):
        assert datazone_targets[kind] == {"Name"}, kind
        assert not design_naming_errors(ROOT, kind), kind
    selected = naming_rule_files(ROOT, "S3")
    assert [path.name for path in selected] == ["aws-resource-naming.md", "S3.md"]
    read_text = Path.read_text

    scoped_read = _bind_framework_callback(_callback_check_service_scoped_naming_scoped_read, read_text)

    with patch.object(Path, "read_text", scoped_read):
        assert not naming_errors(ROOT, "S3.Bucket", [["1", "BucketName", "`app-dev-data-123456789012`", "名前"]])
        assert set(naming_targets(ROOT, "S3")) == {"S3.Bucket"}



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
    expected = ""
    if result:
        expected = "pytest failure\n" * 2
    assert capsys.readouterr().err == expected


def check_one_way_model_contract():


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
    for value in ('value', '`value`', '010', '  quoted \"text\" '):
        assert parse(serialize({'desired.row.001-001.value': value})).values['desired.row.001-001.value'] == value




def check_pending_reference_is_required_input():
    values = {
        'desired.resource.001.resourceType': 'EC2.Subnet',
        'desired.resource.001.logicalId': 'EC2_Subnet_001',
        'desired.resource.001.resourceMode': 'IMPORT',
        'desired.service.identity.lastAllocated': '{"EC2.Subnet":1}',
        'desired.row.001-001.property': 'EC2.Subnet.VpcId',
        'desired.row.001-001.value': '[vpc](vpc.md#network)',
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




def _check_selected_model_row_consumption_duplicated(*args, **kwargs):
    kwargs['consumed'].extend(['001-001', '001-001'])
    return [['001-001', 'RoleName', '`AWSServiceRoleForConfig`', '記録用IAM Role']]


def check_selected_model_row_consumption(monkeypatch):
    resource = {'resourceType': 'Config.ConfigurationRecorder', 'resourceMode': 'IMPORT'}
    rows = [['001-001', 'Config.ConfigurationRecorder.RoleARN', '`AWSServiceRoleForConfig`', '記録用IAM Role']]
    output = model_design.resource_table_lines(resource, 'default', rows, [], ROOT)
    assert any('| RoleName | `AWSServiceRoleForConfig` |' in line for line in output)
    with pytest.raises(ValueError, match='duplicate selected'):
        model_design.resource_table_lines(resource, 'default', rows * 2, [], ROOT)
    monkeypatch.setattr(model_design, 'display_rows', lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match='omitted or consumed more than once'):
        model_design.resource_table_lines(resource, 'default', rows, [], ROOT)
    duplicated = _check_selected_model_row_consumption_duplicated
    monkeypatch.setattr(model_design, 'display_rows', duplicated)
    with pytest.raises(ValueError, match='omitted or consumed more than once'):
        model_design.resource_table_lines(resource, 'default', rows, [], ROOT)





def check_glue_argument_display():
    arguments = '{ "--job-language": "python", "--job-bookmark-option": "job-bookmark-disable", "--enable-spark-ui": "true", "--spark-event-logs-path": "s3://data/temp/spark-ui/", "--SECRET_NAME": "snowflake-keypair", "--ENVIRONMENT": "dev", "--TempDir": "s3://data/temp/", "--custom-logGroup-prefix": "/aws-glue/jobs/app", "--custom-logStream-prefix": "if-outbound-001" }'
    values = model("glue", "Glue.Job", "app-dev-outbound", [
        ("Name", "`app-dev-outbound`", "処理ジョブの名前"),
        ("DefaultArguments", f"`{arguments}`", "ジョブの既定引数"),
        ("NonOverridableArguments", '`{"--LOCKED":"false","--empty":"","--特殊\\u007c<key>`":"line\\n\\u007c<>&`"}`', "上書きできない引数"),
        ("Tags", "`{}`", "ジョブのタグ"),
        ("Role", "[IAM_Role_001](iam.md#iam-net-dev-flow-role)", "処理ジョブの実行ロール"),
        ("Command.Name", "`glueetl`", "処理ジョブの種類"),
    ])
    output = "\n".join(["### Glue.Job: resource", *row_table(display_rows("Glue.Job", resource_rows(values, "001", "Glue.Job", ROOT), mode=values.get("desired.resource.001.resourceMode", "CREATE")))])
    for key, item in json.loads(arguments).items():
        assert f'DefaultArguments["{key}"] | `{item}` |' in output
    assert 'NonOverridableArguments["--LOCKED"] | `false` |' in output
    assert 'NonOverridableArguments["--empty"] | `""` |' in output
    assert "&#124;" in output and "<code>line&#10;&#124;&lt;&gt;&amp;`</code>" in output
    assert output.index('--job-language"]') < output.index('--job-bookmark-option"]') < output.index('--custom-logStream-prefix"]')
    invalid = [
        output.replace('DefaultArguments["--job-language"]', 'DefaultArguments["--missing"]'),
        output.replace('DefaultArguments["--job-bookmark-option"]', 'DefaultArguments["--job-language"]'),
        output.replace(' | `python` |', ' | `scala` |'),
        output.replace(' | ジョブの既定引数 |', ' | 変更された引数 |', 1),
        output.replace('glue-arguments-source:', 'missing-source:'),
        output.replace(', 9] -->', ', 8] -->'),
        '\n'.join(line for line in output.splitlines() if 'DefaultArguments["--ENVIRONMENT"]' not in line),
        output.replace('### Glue.Job:', '### Glue.Connection:'),
    ]
    for bad in invalid:
        assert bad != output
        with pytest.raises(ValueError):
            expanded_display_rows(bad.splitlines())
    for value in ('`{}`', '`{"--one":"one"}`'):
        values["desired.row.001-002.value"] = value
        display_rows("Glue.Job", resource_rows(values, "001", "Glue.Job", ROOT))
    for value in ('`[]`', '`{"--one":true}`', '`{"--one":"first","--one":"second"}`'):
        values["desired.row.001-002.value"] = value
        with pytest.raises(ValueError):
            display_rows("Glue.Job", resource_rows(values, "001", "Glue.Job", ROOT))
    print("Glue Job arguments: PASS (key rows, exact JSON round trip, invalid displays)")

def check_ec2_compact_display():
    name = "app-dev-worker"
    for count in (1, 5):
        devices = []
        for number in range(1, count + 1):
            devices += [("BlockDeviceMappings[].DeviceName", f"`/dev/sd{chr(96 + number)}`", "デバイス名"),
                        ("BlockDeviceMappings[].Ebs.VolumeSize", f"`{number * 10}`", "ディスク容量")]
            if number % 2:
                devices.append(("BlockDeviceMappings[].Ebs.VolumeType", "`gp3`", "ディスク種別"))
        values = model("ec2", "EC2.Instance", name, [
            *devices,
            ("ImageId", "`ami-0123456789abcdef0`", "起動するイメージ"),
            ("InstanceType", "`t3.micro`", "インスタンス種別"),
            ("Tags[].Key", "`purpose`", "用途タグのキー"),
            ("Tags[].Value", "`worker`", "用途タグの値"),
            ("Tags[].Key", '"Name"', "名前タグのキー <識別>"),
            ("Tags[].Value", f"`{name}`", "インスタンス名"),
            ("Tags[].Key", "`owner`", "所有者タグのキー"),
            ("Tags[].Value", "`team`", "所有者タグの値"),
            ("Tenancy", "`default`", "実行するテナンシー"),
        ], "Worker")
        rows = display_rows("EC2.Instance", resource_rows(values, "001", "EC2.Instance", ROOT),
                            mode=values.get("desired.resource.001.resourceMode", "CREATE"))
        output = "\n".join(["### EC2.Instance: resource", *row_table(indexed_rows(rows, "EC2.Instance"))])
        assert "BlockDeviceMappings[]" not in output
        for number in range(1, count + 1):
            assert f"BlockDeviceMappings[{number}].DeviceName |" in output
            assert f"BlockDeviceMappings[{number}].Ebs.VolumeSize | `{number * 10}`" in output
            assert (f"BlockDeviceMappings[{number}].Ebs.VolumeType |" in output) == bool(number % 2)
        assert f"| Name | `{name}` |" in output
        assert '| Tags[].Key | "Name" |' not in output
        assert "| Tags[1].Key | `purpose` |" in output and "| Tags[3].Key | `owner` |" in output
        invalid = [
            output.replace("BlockDeviceMappings[1]", "BlockDeviceMappings[0]"),
            output.replace("BlockDeviceMappings[1]", "BlockDeviceMappings[2]"),
            output.replace("BlockDeviceMappings[1]", "BlockDeviceMappings[01]"),
            output.replace("BlockDeviceMappings[1].DeviceName", "BlockDeviceMappings[1].Ebs.VolumeSize"),
            output.replace("ec2-name-tag:", "missing-name-tag:"),
            output.replace('["\\\"Name\\\""', '["\\\"name\\\""'),
            output.replace("| Name |", "| Tenancy |"),
        ]
        if count > 1:
            invalid.append(output.replace("BlockDeviceMappings[2]", "BlockDeviceMappings[3]"))
        for bad in invalid:
            assert bad != output
            with pytest.raises(ValueError):
                expanded_display_rows(bad.splitlines())
    # IMPORT without a Name tag keeps its existing absence.
    values = model("ec2", "EC2.Instance", "EC2.Instance", [("ImageId", "`ami-0123456789abcdef0`", "起動するイメージ")])
    values["desired.resource.001.resourceMode"] = "IMPORT"
    values.pop("desired.resource.001.cfn-logicalId", None)
    rows = display_rows("EC2.Instance", resource_rows(values, "001", "EC2.Instance", ROOT),
                        mode=values.get("desired.resource.001.resourceMode", "CREATE"))
    output = "\n".join(["### EC2.Instance: resource", *row_table(indexed_rows(rows, "EC2.Instance"))])
    assert "| Name |" not in output and "ec2-name-tag:" not in output
    print("EC2 block device indexes and compact Name tag: PASS (lossless round trip and invalid displays)")

def check_vpc_endpoint_name_display():
    kind, name = "EC2.VPCEndpoint", "vpce-app-dev-s3"
    values = model("vpc", kind, name, [
        ("ServiceName", "`com.amazonaws.ap-northeast-1.s3`", "接続先サービス"),
        ("Tags[].Key", "`purpose`", "用途タグのキー"),
        ("Tags[].Value", "`data`", "用途タグの値"),
        ("Tags[].Key", '"Name"', "名前タグのキー <識別>"),
        ("Tags[].Value", f"`{name}`", "エンドポイント名"),
        ("Tags[].Key", "`owner`", "所有者タグのキー"),
        ("Tags[].Value", "`team`", "所有者タグの値"),
        ("VpcId", "[VPC](#vpc-vpc-app-dev)", "所属するVPC"),
    ], "Endpoint")
    for mode in ("CREATE", "IMPORT"):
        values["desired.resource.001.resourceMode"] = mode
        if mode == "IMPORT":
            values.pop("desired.resource.001.cfn-logicalId", None)
        rows = display_rows("EC2.VPCEndpoint", resource_rows(values, "001", "EC2.VPCEndpoint", ROOT),
                            mode=values.get("desired.resource.001.resourceMode", "CREATE"))
        output = "\n".join(["### EC2.VPCEndpoint: resource", *row_table(indexed_rows(rows, "EC2.VPCEndpoint"))])
        assert output.count(f"| Name | `{name}` |") == 1
        assert "--> エンドポイント名 |" in output
        assert '| Tags[2].Key | "Name" |' not in output
        assert "| Tags[1].Key | `purpose` |" in output
        assert "| Tags[3].Key | `owner` |" in output
        for bad in (
            output.replace("ec2-name-tag:", "missing-name-tag:"),
            output.replace('["\\\"Name\\\""', '["\\\"name\\\""'),
            output.replace("| Name |", "| ServiceName |"),
        ):
            assert bad != output
            with pytest.raises(ValueError):
                expanded_display_rows(bad.splitlines())
    values = model("vpc", kind, kind, [
        ("ServiceName", "`com.amazonaws.ap-northeast-1.s3`", "接続先サービス"),
        ("VpcId", "[VPC](#vpc-vpc-app-dev)", "所属するVPC"),
    ])
    values["desired.resource.001.resourceMode"] = "IMPORT"
    values.pop("desired.resource.001.cfn-logicalId", None)
    rows = display_rows("EC2.VPCEndpoint", resource_rows(values, "001", "EC2.VPCEndpoint", ROOT),
                        mode=values.get("desired.resource.001.resourceMode", "CREATE"))
    output = "\n".join(["### EC2.VPCEndpoint: resource", *row_table(indexed_rows(rows, "EC2.VPCEndpoint"))])
    assert "| Name |" not in output and "ec2-name-tag:" not in output
    print("VPCEndpoint Name tag: PASS (one row, mixed tags, exact round trip, IMPORT and invalid metadata)")

def check_athena_configuration_display():
    kind = "Athena.WorkGroup"
    prefix = kind + ".WorkGroupConfiguration."
    fields = [line.partition("=")[0] for line in
              (ROOT / 'framework/materials/aws/Athena_WorkGroup.properties').read_text(encoding="utf-8").splitlines()]
    rows = [[str(index), field, "値", "設定の説明"] for index, field in enumerate(fields, 1)]
    displayed = display_rows(kind, rows)
    encryption_labels = {
        prefix + "ResultConfiguration.EncryptionConfiguration.EncryptionOption": "ResultConfiguration.Encryption.Option",
        prefix + "ResultConfiguration.EncryptionConfiguration.KmsKey": "ResultConfiguration.Encryption.KmsKey",
    }
    for original, shown in zip(rows, displayed, strict=False):
        ancestor = kind + "."
        if original[1].startswith(prefix):
            ancestor = prefix
        expected = encryption_labels.get(original[1], original[1].removeprefix(ancestor))
        assert shown == [original[0], expected, *original[2:]], (original, shown)
        restored = formal_property(shown[1], kind)
        assert restored == original[1]


def check_catalog_display_order():
    values = model("vpc", "EC2.VPC", "vpc-app-dev", [
        ("EnableDnsSupport", "`true`", "DNS解決"),
        ("Name", "`vpc-app-dev`", "ネットワーク名"),
        ("Tags[].Key", '"purpose"', "タグ名"),
        ("Tags[].Value", '"first"', "最初の用途"),
        ("Tags[].Key", '"owner"', "タグ名"),
        ("Tags[].Value", '"second"', "次の用途"),
        ("CidrBlock", "`10.0.0.0/16`", "アドレス範囲"),
        ("VpcId", "[EC2_VPC_001](vpc.md#vpc-vpc-app-dev)", "ネットワークID"),
        ("EnableDnsHostnames", "`true`", "DNS名"),
    ], logical_id="Vpc")
    values.update({"observed.row.001-008.property": "EC2.VPC.VpcId",
                   "observed.row.001-008.value": "`vpc-123`",
                   "observed.row.001-008.comment": "ネットワークID"})
    original = dict(values)
    shown = catalog_display_rows(resource_rows(values, "001", "EC2.VPC", ROOT), "EC2.VPC", ROOT)
    assert [row[0] for row in shown] == ["001-002", "001-008", "001-007", "001-009", "001-001", "001-003", "001-004", "001-005", "001-006"]
    assert not catalog_order_errors("EC2.VPC", shown, ROOT)
    assert values == original
    for kind, fields in (("QuickSight.DataSource", ["Type", "Name", "DataSourceParameters.AthenaParameters.WorkGroup", "AwsAccountId", "DataSourceId"]),
                         ("S3.Bucket", ["Tags[].Key", "Tags[].Value", "Region", "BucketName"]),
                         ("CodeBuild.Project", ["VpcConfig.VpcId", "VpcConfig.SecurityGroupIds", "VpcConfig.Subnets", "Name"])):
        rows = [[str(number), kind + "." + field, "値", "説明"] for number, field in enumerate(fields)]
        shown = catalog_display_rows(rows, kind, ROOT)
        assert not catalog_order_errors(kind, shown, ROOT)
        assert sorted(row[0] for row in shown) == sorted(row[0] for row in rows)
        if kind == "S3.Bucket":
            assert [row[1] for row in shown[:2]] == [kind + ".BucketName", kind + ".Region"]
    sg = [["1", "EC2.SecurityGroup.GroupDescription", "値", "説明"]]
    assert catalog_display_rows(sg, "EC2.SecurityGroup", ROOT) is sg
    print("Catalog display order: PASS (original row IDs, arrays and special positions)")

def check_optional_naming_suffix():
    patterns = (
        ("CloudFormation.Stack", "StackName", "cfn-stack-{{application}}-{{environment}}-{{purpose}}[-{{number}}][-{{suffix}}]"),
        ("CodeCommit.Repository", "RepositoryName", "ccmt-{{application}}[-{{environment}}]-{{purpose}}[-{{suffix}}]"),
        ("S3.Bucket", "BucketName", "{{application}}-{{environment}}-{{purpose}}-{{account_id}}[-{{suffix}}]"),
        ("IAM.Role", "RoleName", "{{application}}-{{environment}}-{{purpose}}Role[-{{suffix}}]"),
        ("Athena.WorkGroup", "Name", "athwg-{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]"),
        ("Glue.SecurityConfiguration", "Name", "glsc[-{{number}}][-{{suffix}}]"),
        ("CodeBuild.Project", "Name", "cbld-{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]"),
        ("CodePipeline.Pipeline", "Name", "cpln-{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]"),
        ("CloudTrail.Trail", "TrailName", "ctrail-{{application}}-{{environment}}[-{{suffix}}]"),
        ("Macie.ClassificationJob", "name", "macie-{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]"),
    )
    for kind, field, pattern in patterns:
        naming = "\n".join(path.read_text(encoding="utf-8") for path in naming_rule_files(ROOT, kind.partition(".")[0]))
        assert f"| `{kind}` | `{field}` | `{pattern}` |" in naming, kind
        assert field in naming_targets(ROOT, kind.partition(".")[0])[kind], kind
    schema = DesignSchemaCatalog(ROOT)
    for suffix in ("", "-aaaaaa"):
        name = "venusinf-dev-DataManagementRole" + suffix
        assert not schema.literal_errors("IAM.Role", "RoleName", name)
        rows = [["1", "RoleName", f"`{name}`", "データ管理のロール名"]]
        assert resource_display_selection(ROOT, "IAM.Role", rows, None, "CREATE", 1) == (name, name)


def check_secret_naming_values():
    secret_rules = naming_rule_files(ROOT, "SecretsManager")
    assert [path.name for path in secret_rules] == ["aws-resource-naming.md", "SecretsManager.md"]
    rules = secret_rules[1].read_text(encoding="utf-8")
    assert "| `SecretsManager.Secret` | `Name` | `{{application}}/{{environment}}/{{purpose_path}}` |" in rules
    for constraint in ("`application` as the first level", "`environment` as the second level",
                       "one or more levels", "no upper limit on the number of levels",
                       "do not force distinct purposes into the third level", "lower-kebab-case",
                       "CREATE `SecretsManager.Secret.Name` must not end in ASCII `-`",
                       "Empty components, `//`, and leading or trailing `/` are prohibited",
                       "1–512 characters", "ASCII letters, numbers, and `/_+=.@-`",
                       "Do not reject names solely for ending in a hyphen followed by 6 characters",
                       "IMPORT retains actual/current names"):
        assert constraint in rules
    for invalid in ("app/dev/credentials-", "app/dev/snowflake/keypair-",
                    "app/dev//keypair", "/app/dev/credentials", "app/dev/credentials/"):
        assert f"`{invalid}`" in rules.partition("Invalid examples:")[2]
    schema = DesignSchemaCatalog(ROOT)
    for name in ("sample/dev/db-credentials", "app/dev/credentials", "app/dev/snowflake/keypair",
                 "app/dev/snowflake/keypair/lambda", "app/dev/snowflake/keypair/lambda/rotation",
                 "app/dev/snowflake/keypair/lambda/rotation/credentials",
                 "app/dev/snowflake/keypair/lambda-skbm1r"):
        for field in ("Name", "SecretsManager.Secret.Name"):
            assert not naming_errors(ROOT, "SecretsManager.Secret", [["1", field, f"`{name}`", "認証情報の名前"]])
        assert not schema.literal_errors("SecretsManager.Secret", "Name", name)
        assert resource_display_selection(ROOT, "SecretsManager.Secret", [["1", "Name", f"`{name}`", "名前"]], None, "CREATE", 1) == (name, name)
    for invalid in ("", "UNSET", "PENDING_DEPLOY"):
        with pytest.raises(ValueError):
            resource_display_selection(ROOT, "SecretsManager.Secret", [["1", "Name", f"`{invalid}`", "名前"]], None, "CREATE", 1)
    name = "Legacy_Secret.Name"
    rows = [["1", "Name", f"`{name}`", "既存の名前"]]
    with patch("model.validation.naming_targets", return_value={}):
        assert naming_errors(ROOT, "SecretsManager.Secret", rows) == ["naming rule missing: SecretsManager.Secret: Name"]
        assert not naming_errors(ROOT, "SecretsManager.Secret", rows, "IMPORT")
    assert resource_display_selection(ROOT, "SecretsManager.Secret", rows, None, "IMPORT", 1) == (name, name)


def check_kms_policy_accounts():
    identity, execution = "111111111111", "222222222222"
    target = {"environment": "dev", "awsAccountId": identity, "awsExecutionAccountId": execution,
              "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
    root_arn = f"arn:aws:iam::{execution}:root"
    macie_arn = f"arn:aws:iam::{execution}:role/aws-service-role/macie.amazonaws.com/AWSServiceRoleForAmazonMacie"
    policy = {"Version": "2012-10-17", "Id": "key-default", "Statement": [
        {"Sid": "EnableIamUserPermissions", "Effect": "Allow", "Principal": {"AWS": root_arn}, "Action": "kms:*", "Resource": "*"},
        {"Sid": "AllowMacieToDecryptObjects", "Effect": "Allow", "Principal": {"AWS": macie_arn}, "Action": "kms:Decrypt", "Resource": "*"},
    ]}
    values = model("kms", "KMS.Key", "test-key", [
        ("KeyId", '[Key](#kms-test-key)', "キーを識別するID"),
        ("KeyPolicy", "[Policy](kms/test-key-policy.json)", "キーの利用権限"),
    ], "Key", "test-key")
    values.update({"observed.row.001-001.property": "KMS.Key.KeyId", "observed.row.001-001.value": "`PENDING_DEPLOY`",
                   "observed.row.001-001.comment": "キーを識別するID"})
    document_key, comment_key = "desired.row.001-002.document", "desired.row.001-002.comment"
    values[document_key] = json.dumps(policy, separators=(",", ":"))
    original = dict(values)
    validate_kms_policy_accounts(values, target)
    assert values == original and all(s["Resource"] == "*" for s in policy["Statement"])

    for number in (0, 1):
        invalid = json.loads(values[document_key])
        invalid["Statement"][number]["Principal"]["AWS"] = invalid["Statement"][number]["Principal"]["AWS"].replace(execution, identity)
        for array in (False, True):
            wrong = json.loads(json.dumps(invalid))
            arn = wrong["Statement"][number]["Principal"]["AWS"]
            if array:
                wrong["Statement"][number]["Principal"]["AWS"] = [root_arn, arn]
            candidate = {**values, document_key: json.dumps(wrong)}
            for comment in ("キーの利用権限", f"cross-account:{root_arn}", f"cross-account:{arn}extra"):
                with pytest.raises(ValueError) as error:
                    validate_kms_policy_accounts({**candidate, comment_key: comment}, target)
                assert f"Statement[{number + 1}]" in str(error.value) and execution in str(error.value)
            validate_kms_policy_accounts({**candidate, comment_key: f"外部アカウントへ復号を許可 cross-account:{arn}"}, target)
            validate_kms_policy_accounts({**candidate, "desired.resource.001.resourceMode": "IMPORT"}, target)
    fallback = {key: value for key, value in target.items() if key != "awsExecutionAccountId"}
    validate_kms_policy_accounts({**values, document_key: values[document_key].replace(execution, identity)}, fallback)
    other = json.loads(values[document_key])
    other["Statement"] = {"Effect": "Allow", "Principal": {"Service": "logs.ap-northeast-1.amazonaws.com"}, "Action": "kms:Decrypt", "Resource": "*"}
    validate_kms_policy_accounts({**values, document_key: json.dumps(other)}, target)
    other["Statement"]["Principal"] = {"AWS": macie_arn.replace("macie.amazonaws.com", "macie.me-south-1.amazonaws.com")}
    validate_kms_policy_accounts({**values, document_key: json.dumps(other)}, target)




@pytest.mark.parametrize('kind, field', [('CodeBuild.Project', 'Name'), ('IAM.Role', 'RoleName')])
def check_required_resource_names(kind, field):
    name = 'app-dev-worker'
    named = (field, f'`{name}`')
    invalid = [[], [named, named], [('name', f'`{name}`')],
               [('Tags[].Key', '`Name`'), ('Tags[].Value', f'`{name}`')]]
    invalid += [[(field, value)] for value in (
        '', '``', '`   `', '`UNSET`', '` UNSET `', '`PENDING_DEPLOY`', '`Pending`',
        '`TBD`', '`none`', '`未確定`', '`{{application}}`', '[worker](#resource-worker)',
    )]
    for fields in invalid:
        for prefix in ('', kind + '.'):
            rows = [[str(n), prefix + prop, value, '名前'] for n, (prop, value) in enumerate(fields, 1)]
            assert naming_errors(ROOT, kind, rows), (kind, rows)
            with pytest.raises(ValueError, match=kind + '.' + field):
                resource_display_selection(ROOT, kind, rows, 'fallback-label', 'CREATE', 1)


@pytest.mark.parametrize('kind', ['EC2.VPCEndpoint', 'EC2.Instance'])
def check_required_name_tag(kind):
    tags = [('Tags[].Key', '`Name`'), ('Tags[].Value', '`app-dev-worker`')]
    confirmed = [[str(number), kind + '.' + prop, value, '名前'] for number, (prop, value) in enumerate(tags, 1)]
    assert resource_display_name(kind, confirmed) == 'app-dev-worker'
    assert resource_display_selection(ROOT, kind, confirmed, 'fallback-label', 'CREATE', 1) == ('app-dev-worker', 'app-dev-worker')
    valid_findings = Findings(ROOT)
    design_tables.check_required_name_tag(ROOT / 'docs/designs/dev/123456789012/ec2.md', kind, 'app-dev-worker', confirmed,
                                         findings=valid_findings, schema_catalog=DesignSchemaCatalog(ROOT))
    assert not valid_findings.errors, valid_findings.errors
    invalid = [[], tags[:1], [('Tags[].Key', '`name`'), tags[1]],
               [('Tags[].Key', '`NAME`'), tags[1]], tags * 2,
               [('Name', '`app-dev-worker`')], [('Name', '`app-dev-worker`'), *tags],
               [('Tags', '`{"Name":"app-dev-worker"}`')],
               [tags[0], ('ImageId', '`ami-example`'), tags[1]]]
    invalid += [[tags[0], ('Tags[].Value', value)] for value in (
        '', '``', '`   `', '`UNSET`', '` UNSET `', '`PENDING_DEPLOY`', '`Pending`',
        '`TBD`', '`none`', '`not-used`', '`{{application}}`', '[worker](#worker)',
    )]
    path = ROOT / 'docs/designs/dev/123456789012/ec2.md'
    for fields in invalid:
        rows = [[str(n), kind + '.' + prop, value, '名前'] for n, (prop, value) in enumerate(fields, 1)]
        findings = Findings(ROOT)
        design_tables.check_required_name_tag(path, kind, 'app-dev-worker', rows,
                                             findings=findings, schema_catalog=DesignSchemaCatalog(ROOT))
        assert findings.errors, fields
        with pytest.raises(ValueError) as error:
            resource_display_name(kind, rows)
        assert str(error.value) in findings.errors[0]


def check_naming_exclusions():
    schema = DesignSchemaCatalog(ROOT)
    for kind, field in (
        ('IAM.ManagedPolicy', 'ManagedPolicyName'), ('IAM.User', 'UserName'),
        ('IAM.InstanceProfile', 'InstanceProfileName'), ('Config.ConfigurationRecorder', 'Name'),
        ('Config.DeliveryChannel', 'Name'), ('Glue.Connection', 'ConnectionInput.Name'),
        ('GuardDuty.Detector', 'Name'), ('Glue.Database', 'DatabaseInput.Name'),
        ('Glue.Table', 'TableInput.Name'), ('Route53.HostedZone', 'Name'), ('Route53.RecordSet', 'Name'),
    ):
        for prefix in ('', kind + '.'):
            rows = [['1', prefix + field, '`example`', '名前']]
            assert not naming_errors(ROOT, kind, rows)
            if kind == 'GuardDuty.Detector':
                with pytest.raises(ValueError, match='display Mapping property missing'):
                    display_rows(kind, [['1', kind + '.Name', '`example`', '名前']])
                continue
            assert resource_display_selection(ROOT, kind, rows, None, 'CREATE', 1) == ('example', 'example')
            for invalid in ('', 'UNSET', 'PENDING_DEPLOY'):
                with pytest.raises(ValueError, match='must be confirmed'):
                    resource_display_selection(ROOT, kind, [['1', prefix + field, f'`{invalid}`', '名前']], None, 'CREATE', 1)
        assert naming_errors(ROOT, kind, [['1', 'Tags[].Key', '"Name"', 'タグ'], ['2', 'Tags[].Value', '"example"', '名前']]) == [f'naming rule missing: {kind}: Name tag']
    assert naming_errors(ROOT, 'IAM.Group', [['1', 'GroupName', '`example`', '名前']]) == ['naming rule missing: IAM.Group: GroupName']
    assert naming_errors(ROOT, 'Glue.Job', [['1', 'name', '`example`', '名前']]) == ['naming rule missing: Glue.Job: name']
    assert schema.literal_errors('Route53.HostedZone', 'Name', 'x' * 1025)
    for kind, field in (('Config.ConfigurationRecorder', 'Name'), ('SecretsManager.Secret', 'Name'),
                        ('Glue.Database', 'DatabaseInput.Name'), ('Glue.Table', 'TableInput.Name')):
        assert schema.literal_errors(kind, field, 'UNSET')
    with pytest.raises(KeyError):
        schema.property_schema('GuardDuty.Detector', 'Name')


@pytest.mark.parametrize('kind, rows', [
    ('KinesisFirehose.DeliveryStream', [('DeliveryStreamName', '`dummy`'), ('DeliveryStreamType', '`DirectPut`'),
                                    ('S3DestinationConfiguration.BucketARN', 'Pending'), ('S3DestinationConfiguration.RoleARN', 'Pending')]),
    ('Config.ConfigurationRecorder', [('Name', '`default`'), ('RoleARN', 'Pending')]),
])
def check_import_pending_properties(kind, rows):
    values = model('service', kind, 'name', [(prop, value, '設定値') for prop, value in rows])
    values['desired.resource.001.resourceMode'] = 'IMPORT'
    before = dict(values)
    assert not validate_required_properties(values, ROOT)
    assert values == before
    create = values | {'desired.resource.001.resourceMode': 'CREATE'}
    if kind == 'Config.ConfigurationRecorder':
        with pytest.raises(ValueError, match='required provider schema property missing.*RoleARN'):
            validate_required_properties(create, ROOT)
    else:
        assert validate_required_properties(create, ROOT)
    field = rows[-1][0]
    assert not is_import_pending_reference(kind + '.' + field, '`arn:aws:s3:::dummy`')
    assert not is_import_pending_reference(kind + '.' + field, '[dummy](service.md#dummy)')
    shown = display_rows(kind, resource_rows(values, '001', kind, ROOT), mode='IMPORT')
    assert any(row[2] == 'Pending' for row in shown)


def check_stack_policy():
    values = {'desired.deployment.maxConcurrentStacks': '3'}
    for i, (name, order, template) in enumerate((('app-b-01', '20', 'app.yaml'), ('network', '10', 'network.yaml'), ('app-a', '20', 'app.yaml')), 1):
        values.update({f'desired.stack.{i:03d}.{field}': value for field, value in {
            'name': 'cfn-stack-app-dev-' + name, 'template': template, 'parameters': name + '.json',
            'deployOrder': order, 'placementName': name}.items()})
        values[f'display.stack.{i:03d}.comment'] = name + 'を配置するstack'
    before = dict(values)
    limit, stacks = stack_model(values)
    assert limit == 3 and values == before
    assert [entry['name'] for _, entry in stacks] == ['cfn-stack-app-dev-network', 'cfn-stack-app-dev-app-a', 'cfn-stack-app-dev-app-b-01']
    path = ROOT / 'docs/designs/dev/123456789012/cloudformation-stacks.md'
    rendered = model_design.stack_markdown(path, values, ROOT)
    assert '## Deployment設定' not in rendered and '| MaxConcurrentStacks |' not in rendered
    assert '<!-- max-concurrent-stacks: 3 -->' in rendered and '| Deploy<br>Order |' in rendered
    assert 'dependsOn' not in rendered
    with patch('design_layout.input_text', return_value=rendered):
        assert stack_deployment_policy(path) == limit
        restored = stack_design(path)
    assert [{key: value for key, value in entry.items() if key != 'comment'} for entry in restored] == [entry for _, entry in stacks]
    assert [entry['comment'] for entry in restored] == ['networkを配置するstack', 'app-aを配置するstack', 'app-b-01を配置するstack']
    assert stack_model({key: value for key, value in values.items() if key != 'desired.deployment.maxConcurrentStacks'})[0] == 1
    for field, value in (('desired.stack.001.deployOrder', '0'), ('desired.stack.001.deployOrder', '-1'),
                         ('desired.stack.001.deployOrder', 'abc'), ('desired.deployment.maxConcurrentStacks', '0'),
                         ('desired.deployment.maxConcurrentStacks', '-1'), ('desired.deployment.maxConcurrentStacks', '1.5')):
        with pytest.raises(ValueError, match='integer >= 1'):
            stack_model(values | {field: value})
    with pytest.raises(ValueError, match='requires only'):
        stack_model({key: value for key, value in values.items() if key != 'desired.stack.001.deployOrder'})
    with pytest.raises(ValueError, match='unknown stack design'):
        stack_model(values | {'desired.mapping.001.stack': 'cfn-stack-app-dev-network'})
    for invalid in ('', 'invalid', 'stack-resource', 'stack-Bad_Id', ' stack-Resource', 'stack-Resource '):
        with pytest.raises(ValueError):
            cfn_resource_identity(invalid)
    assert cfn_resource_identity('stack-Resource-With-Hyphens') == ('stack-Resource-With', 'Hyphens')


def check_observed_arn_authority():
    path = ROOT / 'model/dev/123456789012/secrets-manager.properties'
    view = ROOT / 'docs/designs/dev/123456789012/secrets-manager.md'
    arn = 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:actual-id'
    values = model('secrets-manager', 'SecretsManager.Secret', 'secret', [('Id', '[SecretsManager_Secret_001](#secret)', 'actual ID')])
    values['observed.row.001-001.value'] = '`' + arn + '`'
    for mode in ('IMPORT', 'CREATE'):
        candidate = values | {'desired.resource.001.resourceMode': mode}
        findings = Findings(ROOT)
        with patch('model.sources.model_exists', return_value=True):
            design_validation.check_observed_values([path], findings=findings, root=ROOT, scope=None, design_sources={view: candidate})
        assert any('generated ARN persisted' in error for error in findings.errors) == (mode == 'CREATE')
        with patch('validation.design_tables.catalog_order_errors', return_value=[]):
            design_tables.check_generated_identifier(view, 'SecretsManager.Secret', 'SecretsManager_Secret_001',
                [['1', 'SecretsManager.Secret.Id', '`' + arn + '`', 'actual']], {'SecretsManager.Secret': {'SecretsManager.Secret.Id'}},
                findings=findings, values=candidate)
        assert any('generated ARN is forbidden' in error for error in findings.errors) == (mode == 'CREATE')


def check_desired_only_identifier_reference():
    values = model('quicksight', 'QuickSight.DataSource', 'source', [
        ('Permissions[].Principal', '[gr-dev-finance](quicksight.md#quicksight-gr-dev-finance)', '分析グループへの権限')])
    expected = values['desired.row.001-001.value']
    assert resource_rows(values, '001', 'QuickSight.DataSource', ROOT)[0][2] == expected
    values['observed.row.001-001.value'] = 'gr-dev-finance'
    before = dict(values)
    assert resource_rows(values, '001', 'QuickSight.DataSource', ROOT)[0][2] == expected
    assert values == before


def check_loggroup_invalid_values():
    schema = DesignSchemaCatalog(ROOT)
    for value in ('31', 'not-a-number'):
        assert schema.literal_errors('Logs.LogGroup', 'RetentionInDays', value)
    with pytest.raises(ValueError, match='must be confirmed'):
        resource_display_selection(ROOT, 'Logs.LogGroup', [['1', 'LogGroupName', '``', '名前']], None, 'CREATE', 1)



def check_authoritative_display_identity(tmp_path):
    detector = model('guardduty', 'GuardDuty.Detector', 'guardduty.detector', [('Id', '[GuardDuty.Detector](#detector)', '識別子')])
    detector['observed.row.001-001.value'] = '`0123456789abcdef0123456789abcdef`'
    before = dict(detector)
    rows = resource_rows(detector, '001', 'GuardDuty.Detector', ROOT)
    resource = dict(entries(detector, 'desired.resource.'))['001']
    assert model_design.display_name(detector, '001', resource, rows, ROOT) == ('GuardDuty.Detector', None)
    assert model_design.display_name(detector | {'display.resource.001.label': 'primary-detector'}, '001', resource, rows, ROOT) == ('primary-detector', None)
    assert detector == before
    kind = 'GuardDuty.MalwareProtectionPlan'
    values = {}
    lines = []
    for number, label in enumerate(('BuildProtectionPlan', 'QuarantineProtectionPlan'), 1):
        identity = f'{number:03d}'
        logical = f'GuardDuty_MalwareProtectionPlan_{identity}'
        anchor = 'resource-' + logical
        values.update({f'desired.resource.{identity}.resourceType': kind,
                       f'desired.resource.{identity}.logicalId': logical,
                       f'desired.resource.{identity}.anchor': anchor,
                       f'display.resource.{identity}.label': label,
                       'desired.service.identity.lastAllocated': '{"GuardDuty.MalwareProtectionPlan":2}'})
        lines.extend([f'<!-- resource-logical-id: {logical} -->', f'<a id="{anchor}"></a>', f'### {kind}: {label}'])
    document = '\n'.join(lines)
    path = tmp_path / 'docs/designs/dev/team/guardduty.md'
    metadata = {path: ('guardduty', (kind,))}
    candidates = [(values, document, None)]
    for identity in ('001', '002'):
        key = f'display.resource.{identity}.label'
        candidates.append(({name: value for name, value in values.items() if name != key}, document, 'display'))
        for label in ('', 'UNSET', 'PENDING_DEPLOY', 'wrong-label'):
            candidates.append((values | {key: label}, document, 'display'))
        logical = f'GuardDuty_MalwareProtectionPlan_{identity}'
        candidates.append((values, document.replace(f'<!-- resource-logical-id: {logical} -->', ''), 'hidden logical ID'))
        for field, value in (('resourceType', 'GuardDuty.Detector'), ('logicalId', 'OtherPlan')):
            invalid = values | {f'desired.resource.{identity}.{field}': value}
            with pytest.raises(ValueError, match='logicalId'):
                resource_index(invalid)
            candidates.append((invalid, document, 'hidden logical ID'))
    renumbered = {key.replace('.001', '.007', 1): value for key, value in values.items()}
    candidates.append((renumbered, document, None))
    for candidate, markdown, diagnostic in candidates:
        before = dict(candidate)
        findings = Findings(tmp_path)
        with patch.object(design_validation, 'input_text', return_value=markdown), \
             patch('model.projection.bound_resource_anchors', return_value={}):
            design_validation.check_resource_names(metadata, [path], design_sources={path: candidate},
                findings=findings, root=tmp_path, scope=None, definitions_root=ROOT)
        if diagnostic is None:
            assert not findings.errors, findings.errors
        else:
            assert any(diagnostic in error for error in findings.errors), findings.errors
        assert candidate == before


@pytest.mark.parametrize('kind, name, field, diagnostic', [
    ('IAM.Role', 'app-dev-worker-role', 'RoleName', 'RoleName'),
    ('EC2.Instance', 'app-dev-worker', 'InstanceId', 'Name tag'),
    ('EC2.VPCEndpoint', 'vpce-app-dev-s3', 'Id', 'Name tag'),
    ('GuardDuty.Detector', 'GuardDuty.Detector', 'Id', 'nameless resource link'),
])
def check_navigation_display_labels(tmp_path, kind, name, field, diagnostic):
    path = tmp_path / 'docs/designs/dev/team/resource.md'
    logical = kind.replace('.', '_') + '_001'
    rows = [['1', kind + '.' + field, '`physical-id`', '識別子']]
    if kind == 'IAM.Role':
        rows = [['1', kind + '.RoleName', f'`{name}`', '名前']]
    lines = [f'<!-- resource-logical-id: {logical} -->', '<a id="resource"></a>', f'### {kind}: {name}', *row_table(rows)]
    for label in (name, logical, 'wrong-label', 'physical-id', '/service-role/' + name):
        index = DesignIndex(ROOT)
        index.get(path, text='\n'.join([*lines, f'参照: [{label}](#resource)']))
        findings = Findings(tmp_path)
        with patch('model.projection.bound_resource_anchors', return_value={}), \
             patch('model.sources.model_exists', return_value=False), \
             patch('validation.design_links.input_is_file', side_effect=lambda target: target == path):
            validate_design_links({kind: {kind + '.' + field}}, [path], design_index=index, design_sources={path: {}},
                               findings=findings, root=tmp_path, scope=None, definitions_root=ROOT)
        assert not findings.errors, findings.errors
        messages = [warning['message'] for warning in findings.warnings]
        if label == name:
            assert not messages, messages
        else:
            assert any(diagnostic in message for message in messages), messages

    if kind != 'IAM.Role':
        source = path.with_name('references.md')
        index = DesignIndex(ROOT)
        index.get(path, text='\n'.join(lines))
        index.get(source, text='\n'.join(row_table([['1', kind + '.' + field, '[physical-id](resource.md#resource)', '参照するID']])))
        findings = Findings(tmp_path)
        with patch('model.projection.bound_resource_anchors', return_value={}), \
             patch('model.sources.model_exists', return_value=False), \
             patch('validation.design_links.input_is_file', side_effect=lambda target: target in {path, source}):
            validate_design_links({kind: {kind + '.' + field}}, [path, source], design_index=index,
                                  design_sources={path: {}, source: {}}, findings=findings,
                                  root=tmp_path, scope=None, definitions_root=ROOT)
        assert not findings.errors and not findings.warnings, (findings.errors, findings.warnings)



def check_cfn_identity_inputs(tmp_path):
    values = model('vpc', 'EC2.VPC', 'vpc', [])
    values['desired.resource.001.cfn-logicalId'] = 'existing-stack-Vpc'
    path = tmp_path / 'docs/designs/dev/team/vpc.md'
    resources = list(entries(values, 'desired.resource.'))
    with patch('model.validation.design_target', return_value={'iacEngine': 'terraform', 'awsAccountId': '123456789012'}):
        with pytest.raises(ValueError, match='forbidden for Terraform'):
            validate_resource_identities(path, values, tmp_path, resources, definitions_root=ROOT)
        without = {key: value for key, value in values.items() if not key.endswith('.cfn-logicalId')}
        validate_resource_identities(path, without, tmp_path, list(entries(without, 'desired.resource.')), definitions_root=ROOT)
    stacks = {'desired.stack.001.name': 'existing-stack', 'desired.stack.001.template': 'network.yaml',
              'desired.stack.001.parameters': 'network.json', 'desired.stack.001.deployOrder': '1'}
    with patch('model.validation.design_target', return_value={'iacEngine': 'cloudformation', 'awsAccountId': '123456789012'}), \
         patch('model.validation.input_is_file', return_value=True), \
         patch('model.files.read_model', return_value=serialize(stacks)), \
         patch('model.projection.bound_stack_names', return_value={'existing-stack'}):
        validate_resource_identities(path, values, tmp_path, resources, definitions_root=ROOT)
        for invalid, message in (('invalid', 'invalid cfn-logicalId'), ('absent-Vpc', 'undeclared stack')):
            candidate = values | {'desired.resource.001.cfn-logicalId': invalid}
            with pytest.raises(ValueError, match=message):
                validate_resource_identities(path, candidate, tmp_path, list(entries(candidate, 'desired.resource.')), definitions_root=ROOT)


if __name__ == '__main__':
    raise SystemExit(run(__file__))
