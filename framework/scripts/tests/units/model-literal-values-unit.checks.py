"""Shape, path and provider literal contracts on synthetic or pinned schemas."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from design.catalog import DesignSchemaCatalog
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
from utils.cloudformation.schema import CloudFormationSchemaCatalog
from utils.comparison_rows import Unresolved, project, select

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "prop,value,shape,expected,parents",
    [
        ("Permissions[].Actions", ["A", "B"], "leaf", (["A", "B"],), ()),
        (
            "Permissions[].Actions",
            [["A", "B"]],
            "projection",
            (["A", "B"],),
            ("Permissions",),
        ),
        (
            "EventSelectors[].DataResources[].Values",
            [[["arn:aws:s3"]]],
            "projection",
            (["arn:aws:s3"],),
            ("EventSelectors", "EventSelectors[].DataResources"),
        ),
        ("Items[]", ["A", "B"], "projection", ("A", "B"), ("Items",)),
        ("Items[]", "A", "leaf", ("A",), ()),
        ("Permissions[].Actions", [], "leaf", ([],), ()),
        ("Permissions[].Actions", [], "projection", (), ("Permissions",)),
        (
            "Groups[].Members[].Values",
            [[]],
            "projection",
            (),
            ("Groups", "Groups[].Members"),
        ),
        (
            "Permissions[].Actions",
            [["A"], ["B"]],
            "projection",
            (["A"], ["B"]),
            ("Permissions",),
        ),
    ],
)
def test_normalize(prop, value, shape, expected, parents):
    before = json.dumps(value)
    result = normalize(prop, value, shape)
    assert result.values == expected
    assert tuple(path for path, _ in result.arrays) == parents
    assert json.dumps(value) == before


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


@pytest.mark.parametrize(
    "value,shape,valid",
    [
        (["ActionA", "ActionB"], "leaf", True),
        ([["ActionA", "ActionB"]], "projection", True),
        ("ActionA", "leaf", False),
        ([], "leaf", False),
        (["ActionA"] * 31, "leaf", False),
        (["ActionA", 1], "leaf", False),
        ([["ActionA", 1]], "projection", False),
        ([[["ActionA"]]], "leaf", False),
        (["ActionA"], "projection", False),
        ([[]], "projection", False),
        ([], "projection", False),
    ],
)
def test_actions(value, shape, valid):
    errors = literal_errors(
        DesignSchemaCatalog(ROOT),
        "QuickSight.DataSource",
        "Permissions[].Actions",
        json.dumps(value),
        shape,
    )
    assert (not errors) == valid, errors


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


@pytest.mark.parametrize(
    "field,raw,valid",
    [
        ("EventSelectors[].IncludeManagementEvents", "[true,false]", True),
        ("EventSelectors[].IncludeManagementEvents", '[true,"false"]', False),
        ("EventSelectors[].ReadWriteType", '["All","ReadOnly"]', True),
        ("EventSelectors[].ReadWriteType", '["All","bad"]', False),
        ("EventSelectors[].DataResources[].Type", '[["AWS::S3::Object"]]', True),
        ("EventSelectors[].DataResources[].Values", '[[["arn:aws:s3"]]]', True),
        ("EventSelectors[].ReadWriteType", '["All"]', True),
        ("EventSelectors[].ReadWriteType", '["bad"]', False),
        ("EventSelectors[].ReadWriteType", '[["All"]]', False),
    ],
)
def test_column_constraints(field, raw, valid):
    errors = literal_errors(
        DesignSchemaCatalog(ROOT), "CloudTrail.Trail", field, raw, "projection"
    )
    assert (not errors) == valid, errors


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


@pytest.mark.parametrize(
    "raw,valid",
    [
        ('["a/","b/"]', True),
        ("[]", True),
        ('  ["a/"]', True),
        ('["a/",]', False),
        ("[", False),
        ("[1]", False),
        ("[null]", False),
        ("[true]", False),
        ("[{}]", False),
        ('[["a/"]]', False),
    ],
)
def test_terminal_projection_constraints(raw, valid):
    catalog = DesignSchemaCatalog(ROOT)
    errors = literal_errors(
        catalog,
        "GuardDuty.MalwareProtectionPlan",
        "ProtectedResource.S3Bucket.ObjectPrefixes[]",
        raw,
        "projection",
    )
    assert (not errors) == valid, errors


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


def test_projection_row_conflicts():
    row = {"property": "Test.Resource.Groups[].Value", "valueShape": "projection"}
    assert not projection_conflicts([("001-001", row)])
    assert projection_conflicts([("001-001", row), ("001-002", row)])
    assert projection_conflicts(
        [
            ("001-001", row),
            (
                "001-002",
                dict(row, property="Test.Resource.Groups[].Other", valueShape="leaf"),
            ),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
