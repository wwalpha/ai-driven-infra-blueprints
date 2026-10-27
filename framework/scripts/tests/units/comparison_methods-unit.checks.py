"""One algorithm suite and static rule coverage; only synthetic comparison values."""

import random
import sys
from collections import Counter
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comparison.methods as methods
import pytest
from comparison import registry
from comparison.evaluation import key_integrity, project_actual
from comparison.methods import (
    MISSING,
    OBJECT,
    ORDERED,
    REFERENCE,
    SCALAR,
    UNORDERED,
    CompareOutcome,
    _Comparison,
    _select_unordered_diagnostics,
    compare_values,
    keyed,
)
from comparison.references import ReferenceDecision, reference_same
from comparison.result import setting_result, value_differences
from design.catalog import DesignSchemaCatalog, property_paths_with_parents
from support.pytest_cli import run
from utils.aws_catalogs import catalogs_for
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    Expression,
    ResourceReference,
    comparison_result,
    safe_value,
    same,
    unordered_matching,
    unordered_same,
)
from utils.reference_contracts import KMS_FORMS

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
        compare_values(left, right, path, rules=registry.rules(kind), whole=True).equal
        is True
    )
    right["Statement"][0]["Action"] = ["wrong"]
    outcome = compare_values(left, right, path, rules=registry.rules(kind), whole=True)
    assert outcome.equal is False and outcome.differences
    assert (
        compare_values(left, left, path, rules=registry.rules(kind), local=False).equal
        is True
    )
    for field in ("Action", "NotAction", "Resource", "NotResource"):
        a = {"Statement": [{field: ["a", "b"], "Effect": "Allow"}]}
        b = {"Statement": [{field: ["b", "a"], "Effect": "Allow"}]}
        assert (
            compare_values(a, b, path, rules=registry.rules(kind), whole=True).equal
            is True
        )
        b["Statement"][0][field] = ["a"]
        assert (
            compare_values(a, b, path, rules=registry.rules(kind), whole=True).equal
            is False
        )
        b["Statement"][0][field] = ["a", "a"]
        assert (
            compare_values(a, b, path, rules=registry.rules(kind), whole=True).equal
            is False
        )
        a["Statement"][0][field] = "a"
        b["Statement"][0][field] = ["a"]
        assert (
            compare_values(a, b, path, rules=registry.rules(kind), whole=True).equal
            is True
        )
    for field, value in (
        ("Effect", "Deny"),
        ("Condition", {"StringEquals": {"key": "other"}}),
    ):
        a = {
            "Statement": [
                {"Effect": "Allow", "Condition": {"StringEquals": {"key": "value"}}}
            ]
        }
        b = {"Statement": [dict(a["Statement"][0], **{field: value})]}
        assert (
            compare_values(a, b, path, rules=registry.rules(kind), whole=True).equal
            is False
        )

    a = {
        "Statement": [
            {"Sid": "First", "Action": ["a", "b"]},
            {"Sid": "Second", "Action": "x"},
        ]
    }
    b = {
        "Statement": [
            {"Sid": "Second", "Action": "x"},
            {"Sid": "First", "Action": ["b", "c"]},
        ]
    }
    outcome = compare_values(a, b, path, rules=registry.rules(kind), whole=True)
    assert outcome.equal is False
    fields = value_differences(outcome, a, b, path)
    assert fields == [
        {"path": "Statement[0].Action[0]", "model": "a", "iac": "欠落"},
        {"path": "Statement[0].Action[IaC:1]", "model": "欠落", "iac": "c"},
    ]
    del a["Statement"][0]["Sid"]
    del b["Statement"][1]["Sid"]
    fields = value_differences(
        compare_values(a, b, path, rules=registry.rules(kind), whole=True), a, b, path
    )
    assert fields == [
        {"path": "Statement[0].Action[0]", "model": "a", "iac": "欠落"},
        {"path": "Statement[0].Action[IaC:1]", "model": "欠落", "iac": "c"},
    ]

    if kind in ("IAM.Role", "IAM.User"):
        policies = [
            {
                "PolicyName": "one",
                "PolicyDocument": {"Statement": [{"Action": ["a", "b"]}]},
            },
            {"PolicyName": "two", "PolicyDocument": {"Statement": []}},
        ]
        actual = list(reversed(policies))
        rules = registry.rules(kind)
        for whole in (True, False):
            assert (
                compare_values(
                    policies, actual, "Policies", rules=rules, whole=whole
                ).equal
                is True
            )
            assert (
                compare_values(
                    policies, actual + [actual[0]], "Policies", rules=rules, whole=whole
                ).equal
                is False
            )
            assert (
                compare_values(
                    policies, actual[:1], "Policies", rules=rules, whole=whole
                ).equal
                is False
            )
            assert (
                compare_values(
                    policies,
                    [Expression("Unverified", []), actual[0]],
                    "Policies",
                    rules=rules,
                    whole=whole,
                    reference=uncertain,
                ).equal
                is None
            )
            assert (
                compare_values(
                    policies * 2, actual, "Policies", rules=rules, whole=whole
                ).equal
                is False
            )
            assert compare_values(
                [{"PolicyDocument": {}}],
                actual,
                "Policies",
                rules=rules,
                whole=whole,
            ).equal is (not whole)
            assert (
                compare_values(
                    policies,
                    [{"PolicyDocument": {}}, actual[0]],
                    "Policies",
                    rules=rules,
                    whole=whole,
                ).equal
                is False
            )
        extra = actual + [{"PolicyName": "extra"}]
        assert compare_values(policies, extra, "Policies", rules=rules).equal is True
        assert (
            compare_values(policies, extra, "Policies", rules=rules, whole=True).equal
            is False
        )
        changed = [
            {"PolicyName": "two", "PolicyDocument": {"Statement": []}},
            {
                "PolicyName": "one",
                "PolicyDocument": {"Statement": [{"Action": ["a", "c"]}]},
            },
        ]
        assert (
            compare_values(policies, changed, "Policies", rules=rules, whole=True).equal
            is False
        )
        fields = value_differences(
            compare_values(policies, changed, "Policies", rules=rules, whole=True),
            policies,
            changed,
            "Policies",
        )
        assert fields == [
            {
                "path": "Policies[PolicyName=one].PolicyDocument.Statement[0].Action[1]",
                "model": "b",
                "iac": "欠落",
            },
            {
                "path": "Policies[PolicyName=one].PolicyDocument.Statement[0].Action[IaC:1]",
                "model": "欠落",
                "iac": "c",
            },
        ]


@pytest.mark.parametrize("whole", [True, False])
def test_action_string_list_and_scope(whole):
    path = "Policies[].PolicyDocument.Statement[].Action"
    declared = registry.rules("IAM.Role")
    for left, right in [("a", ["a"]), (["a"], "a")]:
        assert (
            compare_values(left, right, path, rules=declared, whole=whole).equal is True
        )
    for right in ([], ["b"], ["a", "a"], [True], [["a"]]):
        assert (
            compare_values("a", right, path, rules=declared, whole=whole).equal is False
        )
    assert compare_values(["a", "b"], ["b", "a"], path, rules=declared).equal is True
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
    assert {kind for kind, rules in registry.RULES.items() if rules} == kinds
    for kind in sorted(kinds):
        selected = {
            p
            for p in catalogs.selected(kind)
            if kind + "." + p not in catalogs.outputs(kind)
        }
        expected = property_paths_with_parents(selected)
        assert expected <= registry.rules(kind).keys(), (
            kind,
            expected - registry.rules(kind).keys(),
        )
        for rule in registry.rules(kind).values():
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
            rule = registry.require(kind, path)
            node = catalog.property_schema(kind, path)
            if node.get("type") == "array":
                assert rule.whole in {"ORDERED", "UNORDERED", "KEYED"}, (kind, path)
        # Reading the schema here is test-time evidence, never a runtime prerequisite.
        assert catalog.cloudformation_type(kind).startswith("AWS::")
    assert len(kinds) == 176 and len({k.split(".")[0] for k in kinds}) == 46
    assert set(registry.RULES) - kinds == {"QuickSight.Group"}
    assert registry.resource("QuickSight.Group").imported_arn is not None
    assert not (ROOT / "framework/scripts/comparison/services").exists()
    assert not (ROOT / "framework/scripts/comparison/rulebook.py").exists()
    for prop, forms in KMS_FORMS.items():
        service, resource_type, path = prop.split(".", 2)
        rule = registry.require(service + "." + resource_type, path)
        assert rule.forms is forms and callable(rule.form_compare)
    assert registry.resource("Unknown.Type").identity_same is None
    assert registry.require(
        "CodeBuild.Project", "Environment.EnvironmentVariables[]"
    ).reference_context
    assert (
        registry.require("Route53.RecordSet", "ResourceRecords[]").selected_decision
        is not None
    )
    assert registry.resource("KMS.Key").identity_same is not None


def test_unregistered_rule_is_framework_error():
    with pytest.raises(ValueError, match="Framework comparison rule missing"):
        registry.require("EC2.VPC", "NotImplemented")
    with pytest.raises(ValueError, match="Framework comparison rule missing"):
        registry.require("Unknown.Type", "Value")
    with pytest.raises(ValueError, match="Framework comparison rule missing"):
        compare_values("a", "a", "Value", rules={})
    assert (
        Counter(r.whole for rules in registry.RULES.values() for r in rules.values())[
            "SCALAR"
        ]
        > 0
    )
    assert CompareOutcome(None).differences == ()


def codebuild_reference(
    resolve_literal,
    left,
    right,
    path,
    resource_kind="SecretsManager.Secret",
    *,
    context=None,
):
    return reference_same(
        left,
        right,
        "CodeBuild.Project",
        path,
        local_comparison=True,
        forms_for=lambda *args: None,
        resolve_literal=resolve_literal,
        resource_type=lambda symbol: resource_kind,
        kms_format=lambda value: None,
        diagnostic=lambda *args: {},
        context=context,
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
        rules=registry.rules("CodeBuild.Project"),
        reference=partial(codebuild_reference, resolve),
    )
    assert outcome.equal is False
    assert resolve.call_count == 1
    assert value_differences(outcome, left, right, "CodeBuild.Project.Environment") == [
        {"path": "EnvironmentVariables[0].Name", "model": "LEFT", "iac": "RIGHT"}
    ]
    assert resolve.call_count == 1


@pytest.mark.parametrize("attribute", ["Name", "Id"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "selector,actual,expected",
    [
        ("SECRETS_MANAGER", "app/secret", True),
        (
            "SECRETS_MANAGER",
            "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:app/secret",
            True,
        ),
        ("SECRETS_MANAGER", "app/other", False),
        ("SECRETS_MANAGER", "app/secret:key", False),
        ("SECRETS_MANAGER", "app/secret::AWSCURRENT", False),
        ("SECRETS_MANAGER", "app/secret:::version", False),
        (
            "SECRETS_MANAGER",
            "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:app/secret:key",
            False,
        ),
        ("UNKNOWN", "app/secret", None),
        ("PLAINTEXT", "app/secret", None),
        (None, "app/secret", None),
    ],
)
def test_contextual_secret_comparison(selector, actual, expected, attribute, reverse):
    symbol = ResourceReference(
        {"$resource": ["secrets", "001"], "$attribute": attribute}
    )
    if attribute == "Name" and actual.startswith("arn:") and expected is True:
        expected = False
    values = {
        "Name": "app/secret",
        "Id": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:app/secret",
    }
    resolver = Mock(side_effect=lambda ref: values[ref["$attribute"]])
    left = {"Type": selector, "Value": symbol}
    right = {"Type": selector, "Value": actual}
    if selector is None:
        del left["Type"], right["Type"]
    if reverse:
        left, right = right, left
    outcome = compare_values(
        left,
        right,
        "Environment.EnvironmentVariables[]",
        rules=registry.rules("CodeBuild.Project"),
        reference=partial(codebuild_reference, resolver),
        whole=True,
    )
    assert outcome.equal is expected
    calls = resolver.call_count
    if expected is False:
        assert [difference.path for difference in outcome.differences] == ["Value"]
        assert [(d.model_pointer, d.iac_pointer) for d in outcome.differences] == [
            (("Value",), ("Value",))
        ]
        value_differences(outcome, left, right)
    assert resolver.call_count == calls
    if attribute == "Name":
        assert all(
            call.args[0]["$attribute"] == "Name" for call in resolver.call_args_list
        )


@pytest.mark.parametrize("attribute", ["Name", "Id"])
def test_contextual_reference_identity_and_unknown(attribute):
    symbol = ResourceReference(
        {"$resource": ["secrets", "001"], "$attribute": attribute}
    )
    other = ResourceReference(
        {"$resource": ["secrets", "002"], "$attribute": attribute}
    )
    resolve = Mock(side_effect=KeyError("unresolved"))
    callback = partial(codebuild_reference, resolve)
    rule = registry.rules("CodeBuild.Project")
    left = {"Type": "SECRETS_MANAGER", "Value": symbol}
    for value, expected in [(symbol, True), (other, False), ("app/secret", None)]:
        right = {"Type": "SECRETS_MANAGER", "Value": value}
        assert (
            compare_values(
                left,
                right,
                "Environment.EnvironmentVariables[]",
                rules=rule,
                reference=callback,
                whole=True,
            ).equal
            is expected
        )
    wrong = {"Type": "PARAMETER_STORE", "Value": symbol}
    assert (
        compare_values(
            wrong,
            {"Type": "PARAMETER_STORE", "Value": "app/secret"},
            "Environment.EnvironmentVariables[]",
            rules=rule,
            reference=callback,
            whole=True,
        ).equal
        is None
    )


@pytest.mark.parametrize("left_attribute", ["Name", "Id"])
@pytest.mark.parametrize("right_attribute", ["Name", "Id"])
@pytest.mark.parametrize("selector", ["SECRETS_MANAGER", "PLAINTEXT", None, "UNKNOWN"])
def test_contextual_symbol_attributes_are_not_rewritten(
    left_attribute, right_attribute, selector
):
    left = ResourceReference(
        {"$resource": ["secrets", "001"], "$attribute": left_attribute}
    )
    right = ResourceReference(
        {"$resource": ["secrets", "001"], "$attribute": right_attribute}
    )
    resolve = Mock(
        side_effect=AssertionError("symbol identity must not resolve literals")
    )
    result = codebuild_reference(
        resolve,
        left,
        right,
        "Environment.EnvironmentVariables[].Value",
        context={"Type": selector},
    )
    assert result.equal is (
        left_attribute == right_attribute if selector == "SECRETS_MANAGER" else None
    )
    resolve.assert_not_called()


def test_contextual_parameter_name():
    symbol = ResourceReference(
        {"$resource": ["parameters", "001"], "$attribute": "Name"}
    )
    callback = partial(
        codebuild_reference,
        Mock(return_value="/app/parameter"),
        resource_kind="SSM.Parameter",
    )
    left = {"Type": "PARAMETER_STORE", "Value": symbol}
    right = {"Type": "PARAMETER_STORE", "Value": "/app/parameter"}
    assert (
        compare_values(
            left,
            right,
            "Environment.EnvironmentVariables[]",
            rules=registry.rules("CodeBuild.Project"),
            reference=callback,
            whole=True,
        ).equal
        is True
    )


def test_codebuild_parameter_partial_selection_preserves_extra_fields():
    symbol = ResourceReference(
        {"$resource": ["parameters", "001"], "$attribute": "Name"}
    )
    callback = partial(
        codebuild_reference,
        Mock(return_value="/app/parameter"),
        resource_kind="SSM.Parameter",
    )
    left = {"Type": "PARAMETER_STORE", "Value": symbol}
    right = {"Type": "PARAMETER_STORE", "Value": "/app/parameter", "Name": "EXTRA"}
    assert (
        compare_values(
            left,
            right,
            "Environment.EnvironmentVariables[]",
            rules=registry.rules("CodeBuild.Project"),
            reference=callback,
        ).equal
        is True
    )


def test_codebuild_full_selection_detects_extra_fields():
    symbol = ResourceReference(
        {"$resource": ["parameters", "001"], "$attribute": "Name"}
    )
    callback = partial(
        codebuild_reference,
        Mock(return_value="/app/parameter"),
        resource_kind="SSM.Parameter",
    )
    left = {"Type": "PARAMETER_STORE", "Value": symbol}
    right = {"Type": "PARAMETER_STORE", "Value": "/app/parameter", "Name": "EXTRA"}
    outcome = compare_values(
        left,
        right,
        "Environment.EnvironmentVariables[]",
        rules=registry.rules("CodeBuild.Project"),
        reference=callback,
        whole=True,
    )
    assert outcome.equal is False
    assert [difference.path for difference in outcome.differences] == ["Name"]


def test_codebuild_dynamic_literal_is_unresolved():
    symbol = ResourceReference({"$resource": ["secrets", "001"], "$attribute": "Id"})
    left = {"Type": "SECRETS_MANAGER", "Value": symbol}
    right = {"Type": "SECRETS_MANAGER", "Value": "${Unknown}"}
    assert (
        compare_values(
            left,
            right,
            "Environment.EnvironmentVariables[]",
            rules=registry.rules("CodeBuild.Project"),
            reference=partial(codebuild_reference, Mock(return_value="app/secret")),
            whole=True,
        ).equal
        is None
    )


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


@pytest.mark.parametrize("size", [10, 40, 100])
def test_unordered_length_mismatch_does_not_compare_pairs(size):
    callback = Mock(return_value=ReferenceDecision(NotImplemented))

    left = [{"value": i} for i in range(size)]
    right = left + [{"value": size}]
    outcome = compare(left, right, UNORDERED, reference=callback)
    assert outcome.equal is False
    assert callback.call_count == 1
    assert len(outcome.differences) == 1
    assert outcome.differences[0].model == size
    assert outcome.differences[0].iac == size + 1


@pytest.mark.parametrize("kind", ["IAM.Role", "IAM.User"])
def test_policy_name_unselected_uses_selected_unordered_comparison(kind):
    rules = registry.rules(kind)
    model = [{"PolicyDocument": {"Statement": []}}]
    actual = [{"PolicyName": "OnlyOne", "PolicyDocument": {"Statement": []}}]
    assert compare_values(model, actual, "Policies", rules=rules).equal is True
    assert (
        compare_values(model, actual, "Policies", rules=rules, whole=True).equal
        is False
    )
    assert compare_values(model, actual * 2, "Policies", rules=rules).equal is True
    duplicates = compare_values(
        model * 2,
        [actual[0], dict(actual[0], PolicyName="Other")],
        "Policies",
        rules=rules,
    )
    assert duplicates.equal is True and not duplicates.differences
    assert (
        compare_values(
            model,
            [Expression("Unverified", [])],
            "Policies",
            rules=rules,
            reference=uncertain,
        ).equal
        is None
    )


@pytest.mark.parametrize("kind", ["IAM.Role", "IAM.User"])
@pytest.mark.parametrize("projected", [False, True])
@pytest.mark.parametrize(
    "named,name,action,expected",
    [
        (False, "only", "a", True),
        (False, {"Ref": "MissingPolicyName"}, "a", True),
        (False, {"Fn::Sub": 42}, "a", True),
        (False, Expression("Sub", ["symbolic"]), "a", True),
        (False, ResourceReference({"$resource": ["iam", "001"]}), "a", True),
        (False, {"Ref": "MissingPolicyName"}, "b", False),
        (False, {"Ref": "MissingPolicyName"}, {"Ref": "MissingAction"}, None),
        (True, "only", "a", True),
        (True, {"Ref": "MissingPolicyName"}, "a", None),
        (True, "other", "a", False),
        ("mixed", {"Ref": "MissingPolicyName"}, "a", None),
        ("mixed", "other", "a", False),
    ],
)
def test_policy_key_selection_uncertainty(
    kind, projected, named, name, action, expected
):
    model = [{"PolicyDocument": {"Statement": [{"Action": "a"}]}}]
    if named:
        model[0]["PolicyName"] = "only"
    rules = registry.rules(kind)
    evaluate = Mock(side_effect=policy_selection_intrinsic)
    raw = [{"PolicyName": name, "PolicyDocument": {"Statement": [{"Action": action}]}}]
    if named == "mixed":
        other = {"PolicyDocument": {"Statement": [{"Action": "z"}]}}
        model.append(other)
        raw.append(dict(other, PolicyName="extra"))
    if projected:
        prepared = project_actual(
            raw,
            evaluate=evaluate,
            property_name="Policies",
            model_path="model",
            desired=model,
            exact=False,
            rules=rules,
        )
        actual = prepared.value
    else:
        actual = [
            {
                "PolicyName": Expression("Unverified", [])
                if type(name) is dict
                else name,
                "PolicyDocument": {
                    "Statement": [
                        {
                            "Action": Expression("Unverified", [])
                            if isinstance(action, dict)
                            else action
                        }
                    ]
                },
            }
        ]
        if named == "mixed":
            actual.append(raw[1])
    reference = Mock(side_effect=uncertain)
    result = compare_values(model, actual, "Policies", rules=rules, reference=reference)
    assert result.equal is expected
    assert bool(result.differences) is (expected is False)
    if not named:
        assert not result.diagnostics
        assert not any(
            call.args[2].endswith(".PolicyName") for call in reference.call_args_list
        )
        assert not any(call.args[0] == name for call in evaluate.call_args_list)
        assert not any(
            path.endswith(".PolicyName") for path, _, _ in result.candidate_failures
        )
        assert not any(
            warning["pointer"].endswith("/PolicyName")
            for warning in result.candidate_warnings
        )
        if projected:
            assert not prepared.warnings and not prepared.failures
            integrity_evaluate = Mock(side_effect=policy_integrity_intrinsic)
            integrity = key_integrity(
                raw,
                rule=rules["Policies"],
                evaluate=integrity_evaluate,
                property_name=kind + ".Policies",
                model_path="model",
            )
            integrity_evaluate.assert_not_called()
            assert not integrity.failures and not integrity.warnings
            if isinstance(action, dict):
                assert result.candidate_failures[0][:2] == (
                    "Policies[].PolicyDocument.Statement[].Action",
                    "/0/PolicyDocument/Statement/0/Action",
                )
            else:
                assert not result.candidate_failures
    elif projected and expected is None:
        assert any(
            path.endswith(".PolicyName")
            for path, _, _ in (*prepared.failures, *result.candidate_failures)
        )


def policy_selection_intrinsic(value):
    if isinstance(value, dict) and "Ref" in value:
        raise KeyError(value["Ref"])
    return policy_test_intrinsic(value)


@pytest.mark.parametrize("kind", ["IAM.Role", "IAM.User"])
@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize(
    "names", ["distinct", "unknown", "duplicate", "invalid", "symbolic"]
)
def test_keyless_comparison_and_separate_key_integrity(kind, named, names):
    a = {"PolicyDocument": {"Statement": [{"Action": "a"}]}}
    b = {"PolicyDocument": {"Statement": [{"Action": "b"}]}}
    model = [dict(a, PolicyName="one") if named else a, b]
    raw = [
        dict(
            b,
            PolicyName={
                "distinct": "two",
                "unknown": {"Ref": "MissingPolicyName"},
                "duplicate": "one",
                "invalid": {"Fn::Sub": 42},
                "symbolic": Expression("Sub", ["symbolic"]),
            }[names],
        ),
        dict(a, PolicyName={"Fn::Sub": "one"} if named else "one"),
    ]
    if names == "duplicate":
        raw[1] = {"Fn::If": ["Active", raw[1], {"Ref": "Inactive"}]}
    rules = registry.rules(kind)
    evaluate = Mock(side_effect=policy_selection_intrinsic)
    prepared = project_actual(
        raw,
        evaluate=evaluate,
        property_name="Policies",
        model_path="model",
        desired=model,
        exact=False,
        rules=rules,
    )
    result = compare_values(
        model, prepared.value, "Policies", rules=rules, reference=uncertain
    )
    assert result.equal is True
    assert not result.diagnostics
    assert not result.candidate_warnings and not result.candidate_failures
    assert not prepared.warnings and not prepared.failures
    assert sum(
        call.args[0] == {"Ref": "MissingPolicyName"} for call in evaluate.call_args_list
    ) == int(named and names == "unknown")
    assert sum(
        call.args[0] == {"Fn::Sub": "one"} for call in evaluate.call_args_list
    ) == int(named)
    integrity_evaluate = Mock(side_effect=policy_integrity_intrinsic)
    integrity = key_integrity(
        raw,
        rule=rules["Policies"],
        evaluate=integrity_evaluate,
        property_name=kind + ".Policies",
        model_path="model",
    )
    assert bool(integrity.warnings) is (names == "unknown")
    assert len(integrity.failures) == int(names != "distinct")
    if integrity.failures:
        path, pointer, error = integrity.failures[0]
        assert path == kind + ".Policies[].PolicyName"
        assert pointer == (
            "/1/Fn::If/1/PolicyName" if names == "duplicate" else "/0/PolicyName"
        )
        if names == "duplicate":
            assert error.iac_cause == {
                "kind": "input-invalid",
                "rule": "unique-key",
                "key": "PolicyName",
                "value": "one",
                "pointers": ["/0/PolicyName", "/1/Fn::If/1/PolicyName"],
            }
        else:
            assert isinstance(
                error,
                KeyError
                if names == "unknown"
                else Blocked
                if names == "symbolic"
                else ValueError,
            )
    assert not any(
        isinstance(call.args[0], dict) and "Statement" in call.args[0]
        for call in integrity_evaluate.call_args_list
    )


def policy_integrity_intrinsic(value):
    if value == {"Fn::Sub": 42}:
        raise ValueError("invalid Fn::Sub")
    return policy_selection_intrinsic(value)


def candidate_diagnostic(left, right, path):
    if isinstance(left, str) and isinstance(right, str) and left != right:
        return ReferenceDecision(NotImplemented, ({"reason": "rejected candidate"},))
    return ReferenceDecision(NotImplemented)


def test_keyless_match_ignores_rejected_candidate_diagnostics():
    rules = registry.rules("IAM.User")
    model = [
        {"PolicyDocument": {"Statement": [{"Action": value}]}} for value in ("a", "b")
    ]
    actual = [
        {"PolicyName": value, **item}
        for value, item in zip(("two", "one"), reversed(model), strict=True)
    ]
    result = compare_values(
        model, actual, "Policies", rules=rules, reference=candidate_diagnostic
    )
    assert result.equal is True
    assert not result.diagnostics


@pytest.mark.parametrize("kind", ["IAM.Role", "IAM.User"])
def test_keyless_policy_matching_and_actual_differences(kind):
    rules = registry.rules(kind)
    a = {
        "PolicyDocument": {
            "Statement": [
                {
                    "Action": ["a", "b"],
                    "Resource": "*",
                    "Condition": {"StringEquals": {"x": "y"}},
                }
            ]
        }
    }
    b = {"PolicyDocument": {"Statement": [{"Action": "c", "Resource": "*"}]}}
    model = [a, b]
    actual = [{"PolicyName": "two", **b}, {"PolicyName": "one", **a}]
    assert compare_values(model, actual, "Policies", rules=rules).equal is True
    assert (
        compare_values(
            [dict(a, PolicyName="one"), b], actual, "Policies", rules=rules
        ).equal
        is True
    )
    assert (
        compare_values(
            [dict(a, PolicyName="wrong"), b], actual, "Policies", rules=rules
        ).equal
        is False
    )
    assert compare_values([a, a], [actual[1]], "Policies", rules=rules).equal is False
    assert (
        compare_values(model, [actual[1], actual[1]], "Policies", rules=rules).equal
        is False
    )
    assert (
        compare_values(
            model,
            [actual[1], Expression("Unverified", [])],
            "Policies",
            rules=rules,
            reference=uncertain,
        ).equal
        is None
    )
    assert (
        compare_values(model, actual, "Policies", rules=rules, whole=True).equal
        is False
    )
    for field, replacement in (
        ("Action", ["a"]),
        ("Resource", "different"),
        ("Condition", {"StringEquals": {"x": "z"}}),
    ):
        changed = {
            "PolicyName": "one",
            "PolicyDocument": {
                "Statement": [
                    dict(a["PolicyDocument"]["Statement"][0], **{field: replacement})
                ]
            },
        }
        outcome = compare_values(model, [actual[0], changed], "Policies", rules=rules)
        assert outcome.equal is False and outcome.differences


@pytest.mark.parametrize("kind", ["IAM.Role", "IAM.User"])
@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize(
    "field,left,right,suffix",
    [
        ("Action", "a", "b", ()),
        ("Resource", "one", "two", ()),
        (
            "Condition",
            {"StringEquals": {"x": "y"}},
            {"StringEquals": {"x": "z"}},
            ("StringEquals", "x"),
        ),
    ],
)
def test_policy_unique_attribute_evidence(kind, named, field, left, right, suffix):
    model = [{"PolicyDocument": {"Statement": [{field: left}]}}]
    actual = [{"PolicyName": "only", "PolicyDocument": {"Statement": [{field: right}]}}]
    if named:
        model[0]["PolicyName"] = "only"
    reference = Mock(side_effect=uncertain)
    outcome = compare_values(
        model, actual, "Policies", rules=registry.rules(kind), reference=reference
    )
    calls = reference.call_count
    assert outcome.equal is False
    pointer = (0, "PolicyDocument", "Statement", 0, field, *suffix)
    assert [(d.model_pointer, d.iac_pointer) for d in outcome.differences] == [
        (pointer, pointer)
    ]
    path = (
        ("Policies[PolicyName=only]" if named else "Policies[0]")
        + ".PolicyDocument.Statement[0]."
        + ".".join((field, *suffix))
    )
    assert value_differences(outcome, model, actual) == [
        {
            "path": path,
            "model": "y" if suffix else left,
            "iac": "z" if suffix else right,
        }
    ]
    assert reference.call_count == calls


def test_keyless_unique_remainder_after_reordered_matches():
    a = {"PolicyDocument": {"Statement": [{"Action": "a"}]}}
    b = {"PolicyDocument": {"Statement": [{"Action": "b"}]}}
    c = {"PolicyDocument": {"Statement": [{"Action": "c"}]}}
    actual = [dict(b, PolicyName="second"), dict(c, PolicyName="first")]
    result = compare_values(
        [a, b], actual, "Policies", rules=registry.rules("IAM.Role")
    )
    assert result.equal is False
    assert [(d.model_pointer, d.iac_pointer) for d in result.differences] == [
        (
            (0, "PolicyDocument", "Statement", 0, "Action"),
            (1, "PolicyDocument", "Statement", 0, "Action"),
        )
    ]
    assert value_differences(result, [a, b], actual) == [
        {
            "path": "Policies[0].PolicyDocument.Statement[0].Action",
            "model": "a",
            "iac": "c",
        }
    ]


@pytest.mark.parametrize("kind", ["IAM.Role", "IAM.User"])
@pytest.mark.parametrize(
    "case", ["ambiguous", "duplicate", "missing", "selected-name-missing", "unknown"]
)
def test_keyless_unproven_pairs_remain_missing(kind, case):
    a = {"PolicyDocument": {"Statement": [{"Action": "a"}]}}
    b = {"PolicyDocument": {"Statement": [{"Action": "b"}]}}
    c = {"PolicyDocument": {"Statement": [{"Action": "c"}]}}
    model, actual = [a, b], [dict(c, PolicyName="one"), dict(c, PolicyName="two")]
    if case == "duplicate":
        model, actual = [a, a], [dict(a, PolicyName="one"), dict(b, PolicyName="two")]
    elif case == "missing":
        actual = [dict(a, PolicyName="one")]
    elif case == "selected-name-missing":
        model, actual = (
            [dict(a, PolicyName="missing"), b],
            [dict(c, PolicyName="other"), dict(b, PolicyName="two")],
        )
    elif case == "unknown":
        actual = [Expression("Unverified", []), Expression("Unverified", [])]
    result = compare_values(
        model, actual, "Policies", rules=registry.rules(kind), reference=uncertain
    )
    assert result.equal is (None if case == "unknown" else False)
    if case == "unknown":
        assert not result.differences
    else:
        assert result.differences
        missing = [d for d in result.differences if d.iac is MISSING]
        candidates = [d for d in result.differences if d.model is MISSING]
        assert missing and len(missing) + len(candidates) == len(result.differences)
        assert all(
            d.iac_pointer is None and d.model_pointer in {(0,), (1,)} for d in missing
        )
        assert all(
            d.model_pointer is None and d.iac_pointer in {(0,), (1,)}
            for d in candidates
        )
        assert all("差分未確定" in d.path for d in candidates)


def policy_test_intrinsic(value):
    if value == {"Condition": "Active"}:
        return True
    if value == {"Ref": "AWS::NoValue"}:
        return {"$noValue": True}
    if isinstance(value, dict) and "Fn::Sub" in value:
        return value["Fn::Sub"]
    return value


def test_keyless_conditional_projection_and_masking_use_cached_evidence():
    model = [
        {
            "PolicyDocument": {
                "Statement": [{"Action": "a", "Condition": {"Password": "secret-one"}}]
            }
        }
    ]
    changed = {
        "PolicyName": "active",
        "PolicyDocument": {
            "Statement": [
                {"Action": {"Fn::Sub": "b"}, "Condition": {"Password": "secret-two"}}
            ]
        },
    }
    raw = [
        {"Fn::If": ["Active", {"Ref": "AWS::NoValue"}, changed]},
        {"Fn::If": ["Active", changed, {"Ref": "AWS::NoValue"}]},
    ]
    evaluate = Mock(side_effect=policy_test_intrinsic)
    rules = registry.rules("IAM.Role")
    actual = project_actual(
        raw,
        evaluate=evaluate,
        property_name="Policies",
        model_path="model",
        desired=model,
        exact=False,
        rules=rules,
    ).value
    reference = Mock(side_effect=uncertain)
    result = compare_values(model, actual, "Policies", rules=rules, reference=reference)
    calls = evaluate.call_count, reference.call_count
    assert result.equal is False
    details = value_differences(result, model, actual)
    assert details == [
        {
            "path": "Policies[0].PolicyDocument.Statement[0].Action",
            "model": "a",
            "iac": "b",
        },
        {
            "path": "Policies[0].PolicyDocument.Statement[0].Condition.Password",
            "model": '"<masked>"',
            "iac": '"<masked>"',
        },
    ]
    assert all(
        d.model_pointer == d.iac_pointer and d.iac_pointer[0] == 0
        for d in result.differences
    )
    assert calls == (evaluate.call_count, reference.call_count)


def test_keyless_policy_unresolved_sibling_keeps_known_difference():
    unknown = Expression("Unverified", [])
    model = [{"PolicyDocument": {"Statement": [{"Action": "a", "Resource": "one"}]}}]
    actual = [
        {
            "PolicyName": "only",
            "PolicyDocument": {"Statement": [{"Action": unknown, "Resource": "two"}]},
        }
    ]
    result = compare_values(
        model, actual, "Policies", rules=registry.rules("IAM.Role"), reference=uncertain
    )
    assert result.equal is False
    assert [(d.model_pointer, d.iac_pointer) for d in result.differences] == [
        (
            (0, "PolicyDocument", "Statement", 0, "Resource"),
            (0, "PolicyDocument", "Statement", 0, "Resource"),
        )
    ]
    assert value_differences(result, model, actual) == [
        {
            "path": "Policies[0].PolicyDocument.Statement[0].Resource",
            "model": "one",
            "iac": "two",
        }
    ]


def test_unordered_length_difference_retains_proven_sid_and_pointers():
    path = "PolicyDocument"
    rules = registry.rules("IAM.ManagedPolicy")
    left = {"Statement": [{"Sid": "a", "Effect": "Allow"}]}
    right = {"Statement": [{"Sid": "b"}, {"Sid": "a", "Effect": "Deny"}]}
    result = compare_values(left, right, path, rules=rules, whole=True)
    assert result.equal is False
    assert [(d.path, d.model_pointer, d.iac_pointer) for d in result.differences] == [
        ("Statement.要素数", None, None),
        ("Statement[0].Effect", ("Statement", 0, "Effect"), ("Statement", 1, "Effect")),
    ]
    assert value_differences(result, left, right, path)[1]["iac"] == "Deny"


@pytest.mark.parametrize("named", [True, False])
def test_nested_policy_reference_difference_keeps_keyed_path_and_values(named):
    rules = registry.rules("IAM.Role")
    model = [
        {
            "PolicyName": "IfInboundGlueAccess",
            "PolicyDocument": {
                "Statement": [
                    {"Sid": "UseAppKey", "Resource": "alias-arn"},
                    {"Sid": "Other", "Resource": "same"},
                ]
            },
        },
        {"PolicyName": "OtherPolicy", "PolicyDocument": {"Statement": []}},
    ]
    actual = [
        {"PolicyName": "OtherPolicy", "PolicyDocument": {"Statement": []}},
        {
            "PolicyName": "IfInboundGlueAccess",
            "PolicyDocument": {
                "Statement": [
                    {"Sid": "Other", "Resource": "same"},
                    {"Sid": "UseAppKey", "Resource": "key-arn"},
                ]
            },
        },
    ]

    if not named:
        del model[0]["PolicyName"]
    decision = compare_values(
        model, actual, "Policies", rules=rules, reference=nested_policy_reference
    )
    batch = setting_result(
        "iam",
        "054",
        "IAM.Role.Policies",
        model,
        actual,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
    )
    assert batch.records[0]["category"] == "difference"
    assert [(d.model_pointer, d.iac_pointer) for d in decision.differences] == [
        (
            (0, "PolicyDocument", "Statement", 0, "Resource"),
            (1, "PolicyDocument", "Statement", 1, "Resource"),
        )
    ]
    assert value_differences(decision, model, actual) == [
        {
            "path": (
                "Policies[PolicyName=IfInboundGlueAccess]" if named else "Policies[0]"
            )
            + ".PolicyDocument.Statement[0].Resource",
            "model": "alias-arn",
            "iac": "key-arn",
        }
    ]
    actual[1]["PolicyDocument"]["Statement"][1]["Resource"] = "alias-arn"
    matched = compare_values(model, actual, "Policies", rules=rules)
    assert matched.equal is True
    assert (
        setting_result(
            "iam",
            "054",
            "IAM.Role.Policies",
            model,
            actual,
            matched,
            "stack",
            [{}],
            {},
            actual_error=None,
            redact=safe_value,
        ).records[0]["category"]
        == "matched"
    )


def nested_policy_reference(left, right, path):
    if path == "Policies[].PolicyDocument.Statement[].Resource" and left != right:
        return ReferenceDecision(False)
    if path == "Policies[].PolicyDocument" and left != right:
        return ReferenceDecision(False)
    return ReferenceDecision(NotImplemented)


def diagnostic_candidate(left, right, path):
    if path.endswith(".Value"):
        return ReferenceDecision(
            left == right, ({"path": path, "reason": str(left) + "/" + str(right)},)
        )
    return ReferenceDecision(NotImplemented)


def test_unordered_rejected_candidate_diagnostics():
    outcome = compare(
        [{"Value": "a"}, {"Value": "b"}],
        [{"Value": "b"}, {"Value": "a"}],
        UNORDERED,
        reference=diagnostic_candidate,
    )
    assert outcome.equal is True
    assert {d["reason"] for d in outcome.diagnostics} == {"a/a", "b/b"}


def uncertain_candidate(left, right, path):
    if path.endswith(".Value"):
        if left == right:
            return ReferenceDecision(True)
        return ReferenceDecision(
            None, ({"path": path, "reason": str(left) + "/" + str(right)},)
        )
    return ReferenceDecision(NotImplemented)


def test_unordered_ambiguous_correspondence_is_not_selected():
    outcome = compare(
        [{"Value": "a"}, {"Value": "b"}],
        [{"Value": "x"}, {"Value": "y"}],
        UNORDERED,
        reference=uncertain_candidate,
    )
    assert outcome.equal is None
    assert {d["reason"] for d in outcome.diagnostics} == {"a/x", "a/y", "b/x", "b/y"}
    assert all(d["correspondence"] == "unproven" for d in outcome.diagnostics)


def test_unordered_singleton_difference_keeps_diagnostic():
    outcome = compare(
        [{"Value": "a"}], [{"Value": "b"}], UNORDERED, reference=diagnostic_candidate
    )
    assert outcome.equal is False
    assert [d["reason"] for d in outcome.diagnostics] == ["a/b"]
    keyed = compare(
        [{"Sid": "a", "Value": "a"}],
        [{"Sid": "b", "Value": "b"}],
        replace(UNORDERED, key="Sid"),
        reference=diagnostic_candidate,
    )
    assert keyed.equal is False and not keyed.diagnostics


def test_unordered_nested_rejected_diagnostics():
    rules = {"Setting": UNORDERED, "Setting[].Items": UNORDERED}
    left = [{"Items": [{"Value": "a"}, {"Value": "b"}]}]
    right = [{"Items": [{"Value": "b"}, {"Value": "a"}]}]
    outcome = compare_values(
        left, right, "Setting", rules=rules, reference=diagnostic_candidate
    )
    assert outcome.equal is True
    assert {d["reason"] for d in outcome.diagnostics} == {"a/a", "b/b"}


def test_unordered_unique_key_difference_keeps_evidence():
    rule = replace(UNORDERED, key="Sid")
    left = [{"Sid": "A", "Value": "a"}, {"Sid": "B", "Value": "b"}]
    right = [{"Sid": "B", "Value": "b"}, {"Sid": "A", "Value": "x"}]
    outcome = compare(left, right, rule, reference=diagnostic_candidate)
    assert outcome.equal is False and outcome.differences
    assert any(
        d.get("correspondence", {}).get("value") == "A" and d["reason"] == "a/x"
        for d in outcome.diagnostics
    )
    assert all(d["reason"] not in {"a/b", "b/x"} for d in outcome.diagnostics)


def test_unordered_unequal_length_unknown_direction():
    left = [{"Value": "a"}, {"Value": "b"}]
    right = [{"Value": "a"}, Expression("Unverified", []), Expression("Unverified", [])]
    outcome = compare(left, right, UNORDERED, reference=uncertain_candidate)
    assert outcome.equal is None
    assert all(d.get("correspondence") == "unproven" for d in outcome.diagnostics)


def test_unordered_possible_edges_match_rematching_oracle():
    rng = random.Random(713)
    for rows in range(1, 6):
        for columns in range(rows, 7):
            for _ in range(40):
                matrix = [
                    [rng.choice((True, False, None)) for _ in range(columns)]
                    for _ in range(rows)
                ]
                if len(unordered_matching(matrix, allow_unknown=True)) != rows:
                    continue
                candidates = [
                    (value, (({"edge": [i, j]},), False, (), ()))
                    for i, row in enumerate(matrix)
                    for j, value in enumerate(row)
                ]
                state = _Comparison({}, None, False)
                _select_unordered_diagnostics(
                    state,
                    list(range(columns)) if rows != columns else list(range(rows)),
                    list(range(rows)) if rows != columns else list(range(columns)),
                    "Setting",
                    UNORDERED,
                    None,
                    candidates,
                    [
                        (
                            matrix,
                            unordered_matching(matrix),
                            unordered_matching(matrix, allow_unknown=True),
                        )
                    ],
                )
                selected = {tuple(item["edge"]) for item in state.diagnostics}
                expected = set()
                for i, row in enumerate(matrix):
                    for j, value in enumerate(row):
                        if value is not False:
                            rest = [
                                [v for k, v in enumerate(r) if k != j]
                                for n, r in enumerate(matrix)
                                if n != i
                            ]
                            if (
                                len(unordered_matching(rest, allow_unknown=True))
                                == rows - 1
                            ):
                                expected.add((i, j))
                assert selected == expected


def test_unordered_remainder_preserves_diagnostic_and_pointers():
    left = [{"Value": "a"}, {"Value": "b"}]
    right = [{"Value": "a"}, {"Value": "x"}]
    outcome = compare(left, right, UNORDERED, reference=diagnostic_candidate)
    assert outcome.equal is False
    assert {d["reason"] for d in outcome.diagnostics} == {"a/a", "b/x"}
    assert [(d.model_pointer, d.iac_pointer) for d in outcome.differences] == [
        ((1, "Value"), (1, "Value"))
    ]


def kms_candidate(left, right, path):
    if path.endswith(".Value"):
        reason = (
            "KMS format outside allowed forms: invalid"
            if (left, right) in {("b", "x"), ("a", "c"), ("a", "x")}
            else "equal"
            if left == right
            else "mismatch"
        )
        return ReferenceDecision(left == right, ({"path": path, "reason": reason},))
    return ReferenceDecision(NotImplemented)


def test_unordered_format_classification_uses_only_selected_candidates():
    for left, right, expected in [
        (
            [{"Value": "a"}, {"Value": "b"}],
            [{"Value": "a"}, {"Value": "x"}],
            "KMS format outside allowed forms: invalid",
        ),
        ([{"Value": "a"}, {"Value": "x"}], [{"Value": "x"}, {"Value": "a"}], "equal"),
        (
            [{"Value": "a"}, {"Value": "b"}],
            [{"Value": "a"}, {"Value": "c"}],
            "value mismatch",
        ),
    ]:
        outcome = compare(left, right, UNORDERED, reference=kms_candidate)
        record = setting_result(
            "iam",
            "001",
            "Setting",
            left,
            right,
            outcome,
            "stack",
            [{}],
            {},
            actual_error=None,
            redact=safe_value,
        ).records[0]
        assert record["reason"] == expected
        assert any(
            d["reason"] == "KMS format outside allowed forms: invalid"
            for d in outcome.diagnostics
        ) == expected.startswith("KMS format")


def nested_uncertain_reference(left, right, path):
    if path.endswith("Resource[]"):
        return ReferenceDecision(
            None,
            (
                {
                    "path": path,
                    "model": left,
                    "iac": right,
                    "reason": "recorded_identifier_mismatch",
                },
            ),
        )
    return ReferenceDecision(NotImplemented)


def test_unordered_nested_correspondence_and_duplicate_keys():
    rules = {
        "Statement": replace(UNORDERED, key="Sid"),
        "Statement[].Resource": UNORDERED,
    }
    ref = ResourceReference({"$resource": ["kms", "003"], "$attribute": "KeyId"})
    left = [{"Sid": "UseMaterialKey", "Resource": ["fixed"]}]
    right = [{"Sid": "UseMaterialKey", "Resource": [ref]}]
    outcome = compare_values(
        left, right, "Statement", rules=rules, reference=nested_uncertain_reference
    )
    assert outcome.equal is None
    diagnostic = outcome.diagnostics[0]
    assert diagnostic["correspondence_path"][0]["correspondence"] == {
        "key": "Sid",
        "value": "UseMaterialKey",
    }
    assert diagnostic["correspondence_path"][1]["correspondence"] == "unproven"
    for key in ("Sid", "missing"):
        duplicate_left = [{key: "same", "Resource": ["fixed"]}] * 2
        duplicate_right = [{key: "same", "Resource": [ref]}] * 2
        result = compare_values(
            duplicate_left,
            duplicate_right,
            "Statement",
            rules=rules,
            reference=nested_uncertain_reference,
        )
        assert result.equal is None
        assert all(
            all(
                entry["correspondence"] == "unproven"
                for entry in d["correspondence_path"]
            )
            for d in result.diagnostics
        )


def test_unordered_uncertain_matching_does_not_recompute_per_pair(monkeypatch):
    matching = Mock(wraps=methods.unordered_matching)
    monkeypatch.setattr(methods, "unordered_matching", matching)
    values = [{"Value": str(i)} for i in range(36)]
    outcome = compare(
        values,
        [{"Value": "x"} for _ in values],
        UNORDERED,
        reference=uncertain_candidate,
    )
    assert outcome.equal is None
    assert matching.call_count <= 1
    assert len(outcome.diagnostics) == len(values)
    assert all(d["correspondence"] == "unproven" for d in outcome.diagnostics)


def repeated_reason_candidate(left, right, path):
    if path.endswith(".Value"):
        return ReferenceDecision(
            None, ({"path": path, "model": left, "iac": right, "reason": "unresolved"},)
        )
    return ReferenceDecision(NotImplemented)


def test_unordered_ambiguous_repeated_reason_is_aggregated():
    left = [{"Value": str(i)} for i in range(12)]
    right = [{"Value": "x" + str(i)} for i in range(12)]
    result = compare(left, right, UNORDERED, reference=repeated_reason_candidate)
    assert result.equal is None
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0]["reason"] == "unresolved"
    assert result.diagnostics[0]["correspondence"] == "unproven"
    assert (
        result.diagnostics[0]["model"]
        == result.diagnostics[0]["iac"]
        == "候補複数（未確定）"
    )


def test_unordered_aggregation_keeps_distinct_reference_targets():
    left = [{"Resource": ["first", "second"]}]
    right = [
        {
            "Resource": [
                ResourceReference({"$resource": ["kms", "003"], "$attribute": "KeyId"}),
                ResourceReference({"$resource": ["kms", "004"], "$attribute": "KeyId"}),
            ]
        }
    ]
    result = compare_values(
        left,
        right,
        "Statement",
        rules={"Statement": UNORDERED, "Statement[].Resource": UNORDERED},
        reference=nested_uncertain_reference,
    )
    assert result.equal is None
    assert {tuple(item["iac"]["$resource"]) for item in result.diagnostics} == {
        ("kms", "003"),
        ("kms", "004"),
    }
    assert all(
        item["reason"] == "recorded_identifier_mismatch" for item in result.diagnostics
    )
    assert all(item["model"] == "候補複数（未確定）" for item in result.diagnostics)
