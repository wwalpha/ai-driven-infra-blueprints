"""CloudFormation syntax, Environment semantics and stack mappings."""

from __future__ import annotations
import json
from test_support.validator import MODULE, SCRIPT, project, write


def check_cloudformation_yaml_rules() -> None:
    trust_body = """        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: ec2.amazonaws.com
            Action: sts:AssumeRole
"""
    with project() as root:
        template = root / "infra/cloudformation/templates/iam.yaml"
        template.parent.mkdir(parents=True)

        def errors(yaml: str) -> list[str]:
            write(template, yaml)
            validator = MODULE.Validator(root)
            validator.check_cloudformation_yaml_rules()
            return validator.errors

        valid = (
            "Resources:\n"
            "  RoleA:\n"
            "    Type: AWS::IAM::Role\n"
            "    Properties:\n"
            "      AssumeRolePolicyDocument:\n"
            + trust_body
            + "\n  RoleB:\n"
            "    Type: AWS::IAM::Role\n"
            "    Properties:\n"
            "      AssumeRolePolicyDocument:\n"
            + trust_body
            + "      JobId: !Select [0, !Split ['|', !Ref GlueJob]]\n"
            "      Imported: !ImportValue fixed-export\n"
            "      Description: 'Fn::Select: &shared *alias <<: is text'\n"
            "      UserData: |\n"
            "        Ref: &shared *alias <<: is text too\n"
            "      Extra: {Fn::Length: [a, b]}\n"
            "\n  Consumer:\n"
            "    Type: AWS::EC2::Instance\n"
        )
        assert not errors(valid), errors(valid)
        suffix_import = valid.replace("Imported: !ImportValue fixed-export", "Imported: !ImportValue {Fn::Join: ['', ['KmsAppKeyArn', !Ref Suffix]]}")
        assert not errors(suffix_import), errors(suffix_import)
        assert any("must use YAML short form" in error for error in errors(suffix_import.replace("!Ref Suffix", "{Ref: Suffix}")))
        export_suffix_import = suffix_import.replace("!Ref Suffix", "!Ref ExportSuffix")
        assert not errors(export_suffix_import), errors(export_suffix_import)
        assert any("must use YAML short form" in error for error in errors(export_suffix_import.replace("!Ref ExportSuffix", "{Ref: ExportSuffix}")))
        for parameter in ("OtherSuffix", "ExportVersion", "NamePart", "namePart2"):
            parameter_import = suffix_import.replace("!Ref Suffix", f"!Ref {parameter}")
            assert not errors(parameter_import), errors(parameter_import)
        assert any("must use YAML short form" in error for error in errors(suffix_import.replace("!Ref Suffix", "!Ref Invalid_Name")))
        assert any("must use YAML short form" in error for error in errors(suffix_import.replace("['',", "['-',")))
        for imported in (
            "Imported:\n        Fn::ImportValue: !Sub 'VpcId${Suffix}'",
            'Imported:\n        Fn::ImportValue: !Sub "SubnetId${OtherSuffix}"',
            "Imported:\n        Fn::ImportValue:\n          # Import name\n          !Sub 'VpcId${NamePart}'",
            "Imported:\n        'Fn::ImportValue': !Sub 'VpcId${Suffix}'",
            'Imported: {"Fn::ImportValue": !Sub "VpcId${Suffix}"}',
            "Imported: !ImportValue {Fn::Sub: 'VpcId${Suffix}'}",
            'Imported: !ImportValue {Fn::Sub: "SubnetId${OtherSuffix}"}',
            "Imported: !ImportValue {'Fn::Sub': 'VpcId${NamePart}'}",
            'Imported: !ImportValue {"Fn::Sub": "VpcId${Suffix}"}',
            "Imported: !ImportValue {Fn::Sub: ['VpcId${Part}', {Part: !Ref Suffix}]}",
        ):
            sub_import = valid.replace("Imported: !ImportValue fixed-export", imported)
            assert not errors(sub_import), errors(sub_import)
        assert any(
            "resources must be separated by a blank line" in error
            for error in errors(valid.replace("\n  RoleB:", "  RoleB:", 1))
        )
        for bad in (
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId:\n        Fn::Select:\n          - 0\n          - Ref: GlueJob"),
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Select: [0, {Ref: GlueJob}]}"),
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {'Fn::Select': [0, !Ref GlueJob]}"),
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Join: ['-', [a, b]]}"),
            valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Sub: '${AWS::Region}'}"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported:\n        Fn::ImportValue: fixed-export"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported:\n        Fn::ImportValue: {Fn::Sub: 'VpcId${Suffix}'}"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported:\n        Fn::ImportValue:\n        Description: !Sub 'VpcId${Suffix}'"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported:\n        Fn::ImportValue:\n          Ref: Suffix"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported: !ImportValue fixed-export # Fn::ImportValue: !Sub 'text'\n      ExtraImport: {Fn::Sub: text}"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported: 'Fn::ImportValue: !Sub text'\n      ExtraImport: {Fn::Sub: text}"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported: !ImportValue {Fn::Sub: ['VpcId${Part}', {Part: {Ref: Suffix}}]}"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported: !ImportValue {Fn::Sub: 'VpcId${Suffix}'}\n      ExtraImport: {Fn::Sub: text}"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported: '!ImportValue {Fn::Sub: text}'\n      ExtraImport: {Fn::Sub: text}"),
            valid.replace("Imported: !ImportValue fixed-export", "Imported: !ImportValue fixed-export # !ImportValue {Fn::Sub: text}\n      ExtraImport: {Fn::Sub: text}"),
        ):
            assert any("must use YAML short form" in error for error in errors(bad)), errors(bad)

        block_array = valid.replace(
            "JobId: !Select [0, !Split ['|', !Ref GlueJob]]",
            "JobId: !Select\n        - 0\n        - !Split ['|', !Ref GlueJob]",
        )
        assert any("must use YAML flow form" in error for error in errors(block_array)), errors(block_array)
        join_block_array = valid.replace(
            "JobId: !Select [0, !Split ['|', !Ref GlueJob]]",
            "JobId: !Join\n        - '-'\n        - [a, b]",
        )
        assert any("must use YAML flow form" in error for error in errors(join_block_array)), errors(join_block_array)

        for forbidden in (
            valid.replace("AssumeRolePolicyDocument:\n", "AssumeRolePolicyDocument: &sharedTrustPolicy\n", 1),
            valid.replace("AssumeRolePolicyDocument:\n" + trust_body, "AssumeRolePolicyDocument: *sharedTrustPolicy\n", 1),
            valid.replace("AssumeRolePolicyDocument:\n" + trust_body, "AssumeRolePolicyDocument:\n        <<: {}\n", 1),
        ):
            assert any("anchor/alias/merge is forbidden" in error for error in errors(forbidden)), errors(forbidden)
        different = valid.replace("ec2.amazonaws.com", "lambda.amazonaws.com", 1)
        assert not errors(different), errors(different)

        consumer = "\n  Consumer:\n    Type: AWS::EC2::Instance\n"
        boundary_error = "must share the consuming resource template"
        marker = "Metadata:\n  RolePlacement: standalone\n"
        role_only = "Resources:\n  Role:\n    Type: AWS::IAM::Role\n"
        assert any("Role-only template requires" in error for error in errors(valid.replace(consumer, "")))
        assert any("Role-only template requires" in error for error in errors(role_only))
        assert not errors(marker + role_only)
        assert not errors(
            marker + role_only + "\n  Policy:\n    Type: AWS::IAM::Policy\n"
        )
        assert not errors(
            marker + role_only + "\n  Policy:\n    Type: AWS::IAM::ManagedPolicy\n"
        )
        assert any("requires a Role-only template" in error for error in errors(marker + valid))
        assert any(boundary_error in error for error in errors("Resources:\n  Logs:\n    Type: AWS::Logs::LogGroup\n"))
        assert any(boundary_error in error for error in errors(
            "Resources:\n  Role:\n    Type: AWS::IAM::Role\n\n  Logs:\n    Type: AWS::Logs::LogGroup\n"
        ))
        assert any(boundary_error in error for error in errors("Resources:\n  Filter:\n    Type: AWS::Logs::SubscriptionFilter\n"))
        assert any(boundary_error in error for error in errors(
            "Resources:\n  Role:\n    Type: AWS::IAM::Role\n\n  Profile:\n    Type: AWS::IAM::InstanceProfile\n"
        ))
        assert any(boundary_error in error for error in errors(
            "Resources:\n  Group:\n    Type: AWS::EC2::SecurityGroup\n  Ingress:\n    Type: AWS::EC2::SecurityGroupIngress\n"
        ))
        ingress = (
            "Resources:\n  Ingress:\n    Type: AWS::EC2::SecurityGroupIngress\n"
            "    Properties:\n"
            "      GroupId: !ImportValue GroupAId\n"
            "      SourceSecurityGroupId: !ImportValue GroupBId\n"
        )
        egress = (
            "\n  Egress:\n    Type: AWS::EC2::SecurityGroupEgress\n"
            "    Properties:\n"
            "      GroupId: !ImportValue GroupBId\n"
            "      DestinationSecurityGroupId: !ImportValue GroupAId\n"
        )
        assert not errors(ingress)
        assert not errors("Resources:\n" + egress)
        assert not errors(ingress + egress)
        for support in (
            "AWS::EC2::SecurityGroup", "AWS::Logs::LogGroup", "AWS::IAM::Role",
        ):
            assert any(boundary_error in error for error in errors(
                ingress + egress + f"\n  Support:\n    Type: {support}\n"
            ))
        assert any("requires a Role-only template" in error for error in errors(marker + ingress))
        assert not errors("Resources:\n  Logs:\n    Type: AWS::Logs::LogGroup\n" + consumer)
        assert not errors("Resources:\n  Group:\n    Type: AWS::EC2::SecurityGroup\n" + consumer)


def check_cloudformation_environment_parameters() -> None:
    with project() as root:
        template = root / "infra/cloudformation/templates/role.yaml"
        parameter = root / "infra/cloudformation/parameters/dev/123456789012/role.json"
        template.parent.mkdir(parents=True)
        parameter.parent.mkdir(parents=True)
        valid_template = """Parameters:
  Environment:
    Type: String
  NamePrefix:
    Type: String
Resources:
  Role:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'
"""

        def errors(yaml: str, values: list[dict[str, str]]) -> list[str]:
            write(template, yaml)
            write(parameter, json.dumps(values))
            validator = MODULE.Validator(root)
            validator.check_cloudformation_environment_parameters()
            return validator.errors

        valid_values = [
            {"ParameterKey": "Environment", "ParameterValue": "dev"},
            {"ParameterKey": "NamePrefix", "ParameterValue": "app"},
        ]
        assert not errors(valid_template, valid_values)
        assert not errors(valid_template.replace("  ", "    "), valid_values)
        assert not errors(valid_template.replace("!Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'", "!Ref Environment"), valid_values)
        assert any("without Parameters.Environment" in error for error in errors(
            valid_template.replace("  Environment:\n    Type: String\n", ""), valid_values
        ))
        assert any("must equal target environment" in error for error in errors(
            valid_template, valid_values[1:]
        ))
        assert any("must equal target environment" in error for error in errors(
            valid_template, [{**valid_values[0], "ParameterValue": "prod"}, valid_values[1]]
        ))
        assert any("contains Environment component" in error for error in errors(
            valid_template, [valid_values[0], {**valid_values[1], "ParameterValue": "app-dev"}]
        ))
        assert any("contains Environment component" in error for error in errors(
            valid_template.replace("!Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'", "!Ref NamePrefix"),
            [{"ParameterKey": "NamePrefix", "ParameterValue": "app-dev-role"}],
        ))
        assert not errors(
            valid_template, [valid_values[0], {**valid_values[1], "ParameterValue": "device"}]
        )

        # Decode real short/long YAML intrinsics; names cannot hide Environment control-flow.
        conditions = [
            ("IsDev: !Equals [!Ref Environment, dev]", "IsDev"),
            ("UseSmall: !Equals [!Ref Environment, dev]", "UseSmall"),
            ("IsNonProd: !Not [!Equals [!Ref Environment, prod]]", "IsNonProd"),
            ("NestedAnd:\n    Fn::And:\n      - Fn::Equals: [{Ref: Environment}, dev]\n      - Fn::Equals: [{Ref: EnableFeature}, 'true']", "NestedAnd"),
            ("NestedOr: !Or [!Equals [!Ref Environment, dev], !Equals [!Ref EnableFeature, 'true']]", "NestedOr"),
            ("Composed: !Equals [!Join ['-', [app, !Ref Environment]], app-dev]", "Composed"),
            ("Substituted: !Equals [!Sub '${Environment}', dev]", "Substituted"),
            ("Alias: !Equals [!Sub ['${Stage}', {Stage: !Ref Environment}], dev]", "Alias"),
            ("Base: !Equals [!Ref Environment, dev]\n  Indirect: !Condition Base", "Base"),
        ]
        for expression, name in conditions:
            yaml = valid_template + "Conditions:\n  " + expression + "\n"
            failures = errors(yaml, valid_values)
            assert any("must not branch on Environment" in failure and f"Conditions.{name}" in failure
                       and "role.yaml" in failure and "deployment parameters" in failure
                       for failure in failures), (expression, failures)
        # Resource, property and Output existence/values all share the checked Conditions.
        yaml = valid_template.replace("    Properties:", "    Condition: UseSmall\n    Properties:")
        yaml += "Conditions:\n  UseSmall: !Equals [!Ref Environment, dev]\nOutputs:\n  Name:\n    Condition: UseSmall\n    Value: !If [UseSmall, small, large]\n"
        assert any("Conditions.UseSmall" in failure for failure in errors(yaml, valid_values))

        value_path = "Resources.Role.Properties.RoleName"
        name_expression = "!Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'"
        selectors = [
            ("!FindInMap [EnvironmentConfig, !Ref Environment, InstanceType]", "Fn::FindInMap"),
            ("!FindInMap [EnvironmentConfig, dev, !Ref Environment]", "Fn::FindInMap"),
            ("!FindInMap [!Sub '${Environment}Config', dev, InstanceType]", "Fn::FindInMap"),
            ("!FindInMap [EnvironmentConfig, !Join ['', [!Ref Environment]], InstanceType]", "Fn::FindInMap"),
            ("!FindInMap [EnvironmentConfig, !Sub ['${Stage}', {Stage: !Ref Environment}], InstanceType]", "Fn::FindInMap"),
            ("!Select [!Ref Environment, [small, large]]", "Fn::Select"),
            ("!Select [!FindInMap [EnvironmentConfig, !Ref Environment, Index], [small, large]]", "Fn::Select[0].Fn::FindInMap"),
            ("!If [!Ref Environment, small, large]", "Fn::If"),
        ]
        for expression, intrinsic in selectors:
            failures = errors(valid_template.replace(name_expression, expression), valid_values)
            assert any(f"{value_path}.{intrinsic}" in failure for failure in failures), (expression, failures)
        loop = "\n  Fn::ForEach::Loop:\n    - Item\n    - !Split [',', !Ref Environment]\n    - Bucket${Item}:\n        Type: AWS::S3::Bucket\n"
        assert any("Resources.Fn::ForEach::Loop" in failure for failure in errors(valid_template + loop, valid_values))

        permitted = [
            valid_template,
            valid_template.replace(name_expression, "!Join ['-', [app, !Ref Environment, role]]"),
            valid_template + "      Tags:\n        - Key: Environment\n          Value: !Ref Environment\n",
            valid_template + "Outputs:\n  Name:\n    Value: !Ref Role\n    Export:\n      Name: !Sub 'App${Environment}Role'\n",
            valid_template + "Conditions:\n  HasSuffix: !Not [!Equals [!Ref Suffix, '']]\n",
            valid_template + "Conditions:\n  UseFeature: !Equals [!Ref EnableFeature, 'true']\n",
            valid_template.replace(name_expression, "!If [UseFeature, !Sub 'app-${Environment}-role', !Join ['-', [app, !Ref Environment]]]")
                + "Conditions:\n  UseFeature: !Equals [!Ref EnableFeature, 'true']\n",
            valid_template + "Conditions:\n  IsDev: !Equals [!Ref EnableFeature, 'true']\n",
            valid_template + "Conditions:\n  Environment: !Equals [!Ref EnableFeature, 'true']\n  Indirect: !Condition Environment\n",
            valid_template + "Conditions:\n  Literal: !Equals [Environment, dev]\n",
            valid_template + "Conditions:\n  Escaped: !Equals [!Sub '${!Environment}', dev]\n",
            valid_template + "Conditions:\n  Overridden: !Equals [!Sub ['${Environment}', {Environment: literal}], dev]\n",
            valid_template + "Conditions:\n  Unused: !Equals [!Sub ['literal', {Stage: !Ref Environment}], dev]\n",
            valid_template.replace(name_expression, "!Select [0, [!Ref Environment, other]]"),
            valid_template.replace(name_expression, "!FindInMap [Config, Feature, Name, {DefaultValue: !Ref Environment}]"),
            valid_template + "# IsDev: !Equals [!Ref Environment, dev]\n",
            valid_template + "Mappings:\n  Config:\n    dev:\n      0: [small, large]\n",
        ]
        for yaml in permitted:
            assert not errors(yaml, valid_values), (yaml, errors(yaml, valid_values))

        # JSON templates and long-form intrinsics use the same AST and file gate.
        template.unlink()
        template = template.with_suffix(".json")
        document = {"Parameters": {"Environment": {"Type": "String"}},
                    "Resources": {"Bucket": {"Type": "AWS::S3::Bucket", "Properties": {
                        "BucketName": {"Fn::Sub": "app-${Environment}-bucket"}}}}}
        assert not errors(json.dumps(document), valid_values)
        document["Conditions"] = {"Renamed": {"Fn::Equals": [{"Ref": "Environment"}, "dev"]}}
        failures = errors(json.dumps(document), valid_values)
        assert any("role.json: Conditions.Renamed" in failure for failure in failures), failures
        validator = MODULE.Validator(root, set())
        validator.file_gate_paths = set()
        validator.check_cloudformation_environment_parameters()
        assert not validator.errors and any("must not branch" in failure for failure in validator.non_blocking_findings)
        validator.file_gate_paths.add(template.relative_to(root).as_posix())
        validator.check_cloudformation_environment_parameters()
        assert any("must not branch" in failure for failure in validator.errors)
        assert any("invalid CloudFormation template" in failure for failure in errors("Resources: [", valid_values))
    print("CloudFormation Environment checks: PASS (AST control-flow/selectors, naming/composition, JSON, file gating)")


def check_cloudformation_stack_design() -> None:
    with project() as root:
        target = root / "docs" / "designs" / "dev" / "123456789012"
        target.mkdir(parents=True)
        write(target / "glue.md",
            '<a id="glue-job01"></a>\n### Glue.Job: Job01\n<a id="glue-job02"></a>\n### Glue.Job: Job02\n'
        )
        stack_file = target / "cloudformation-stacks.md"
        write(stack_file,
            """# CloudFormation stack 詳細設計

<!-- max-concurrent-stacks: 2 -->

## Stack一覧
| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 10 | stack-job-01 | job.yaml | job-01.json | 日次jobを配置するstack |
| 2 | 10 | stack-job-02 | job.yaml | job-02.json | 月次jobを配置するstack |
"""
        )
        template = root / "infra" / "cloudformation" / "templates" / "job.yaml"
        template.parent.mkdir(parents=True)
        write(template,
            "Parameters:\n  Environment:\n    Type: String\nResources:\n  Job:\n    Type: AWS::Glue::Job\n    Properties:\n      Name: !Ref Environment\n"
        )
        parameter_dir = root / "infra" / "cloudformation" / "parameters" / "dev" / "123456789012"
        parameter_dir.mkdir(parents=True)
        for name in ("job-01", "job-02"):
            write(parameter_dir / f"{name}.json",
                '[{"ParameterKey":"Environment","ParameterValue":"dev"}]\n'
            )

        def errors() -> list[str]:
            validator = MODULE.Validator(root)
            validator.accounts[("dev", "123456789012")] = {
                "account": "123456789012", "region": "ap-northeast-1", "alias": "", "engine": "cloudformation"
            }
            validator.check_stack_designs()
            validator.check_cloudformation_environment_parameters()
            return validator.errors

        assert not errors(), errors()
        original = stack_file.read_text(encoding="utf-8")
        for old, replacement in (("<!-- max-concurrent-stacks: 2 -->", "<!-- max-concurrent-stacks: 0 -->"),
                                 ("<!-- max-concurrent-stacks: 2 -->", "<!-- max-concurrent-stacks: -1 -->"),
                                 ("| 1 | 10 |", "| 1 | 0 |"), ("| 1 | 10 |", "| 1 | -1 |"),
                                 ("| 1 | 10 |", "| 1 | abc |")):
            write(stack_file, original.replace(old, replacement))
            assert any("integer >= 1" in error for error in errors()), errors()
        write(stack_file, original)
        for old, replacement, message in (
            ('| 2 | 10 | stack-job-02 | job.yaml', '| 2 | 10 | stack-job-01 | job.yaml', 'duplicate stack name'),
            ('job-02.json', 'job-01.json', 'parameter file belongs to multiple stacks'),
            ('| job.yaml |', '| ../job.yaml |', 'invalid stack template filename'),
            ('| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |', '| StackName | Template | Parameters |', 'invalid CloudFormation stack design header'),
            ('| 2 | 10 | stack-job-02', '| 3 | 10 | stack-job-02', 'No. must be sequential'),
            ('| 月次jobを配置するstack |', '| |', 'invalid CloudFormation stack design row'),
            ('月次jobを配置するstack', 'monthly job', 'stack Comment must describe its purpose in Japanese'),
        ):
            write(stack_file, original.replace(old, replacement, 1))
            assert any(message in error for error in errors()), (message, errors())
        write(stack_file, original)
        write(parameter_dir / "job-02.json", "[]\n")
        assert any("must equal target environment" in error for error in errors())
        write(parameter_dir / "job-02.json",
            '[{"ParameterKey":"Environment","ParameterValue":"dev"}]\n'
        )


def check_stack_mapping_targets():
    from model_design import markdown_for
    import shutil
    with project() as root:
        shutil.copytree(SCRIPT.parents[2] / "framework", root / "framework")
        model_dir = root / "model/dev/123456789012"
        model_dir.mkdir(parents=True)
        target = root / "docs/designs/dev/123456789012"
        target.mkdir(parents=True)
        values = {"desired.stack.001.name": "cfn-stack-app-dev-ism", "desired.stack.001.template": "department.yaml",
                  "desired.stack.001.parameters": "ism.json", "desired.stack.001.deployOrder": "10", "display.stack.001.comment": "部署用リソースを配置するstack",
                  }
        source = model_dir / "cloudformation-stacks.properties"
        write(source, "\n".join(k + "=" + v for k, v in values.items()))
        path = target / "cloudformation-stacks.md"
        write(path, markdown_for(path, values, root))
        model = model_dir / "ec2.properties"
        write(model, "desired.resource.001.resourceType=EC2.VPC\ndesired.resource.001.cfn-logicalId=cfn-stack-app-dev-ism-DepartmentVpc\n")
        def errors():
            validator = MODULE.Validator(root)
            validator.accounts[("dev", "123456789012")] = {"account": "123456789012", "region": "ap-northeast-1", "alias": "", "engine": "cloudformation"}
            validator.check_stack_designs()
            return validator.errors
        assert not errors(), errors()
        write(model, model.read_text(encoding="utf-8") + "desired.resource.001.resourceMode=IMPORT\n")
        assert any("CREATE" in error for error in errors()), errors()
        write(model, model.read_text(encoding="utf-8").replace("cfn-stack-app-dev-ism-DepartmentVpc", "absent-DepartmentVpc").replace("desired.resource.001.resourceMode=IMPORT\n", ""))
        assert any("undeclared stack" in error for error in errors()), errors()
    with project() as root:
        path = root / "docs/designs/dev/123456789012/iam.md"
        path.parent.mkdir(parents=True)
        write(path, '<a id="iam-confirmed-role"></a>\n')
        model = root / "model/dev/123456789012/iam.properties"
        model.parent.mkdir(parents=True)
        write(model, 'desired.resource.007.resourceType=IAM.Role\ndesired.resource.007.anchor=iam-confirmed-role\n')
        validator = MODULE.Validator(root)
        validator.check_markdown_iam_policy_artifacts(path, "007", [["1", "AssumeRolePolicyDocument", "[Trust](iam/confirmed-role-trust-policy.json)", "信頼ポリシー"]])
        assert not validator.errors, validator.errors
    prompt = (SCRIPT.parents[2] / "framework/prompts/codex/03_implement.md").read_text(encoding="utf-8")
    assert "python framework/scripts/cloudformation_observed.py --environment" in prompt
    assert "After generation/changes as well" in prompt and "Do not automatically fill missing identifier rows" in prompt
