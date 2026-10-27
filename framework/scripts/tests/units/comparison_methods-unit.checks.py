"""One algorithm suite and static rule coverage; only synthetic comparison values."""

import sys
from collections import Counter
from functools import partial
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison import registry, rulebook
from comparison.methods import (
    OBJECT,
    ORDERED,
    REFERENCE,
    SCALAR,
    UNORDERED,
    CompareOutcome,
    compare_values,
    keyed,
)
from comparison.references import ReferenceDecision, reference_same
from comparison.result import value_differences
from design.catalog import DesignSchemaCatalog, property_paths_with_parents
from support.pytest_cli import run
from utils.aws_catalogs import catalogs_for
from utils.iac_values import (
    Expression,
    ResourceReference,
    comparison_result,
    same,
    unordered_same,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]


def compare(left, right, rule=OBJECT, *, whole=False, reference=None):
    return compare_values(
        left,
        right,
        "Setting",
        rules={"Setting": rule},
        whole=whole,
        reference=reference,
    )


@pytest.mark.parametrize(
    "left,right,equal",
    [
        (True, 1, False),
        (1, 1.0, False),
        ("1", 1, False),
        (None, "", False),
        ({}, [], False),
        (None, None, True),
        ("same", "same", True),
        (0, 1, False),
    ],
)
def test_scalar(left, right, equal):
    assert compare(left, right, SCALAR).equal is equal
    assert same(left, right) is equal


@pytest.mark.parametrize("whole,expected", [(False, True), (True, False)])
def test_object_scope(whole, expected):
    assert compare({"a": 1}, {"a": 1, "b": 2}, whole=whole).equal is expected
    assert compare({"a": None}, {}, whole=whole).equal is False


@pytest.mark.parametrize(
    "right,expected",
    [
        ([1, 2], True),
        ([2, 1], False),
        ([1], False),
        ([1, 1], False),
    ],
)
def test_ordered(right, expected):
    assert compare([1, 2], right, ORDERED).equal is expected


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ([1, 2], [2, 1], True),
        ([1, 1], [1, 2], False),
        ([1, 1], [1], False),
        ([], [], True),
    ],
)
def test_unordered(left, right, expected):
    assert compare(left, right, UNORDERED).equal is expected
    assert unordered_same(left, right) is expected


def test_unordered_augmenting_paths():
    pairs = {(1, 3): True, (1, 4): True, (2, 3): True}
    reference = partial(candidate_pairs, pairs)
    # Containers are structural; candidate pairs use the declared reference handler.
    assert (
        compare(
            [1, 2], [3, 4], UNORDERED, reference=partial(candidate_reference, reference)
        ).equal
        is True
    )
    assert unordered_same([1, 2], [3, 4], reference=lambda a, b, p: None) is None
    assert comparison_result([None, False]) is False
    assert comparison_result([None, True]) is None
    assert comparison_result([None, True], any_match=True) is True


def candidate_pairs(pairs, left, right, path):
    return ReferenceDecision(pairs.get((left, right), False))


def candidate_reference(reference, left, right, path):
    return (
        ReferenceDecision(NotImplemented)
        if isinstance(left, list)
        else reference(left, right, path)
    )


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("reordered", True),
        ("extra", True),
        ("missing", False),
        ("duplicate", False),
        ("model-duplicate", False),
        ("wrong", False),
        ("unknown", None),
        ("unknown-key", None),
        ("known-wrong", False),
    ],
)
def test_keyed(mode, expected):
    left = [{"Key": "Name", "Value": "one"}]
    right = [{"Key": "Other", "Value": "extra"}, *left]
    unknown = Expression("Unverified", [])
    if mode == "extra":
        right[-1] = dict(left[0], Extra=True)
    elif mode == "missing":
        right = []
    elif mode == "duplicate":
        right = left * 2
    elif mode == "model-duplicate":
        left = left * 2
    elif mode == "wrong":
        right = [{"Key": "Name", "Value": "two"}]
    elif mode == "unknown":
        right = [unknown]
    elif mode == "unknown-key":
        right = [{"Key": unknown, "Value": "one"}]
    elif mode == "known-wrong":
        right = [{"Key": "Name", "Value": "two"}, unknown]
    assert compare(left, right, keyed("Key")).equal is expected


def uncertain(left, right, path):
    return ReferenceDecision(
        None
        if any(isinstance(v, Expression) for v in (left, right))
        else NotImplemented
    )


@pytest.mark.parametrize("rule", [ORDERED, UNORDERED, keyed("Key")])
def test_unknown_presence(rule):
    unknown = Expression("Unverified", [])
    left = [{"Key": "one"}, {"Key": "two"}]
    assert compare(left, [unknown], rule, reference=uncertain).equal is False
    assert compare(left[:1], [unknown], rule, reference=uncertain).equal is None


def test_reference_diagnostics_once_and_render_masking():
    left = {"Password": "first", "a/b~c": ["one"]}
    right = {"Password": "second", "a/b~c": ["two"]}
    callback = Mock(side_effect=traced_reference)
    outcome = compare(left, right, reference=callback)
    calls = callback.call_count
    assert calls == 4
    assert outcome.equal is False and outcome.equivalent is True
    assert outcome.diagnostics == ({"path": "Setting.a/b~c[]"},)
    fields = value_differences(outcome, left, right, "Setting")
    assert callback.call_count == calls
    assert fields == [
        {"path": "Password", "model": '"<masked>"', "iac": '"<masked>"'},
        {"path": "a/b~c[0]", "model": "one", "iac": "two"},
    ]


def traced_reference(left, right, path):
    if path.endswith("[]"):
        return ReferenceDecision(False, ({"path": path},), True)
    return ReferenceDecision(NotImplemented)


def test_reference_identity_and_unproven():
    left = ResourceReference({"$resource": ["service", "001"], "$attribute": "Arn"})
    assert compare(left, ResourceReference(left), REFERENCE).equal is True
    assert compare(left, dict(left), REFERENCE).equal is False
    assert (
        compare(
            left,
            "physical",
            REFERENCE,
            reference=lambda a, b, p: ReferenceDecision(None),
        ).equal
        is None
    )


@pytest.mark.parametrize(
    "kind,path",
    [
        ("IAM.Role", "AssumeRolePolicyDocument"),
        ("IAM.Role", "Policies[].PolicyDocument"),
        ("IAM.ManagedPolicy", "PolicyDocument"),
        ("IAM.User", "Policies[].PolicyDocument"),
    ],
)
def test_iam_rules(kind, path):
    left = {"Statement": [{"Action": "a", "Effect": "Allow"}, {"Action": ["b"]}]}
    right = {"Statement": [{"Action": "b"}, {"Action": ["a"], "Effect": "Allow"}]}
    assert (
        compare_values(left, right, path, rules=rulebook.rules(kind), whole=True).equal
        is True
    )
    right["Statement"][0]["Action"] = ["wrong"]
    outcome = compare_values(left, right, path, rules=rulebook.rules(kind), whole=True)
    assert outcome.equal is False and outcome.differences
    assert (
        compare_values(left, left, path, rules=rulebook.rules(kind), local=False).equal
        is True
    )


@pytest.mark.parametrize("whole", [True, False])
def test_action_string_list_and_scope(whole):
    path = "Policies[].PolicyDocument.Statement[].Action"
    declared = rulebook.rules("IAM.Role")
    for left, right in [("a", ["a"]), (["a"], "a")]:
        assert (
            compare_values(left, right, path, rules=declared, whole=whole).equal is True
        )
    for right in ([], ["b"], ["a", "a"], [True], [["a"]]):
        assert (
            compare_values("a", right, path, rules=declared, whole=whole).equal is False
        )
    assert compare_values(["a", "b"], ["b", "a"], path, rules=declared).equal is False
    assert compare_values("a", ["a"], path, rules=declared, local=False).equal is False
    assert compare("a", ["a"], SCALAR).equal is False


def test_nested_override_and_keyed_evidence():
    declared = {"Setting": OBJECT, "Setting.Items": UNORDERED}
    assert (
        compare_values(
            {"Items": [1, 2]}, {"Items": [2, 1]}, "Setting", rules=declared
        ).equal
        is True
    )
    left = [{"Key": "SECRET_TOKEN", "Value": "first"}]
    right = [
        {"Key": "Other", "Value": "extra"},
        {"Key": "SECRET_TOKEN", "Value": "second"},
    ]
    outcome = compare(left, right, keyed("Key"))
    assert value_differences(outcome, left, right, "Setting") == [
        {
            "path": "Setting[Key=SECRET_TOKEN].Value",
            "model": '"<masked>"',
            "iac": '"<masked>"',
        }
    ]
    assert compare(left, right, keyed("Key"), whole=True).equal is False


def test_rulebook_complete_static_coverage():
    catalog, catalogs = DesignSchemaCatalog(ROOT), catalogs_for(ROOT)
    kinds = {
        path.stem.replace("_", ".", 1)
        for path in catalogs.paths
        if path.parent.name == "aws"
    }
    assert set(rulebook.RULES) == kinds
    for kind in sorted(kinds):
        selected = {
            p
            for p in catalogs.selected(kind)
            if kind + "." + p not in catalogs.outputs(kind)
        }
        expected = property_paths_with_parents(selected)
        assert expected <= rulebook.rules(kind).keys(), (
            kind,
            expected - rulebook.rules(kind).keys(),
        )
        for rule in rulebook.rules(kind).values():
            assert {rule.whole, rule.selected} <= {
                "SCALAR",
                "OBJECT",
                "ORDERED",
                "UNORDERED",
                "KEYED",
                "REFERENCE",
                "CUSTOM",
            }
        for path in expected:
            rule = rulebook.require(kind, path)
            node = catalog.property_schema(kind, path)
            if node.get("type") == "array":
                assert rule.whole in {"ORDERED", "UNORDERED"}, (kind, path)
        # Reading the schema here is test-time evidence, never a runtime prerequisite.
        assert catalog.cloudformation_type(kind).startswith("AWS::")
    assert len(kinds) == 176 and len({k.split(".")[0] for k in kinds}) == 46
    assert {k for k in registry.SERVICES if k not in kinds} == {
        "IAM.Group",
        "IAM.Policy",
        "QuickSight.Group",
    }


def test_unregistered_rule_is_framework_error():
    with pytest.raises(ValueError, match="Framework comparison rule missing"):
        rulebook.require("EC2.VPC", "NotImplemented")
    with pytest.raises(ValueError, match="Framework comparison rule missing"):
        rulebook.require("Unknown.Type", "Value")
    with pytest.raises(ValueError, match="Framework comparison rule missing"):
        compare_values("a", "a", "Value", rules={})
    assert (
        Counter(r.whole for rules in rulebook.RULES.values() for r in rules.values())[
            "SCALAR"
        ]
        > 0
    )
    assert CompareOutcome(None).differences == ()


def codebuild_reference(resolve_literal, left, right, path):
    return reference_same(
        left,
        right,
        "CodeBuild.Project",
        path,
        local_comparison=True,
        forms_for=lambda *args: None,
        resolve_literal=resolve_literal,
        resource_type=lambda symbol: "SecretsManager.Secret",
        kms_format=lambda value: None,
        diagnostic=lambda *args: {},
    )


def test_codebuild_nested_reference_proof_is_reused():
    symbol = ResourceReference({"$resource": ["secrets", "001"], "$attribute": "Id"})
    left = {
        "EnvironmentVariables": [
            {"Name": "LEFT", "Type": "SECRETS_MANAGER", "Value": symbol}
        ]
    }
    right = {
        "EnvironmentVariables": [
            {"Name": "RIGHT", "Type": "SECRETS_MANAGER", "Value": "secret/name"}
        ]
    }
    resolve = Mock(return_value="secret/name")
    outcome = compare_values(
        left,
        right,
        "Environment",
        rules=rulebook.rules("CodeBuild.Project"),
        reference=partial(codebuild_reference, resolve),
    )
    assert outcome.equal is False
    assert resolve.call_count == 1
    assert value_differences(outcome, left, right, "CodeBuild.Project.Environment") == [
        {"path": "EnvironmentVariables[0].Name", "model": "LEFT", "iac": "RIGHT"}
    ]
    assert resolve.call_count == 1


def test_reference_atomic_difference_path_and_missing():
    left = ResourceReference({"$resource": ["s3", "001"], "$attribute": "Arn"})
    right = ResourceReference(dict(left, **{"$attribute": "BucketName"}))
    callback = Mock(return_value=ReferenceDecision(False))
    outcome = compare(left, right, REFERENCE, reference=callback)
    assert callback.call_count == 1
    assert value_differences(outcome, left, right, "Setting") == [
        {"path": "$attribute", "model": "Arn", "iac": "BucketName"}
    ]
    assert callback.call_count == 1
    missing = compare_values(
        None, None, "Setting", rules={"Setting": SCALAR}, missing=True
    )
    assert value_differences(missing, None, None, "Setting") == [
        {"path": "Setting", "model": "null", "iac": "欠落"}
    ]


def test_nested_array_rule_and_unknown_prefix():
    declared = {"Setting": OBJECT, "Setting.Items[].Values": UNORDERED}
    left = {"Items": [{"Values": [1, 2]}]}
    right = {"Items": [{"Values": [2, 1]}]}
    assert compare_values(left, right, "Setting", rules=declared).equal is True
    unknown = Expression("Unverified", [])
    outcome = compare([1, 2], [3, unknown], ORDERED, reference=uncertain)
    assert outcome.equal is False
    assert value_differences(outcome, [1, 2], [3, unknown], "Setting") == [
        {"path": "Setting[0]", "model": "1", "iac": "3"}
    ]


if __name__ == "__main__":
    raise SystemExit(run(__file__))
