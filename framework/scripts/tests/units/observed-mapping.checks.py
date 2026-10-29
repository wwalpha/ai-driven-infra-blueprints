"""Observed mappings preserves ownership and narrowly permits static Export scaffolds."""

import json
import sys
from collections import Counter
from copy import deepcopy
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import observed as deploy_observed
from model.adapters import observed
from model.core import entries as entries
from model.display import display_rows
from model.projection import resource_rows
from support.model_sources import allocate_fixture, write_model
from utils.sealed_evidence import read_sealed, write_sealed

from model import dependency_index, sources

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


@pytest.fixture
def preflight_files(project_workspace, monkeypatch):
    root = project_workspace
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    target = {
        "environment": "dev",
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "iacEngine": "cloudformation",
    }
    (root / "project.json").write_text(
        json.dumps({"targets": [target]}), encoding="utf-8"
    )
    stacks, templates, paths = {}, {}, []
    for number, name in enumerate(("First", "Second"), 1):
        path = root / f"model/dev/123456789012/bucket-{number}.properties"
        values = {
            "desired.resource.001.resourceType": "EC2.VPC",
            "desired.resource.001.cfn-logicalId": name + "-Bucket",
            "desired.row.001-001.property": "EC2.VPC.VpcId",
            "desired.row.001-001.value": "[self](#resource-EC2_VPC_001)",
            "desired.row.001-001.comment": "識別子",
        }
        values.update(allocate_fixture(values, ["001"]))
        write_model(path, values)
        paths.append(path)
        unit = {
            "name": name,
            "template": name + ".yaml",
            "parameters": name + ".json",
            "deployOrder": str(number),
        }
        stacks.update(
            {f"desired.stack.{number:03d}.{key}": value for key, value in unit.items()}
        )
        template = root / "infra/cloudformation/templates" / unit["template"]
        template.parent.mkdir(parents=True, exist_ok=True)
        document = {"Resources": {"Bucket": {"Type": "AWS::EC2::VPC"}}}
        template.write_text(json.dumps(document), encoding="utf-8")
        parameters = (
            root
            / "infra/cloudformation/parameters/dev/123456789012"
            / unit["parameters"]
        )
        parameters.parent.mkdir(parents=True, exist_ok=True)
        parameters.write_text("[]", encoding="utf-8")
        templates[name] = document
    write_model(paths[0].with_name("cloudformation-stacks.properties"), stacks)
    return root, paths, templates


@pytest.mark.parametrize("unrelated_count", [1, 40])
def check_preflight_indexed_read_budget(preflight_files, unrelated_count):
    root, paths, documents = preflight_files
    for number in range(unrelated_count):
        write_model(paths[0].with_name(f"unrelated-{number}.properties"), {})
    dependency_index.rebuild(root)
    with (
        sources.model_session(observed.RunModels(root, {})),
        patch.object(sources, "_read_model", wraps=sources._read_model) as before,
    ):
        observed._mappings(
            root,
            "dev",
            "123456789012",
            {"First": (documents["First"], {})},
            [{"name": "First"}],
            implementation=True,
            check_scope=False,
        )
    baseline = Counter(call.args[0].path for call in before.call_args_list)
    with (
        patch.object(sources, "_read_model", wraps=sources._read_model) as loads,
        patch.object(
            sources._imports_model_references,
            "diagnose",
            wraps=sources._imports_model_references.diagnose,
        ) as checks,
        patch.object(
            dependency_index, "read_sealed", wraps=dependency_index.read_sealed
        ) as index_reads,
        patch.object(
            dependency_index,
            "rebuild",
            side_effect=AssertionError("preflight rebuilt index"),
        ),
        patch.object(
            dependency_index,
            "record",
            side_effect=AssertionError("preflight rebuilt record"),
        ),
    ):
        loaded, mapped = observed.preflight(root, "dev", "123456789012", ["First"])
    assert set(loaded) == {paths[0]}
    assert set(mapped["First"]) == {"Bucket"}
    assert Counter(call.args[0].path for call in loads.call_args_list) == Counter(
        {paths[0]: 1, paths[0].with_name("cloudformation-stacks.properties"): 1}
    )
    assert Counter(
        call.args[0].scope.path for call in checks.call_args_list
    ) == Counter(
        {paths[0]: 1, paths[0].with_name("cloudformation-stacks.properties"): 1}
    )
    assert index_reads.call_count == 1
    assert len(baseline) == unrelated_count + 3
    print(
        f"preflight services: before={unrelated_count + 2}, after=1; unrelated parse=0; index reads=1, rebuild=0"
    )


@pytest.mark.parametrize("selected", [False, True])
def check_preflight_indexed_invalid_model(preflight_files, selected):
    root, paths, _ = preflight_files
    path = paths[0] if selected else paths[1]
    # Raw index metadata is readable; full Model loading rejects this declaration.
    path.write_text(
        path.read_text(encoding="utf-8")
        + "desired.reference.001.producerKind=unknown\n",
        encoding="utf-8",
    )
    dependency_index.rebuild(root)
    with pytest.raises(ValueError):
        sources.load_model(path)
    if selected:
        with pytest.raises(ValueError):
            observed.preflight(root, "dev", "123456789012", ["First"])
    else:
        assert set(observed.preflight(root, "dev", "123456789012", ["First"])[0]) == {
            paths[0]
        }


@pytest.mark.parametrize(
    "fault", ["duplicate", "type", "import", "identifier", "condition", "output"]
)
def check_preflight_indexed_mapping_errors(preflight_files, fault):
    root, paths, documents = preflight_files
    text = paths[0].read_text(encoding="utf-8")
    if fault == "duplicate":
        write_model(paths[0].with_name("duplicate.properties"), text)
    elif fault == "type":
        documents["First"]["Resources"]["Bucket"]["Type"] = "AWS::S3::Bucket"
    elif fault == "import":
        write_model(paths[0], text + "desired.resource.001.resourceMode=IMPORT\n")
    elif fault == "identifier":
        write_model(
            paths[0], text.replace("[self](#resource-EC2_VPC_001)", "`literal`")
        )
    elif fault == "condition":
        documents["First"]["Resources"]["Bucket"]["Condition"] = "Missing"
    else:
        documents["First"]["Outputs"] = {
            "Bad": {"Condition": "Missing", "Value": {"Ref": "Bucket"}}
        }
    (root / "infra/cloudformation/templates/First.yaml").write_text(
        json.dumps(documents["First"]), encoding="utf-8"
    )
    dependency_index.rebuild(root)
    with pytest.raises((ValueError, observed.Blocked)):
        observed.preflight(root, "dev", "123456789012", ["First"])


def check_preflight_indexed_multiple_stacks(preflight_files):
    root, paths, _ = preflight_files
    paths[0].with_name("unrelated.properties").write_text(
        "# model-format: 2\ndesired.reference.001.producerKind=unknown\n",
        encoding="utf-8",
    )
    dependency_index.rebuild(root)
    with patch.object(sources, "_read_model", wraps=sources._read_model) as loads:
        loaded, mapped = observed.preflight(
            root, "dev", "123456789012", ["First", "Second"]
        )
    assert set(loaded) == set(paths)
    assert set(mapped) == {"First", "Second"}
    assert len(loads.call_args_list) == 3


@pytest.mark.parametrize(
    "kind,properties",
    [
        ("LakeFormation.Resource", ["Id"]),
        (
            "LakeFormation.PrincipalPermissions",
            ["PrincipalIdentifier", "ResourceIdentifier"],
        ),
    ],
)
@pytest.mark.parametrize("existing_rows", [False, True])
def check_lakeformation_arn_identifiers_are_not_collected(
    preflight_files, monkeypatch, kind, properties, existing_rows
):
    root, paths, documents = preflight_files
    source = paths[0]
    text = source.read_text(encoding="utf-8")
    text = text.replace("EC2.VPC", kind).replace("EC2_VPC", kind.replace(".", "_"))
    text = text.replace(kind + ".VpcId", kind + "." + properties[0])
    if not existing_rows:
        text = (
            "\n".join(
                line
                for line in text.splitlines()
                if not line.startswith("desired.row.")
            )
            + "\n"
        )
    else:
        text += "observed.row.001-001.value=`PENDING_DEPLOY`\n"
        if len(properties) > 1:
            text += f"desired.row.001-002.property={kind}.{properties[1]}\ndesired.row.001-002.value=[self](#resource-{kind.replace('.', '_')}_001)\ndesired.row.001-002.comment=identifier\n"
    write_model(source, text)
    document = documents["First"]
    document["Resources"]["Bucket"]["Type"] = "AWS::" + kind.replace(".", "::")
    document["Outputs"] = {
        name: {"Value": {"Fn::GetAtt": ["Bucket", name]}} for name in properties
    }
    arn = "LakeFormation-arn:aws:glue:ap-northeast-1:123456789012:connection/example"
    backend = SimpleNamespace(
        root=root,
        environment="dev",
        directory="123456789012",
        target={"awsRegion": "ap-northeast-1", "awsAccountId": "123456789012"},
        templates={"First": (document, {})},
        run_context={},
        aws=Mock(
            side_effect=[
                {
                    "Stacks": [
                        {
                            "StackStatus": "CREATE_COMPLETE",
                            "Outputs": [
                                {"OutputKey": name, "OutputValue": arn}
                                for name in properties
                            ],
                        }
                    ]
                },
                {
                    "StackResourceSummaries": [
                        {
                            "LogicalResourceId": "Bucket",
                            "ResourceType": document["Resources"]["Bucket"]["Type"],
                            "PhysicalResourceId": arn,
                        }
                    ]
                },
            ]
        ),
    )
    monkeypatch.setattr(observed, "active_scope", lambda root: None)
    before = source.read_bytes()
    assert deploy_observed.collect_successful(
        backend, [{"name": "First"}], {"First": {}}
    ) == ({}, [], None)
    assert source.read_bytes() == before
    if existing_rows:
        values = sources.load_model(source).authoritative
        rows = resource_rows(values, "001", kind, root)
        assert not display_rows(kind, rows, root=root)
    document["Outputs"] = {}
    _, mapped = observed.resolve_resources(
        root,
        "dev",
        "123456789012",
        backend.templates,
        [{"name": "First"}],
        {"First": {"Bucket"}},
        target=backend.target,
    )
    assert mapped["First"]["Bucket"][4] == set()
    plan = observed.destroy_plan(
        root, "dev", "123456789012", ["First"], check_scope=False
    )
    assert plan["updates"] == {"First": {}}
    assert plan["owners"]["First"][0]["logicalId"] == "Bucket"
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "fault", ["missing", "stale", "new-owner", "removed", "metadata", "invalid"]
)
def check_preflight_index_integrity(preflight_files, fault):
    root, paths, _ = preflight_files
    dependency_index.rebuild(root)
    index_path = dependency_index.location(root)
    if fault == "missing":
        index_path.unlink()
        assert set(
            observed.preflight(root, "dev", "123456789012", ["First"])[0]
        ) == set(paths)
        assert not index_path.exists()
        paths[1].write_text("broken syntax", encoding="utf-8")
    elif fault == "stale":
        paths[1].write_text(paths[0].read_text(encoding="utf-8"), encoding="utf-8")
    elif fault == "new-owner":
        write_model(
            paths[0].with_name("new-owner.properties"),
            paths[0].read_text(encoding="utf-8"),
        )
    elif fault == "removed":
        paths[1].unlink()
    elif fault == "metadata":
        index = read_sealed(root, index_path)
        index["models"][paths[0].relative_to(root).as_posix()]["owners"].append(
            "Other-Resource"
        )
        write_sealed(root, index_path, index)
    else:
        index_path.write_text("invalid sealed index", encoding="utf-8")
    with pytest.raises(ValueError):
        observed.preflight(root, "dev", "123456789012", ["First"])


@pytest.mark.parametrize("mode", ["IMPORT", "CREATE", "mapped"])
def check_preflight_import_only_fallback(preflight_files, mode):
    root, paths, documents = preflight_files
    text = (
        paths[0]
        .read_text(encoding="utf-8")
        .replace("desired.resource.001.cfn-logicalId=First-Bucket\n", "")
    )
    write_model(paths[0], text + "desired.resource.001.resourceMode=IMPORT\n")
    second = paths[1].read_text(encoding="utf-8")
    if mode != "mapped":
        second = second.replace(
            "desired.resource.001.cfn-logicalId=Second-Bucket\n", ""
        )
        write_model(paths[1], second + f"desired.resource.001.resourceMode={mode}\n")
    dependency_index.rebuild(root)
    with patch.object(observed, "models", wraps=observed.models) as fallback:
        if mode == "IMPORT":
            assert observed.preflight(root, "dev", "123456789012", ["First"])[1] == {
                "First": {}
            }
        else:
            with pytest.raises(
                observed.MappingError, match="explicit mapping required"
            ):
                observed.preflight(root, "dev", "123456789012", ["First"])
    assert fallback.call_count == 1


@pytest.mark.parametrize("missing_settings", [False, True])
def check_preflight_integrated_child(preflight_files, missing_settings):
    root, paths, documents = preflight_files
    text = (
        paths[0]
        .read_text(encoding="utf-8")
        .replace("EC2.VPC", "S3.Bucket")
        .replace("EC2_VPC", "S3_Bucket")
        .replace("S3.Bucket.VpcId", "S3.Bucket.BucketName")
    )
    if not missing_settings:
        text += 'desired.row.001-002.property=S3.BucketPolicy.PolicyDocument\ndesired.row.001-002.value=`{"Statement":[]}`\ndesired.row.001-002.comment=子設定\n'
    write_model(paths[0], text)
    documents["First"]["Resources"]["Bucket"]["Type"] = "AWS::S3::Bucket"
    documents["First"]["Resources"]["Policy"] = {
        "Type": "AWS::S3::BucketPolicy",
        "Properties": {"Bucket": {"Ref": "Bucket"}},
    }
    (root / "infra/cloudformation/templates/First.yaml").write_text(
        json.dumps(documents["First"]), encoding="utf-8"
    )
    if not missing_settings:
        with (
            sources.model_session(observed.RunModels(root, {})),
            patch.object(sources, "_read_model", wraps=sources._read_model) as baseline,
        ):
            observed._mappings(
                root,
                "dev",
                "123456789012",
                {"First": (documents["First"], {})},
                [{"name": "First"}],
                implementation=True,
                check_scope=False,
            )
        baseline_counts = Counter(call.args[0].path for call in baseline.call_args_list)
        assert baseline_counts[paths[0]] == baseline_counts[paths[1]] == 1
    paths[1].write_text(
        paths[1].read_text(encoding="utf-8")
        + "desired.reference.001.producerKind=unknown\n",
        encoding="utf-8",
    )
    dependency_index.rebuild(root)
    with (
        patch.object(sources, "_read_model", wraps=sources._read_model) as loads,
        patch.object(observed, "models", wraps=observed.models) as fallback,
        patch.object(
            dependency_index, "rebuild", side_effect=AssertionError("rebuild")
        ),
    ):
        if missing_settings:
            with pytest.raises(
                observed.MappingError, match="integrated child settings missing"
            ):
                observed.preflight(root, "dev", "123456789012", ["First"])
        else:
            _, mapped = observed.preflight(root, "dev", "123456789012", ["First"])
            assert set(mapped["First"]) == {"Bucket", "Policy"}
            assert all(item[0] == paths[0] for item in mapped["First"].values())
        counts = Counter(call.args[0].path for call in loads.call_args_list)
        assert counts[paths[0]] == 1
        assert counts[paths[1]] == 0
        assert fallback.call_count == 0

    if not missing_settings:
        template = root / "infra/cloudformation/templates/First.yaml"
        original = deepcopy(documents["First"])
        for fault in ("missing", "ref", "type"):
            document = deepcopy(original)
            if fault == "missing":
                del document["Resources"]["Bucket"]
            elif fault == "ref":
                document["Resources"]["Policy"]["Properties"]["Bucket"] = "invalid"
            else:
                document["Resources"]["Bucket"]["Type"] = "AWS::EC2::VPC"
            template.write_text(json.dumps(document), encoding="utf-8")
            with pytest.raises(ValueError, match="integrated child parent"):
                observed.preflight(root, "dev", "123456789012", ["First"])

        second = text.replace("First-Bucket", "First-OtherBucket")
        write_model(paths[1], second)
        document = deepcopy(original)
        document["Resources"]["OtherBucket"] = {"Type": "AWS::S3::Bucket"}
        document["Resources"]["OtherPolicy"] = {
            "Type": "AWS::S3::BucketPolicy",
            "Properties": {"Bucket": {"Ref": "OtherBucket"}},
        }
        template.write_text(json.dumps(document), encoding="utf-8")
        dependency_index.rebuild(root)
        with patch.object(observed, "models", wraps=observed.models) as fallback:
            _, mapped = observed.preflight(root, "dev", "123456789012", ["First"])
        assert mapped["First"]["Policy"][0] == paths[0]
        assert mapped["First"]["OtherPolicy"][0] == paths[1]
        assert fallback.call_count == 0


def check_preflight_indexed_task_scope_and_other_targets(preflight_files):
    root, paths, documents = preflight_files
    tasks = root / "tasks"
    tasks.mkdir()
    (tasks / "selected.md").write_text(
        "## Task contract\n- Task status: `running`\n## Validation scope\n- `dev/123456789012/bucket-1`\n## Modified files\n- `tasks/selected.md`\n## Allowed paths\n- `tasks/selected.md`\n",
        encoding="utf-8",
    )
    dependency_index.rebuild(root)
    # A new malformed authority in another environment is outside this read scope.
    outside = root / "model/stg/123456789012/broken.properties"
    outside.parent.mkdir(parents=True)
    outside.write_text("broken syntax", encoding="utf-8")
    assert set(observed.preflight(root, "dev", "123456789012", ["Second"])[0]) == {
        paths[1]
    }
    outside.unlink()
    with pytest.raises(observed.MappingError, match="task scope violation"):
        observed.mappings(
            root,
            "dev",
            "123456789012",
            {"Second": (documents["Second"], {})},
            [{"name": "Second"}],
        )


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
