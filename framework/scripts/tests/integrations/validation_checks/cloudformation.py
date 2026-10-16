"""CloudFormation syntax, Environment semantics and stack mappings."""


from __future__ import annotations

from support.it_case_receipt import it_case


import json


from support.validator import MODULE, SCRIPT, project, write


from support.it_workspace import copy_framework

@it_case
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


@it_case
def check_stack_mapping_targets():
    from model_design import markdown_for
    import shutil
    with project() as root:
        copy_framework(root / 'framework')
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
        write(model, "desired.resource.001.resourceType=EC2.VPC\ndesired.resource.001.anchor=ec2-fixture-vpc\ndesired.resource.001.cfn-logicalId=cfn-stack-app-dev-ism-DepartmentVpc\n")
        def errors():
            validator = MODULE.Validator(root)
            validator.accounts[("dev", "123456789012")] = {"account": "123456789012", "region": "ap-northeast-1", "alias": "", "engine": "cloudformation"}
            validator.check_stack_designs()
            return validator.errors
        assert not errors(), errors()
        write(model, __import__("model_files").read_model(model) + "desired.resource.001.resourceMode=IMPORT\n")
        assert any("CREATE" in error for error in errors()), errors()
        write(model, __import__("model_files").read_model(model).replace("cfn-stack-app-dev-ism-DepartmentVpc", "absent-DepartmentVpc").replace("desired.resource.001.resourceMode=IMPORT\n", ""))
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

