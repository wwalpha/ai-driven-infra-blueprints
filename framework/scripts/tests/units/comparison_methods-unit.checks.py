"""One algorithm suite and static rule coverage; only synthetic comparison values."""

import sys
from collections import Counter
from functools import partial
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison import registry
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
from comparison.result import setting_result, value_differences
from design.catalog import DesignSchemaCatalog, property_paths_with_parents
from support.pytest_cli import run
from utils.aws_catalogs import catalogs_for
from utils.iac_values import (
    Expression,
    ResourceReference,
    comparison_result,
    safe_value,
    same,
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
    assert len(fields) == 2 and all(".Action" not in item["path"] for item in fields)

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
                "path": "Policies[PolicyName=one].PolicyDocument.Statement[0]",
                "model": '{"Action":["a","b"]}',
                "iac": "欠落",
            },
            {
                "path": "Policies[PolicyName=one].PolicyDocument.Statement[IaC:0]",
                "model": "欠落",
                "iac": '{"Action":["a","c"]}',
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
        ("PLAINTEXT", "app/secret", None),
        (None, "app/secret", None),
    ],
)
def test_contextual_secret_comparison(selector, actual, expected):
    symbol = ResourceReference({"$resource": ["secrets", "001"], "$attribute": "Id"})
    values = {
        "Name": "app/secret",
        "Id": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:app/secret",
    }
    resolver = Mock(side_effect=lambda ref: values[ref["$attribute"]])
    left = {"Type": selector, "Value": symbol}
    right = {"Type": selector, "Value": actual}
    outcome = compare_values(
        left,
        right,
        "Environment.EnvironmentVariables[]",
        rules=registry.rules("CodeBuild.Project"),
        reference=partial(codebuild_reference, resolver),
        whole=True,
    )
    assert outcome.equal is expected
    if expected is False:
        assert [difference.path for difference in outcome.differences] == ["Value"]


def test_contextual_reference_identity_and_unknown():
    symbol = ResourceReference({"$resource": ["secrets", "001"], "$attribute": "Id"})
    other = ResourceReference({"$resource": ["secrets", "002"], "$attribute": "Id"})
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
    assert compare_values(model, actual * 2, "Policies", rules=rules).equal is False
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


def test_nested_policy_reference_difference_keeps_keyed_path_and_values():
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

    def reference(left, right, path):
        if path == "Policies[].PolicyDocument.Statement[].Resource" and left != right:
            return ReferenceDecision(False)
        if path == "Policies[].PolicyDocument" and left != right:
            return ReferenceDecision(False)
        return ReferenceDecision(NotImplemented)

    decision = compare_values(
        model, actual, "Policies", rules=rules, reference=reference
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
    assert value_differences(decision, model, actual) == [
        {
            "path": "Policies[PolicyName=IfInboundGlueAccess].PolicyDocument.Statement[0].Resource",
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
