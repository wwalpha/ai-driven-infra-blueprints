"""Mapping-defined environment values across Model, references, comparison and CFN."""

import copy
import json
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from aws_mapping import registry
from comparison.methods import compare_values
from comparison.registry import rules
from comparison.values import desired_value
from deploy.controller import load_inputs
from deploy.scheduler import run_group
from design.catalog import DesignSchemaCatalog
from design.services.codepipeline import pipeline_display_rows, pipeline_rows
from model.core import ModelNeedsFixError, literal
from model.environment_values import (
    glue_variables,
    identity,
    inspect,
    mapping_for,
    pending_errors,
)
from model.environment_values import project as project_environment
from model.format import parse as parse_properties
from model.format import serialize
from model.identity import Resolver
from model.operations import validate_candidates
from model.projection import generated_document, reference_display, reference_resolver
from model.reference_nodes import parse
from model.reference_values import ProducerValues, reference_value
from model.references import codebuild_reference_errors
from model.sources import load_model
from model.validations.environment import validate_environment_settings
from model.validations.full_inputs import check_model_inputs as model_inputs
from model.validations.json_settings import validate_json_settings
from support.model_reference_fixtures import (
    FRAMEWORK,
    comparison,
    pipeline,
    project,
    reference,
    resource,
    save,
)
from support.pytest_cli import run
from utils.aws_mappings import mapping_alias
from utils.cloudformation.environment import (
    EnvironmentValuePending,
    validate_environment_inputs,
)
from utils.cloudformation.inputs import Blocked
from utils.mapping_types import definition, validate_definition

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

TARGET = {"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"}

CASES = (
    (
        "CodeBuild.Project",
        "Environment.EnvironmentVariables[].Value",
        "PENDING_DEPLOY",
        "",
    ),
    (
        "Lambda.Function",
        "Environment.Variables",
        {"KEY": "PENDING_DEPLOY", "OTHER": "fixed"},
        "/KEY",
    ),
    (
        "ECS.TaskDefinition",
        "ContainerDefinitions",
        [
            {
                "Name": "main",
                "Environment": [{"Name": "KEY", "Value": "PENDING_DEPLOY"}],
                "Image": "fixed",
            }
        ],
        "/0/Environment/0/Value",
    ),
    (
        "CodePipeline.Pipeline",
        "Stages[].Actions[].EnvironmentVariables[].Value",
        "PENDING_DEPLOY",
        "",
    ),
    (
        "CodePipeline.Pipeline",
        "Stages[].Actions[].Configuration",
        {
            "ProjectName": "fixed",
            "EnvironmentVariables": json.dumps(
                [{"name": "KEY", "value": "PENDING_DEPLOY", "type": "PLAINTEXT"}]
            ),
        },
        "/EnvironmentVariables/0/value",
    ),
    (
        "Glue.Job",
        "DefaultArguments",
        {
            "--customer-driver-env-vars": 'CUSTOMER_A="hello, world",CUSTOMER_B=PENDING_DEPLOY',
            "--other": "fixed",
        },
        "/--customer-driver-env-vars/1/Value",
    ),
    (
        "Glue.Job",
        "NonOverridableArguments",
        {"--customer-executor-env-vars": "CUSTOMER_A=PENDING_DEPLOY"},
        "/--customer-executor-env-vars/0/Value",
    ),
)


@pytest.fixture
def models(tmp_path):
    with (
        mapping_alias(FRAMEWORK, tmp_path),
        patch("socket.socket", side_effect=AssertionError("network forbidden")),
    ):
        project(tmp_path)
        yield tmp_path


def authored(root, kind, prop, value, mode):
    service = {
        "CodeBuild": "codebuild",
        "Lambda": "lambda",
        "ECS": "ecs",
        "CodePipeline": "codepipeline",
        "Glue": "glue",
    }[kind.split(".")[0]]
    scope, values = resource(root, service, kind, attribute=prop)
    values["desired.resource.001.resourceMode"] = mode
    if mode == "IMPORT":
        values.pop("desired.resource.001.cfn-logicalId")
    values["desired.row.001-001.value"] = (
        "`" + (json.dumps(value) if isinstance(value, (dict, list)) else value) + "`"
    )
    save(scope, values)
    return scope, values


@pytest.mark.parametrize("kind,prop,value,pointer", CASES)
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def check_model_pending_values(models, kind, prop, value, pointer, mode):
    scope, values = authored(models, kind, prop, value, mode)
    warnings = []
    validate_environment_settings(values, scope.path, warnings=warnings)
    assert len(warnings) == 1 and warnings[0]["pointer"] == pointer
    assert (
        warnings[0]["resolutionState"] == "unresolved"
        and "unknown" in warnings[0]["message"]
    )
    assert parse_properties(serialize(values)).values == values
    assert load_model(scope).authoritative


@pytest.mark.parametrize(
    "kind,prop,value",
    [
        (
            "CodeBuild.Project",
            "Environment.EnvironmentVariables[].Name",
            "PENDING_DEPLOY",
        ),
        (
            "CodeBuild.Project",
            "Environment.EnvironmentVariables[].Type",
            "PENDING_DEPLOY",
        ),
        ("Lambda.Function", "Role", "PENDING_DEPLOY"),
        ("EC2.VPC", "CidrBlock", "PENDING_DEPLOY"),
        (
            "ECS.TaskDefinition",
            "ContainerDefinitions",
            [{"Secrets": [{"Name": "s", "ValueFrom": "PENDING_DEPLOY"}]}],
        ),
        (
            "ECS.TaskDefinition",
            "ContainerDefinitions",
            [{"EnvironmentFiles": [{"Value": "PENDING_DEPLOY"}]}],
        ),
        ("CodePipeline.Pipeline", "Variables[].DefaultValue", "PENDING_DEPLOY"),
        ("ApiGateway.Stage", "Variables", {"KEY": "PENDING_DEPLOY"}),
        ("Glue.Job", "DefaultArguments", {"--unrelated": "PENDING_DEPLOY"}),
        ("Lambda.Function", "Environment.Variables", "PENDING_DEPLOY"),
    ],
)
def check_pending_not_an_escape(kind, prop, value):
    assert pending_errors(kind, kind + "." + prop, value, mapping_for(FRAMEWORK, kind))


@pytest.mark.parametrize("type_", ["SECRETS_MANAGER", "PARAMETER_STORE"])
def check_codebuild_secret_reference_not_plaintext(models, type_):
    scope, values = authored(
        models,
        "CodeBuild.Project",
        "Environment.EnvironmentVariables[].Value",
        "PENDING_DEPLOY",
        "IMPORT",
    )
    for number, field, value in [(2, "Name", "KEY"), (3, "Type", type_)]:
        values[f"desired.row.001-00{number}.property"] = (
            "CodeBuild.Project.Environment.EnvironmentVariables[]." + field
        )
        values[f"desired.row.001-00{number}.value"] = "`" + value + "`"
        values[f"desired.row.001-00{number}.comment"] = "合成"
    with pytest.raises(ModelNeedsFixError, match="PENDING_DEPLOY"):
        validate_environment_settings(values, scope.path)


def check_glue_quoting():
    raw = r'CUSTOMER_A="a,b",CUSTOMER_B=\"quote\",CUSTOMER_C=,CUSTOMER_D="x\\y"'
    assert glue_variables(raw) == [
        dict(Name="CUSTOMER_A", Value="a,b"),
        dict(Name="CUSTOMER_B", Value='"quote"'),
        dict(Name="CUSTOMER_C", Value=""),
        dict(Name="CUSTOMER_D", Value=r"x\y"),
    ]
    for raw in (
        'CUSTOMER_A="unfinished',
        "CUSTOMER_A=x,CUSTOMER_A=y",
        "OTHER_A=x",
        "CUSTOMER_A=x,broken",
    ):
        with pytest.raises(ValueError):
            glue_variables(raw)


@pytest.mark.parametrize(
    "metadata",
    [
        {"path": "$", "encoding": "unknown"},
        {"path": "x..Value", "encoding": "value"},
        {"path": "$", "encoding": "value", "typo": True},
        {"path": "$", "encoding": "json", "valuePath": "[].Name"},
        {"path": "$", "encoding": "glue", "keys": []},
    ],
)
def check_invalid_mapping_metadata(metadata):
    with pytest.raises(ValueError):
        definition(metadata)


def check_mapping_schema_paths_and_publication():
    catalog = DesignSchemaCatalog(FRAMEWORK)
    with pytest.raises(ValueError, match="unknown environment"):
        validate_definition(
            catalog,
            "ECS.TaskDefinition",
            "ContainerDefinitions",
            definition({"path": "[].Typo[].Value", "encoding": "value"}),
        )
    for service, prop in [
        ("lambda", "Lambda.Function.Environment.Variables"),
        ("ecs", "ECS.TaskDefinition.ContainerDefinitions"),
        (
            "codepipeline",
            "CodePipeline.Pipeline.Stages[].Actions[].EnvironmentVariables[].Value",
        ),
    ]:
        item = registry(FRAMEWORK, service).properties[prop]
        assert item.include and item.show and item.environment


@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def check_pipeline_name_reference_and_candidate_guard(models, mode):
    _, scope, values, _ = pipeline(models)
    producer_scope, producer = resource(
        models,
        "codebuild",
        "CodeBuild.Project",
        attribute="Name",
        observed="PENDING_DEPLOY",
    )
    producer["desired.resource.001.resourceMode"] = mode
    if mode == "IMPORT":
        producer.pop("desired.resource.001.cfn-logicalId")
    producer["desired.row.001-001.value"] = "`synthetic-codebuild-a`"
    producer.update(
        {
            "desired.row.001-002.property": "CodeBuild.Project.Environment.EnvironmentVariables[].Value",
            "desired.row.001-002.value": "`PENDING_DEPLOY`",
            "desired.row.001-002.comment": "合成",
        }
    )
    save(producer_scope, producer)
    resolver = reference_resolver(values, scope, models)
    result = reference_value(
        resolver, scope, parse(reference("CodeBuild_Project_001", "Name"))
    )
    assert result.status == "resolved" and result.value == "synthetic-codebuild-a"
    validate_json_settings(values, scope.path)
    before = producer_scope.path.read_bytes()
    with pytest.raises(ValueError, match="change comparison unavailable"):
        validate_candidates(
            models,
            [scope.path.relative_to(models).as_posix()],
            {},
            {("qa", "team", "codepipeline")},
        )
    assert producer_scope.path.read_bytes() == before
    producer["desired.row.001-001.value"] = "`PENDING_DEPLOY`"
    save(producer_scope, producer)
    with pytest.raises(ModelNeedsFixError, match="MODEL_REF_INVALID_PENDING_STATE"):
        reference_value(
            reference_resolver(values, scope, models),
            scope,
            parse(reference("CodeBuild_Project_001", "Name")),
        )


def check_unrelated_pending_does_not_hide_invalid_requested_value(models):
    scope, values = authored(
        models,
        "CodeBuild.Project",
        "Environment.EnvironmentVariables[].Value",
        "PENDING_DEPLOY",
        "IMPORT",
    )
    values.update(
        {
            "desired.row.001-002.property": "CodeBuild.Project.Name",
            "desired.row.001-002.value": "`invalid name`",
            "desired.row.001-002.comment": "合成",
        }
    )
    save(scope, values)
    with pytest.raises(ModelNeedsFixError, match="MODEL_REF_INVALID_VALUE"):
        reference_value(
            reference_resolver(values, scope, models),
            scope,
            parse(reference("CodeBuild_Project_001", "Name")),
        )
    resolver = Resolver(models)
    resolver.catalog = DesignSchemaCatalog(models)
    producer = ProducerValues(
        load_model(scope), "001", {"resourceType": "CodeBuild.Project"}, resolver
    )
    assert producer.value("Environment.EnvironmentVariables[].Value") is None
    assert producer.waiting(["Environment.EnvironmentVariables[].Value"])


def check_codebuild_plaintext_link_still_rejected(models):
    scope, values = authored(
        models,
        "CodeBuild.Project",
        "Environment.EnvironmentVariables[].Value",
        "[key](kms.md#saved-001)",
        "CREATE",
    )
    values["desired.row.001-001.value"] = "[key](kms.md#saved-001)"
    assert codebuild_reference_errors(scope.path, values)
    findings = model_inputs(scope.path, values, models)
    assert any("PLAINTEXT" in error for error in findings.errors)


@pytest.mark.parametrize(
    "kind,prop,value,pointer",
    [case for case in CASES[1:] if isinstance(case[2], (dict, list))],
)
def check_comparison_preserves_confirmed_siblings(models, kind, prop, value, pointer):
    # Configuration AWS uses lower-case name/value/type; Model uses the exact same JSON format.
    scope, _ = authored(models, kind, prop, value, "IMPORT")
    catalog = DesignSchemaCatalog(FRAMEWORK)
    row = {"property": kind + "." + prop, "value": "`" + json.dumps(value) + "`"}
    prepared = desired_value(
        scope.service,
        row,
        kind,
        local_comparison=True,
        desired_reference=Mock(side_effect=AssertionError("not a link")),
        property_schema=catalog.property_schema,
        evaluate=Mock(side_effect=AssertionError("not an intrinsic")),
        model_path=scope.path,
        environment_mapping=mapping_for(models, kind),
    )
    assert prepared.error is None and len(prepared.failures) == 1
    assert prepared.failures[0][1] == pointer
    mapping = mapping_for(models, kind)
    actual = project_environment(kind, kind + "." + prop, value, mapping, identity)
    assert (
        compare_values(
            prepared.value,
            actual,
            prop,
            whole=True,
            rules=rules(kind),
            reference=partial(_decision, comparison(models), kind),
        ).equal
        is None
    )
    changed = copy.deepcopy(actual)
    if kind == "Lambda.Function":
        changed["OTHER"] = "changed"
    elif kind == "ECS.TaskDefinition":
        changed[0]["Image"] = "changed"
    elif kind == "CodePipeline.Pipeline":
        changed["ProjectName"] = "changed"
    else:
        changed[next(key for key in changed if key.startswith("--customer-"))][0][
            "Name"
        ] = "CUSTOMER_CHANGED"
    assert (
        compare_values(
            prepared.value,
            changed,
            prop,
            whole=True,
            rules=rules(kind),
            reference=partial(_decision, comparison(models), kind),
        ).equal
        is False
    )


def _decision(comparator, kind, left, right, path):
    return comparator.reference_decision(left, right, kind, path)


def template(kind, properties):
    return {
        "Resources": {
            "Resource": {
                "Type": "AWS::" + kind.replace(".", "::"),
                "Properties": properties,
            }
        }
    }


@pytest.mark.parametrize(
    "value",
    [
        "PENDING_DEPLOY",
        {"Ref": "Key"},
        {"Fn::Sub": "${Key}"},
        {"Fn::Sub": "prefix-${Key}-suffix"},
        {"Fn::Sub": ["prefix-${Value}", {"Value": {"Ref": "Key"}}]},
        {"Fn::Join": ["", ["prefix-", {"Ref": "Key"}]]},
        {"Fn::Select": [0, {"Fn::Split": ["-", {"Ref": "Key"}]}]},
        {"Fn::Sub": ["${Resource.Arn}:${Key}", {}]},
        {"Fn::Base64": {"Ref": "Key"}},
        {"Fn::Base64": {"Fn::Join": ["_", ["PENDING", "DEPLOY"]]}},
        {"Fn::Join": ["", [{"Fn::Base64": {"Ref": "Key"}}]]},
        {"Fn::Sub": ["prefix-${Value}", {"Value": {"Fn::Base64": {"Ref": "Key"}}}]},
        {"Fn::Select": [0, {"Fn::GetAZs": {"Ref": "Key"}}]},
        {"Fn::ImportValue": {"Fn::Sub": "${Key}-export"}},
        {"Fn::Select": [1, {"Fn::Split": [",", {"Fn::ImportValue": {"Ref": "Key"}}]}]},
    ],
)
def check_deploy_blocks_literals_and_parameters(value):
    doc = template("Lambda.Function", {"Environment": {"Variables": {"KEY": value}}})
    with pytest.raises(Blocked, match="PENDING_DEPLOY"):
        validate_environment_inputs(
            FRAMEWORK,
            doc,
            {"Key": "PENDING_DEPLOY"},
            {"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"},
            "stack",
        )


@pytest.mark.parametrize(
    "value",
    [
        {"Ref": "Resource"},
        {"Fn::GetAtt": ["Resource", "Arn"]},
        {"Fn::Sub": "${Resource.Arn}"},
        {"Ref": "Key"},
        "PREFIX_PENDING_DEPLOY_SUFFIX",
        {"Fn::Sub": "prefix-${Key}-suffix"},
        {"Fn::Sub": "PREFIX_PENDING_DEPLOY_SUFFIX"},
        {"Fn::Join": ["-", ["PREFIX_PENDING_DEPLOY_SUFFIX", {"Ref": "Key"}]]},
        {"Fn::ImportValue": {"Fn::Sub": "${Key}-export"}},
        {"Fn::Sub": "arn:${AWS::Partition}:service:${AWS::Region}:${AWS::AccountId}"},
        {"Ref": "AWS::StackId"},
        {"Ref": "AWS::URLSuffix"},
        {"Ref": "AWS::NoValue"},
        {"Fn::Base64": "fixed"},
        {"Fn::Join": ["-", ["prefix", {"Fn::Base64": "fixed"}]]},
        {"Fn::Select": [1, {"Fn::GetAZs": ""}]},
        {"Fn::Sub": ["prefix-${Value}", {"Value": {"Fn::Base64": "fixed"}}]},
        {"Fn::Select": [1, {"Fn::Split": [",", {"Fn::ImportValue": "export"}]}]},
    ],
)
def check_deploy_accepts_cfn_references(value):
    doc = template("Lambda.Function", {"Environment": {"Variables": {"KEY": value}}})
    before = copy.deepcopy(doc)
    validate_environment_inputs(
        FRAMEWORK,
        doc,
        {"Key": "PREFIX_PENDING_DEPLOY_SUFFIX"},
        {"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"},
        "stack",
    )
    assert doc == before


@pytest.mark.parametrize(
    "value,exception,reason",
    [
        ({"Fn::Select": [1, ["fixed"]]}, ValueError, "invalid Select operands"),
        ({"Fn::Select": [-1, {"Fn::GetAZs": ""}]}, ValueError, "invalid"),
        ({"Fn::Select": [0, {"Fn::Base64": "fixed"}]}, ValueError, "not an array"),
        ({"Fn::Base64": ["fixed"]}, ValueError, "invalid Fn::Base64"),
        (
            {"Fn::GetAZs": {"Ref": "Missing"}},
            Blocked,
            "undefined CloudFormation resource",
        ),
        ({"Fn::Base64": {"Fn::Unknown": "fixed"}}, Blocked, "unsupported"),
    ],
)
def check_deploy_runtime_expressions_keep_static_errors(value, exception, reason):
    doc = template("Lambda.Function", {"Environment": {"Variables": {"KEY": value}}})
    with pytest.raises(exception, match=reason):
        validate_environment_inputs(FRAMEWORK, doc, {}, TARGET, "stack")


def check_deploy_selects_active_branch_and_only_environment():
    doc = template(
        "Lambda.Function",
        {
            "Environment": {
                "Variables": {
                    "KEY": {"Fn::If": ["Enabled", "confirmed", "PENDING_DEPLOY"]}
                }
            },
            "Description": "PENDING_DEPLOY",
        },
    )
    doc["Conditions"] = {"Enabled": {"Fn::Equals": [{"Ref": "Flag"}, "yes"]}}
    validate_environment_inputs(
        FRAMEWORK,
        doc,
        {"Flag": "yes"},
        {"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"},
        "stack",
    )
    doc["Resources"]["Resource"]["Condition"] = "Disabled"
    doc["Conditions"]["Disabled"] = {"Fn::Equals": ["yes", "no"]}
    validate_environment_inputs(FRAMEWORK, doc, {"Flag": "no"}, TARGET, "stack")

    pipeline = template(
        "CodePipeline.Pipeline",
        {
            "Stages": [
                {
                    "Actions": [
                        {
                            "Configuration": {
                                "ProjectName": {"Fn::GetAtt": ["Build", "Name"]},
                                "EnvironmentVariables": json.dumps(
                                    [{"name": "KEY", "value": "fixed"}]
                                ),
                            }
                        }
                    ]
                }
            ]
        },
    )
    pipeline["Resources"]["Build"] = {
        "Type": "AWS::CodeBuild::Project",
        "Properties": {"Name": "PREFIX_PENDING_DEPLOY_SUFFIX"},
    }
    validate_environment_inputs(FRAMEWORK, pipeline, {}, TARGET, "stack")


@pytest.mark.parametrize("value", ["PENDING_DEPLOY", {"Fn::Base64": {"Ref": "Key"}}])
def check_deploy_snapshot_guard_precedes_aws_and_is_per_stack(models, value):
    pending = template(
        "Lambda.Function", {"Environment": {"Variables": {"KEY": value}}}
    )
    target = {"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"}
    runtime = SimpleNamespace(
        root=models,
        target=target,
        templates={},
        paths=Mock(return_value=(Path("template"), Path("parameters"))),
        file_digest=Mock(return_value="digest"),
        aws=Mock(side_effect=AssertionError("AWS forbidden")),
    )
    with patch(
        "deploy.controller.load_template_inputs",
        return_value=(pending, {"Key": "PENDING_DEPLOY"}),
    ):
        with pytest.raises(Blocked, match="Stack=bad"):
            load_inputs(runtime, {"name": "bad"})
    assert not runtime.aws.called and "bad" not in getattr(runtime, "loaded_inputs", {})
    validate_environment_inputs(
        models,
        template("Lambda.Function", {"Environment": {"Variables": {"KEY": "fixed"}}}),
        {},
        target,
        "good",
    )


def check_display_and_artifact_retain_pending(models):
    scope, values = authored(
        models,
        "Lambda.Function",
        "Environment.Variables",
        {"KEY": "PENDING_DEPLOY", "OTHER": "fixed"},
        "IMPORT",
    )
    resolver = reference_resolver(values, scope, models)
    displayed = reference_display(values, scope.path, models)
    assert json.loads(literal(displayed["desired.row.001-001.value"])) == {
        "KEY": "PENDING_DEPLOY",
        "OTHER": "fixed",
    }
    warnings = []
    assert generated_document(
        {"KEY": "PENDING_DEPLOY"},
        models,
        resolver=resolver,
        scope=scope,
        property_name="Lambda.Function.Environment.Variables",
        warnings=warnings,
    ) == {"KEY": "PENDING_DEPLOY"}
    assert warnings[0]["category"] == "REFERENCE_PENDING_DEPLOY"
    assert warnings[0]["pointer"] == "/KEY"
    assert values == parse_properties(serialize(values)).values


def check_pipeline_direct_display_roundtrip():
    rows = [
        ["001-001", "Stages[].Name", "`Build`", "合成"],
        ["001-002", "Stages[].Actions[].Name", "`Action`", "合成"],
        ["001-003", "Stages[].Actions[].EnvironmentVariables[].Name", "`KEY`", "合成"],
        [
            "001-004",
            "Stages[].Actions[].EnvironmentVariables[].Type",
            "`PLAINTEXT`",
            "合成",
        ],
        [
            "001-005",
            "Stages[].Actions[].EnvironmentVariables[].Value",
            "`PENDING_DEPLOY`",
            "合成",
        ],
    ]
    displayed = pipeline_rows(rows)
    restored = pipeline_display_rows(displayed)
    assert [row[1:] for row in restored] == [
        ["CodePipeline.Pipeline." + row[1], *row[2:]] for row in rows
    ]


@pytest.mark.parametrize("kind,prop,value,pointer", CASES)
def check_deploy_five_services(kind, prop, value, pointer):
    properties = {}
    if kind == "CodeBuild.Project":
        properties = {
            "Environment": {
                "EnvironmentVariables": [
                    {"Name": "KEY", "Type": "PLAINTEXT", "Value": value}
                ]
            }
        }
    elif kind == "CodePipeline.Pipeline":
        action = (
            {"EnvironmentVariables": [{"Name": "KEY", "Value": value}]}
            if isinstance(value, str)
            else {"Configuration": value}
        )
        properties = {"Stages": [{"Actions": [action]}]}
    elif kind == "Lambda.Function":
        properties = {"Environment": {"Variables": value}}
    else:
        properties[prop] = value
    with pytest.raises(EnvironmentValuePending):
        validate_environment_inputs(
            FRAMEWORK, template(kind, properties), {}, TARGET, "stack"
        )
    confirmed = json.loads(
        json.dumps(properties).replace("PENDING_DEPLOY", "PREFIX_PENDING_DEPLOY_SUFFIX")
    )
    validate_environment_inputs(
        FRAMEWORK, template(kind, confirmed), {}, TARGET, "stack"
    )


def check_deploy_only_evaluates_selected_settings():
    doc = template(
        "Lambda.Function",
        {
            "Environment": {"Variables": {"KEY": "fixed"}},
            "Description": {"Fn::If": ["Undefined", "PENDING_DEPLOY", "fixed"]},
        },
    )
    validate_environment_inputs(FRAMEWORK, doc, {}, TARGET, "stack")
    for type_ in ("SECRETS_MANAGER", "PARAMETER_STORE"):
        doc = template(
            "CodeBuild.Project",
            {
                "Environment": {
                    "EnvironmentVariables": [
                        {"Name": "KEY", "Type": type_, "Value": "PENDING_DEPLOY"}
                    ]
                }
            },
        )
        with pytest.raises(EnvironmentValuePending):
            validate_environment_inputs(FRAMEWORK, doc, {}, TARGET, "stack")


class EnvironmentBackend:
    def __init__(self):
        self.executed = []
        self.run_context = {"metrics": {}}

    def load_inputs(self, unit):
        validate_environment_inputs(
            FRAMEWORK,
            template(
                "Lambda.Function",
                {
                    "Environment": {
                        "Variables": {
                            "KEY": "PENDING_DEPLOY"
                            if unit["name"] == "bad"
                            else "fixed"
                        }
                    }
                },
            ),
            {},
            TARGET,
            unit["name"],
        )

    def prepare(self, unit, state):
        return "READY"

    def execute(self, unit, state):
        self.load_inputs(unit)
        self.executed.append(unit["name"])

    def poll(self, unit, state):
        return "CREATE_COMPLETE"


@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize("ready", [False, True])
def check_pending_stack_keeps_independent_peer_running(limit, ready):
    backend = EnvironmentBackend()
    units = [{"name": name, "deployOrder": 1} for name in ("bad", "good")]
    states = {
        unit["name"]: {"status": "READY" if ready else "NOT_STARTED"} for unit in units
    }
    assert run_group(units, limit, states, backend, sleep=lambda _: None) == "STOPPED"
    assert backend.executed == ["good"]
    if not ready:
        assert backend.run_context["metrics"]["inputLoadSeconds"] > 0
    assert (
        states["bad"]["status"] == "BLOCKED" and states["good"]["status"] == "SUCCESS"
    )


def check_encoded_configuration_roundtrip():
    value = CASES[4][2]
    rows = [
        ["001-001", "Stages[].Name", "`Stage`", "合成"],
        ["001-002", "Stages[].Actions[].Name", "`Action`", "合成"],
        [
            "001-003",
            "Stages[].Actions[].Configuration",
            "`" + json.dumps(value) + "`",
            "ProjectName: 合成 / EnvironmentVariables: 合成",
        ],
    ]
    displayed = pipeline_rows(rows)
    restored = pipeline_display_rows(displayed)
    assert json.loads(literal(restored[-1][2])) == value
    assert glue_variables('CUSTOMER_A=" a,b "')[0]["Value"] == " a,b "


def check_all_confirmed_values_are_preserved():
    for kind, prop, value, _ in CASES:
        before = copy.deepcopy(value)
        items = inspect(kind, kind + "." + prop, value, mapping_for(FRAMEWORK, kind))
        assert value == before
        assert any(item.value == "PENDING_DEPLOY" for item in items)
        assert all(
            item.status == "resolved"
            for item in items
            if isinstance(item.value, str) and item.value != "PENDING_DEPLOY"
        )


def check_snapshot_validated_once(models, tmp_path):
    doc = template("Lambda.Function", {"Environment": {"Variables": {"KEY": "fixed"}}})
    path = tmp_path / "template.json"
    path.write_text(json.dumps(doc))
    runtime = SimpleNamespace(
        root=models,
        target=TARGET,
        environment="qa",
        directory="team",
        templates={},
        paths=Mock(return_value=(path, path)),
        file_digest=Mock(return_value="digest"),
    )
    with (
        patch(
            "deploy.controller.load_template_inputs", return_value=(doc, {})
        ) as decode,
        patch("deploy.controller.validate_environment_inputs") as validate,
    ):
        load_inputs(runtime, {"name": "good"})
        load_inputs(runtime, {"name": "good"})
    assert decode.call_count == validate.call_count == 1


@pytest.mark.parametrize("different", [False, True])
def check_comparison_pipeline_records_only_pending_leaf(models, different):
    value = {
        "WAIT": "PENDING_DEPLOY",
        "ONE": "1",
        "TWO": "2",
        "THREE": "3",
        "FOUR": "4",
    }
    scope, _ = authored(
        models, "Lambda.Function", "Environment.Variables", value, "CREATE"
    )
    comparator = comparison(models, (scope.service,))
    actual = dict(value, WAIT="aws-id")
    if different:
        actual["FOUR"] = "changed"
    document = template("Lambda.Function", {"Environment": {"Variables": actual}})
    document["Resources"]["Resource001"] = document["Resources"].pop("Resource")
    file = models / "infra/cloudformation/templates/team/producer.yaml"
    file.parent.mkdir(parents=True)
    file.write_text(json.dumps(document))
    comparator.stack_inputs = {
        "producer": (
            document,
            {},
            {
                "AWS::Region": "ap-northeast-1",
                "AWS::AccountId": "123456789012",
                "AWS::Partition": "aws",
            },
        )
    }
    comparator._templates = [
        (
            "producer",
            {
                "name": "producer",
                "template": "producer.yaml",
                "parameters": "producer.json",
            },
        )
    ]
    records = comparator.run()
    pending = [
        item
        for item in records
        if item.get("cause", {}).get("kind") == "desired-value-excluded"
    ]
    assert len(pending) == 1 and pending[0]["model"]["pointer"] == "/WAIT", records
    assert not any(item["category"] == "uncompared" for item in records)
    assert any(item["category"] == "difference" for item in records) == different


@pytest.mark.parametrize("index", [0, 1])
def check_deploy_uses_existing_select_and_mapping_evaluation(index):
    doc = template(
        "Lambda.Function",
        {
            "Environment": {
                "Variables": {
                    "KEY": {
                        "Fn::Select": [
                            index,
                            {"Fn::FindInMap": ["Env", "qa", "Values"]},
                        ]
                    }
                }
            }
        },
    )
    doc["Mappings"] = {"Env": {"qa": {"Values": ["fixed", "PENDING_DEPLOY"]}}}
    if index:
        with pytest.raises(EnvironmentValuePending):
            validate_environment_inputs(FRAMEWORK, doc, {}, TARGET, "stack")
    else:
        validate_environment_inputs(FRAMEWORK, doc, {}, TARGET, "stack")
    doc = template(
        "Lambda.Function",
        {
            "Environment": {
                "Variables": {
                    "KEY": {
                        "Fn::Sub": [
                            "${Resource.Arn}",
                            {
                                "Unused": "PENDING_DEPLOY",
                                "Undefined": {"Ref": "Missing"},
                            },
                        ]
                    }
                }
            }
        },
    )
    validate_environment_inputs(FRAMEWORK, doc, {}, TARGET, "stack")


@pytest.mark.parametrize(
    "physical", ["PENDING_DEPLOY", "12345678-1234-1234-1234-123456789012"]
)
def check_encoded_environment_typed_reference_retains_state(models, physical):
    producer, kms = resource(
        models, "kms", "KMS.Key", attribute="KeyId", observed=physical
    )
    save(producer, kms)
    value = {
        "EnvironmentVariables": json.dumps(
            [
                {
                    "name": "KEY",
                    "value": reference("KMS_Key_001", "KeyId"),
                    "type": "PLAINTEXT",
                }
            ]
        )
    }
    scope, values = authored(
        models,
        "CodePipeline.Pipeline",
        "Stages[].Actions[].Configuration",
        value,
        "IMPORT",
    )
    values["desired.row.001-001.comment"] = "EnvironmentVariables: 合成"
    warnings = []
    validate_json_settings(values, scope.path, warnings=warnings)
    pending = [
        item for item in warnings if item.get("category") == "REFERENCE_PENDING_DEPLOY"
    ]
    assert bool(pending) == (physical == "PENDING_DEPLOY")
    displayed = reference_display(values, scope.path, models)
    config = json.loads(literal(displayed["desired.row.001-001.value"]))
    assert json.loads(config["EnvironmentVariables"])[0]["value"] == (
        reference("KMS_Key_001", "KeyId") if physical == "PENDING_DEPLOY" else physical
    )
    assert values["desired.row.001-001.value"] == "`" + json.dumps(value) + "`"


@pytest.mark.parametrize("value", [{"Ref": "Vars"}, {"Fn::Sub": "CUSTOMER_A=${Value}"}])
def check_glue_execution_expressions(value):
    doc = template(
        "Glue.Job", {"DefaultArguments": {"--customer-driver-env-vars": value}}
    )
    with pytest.raises(EnvironmentValuePending):
        validate_environment_inputs(
            FRAMEWORK,
            doc,
            {"Vars": "CUSTOMER_A=PENDING_DEPLOY", "Value": "PENDING_DEPLOY"},
            TARGET,
            "stack",
        )
    validate_environment_inputs(
        FRAMEWORK, doc, {"Vars": "CUSTOMER_A=fixed", "Value": "fixed"}, TARGET, "stack"
    )


@pytest.mark.parametrize(
    "entry",
    [
        False,
        {"name": "KEY"},
        {"name": "KEY", "value": 1},
        {"name": "KEY", "value": "fixed", "type": "INVALID"},
    ],
)
def check_encoded_environment_invalid_entries(entry):
    kind = "CodePipeline.Pipeline"
    with pytest.raises(ValueError):
        inspect(
            kind,
            kind + ".Stages[].Actions[].Configuration",
            {"EnvironmentVariables": json.dumps([entry])},
            mapping_for(FRAMEWORK, kind),
        )


def check_plain_json_string_is_not_an_encoded_environment_structure(models):
    scope, values = authored(
        models,
        "Lambda.Function",
        "Environment.Variables",
        {"KEY": '{"literal":"PENDING_DEPLOY"}'},
        "IMPORT",
    )
    validate_environment_settings(values, scope.path)
    assert (
        reference_display(values, scope.path, models)["desired.row.001-001.value"]
        == values["desired.row.001-001.value"]
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
