"""Shape, path and provider literal contracts on synthetic or pinned schemas."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from design.catalog import DesignSchemaCatalog, property_paths_with_parents
from model.literal_values import (
    array_paths,
    literal_errors,
    normalize,
    projection_conflicts,
    projection_value,
    typed_value,
    value_shape,
)
from support.pytest_cli import run
from support.regression_cases import case_ids
from utils.cloudformation.schema import CloudFormationSchemaCatalog
from utils.comparison_rows import Unresolved, project, put_row, select
from utils.property_path import definition_path

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]


def normalize_case(case):
    data = case["data"]
    before = deepcopy(data)
    result = normalize(data["prop"], data["value"], data["shape"])
    TestCase().assertIs(type(result.values), tuple)
    TestCase().assertIs(type(result.arrays), tuple)
    for pair in result.arrays:
        TestCase().assertIs(type(pair), tuple)
    TestCase().assertEqual(data, before)
    return {
        "values": list(result.values),
        "arrays": [[path, array] for path, array in result.arrays],
    }


@pytest.mark.parametrize(
    "case_id", case_ids("model_literal_values", prefix="normalize-")
)
def test_normalize(case_runner, case_id):
    case_runner.run("model_literal_values", case_id, normalize_case)


@pytest.mark.parametrize(
    "prop,value,shape",
    [
        ("Parents[].Value", "A", "projection"),
        ("Parents[].Children[].Value", ["A"], "projection"),
        ("Parents[].Children[].Value", [[], "A"], "projection"),
        ("Value", [], "projection"),
        ("Parents[].Value", [], "unknown"),
    ],
)
def test_invalid_hierarchy(prop, value, shape):
    with pytest.raises(ValueError, match="projection|valueShape"):
        normalize(prop, value, shape)


def actions_case(case):
    data = case["data"]
    before = deepcopy(data)
    errors = literal_errors(
        DesignSchemaCatalog(ROOT),
        "QuickSight.DataSource",
        "Permissions[].Actions",
        json.dumps(data["value"]),
        data["shape"],
    )
    TestCase().assertEqual(not errors, data["valid"])
    TestCase().assertEqual(data, before)
    return {"errors": errors}


@pytest.mark.parametrize("case_id", case_ids("model_literal_values", prefix="actions-"))
def test_actions(case_runner, case_id):
    case_runner.run("model_literal_values", case_id, actions_case)


def test_deep_projection_and_terminal_selection():
    catalog = DesignSchemaCatalog(ROOT)
    assert not literal_errors(
        catalog,
        "CloudTrail.Trail",
        "EventSelectors[].DataResources[].Values",
        '[[["arn:aws:s3"]]]',
        "projection",
    )
    assert not literal_errors(
        catalog,
        "CodeBuild.Project",
        "VpcConfig.Subnets[]",
        '["subnet-first","subnet-second"]',
        "projection",
    )
    assert not literal_errors(
        catalog,
        "CodeBuild.Project",
        "VpcConfig.Subnets[]",
        "subnet-first",
    )
    assert literal_errors(
        catalog,
        "CodeBuild.Project",
        "VpcConfig.Subnets[]",
        "[1]",
        "projection",
    )


def column_constraints_case(case):
    data = case["data"]
    before = deepcopy(data)
    errors = literal_errors(
        DesignSchemaCatalog(ROOT),
        "CloudTrail.Trail",
        data["field"],
        data["raw"],
        "projection",
    )
    TestCase().assertEqual(not errors, data["valid"])
    TestCase().assertEqual(data, before)
    return {"errors": errors}


@pytest.mark.parametrize(
    "case_id", case_ids("model_literal_values", prefix="column-constraints-")
)
def test_column_constraints(case_runner, case_id):
    case_runner.run("model_literal_values", case_id, column_constraints_case)


def test_empty_parent_uses_its_schema():
    catalog = CloudFormationSchemaCatalog(ROOT)
    catalog.schemas["AWS::Test::Array"] = {
        "properties": {
            "Parents": {
                "type": ["array", "null"],
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "Values": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        }
                    },
                },
            }
        }
    }
    assert not literal_errors(
        catalog, "Test.Array", "Parents[].Values", "[]", "projection"
    )
    assert literal_errors(catalog, "Test.Array", "Parents[].Values", "[]", "leaf")
    assert literal_errors(
        catalog, "Test.Array", "Parents[].Values", "[[]]", "projection"
    )
    assert literal_errors(
        catalog, "Test.Array", "Parents[].Values", '[["A"],["B"]]', "projection"
    )
    with pytest.raises(KeyError):
        literal_errors(catalog, "Test.Array", "Parents[].Missing", "[]", "projection")


def terminal_projection_constraints_case(case):
    data = case["data"]
    before = deepcopy(data)
    errors = literal_errors(
        DesignSchemaCatalog(ROOT),
        "GuardDuty.MalwareProtectionPlan",
        "ProtectedResource.S3Bucket.ObjectPrefixes[]",
        data["raw"],
        "projection",
    )
    TestCase().assertEqual(not errors, data["valid"])
    TestCase().assertEqual(data, before)
    return {"errors": errors}


@pytest.mark.parametrize(
    "case_id",
    case_ids("model_literal_values", prefix="terminal-projection-constraints-"),
)
def test_terminal_projection_constraints(case_runner, case_id):
    case_runner.run(
        "model_literal_values", case_id, terminal_projection_constraints_case
    )


@pytest.mark.parametrize(
    "items,good,bad",
    [
        (
            {
                "type": "string",
                "minLength": 1,
                "maxLength": 2,
                "pattern": "^A",
                "enum": ["A", "AB"],
            },
            ["A", "AB"],
            [[1], [""], ["B"], ["ABC"]],
        ),
        (
            {"type": "integer", "minimum": 1, "maximum": 2},
            [1, 2],
            [[True], ["1"], [0], [3]],
        ),
        ({"type": "number", "minimum": 0}, [0.5], [[False], ["0.5"], [-1]]),
        ({"type": "boolean"}, [False, True], [[0], ["false"]]),
        (
            {"type": "array", "minItems": 1, "items": {"type": "string"}},
            [["A"]],
            [[[]], [[1]]],
        ),
        (
            {"type": ["string", "integer"], "enum": ["A", 1]},
            ["A", 1],
            [[True], ["B"], ["1"]],
        ),
        (
            {
                "type": "object",
                "required": ["Name"],
                "properties": {"Name": {"type": "string", "pattern": "^A$"}},
                "additionalProperties": False,
            },
            [{"Name": "A"}],
            [[{}], [{"Name": 1}], [{"Name": "B"}], [{"Name": "A", "Other": 1}]],
        ),
    ],
)
def test_provider_items(items, good, bad):
    catalog = CloudFormationSchemaCatalog(ROOT)
    catalog.schemas["AWS::Test::Array"] = {
        "properties": {
            "Values": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {"$ref": "#/definitions/Item"},
            }
        },
        "definitions": {"Item": items},
    }
    assert not catalog.literal_errors("Test.Array", "Values", json.dumps(good))
    for value in [[], good * 3, *bad]:
        assert catalog.literal_errors("Test.Array", "Values", json.dumps(value)), value


@pytest.mark.parametrize(
    "kind,field,good,bad",
    [
        ("CodePipeline.Pipeline", "Stages[1].Name", "Stage", None),
        ("CloudTrail.Trail", "EventSelectors[1].ReadWriteType", "All", "invalid"),
        ("Route53.RecordSet", "ResourceRecords[1]", "192.0.2.1", None),
    ],
)
def test_indexed_leaf_definition(kind, field, good, bad):
    catalog = DesignSchemaCatalog(ROOT)
    assert not literal_errors(catalog, kind, field, good)
    if bad is not None:
        assert literal_errors(catalog, kind, field, bad)


def test_definition_path_and_parents():
    assert definition_path("Stages[1].Actions[2].Name") == "Stages[].Actions[].Name"
    assert definition_path("Stages[0].Name") == "Stages[0].Name"
    assert definition_path("Stages[01].Name") == "Stages[01].Name"
    assert property_paths_with_parents({"Stages[1].Name"}) == {
        "Stages",
        "Stages[]",
        "Stages[].Name",
    }
    catalog = DesignSchemaCatalog(ROOT)
    for field in ("Stages[0].Name", "Stages[01].Name", "Stages[1].Missing"):
        with pytest.raises(KeyError):
            literal_errors(catalog, "CodePipeline.Pipeline", field, "x")


def test_dynamic_reference_in_array():
    catalog = DesignSchemaCatalog(ROOT)
    node = {"type": "array", "items": {"type": "string", "pattern": "^literal$"}}
    catalog.schemas["AWS::Test::Dynamic"] = {"properties": {"Values": node}}
    assert not catalog.literal_errors(
        "Test.Dynamic", "Values", '["{{resolve:ssm:/parameter}}"]'
    )
    assert catalog.literal_errors(
        "Test.Dynamic", "Values", '["{{resolve:ssm:bad space}}"]'
    )
    assert catalog.literal_errors("Test.Dynamic", "Values", '["other"]')


def test_decoding_is_explicit():
    schema = {"type": "string"}
    row = {"property": "Parents[].Value"}
    assert value_shape(row) == "leaf"
    assert typed_value(row, '`["A"]`', schema) == '["A"]'
    assert typed_value(dict(row, valueShape="projection"), '`["A"]`', schema) == ["A"]
    assert array_paths("Parents[].Values") == ("Parents",)
    assert array_paths("Parents[].Values[]") == ("Parents", "Parents[].Values")
    for shape in ("auto", None, [], 1):
        with pytest.raises(ValueError, match="valueShape"):
            typed_value(dict(row, valueShape=shape), "A", schema)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("True", True),
        ("False", False),
        ("true", True),
        ("false", False),
        ("TRUE", True),
        ("FALSE", False),
        ("tRuE", True),
    ],
)
def test_boolean_leaf(raw, expected):
    assert (
        typed_value({"property": "Value"}, f"`{raw}`", {"type": "boolean"}) is expected
    )


@pytest.mark.parametrize("raw", ["yes", "1", "0", "null", '"false"', " true", "false "])
def test_invalid_boolean_leaf(raw):
    with pytest.raises(ValueError, match="invalid native type"):
        typed_value({"property": "Value"}, raw, {"type": "boolean"})


def test_non_boolean_and_explicit_shapes():
    row = {"property": "Items[].Value"}
    for kind, raw, expected in [
        ("string", "False", "False"),
        ("integer", "1", 1),
        ("array", "[false]", [False]),
        ("object", '{"a":false}', {"a": False}),
    ]:
        assert typed_value(row, raw, {"type": kind}) == expected
    assert typed_value(
        dict(row, document="[false]"), "ignored", {"type": "boolean"}
    ) == [False]
    assert typed_value(
        dict(row, valueShape="projection"), "[false]", {"type": "boolean"}
    ) == [False]
    with pytest.raises(ValueError):
        typed_value(dict(row, valueShape="projection"), "[False]", {"type": "boolean"})


def test_property_projection_retains_array_leaf_and_rejects_ambiguous_groups():
    prop = "Parents[].Actions"
    assert projection_value(prop, [("leaf", ["A", "B"])]) == [["A", "B"]]
    assert projection_value(prop, [("projection", [["A", "B"]])]) == [["A", "B"]]
    assert projection_value(prop, [("leaf", ["A"]), ("leaf", ["B"])]) == [["A"], ["B"]]
    assert projection_value("Parents[].Children[].Values", [("leaf", ["A"])]) == [
        [["A"]]
    ]
    with pytest.raises(ValueError, match="ambiguous"):
        projection_value(
            "Parents[].Children[].Values", [("leaf", ["A"]), ("leaf", ["B"])]
        )
    with pytest.raises(ValueError, match="ambiguous"):
        projection_value(prop, [("projection", [["A"]]), ("leaf", ["B"])])


def test_projection_tree_retains_membership():
    value = [[["A"]], [["B"], ["C"]]]
    tree = {}
    project(tree, "Groups[].Members[].Values", value)
    assert select(tree, "Groups[].Members[].Values") == value
    with pytest.raises(Unresolved, match="length"):
        project(tree, "Groups[].Name", ["one"])


def test_indexed_paths_reconstruct_and_select():
    tree = {}
    put_row(tree, "Groups[1].Name", "Name1")
    project(tree, "Groups[1].Values[]", ["v1"])
    put_row(tree, "Groups[2].Name", "Name2")
    project(tree, "Groups[1].Children[1].Values[]", ["child"])
    put_row(tree, "Groups[1].Children[1].Name", "first")
    assert tree == {
        "Groups": [
            {
                "Name": "Name1",
                "Values": ["v1"],
                "Children": [{"Values": ["child"], "Name": "first"}],
            },
            {"Name": "Name2"},
        ]
    }
    assert select(tree, "Groups[1].Values[]") == ["v1"]
    assert select(tree, "Groups[2].Name") == "Name2"
    assert select(tree, "Groups[1].Children[1].Name") == "first"
    assert select(tree, "Groups[3].Name") == {"absent": True}
    assert select(tree, "Groups[].Name") == ["Name1", "Name2"]
    for function in (put_row, project):
        with pytest.raises(Unresolved):
            function({}, "Groups[0]", "x")
        with pytest.raises(Unresolved):
            function({"Groups": "bad"}, "Groups[1].Name", "x")
        with pytest.raises(Unresolved):
            function({"Groups": ["bad"]}, "Groups[1].Name", "x")
    with pytest.raises(Unresolved):
        select({}, "Groups[0]")
    with pytest.raises(Unresolved):
        select({"Groups": "bad"}, "Groups[1]")
    with pytest.raises(Unresolved):
        select({"Groups": ["bad"]}, "Groups[1].Name")


def test_no_projection_skips_pair_scan():
    rows = [(str(i), {"property": f"Resource.Field{i}"}) for i in range(1000)]
    with patch(
        "model.literal_values.combinations", side_effect=AssertionError("pair scan")
    ):
        assert projection_conflicts(rows) == {}


@pytest.mark.parametrize(
    "first,shape,second,other_shape,conflict",
    [
        ("VpcConfig.VpcId", "leaf", "VpcConfig.Subnets[]", "projection", False),
        (
            "VpcConfig.Subnets[]",
            "projection",
            "VpcConfig.SecurityGroupIds[]",
            "leaf",
            False,
        ),
        ("Groups[].Name", "leaf", "Groups[].Value", "projection", True),
        ("Groups[].Value", "projection", "Groups[].Value", "projection", True),
        ("Groups[].Name", "leaf", "Groups[].Members[].Values", "projection", True),
        ("VpcConfig", "leaf", "VpcConfig.Subnets[]", "projection", True),
        ("Groups[].Value", "projection", None, None, False),
        ("Groups[1].Name", "leaf", "Groups[].Value", "projection", True),
        ("Groups[].Name", "leaf", "Groups[1].Values[]", "projection", True),
        ("Groups[1].Name", "leaf", "Groups[2].Values[]", "projection", False),
        ("Groups[1].Name", "leaf", "Groups[1].Values[]", "projection", False),
        ("VpcConfig.Subnets", "leaf", "VpcConfig.Subnets[]", "projection", True),
        ("Groups[].Members", "leaf", "Groups[].Members[].Values", "projection", True),
        ("Groups[]", "leaf", "Groups[].Value", "projection", True),
        ("Groups[].Name", "projection", "Groups[].Value", "projection", False),
        ("Groups[].Value", "projection", "Groups[].Values", "leaf", True),
        ("VpcConfig.Subnets[]", "projection", "VpcConfig.SubnetsExtra", "leaf", False),
        ("Groups[].Name", "leaf", "Groups[].Name", "leaf", False),
        (
            "Groups[].Members[]",
            "projection",
            "Groups[].Members[].Value",
            "projection",
            True,
        ),
        ("Groups[1].Values[]", "projection", "Groups[2].Values[]", "projection", False),
        ("Groups[1].Values[]", "projection", "Groups[1].Values[]", "projection", True),
        ("Groups[1].Values[]", "projection", "Groups[].Values[]", "projection", True),
    ],
)
def test_projection_row_conflicts(first, shape, second, other_shape, conflict):
    rows = [("001-001", {"property": "Test.Resource." + first, "valueShape": shape})]
    if second is not None:
        rows.append(
            (
                "001-002",
                {"property": "Test.Resource." + second, "valueShape": other_shape},
            )
        )
    expected = {row["property"] for _, row in rows} if conflict else set()
    rows.append(
        ("001-003", {"property": "Test.Resource.Independent", "valueShape": "leaf"})
    )
    assert set(projection_conflicts(rows)) == expected
    assert set(projection_conflicts(list(reversed(rows)))) == expected


def projection_siblings_reconstruct_case(case):
    data = case["data"]
    before = deepcopy(data)
    values = data["values"]
    rows = [
        (str(index), {"property": "Test.Resource." + prop, "valueShape": shape})
        for index, (prop, shape, _) in enumerate(values)
    ]
    TestCase().assertEqual(projection_conflicts(rows), {})
    tree = {}
    for prop, shape, value in values:
        if shape == "projection":
            project(tree, prop, value)
        else:
            put_row(tree, prop, value)
    for prop, _, value in values:
        TestCase().assertEqual(
            select(tree, prop),
            value if "[]" not in prop or isinstance(value, list) else [value],
        )
    TestCase().assertEqual(data, before)
    return {"tree": tree}


@pytest.mark.parametrize(
    "case_id",
    case_ids("model_literal_values", prefix="projection-siblings-reconstruct-"),
)
def test_projection_siblings_reconstruct(case_runner, case_id):
    case_runner.run(
        "model_literal_values", case_id, projection_siblings_reconstruct_case
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
