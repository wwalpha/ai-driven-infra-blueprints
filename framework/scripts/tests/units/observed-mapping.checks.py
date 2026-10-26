"""Observed mappings preserves ownership and narrowly permits static Export scaffolds."""

import sys
from copy import deepcopy
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import observed as deploy_observed
from model.adapters import observed
from model.core import entries as entries

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _mapping_inputs___init__(self, root):
    pass


def _mapping_inputs_cloudformation_type(self, kind):
    return "AWS::EC2::VPC"


def _callback_mapping_inputs_invoke(
    tmp_path,
    /,
    resources,
    *,
    document=None,
    parameters=None,
    removed=None,
    implementation=False,
):
    return observed.mappings(
        tmp_path,
        "dev",
        "test",
        {
            "Stack": (
                document if document is not None else {"Resources": resources},
                parameters or {"NetworkId": "vpc-fixture"},
            )
        },
        [{"name": "Stack"}],
        removed=removed,
        target={"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"},
        implementation=implementation,
    )


@pytest.fixture
def mapping_inputs(tmp_path, monkeypatch):
    loaded = {}
    monkeypatch.setattr(observed, "models", lambda *args: loaded)
    monkeypatch.setattr(observed, "model_exists", lambda path: False)
    monkeypatch.setattr(observed, "require_fixed_stack_names", lambda *args: {})
    monkeypatch.setattr(observed, "active_scope", lambda root: None)
    monkeypatch.setattr(observed, "GROUPED", {})
    monkeypatch.setattr(observed, "catalog_outputs", lambda *args: set())

    class Catalog:
        __init__ = _mapping_inputs___init__
        cloudformation_type = _mapping_inputs_cloudformation_type

    monkeypatch.setattr(observed, "DesignSchemaCatalog", Catalog)
    monkeypatch.setattr(deploy_observed, "DesignSchemaCatalog", Catalog)
    monkeypatch.setattr(
        deploy_observed,
        "resolve_resources",
        lambda root,
        env,
        directory,
        templates,
        units,
        selected,
        removed=None,
        **kwargs: observed._mappings(
            root,
            env,
            directory,
            templates,
            units,
            removed,
            kwargs.get("target"),
            loaded=loaded,
            selection=selected,
        ),
    )
    invoke = _bind_framework_callback(_callback_mapping_inputs_invoke, tmp_path)
    return tmp_path, loaded, invoke


def resource(values, identity, logical):
    values.update(
        {
            f"desired.resource.{identity}.resourceType": "EC2.VPC",
            f"desired.resource.{identity}.logicalId": "EC2_VPC_" + identity,
            f"desired.resource.{identity}.cfn-logicalId": "Stack-" + logical,
        }
    )


def definition():
    return {"Type": "AWS::EC2::VPC"}


def check_fixed_ownership_and_invocation_isolation(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / "model/dev/test/vpc.properties"] = {}
    resource(values, "001", "Parent")
    resource(values, "002", "Child")
    for rid in ["001-002", "002-001", "001-001"]:
        values[f"desired.row.{rid}.value"] = rid
        values[f"desired.row.{rid}.property"] = "EC2.VPC.CidrBlock"
    result = invoke({"Parent": definition(), "Child": definition()})[1]["Stack"]
    assert [rid for rid, row in result["Parent"][3]] == ["001-001", "001-002"]
    assert [rid for rid, row in result["Child"][3]] == ["002-001"]
    result["Parent"][3][0][1]["value"] = "changed"
    assert values["desired.row.001-001.value"] == "001-001"
    values["desired.row.001-001.value"] = "next call"
    assert (
        dict(invoke({"Parent": definition()})[1]["Stack"]["Parent"][3])["001-001"][
            "value"
        ]
        == "next call"
    )


def check_lazy_whole_model_parse_and_error_order(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / "model/dev/test/vpc.properties"] = {
        "desired.row.orphan": "malformed"
    }
    resource(values, "001", "First")
    resource(values, "002", "Second")
    assert invoke({})[1] == {"Stack": {}}
    with patch.object(observed, "condition_active", return_value=False):
        assert invoke({"First": definition()})[1] == {"Stack": {}}
    with pytest.raises(observed.MappingError) as caught:
        invoke({"Unknown": definition(), "First": definition(), "Second": definition()})
    assert caught.value.errors == {
        "Stack": [
            "Stack/Unknown: cfn-logicalId matches=0; explicit mapping required",
            "Stack/First: invalid model entry: desired.row.orphan",
            "Stack/Second: invalid model entry: desired.row.orphan",
        ]
    }
    loaded[root / "model/dev/test/unused.properties"] = {
        "desired.row.unused": "malformed"
    }
    del values["desired.row.orphan"]
    assert invoke({"First": definition()})[1]["Stack"]["First"][3] == []
    values["desired.row.999-001.value"] = "orphan"
    with pytest.raises(observed.MappingError, match="orphan desired row"):
        invoke({"First": definition()})


@pytest.mark.parametrize("fault", ["none", "type", "duplicate", "import", "condition"])
def check_preflight_uses_shared_selected_mapping(mapping_inputs, monkeypatch, fault):
    root, loaded, _ = mapping_inputs
    values = loaded[root / "model/dev/test/vpc.properties"] = {}
    resource(values, "001", "Vpc")
    # Ownership metadata for a different Stack must not trigger its validation.
    resource(values, "002", "Other")
    values["desired.resource.002.cfn-logicalId"] = "Undeclared-Other"
    document = {"Resources": {"Vpc": definition()}}
    if fault == "type":
        document["Resources"]["Vpc"]["Type"] = "AWS::EC2::Subnet"
    elif fault == "duplicate":
        resource(values, "003", "Vpc")
    elif fault == "import":
        values["desired.resource.001.resourceMode"] = "IMPORT"
    elif fault == "condition":
        document["Resources"]["Vpc"]["Condition"] = "Unknown"
    monkeypatch.setattr(
        observed, "load_target", lambda *args: {"iacEngine": "cloudformation"}
    )
    monkeypatch.setattr(observed, "read_model", lambda *args: "")
    monkeypatch.setattr(
        observed,
        "stack_model",
        lambda *args: (
            {},
            [
                (
                    "001",
                    {
                        "name": "Stack",
                        "template": "selected.yaml",
                        "parameters": "selected.json",
                    },
                ),
                (
                    "002",
                    {
                        "name": "Other",
                        "template": "unselected.yaml",
                        "parameters": "unselected.json",
                    },
                ),
            ],
        ),
    )
    with (
        patch.object(
            observed,
            "active_scope",
            side_effect=AssertionError("preflight must not request scope"),
        ),
        patch.object(
            observed, "load_template_inputs", return_value=(document, {})
        ) as reads,
    ):
        if fault == "none":
            assert set(
                observed.preflight(root, "dev", "test", ["Stack"])[1]["Stack"]
            ) == {"Vpc"}
        else:
            with pytest.raises(observed.MappingError):
                observed.preflight(root, "dev", "test", ["Stack"])
        assert reads.call_count == 1
        assert reads.call_args.args[0].name == "selected.yaml"


def check_explicit_mapping_uniqueness_and_no_name_inference(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / "model/dev/test/vpc.properties"] = {}
    resource(values, "001", "First")
    del values["desired.resource.001.cfn-logicalId"]
    with pytest.raises(observed.MappingError, match="explicit mapping required"):
        invoke({"First": definition()})
    values["desired.resource.001.cfn-logicalId"] = "Stack-First"
    resource(values, "002", "First")
    with pytest.raises(observed.MappingError, match="matches=2"):
        invoke({"First": definition()})
    values["desired.row.orphan"] = "malformed"
    with pytest.raises(observed.MappingError) as caught:
        invoke({"First": definition()})
    assert caught.value.errors == {
        "Stack": ["Stack/First: cfn-logicalId matches=2; explicit mapping required"]
    }


HANDLE = "AWS::CloudFormation::WaitConditionHandle"


def static_template(logical="StaticExportHandle"):
    return {
        "Parameters": {"NetworkId": {"Type": "String"}},
        "Resources": {logical: {"Type": HANDLE}},
        "Outputs": {
            "NetworkId": {
                "Value": {"Ref": "NetworkId"},
                "Export": {"Name": "NetworkId"},
            }
        },
    }


def _check_static_exports_share_mapping_and_skip_observed_unexpected(*args, **kwargs):
    pytest.fail(
        "static Export scaffold must not map, read AWS, or publish observations"
    )


def check_static_exports_share_mapping_and_skip_observed(mapping_inputs, monkeypatch):
    root, loaded, invoke = mapping_inputs
    unexpected = _check_static_exports_share_mapping_and_skip_observed_unexpected
    monkeypatch.setattr(observed, "mapped_resource", unexpected)
    monkeypatch.setattr(observed, "publish_observed", unexpected)
    for logical in ("StaticExportHandle", "DifferentHandle"):
        document = static_template(logical)
        # Parameter-derived Export names use the existing intrinsic evaluator.
        if logical == "DifferentHandle":
            document["Outputs"]["NetworkId"]["Export"]["Name"] = {
                "Fn::Sub": "Network${AWS::Region}"
            }
        normal = invoke({}, document=document)
        assert (
            normal
            == invoke({}, document=document, implementation=True)
            == ({}, {"Stack": {}})
        )
        for cached in (False, True):
            backend = SimpleNamespace(
                run_context={},
                root=root,
                environment="dev",
                directory="test",
                target={"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"},
                templates={"Stack": (document, {"NetworkId": "vpc-fixture"})},
                aws=unexpected,
            )
            if cached:
                backend.mapping_plan = normal
            states = {"Stack": {}}
            assert (
                deploy_observed.sync_successful(backend, [{"name": "Stack"}], states)
                is None
            )
            assert states == {"Stack": {"observedSynced": True}}
        assert loaded == {}


def check_static_export_decoded_fixture(mapping_inputs):
    root, _, invoke = mapping_inputs
    template, inputs = root / "static.yaml", root / "static.json"
    template.write_text(
        """Parameters:
  NetworkId:
    Type: String
  SubnetId:
    Type: String
Resources:
  StaticExportHandle:
    Type: AWS::CloudFormation::WaitConditionHandle
Outputs:
  NetworkId:
    Value: !Ref NetworkId
    Export:
      Name: NetworkId
  SubnetId:
    Value: !Ref SubnetId
    Export:
      Name: SubnetId
""",
        encoding="utf-8",
    )
    inputs.write_text(
        '[{"ParameterKey":"NetworkId","ParameterValue":"vpc-fixture"},'
        '{"ParameterKey":"SubnetId","ParameterValue":"subnet-fixture"}]',
        encoding="utf-8",
    )
    document, parameters = observed.load_template_inputs(template, inputs)
    assert (
        invoke({}, document=document, parameters=parameters)
        == invoke({}, document=document, parameters=parameters, implementation=True)
        == ({}, {"Stack": {}})
    )


def check_static_export_rejects_resource_configuration(mapping_inputs):
    _, _, invoke = mapping_inputs
    for key, value in (
        ("Properties", {}),
        ("Condition", "Enabled"),
        ("DependsOn", []),
        ("Metadata", {}),
        ("DeletionPolicy", "Retain"),
        ("UpdateReplacePolicy", "Retain"),
        ("CreationPolicy", {}),
        ("UpdatePolicy", {}),
    ):
        document = static_template()
        document["Resources"]["StaticExportHandle"][key] = value
        document["Conditions"] = {"Enabled": True}
        for implementation in (False, True):
            with pytest.raises(
                observed.MappingError, match="explicit mapping required"
            ):
                invoke({}, document=document, implementation=implementation)


def check_static_export_requires_direct_parameter_exports(mapping_inputs):
    _, _, invoke = mapping_inputs
    invalid = [
        {"Outputs": {}},
        {"Parameters": {}},
        {"Parameters": None},
        {"Parameters": {"NetworkId": None}},
        {
            "Parameters": {
                "NetworkId": {"Type": "String"},
                "StaticExportHandle": {"Type": "String"},
            }
        },
        {"Outputs": {"NetworkId": {"Value": {"Ref": "NetworkId"}}}},
        {"Outputs": {"NetworkId": {"Value": {"Ref": "NetworkId"}, "Export": {}}}},
    ]
    for value in (
        {"Ref": "StaticExportHandle"},
        {"Ref": "Unknown"},
        "literal",
        {"Fn::Sub": "${NetworkId}"},
        {"Fn::Join": ["", [{"Ref": "NetworkId"}]]},
        {"Fn::GetAtt": ["StaticExportHandle", "Id"]},
    ):
        output = deepcopy(static_template()["Outputs"])
        output["NetworkId"]["Value"] = value
        invalid.append({"Outputs": output})
    for export in (
        None,
        {},
        {"Name": ""},
        {"Name": None},
        {"Name": {"Ref": "Unknown"}},
        {"Name": "NetworkId", "Extra": "value"},
    ):
        output = deepcopy(static_template()["Outputs"])
        output["NetworkId"]["Export"] = export
        invalid.append({"Outputs": output})
    for change in invalid:
        document = static_template() | change
        for implementation in (False, True):
            with pytest.raises(
                observed.MappingError, match="explicit mapping required"
            ):
                invoke({}, document=document, implementation=implementation)
    assert not observed.static_export_handle(
        static_template() | {"Outputs": None}, "StaticExportHandle", {}, {}
    )


def check_static_export_rejects_dependencies_and_unknown_expressions(mapping_inputs):
    _, _, invoke = mapping_inputs
    expressions = [
        {"Ref": "StaticExportHandle"},
        {"Fn::GetAtt": ["StaticExportHandle", "Id"]},
        {"Fn::GetAtt": "StaticExportHandle.Id"},
        {"Fn::Sub": "${StaticExportHandle}"},
        {"Fn::Sub": "${StaticExportHandle.Id}"},
        {"Fn::Sub": ["${Alias}", {"Alias": {"Ref": "StaticExportHandle"}}]},
        {"Fn::Sub": ["literal", {"Unused": {"Ref": "StaticExportHandle"}}]},
        {"Fn::If": ["Enabled", "unused", {"Ref": "StaticExportHandle"}]},
        {"Fn::Unknown": "value"},
        {"Ref": "Unknown"},
        {"Fn::Sub": [1]},
        {"DependsOn": "StaticExportHandle"},
        {"DependsOn": ["StaticExportHandle"]},
    ]
    for expression in expressions:
        for location in ("Metadata", "Export"):
            document = static_template()
            document["Conditions"] = {"Enabled": True}
            if location == "Export":
                document["Outputs"]["NetworkId"]["Export"]["Name"] = expression
            else:
                document["Metadata"] = {"Nested": [expression]}
            for implementation in (False, True):
                with pytest.raises(
                    observed.MappingError, match="explicit mapping required"
                ):
                    invoke(
                        {},
                        document=document,
                        parameters={
                            "NetworkId": "vpc-fixture",
                            "StaticExportHandle": "must-not-mask-resource-reference",
                        },
                        implementation=implementation,
                    )
    document = static_template() | {"Transform": "UnknownTransform"}
    with pytest.raises(observed.MappingError, match="explicit mapping required"):
        invoke({}, document=document)


def check_static_export_requires_sole_resource(mapping_inputs):
    _, _, invoke = mapping_inputs
    for other in (
        {"Other": definition()},
        {
            "Wait": {
                "Type": "AWS::CloudFormation::WaitCondition",
                "Properties": {"Handle": {"Ref": "StaticExportHandle"}, "Timeout": "1"},
            }
        },
    ):
        document = static_template()
        document["Resources"].update(other)
        for implementation in (False, True):
            with pytest.raises(observed.MappingError) as caught:
                invoke({}, document=document, implementation=implementation)
            assert len(caught.value.errors["Stack"]) == 2
            assert all(
                "explicit mapping required" in error
                for error in caught.value.errors["Stack"]
            )
    document = static_template()
    document["Resources"]["StaticExportHandle"] = definition()
    with pytest.raises(observed.MappingError, match="explicit mapping required"):
        invoke({}, document=document)


def check_static_export_preserves_explicit_mapping_checks(mapping_inputs, monkeypatch):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / "model/dev/test/vpc.properties"] = {}
    resource(values, "001", "StaticExportHandle")
    document = static_template()
    for implementation in (False, True):
        with pytest.raises(observed.MappingError, match="formal CFn type mismatch"):
            invoke({}, document=document, implementation=implementation)
    monkeypatch.setattr(
        observed.DesignSchemaCatalog, "cloudformation_type", lambda *args: HANDLE
    )
    normal = invoke({}, document=document)
    assert normal == invoke({}, document=document, implementation=True)
    assert set(normal[1]["Stack"]) == {"StaticExportHandle"}
    values["desired.resource.001.resourceMode"] = "IMPORT"
    with pytest.raises(observed.MappingError, match="requires CREATE"):
        invoke({}, document=document)
    del values["desired.resource.001.resourceMode"]
    resource(values, "002", "StaticExportHandle")
    for implementation in (False, True):
        with pytest.raises(observed.MappingError, match="matches=2"):
            invoke({}, document=document, implementation=implementation)


def check_static_export_preserves_removal_guards(mapping_inputs, monkeypatch):
    root, _, invoke = mapping_inputs
    document = static_template()
    units = [{"name": "Stack"}]
    states = {
        "Stack": {
            "changes": [
                {
                    "Action": "Remove",
                    "LogicalResourceId": "StaticExportHandle",
                    "ResourceType": HANDLE,
                    "PolicyAction": "Delete",
                }
            ]
        }
    }
    removed = deploy_observed.removed_resources(units, states)
    for resources in (document["Resources"], {}):
        deleting_document = document | {"Resources": resources}
        for implementation in (False, True):
            with pytest.raises(
                observed.MappingError, match="explicit mapping required"
            ):
                invoke(
                    {},
                    document=deleting_document,
                    removed=removed,
                    implementation=implementation,
                )
    backend = SimpleNamespace(
        run_context={},
        root=root,
        environment="dev",
        directory="test",
        target={"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"},
        templates={"Stack": (document, {"NetworkId": "vpc-fixture"})},
    )
    with pytest.raises(observed.MappingError, match="explicit mapping required"):
        deploy_observed.sync_successful(backend, units, states)
    backend.mapping_plan = invoke({}, document=document)
    with pytest.raises(observed.MappingError, match="explicit mapping required"):
        deploy_observed.sync_successful(backend, units, states)
    assert "observedSynced" not in states["Stack"]


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__, message="observed explicit mapping checks: PASS"))
