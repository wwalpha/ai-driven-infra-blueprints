"""Pure comparison contracts; explicit expected values, no AWS or project."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from functools import partial
from unittest.mock import Mock

from comparison.design_link import desired_reference
from comparison.resource import inactive_evidence
from comparison.rules.cloud_trail import cloudtrail_rows
from design.array_display import indexed_rows
from iac_evaluation import Evaluation
from support.cloudformation_inputs_fixtures import condition_document
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import Unresolved, put_row
from utils.iac_values import (
    Expression,
    ResourceReference,
    safe_value,
    same,
)
from utils.reference_contracts import contract, reference_attribute

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

index_rows = partial(indexed_rows, root=Path(__file__).resolve().parents[4])

trail_kind = "CloudTrail.Trail."
trail_fields = [
    ("EventSelectors[].IncludeManagementEvents", "`true`"),
    ("EventSelectors[].ReadWriteType", "`All`"),
    ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`"),
    ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3"]`'),
    ("EventSelectors[].IncludeManagementEvents", "`false`"),
    ("EventSelectors[].DataResources[].Type", "`AWS::Lambda::Function`"),
    ("EventSelectors[].DataResources[].Values", "[function](lambda.md#function)"),
    ("EventSelectors[].DataResources[].Type", "`AWS::Lambda::Function`"),
    ("EventSelectors[].DataResources[].Values", "[other](lambda.md#other)"),
]
trail_rows = [
    (f"001-{i:03d}", dict(property=trail_kind + prop, value=value))
    for i, (prop, value) in enumerate(trail_fields, 1)
]
trail_paths = [
    "EventSelectors[1].IncludeManagementEvents",
    "EventSelectors[1].ReadWriteType",
    "EventSelectors[1].DataResources[1].Type",
    "EventSelectors[1].DataResources[1].Values",
    "EventSelectors[2].IncludeManagementEvents",
    "EventSelectors[2].DataResources[1].Type",
    "EventSelectors[2].DataResources[1].Values",
    "EventSelectors[2].DataResources[2].Type",
    "EventSelectors[2].DataResources[2].Values",
]
trail_expected = {
    rid: dict(row, property=trail_kind + prop)
    for (rid, row), prop in zip(trail_rows, trail_paths, strict=False)
}
for ordered in (trail_rows, trail_rows[::-1], trail_rows[::2] + trail_rows[1::2]):
    projected = dict(cloudtrail_rows(ordered, index_rows=index_rows))
    assert projected == trail_expected, projected
    assert all(
        row["property"] == trail_kind + prop
        for (_, row), (prop, _) in zip(trail_rows, trail_fields, strict=False)
    )
for invalid in (
    trail_rows[:3],
    trail_rows + [(trail_rows[0][0], dict(trail_rows[0][1], value="`false`"))],
    [("unknown", trail_rows[0][1]), *trail_rows[1:]],
    [
        (
            trail_rows[0][0],
            dict(
                trail_rows[0][1],
                property=trail_kind + "EventSelectors[1].IncludeManagementEvents",
            ),
        ),
        *trail_rows[1:],
    ],
):
    try:
        cloudtrail_rows(invalid, index_rows=index_rows)
    except Unresolved as error:
        assert "array membership unresolved" in str(error)
    else:
        raise AssertionError("unproven CloudTrail membership accepted")

for rows, expected in [
    ([("A", 1), ("B.C", None)], {"A": 1, "B": {"C": None}}),
    (
        [("A[].K", "a"), ("A[].V", 1), ("A[].K", "a"), ("A[].V", 2)],
        {"A": [{"K": "a", "V": 1}, {"K": "a", "V": 2}]},
    ),
    ([("A[2].K", "b"), ("A[1].K", "a")], {"A": [{"K": "a"}, {"K": "b"}]}),
    (
        [("A[]", [1, 1]), ("A[]", 2), ("B", 1), ("B", [2, 2])],
        {"A": [1, 1, 2], "B": [1, 2, 2]},
    ),
    ([("A[1].B[]", [1, 1]), ("A[2].B[]", [])], {"A": [{"B": [1, 1]}, {"B": []}]}),
    ([("A[2]", "same"), ("A[1]", "same")], {"A": ["same", "same"]}),
]:
    tree = {}
    for path, value in rows:
        put_row(tree, path, value)
    assert tree == expected, (rows, tree)
# Explicit indexes are membership, independent of catalog order and optional fields.
stages = [
    {
        "Name": "same",
        "Actions": [
            {
                "Name": "a",
                "InputArtifacts": [{"Name": "same"}, {"Name": "same"}],
                "OutputArtifacts": [],
            },
            {"Name": "b", "RunOrder": 2, "OutputArtifacts": [{"Name": "out"}]},
        ],
    },
    {"Name": "same", "Actions": [{"Name": "c", "InputArtifacts": []}]},
]
rows = []


def flatten(value, path):
    if isinstance(value, dict):
        for key, child in value.items():
            flatten(child, path + "." + key if path else key)
    elif isinstance(value, list) and value:
        for index, child in enumerate(value, 1):
            flatten(child, f"{path}[{index}]")
    else:
        rows.append((path, value))


flatten(stages, "Stages")
for ordered in (rows, list(reversed(rows)), sorted(rows)):
    tree = {}
    for path, value in ordered:
        put_row(tree, path, value)
    assert tree == {"Stages": stages}, tree
for path in ("A[].B[].K", "A[].B[1].K", "A[1].B[].K", "A[].B[]", "A[0].K"):
    tree = {"Existing": 1}
    try:
        put_row(tree, path, "same")
    except Unresolved as error:
        assert path in str(error)
        assert tree == {"Existing": 1}, (
            "unresolved rows must not partially mutate the tree"
        )
    else:
        raise AssertionError("ambiguous membership accepted: " + path)


ref = ResourceReference({"$resource": ["s3", "001"], "$attribute": "Arn"})
assert same(ref, dict(ref)) is False and same(ref, ResourceReference(ref)) is True
expression = Expression("Join", ["", [ref, "/*"]])
assert same(expression, safe_value(expression)) is False
assert safe_value(
    {
        "Password": "arn:aws:s3:::private",
        "Token": "one",
        "Arn": "arn:aws:s3:::private",
    }
) == {
    "Password": "<masked>",
    "Token": "<masked>",
    "Arn": "arn:aws:s3:::private",
}
for value in (
    "arn:aws:iam::aws:policy/AdministratorAccess",
    "arn:aws:iam::123456789012:role/example",
    "arn:aws:s3:::example-bucket",
    "arn:aws:kms:ap-northeast-1:123456789012:key/example",
    "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:example",
    "arn:aws-cn:iam::123456789012:role/example",
    "arn:aws-us-gov:iam::123456789012:role/example",
    "Resource arn:aws:s3:::example-bucket differs from the desired value",
):
    assert safe_value(value) == value


# Schemas prove types/bounds, never DNS values or array elements.
schemas = {
    "DnsEntries": {"type": "array", "minItems": 1, "maxItems": 2},
    "DnsEntries[]": {"type": "string"},
    "UnknownLength": {"type": "array"},
    "UnknownType": {},
    "UnknownElement": {"type": "array", "minItems": 1},
    "UnknownElement[]": {},
    "Numbers": {"type": "array", "minItems": 1},
    "Numbers[]": {"type": "integer"},
    "Name": {"type": "string"},
}
resources = {"vpc-endpoint": {"001": {"resourceType": "EC2.VPCEndpoint"}}}


def symbol(stack, logical, attribute):
    assert logical == "Endpoint"
    return ResourceReference(
        {"$resource": ["vpc-endpoint", "001"], "$attribute": attribute}
    )


def forbidden(*args):
    raise AssertionError("unexpected import lookup")


evaluator = Evaluation(
    {"stack": ({}, {}, {})},
    resources,
    lambda kind, path: schemas[path],
    symbol,
    forbidden,
    True,
    lambda kind: {"readOnlyProperties": ["/properties/" + path for path in schemas]},
)


def evaluate(value):
    return evaluator.evaluate("stack", value)


def getatt(attribute):
    return {"Fn::GetAtt": ["Endpoint", attribute]}


def select(index, items):
    return {"Fn::Select": [index, items]}


def rejects(value, exception, reason):
    try:
        evaluate(value)
    except exception as error:
        assert reason in str(error), str(error)
    else:
        raise AssertionError((value, exception, reason))


first = select("0", getatt("DnsEntries"))
split = {"Fn::Split": [":", first]}
chain = select(0, split)
expected = Expression(
    "Select",
    [
        0,
        Expression(
            "Split",
            [":", Expression("Select", [0, symbol("stack", "Endpoint", "DnsEntries")])],
        ),
    ],
)
assert same(evaluate(chain), expected)
assert same(evaluate(chain), evaluate(select("0", split)))
assert evaluator.string_operand(evaluate(first))
assert not same(evaluate(chain), safe_value(expected))
assert not same(evaluate(chain), evaluate(select(0, {"Fn::Split": [",", first]})))
assert evaluator.string_operand(evaluate(select(0, getatt("Numbers")))) is False
assert evaluate(select(1, ["a", "b"])) == "b"
assert evaluate(select(1, {"Fn::Split": [":", "zone:dns"]})) == "dns"
assert evaluate({"Fn::Split": [":", ""]}) == [""]
for value, reason in [
    (select(0, getatt("UnknownLength")), "index 0, symbolic array minItems=0"),
    (select(1, getatt("DnsEntries")), "index 1, symbolic array minItems=1"),
    (select(0, getatt("UnknownType")), "array type is unproven"),
    (select(1, split), "index 1, symbolic array minItems=1"),
    (select(getatt("Name"), ["a"]), "index is unproven"),
    (
        {"Fn::Split": [":", select(0, getatt("UnknownElement"))]},
        "string type is unproven",
    ),
]:
    rejects(value, Blocked, reason)
for value in [
    select(2, getatt("DnsEntries")),
    select(0, getatt("Name")),
    select(True, ["a"]),
    select(-1, ["a"]),
    select(1.0, ["a"]),
    select("x", ["a"]),
    select(1, ["a"]),
    select(0, []),
    select(0, [None]),
    select(0, {}),
    {"Fn::Select": [0]},
    {"Fn::Split": [":", getatt("DnsEntries")]},
    {"Fn::Split": [":", select(0, getatt("Numbers"))]},
    {"Fn::Split": ["", "text"]},
    {"Fn::Split": [1, "text"]},
    {"Fn::Split": [":", None]},
    {"Fn::Split": [":"]},
    {"Fn::Join": ["", [select(0, getatt("Numbers"))]]},
]:
    rejects(value, ValueError, "invalid")
# AWS/deploy mode still refuses symbolic array/string evaluation.
evaluator.local_comparison = False
assert evaluate(select(1, {"Fn::Split": [":", "zone:dns"]})) == "dns"
rejects(first, ValueError, "invalid Select operands")
rejects({"Fn::Split": [":", getatt("Name")]}, ValueError, "invalid Split operands")
print(
    "Symbolic array evaluation: PASS (schema types/bounds, chains, concrete inputs, errors, deploy isolation)"
)

for condition, names in [
    ("Combined", {"Enable", "Other"}),
    ("Branch", {"Enable"}),
    ("SubOff", {"Enable"}),
]:
    location, cause = inactive_evidence(
        "stack",
        "Bucket",
        {"Condition": condition},
        condition_document,
        {"Enable": "false", "Other": "yes"},
        {},
        path="template.yaml",
        parameter_path="parameters.json",
        supplied=set(),
        stack_id="001",
        target={},
        environment="dev",
        directory="team",
        marks={},
        source_lookup=Mock(),
        redact=lambda value, key: value,
    )
    assert {item["name"] for item in cause["inputs"]} == names
    assert all(item["source"]["kind"] == "template-default" for item in cause["inputs"])
    assert set(cause["conditions"]) == (
        {"Combined", "IsEnabled", "OtherEnabled"}
        if condition == "Combined"
        else {condition, "IsEnabled"}
        if condition == "Branch"
        else {condition}
    )
for value, noecho, name in [
    ("private", True, "Confidential"),
    (8912, True, "Numeric"),
    ("private", False, "SecretToken"),
]:
    document = {
        "Parameters": {name: {"NoEcho": noecho}},
        "Conditions": {"Off": {"Fn::Equals": [{"Ref": name}, "other"]}},
    }
    for supplied in (set(), {name}):
        _, cause = inactive_evidence(
            "stack",
            "Bucket",
            {"Condition": "Off"},
            document,
            {name: value},
            {},
            path="template.yaml",
            parameter_path="parameters.json",
            supplied=supplied,
            stack_id="001",
            target={},
            environment="dev",
            directory="team",
            marks={},
            source_lookup=Mock(),
            redact=safe_value,
        )
        assert cause["inputs"][0]["value"] in {
            "<masked sensitive parameter>",
            "<masked>",
        }
for name, source in [
    ("AWS::Region", {"path": "project.json", "key": "awsRegion"}),
    ("AWS::StackName", {"path": "stacks.properties", "key": "desired.stack.001.name"}),
]:
    document = {"Conditions": {"Off": {"Fn::Equals": [{"Ref": name}, "other"]}}}
    _, cause = inactive_evidence(
        "stack",
        "Bucket",
        {"Condition": "Off"},
        document,
        {},
        {name: "fixture"},
        path="template.yaml",
        parameter_path="parameters.json",
        supplied=set(),
        stack_id="001",
        target={},
        environment="dev",
        directory="team",
        marks={},
        source_lookup=Mock(return_value=source),
        redact=safe_value,
    )
    assert all(
        cause["inputs"][0]["source"][key] == value for key, value in source.items()
    )


# Shared receiving contracts must validate before IMPORT deferral.
def _mock_reference(service, value, selected, *, protect_import):
    return (
        value
        if isinstance(value, ResourceReference)
        else ResourceReference(
            {"$resource": ["producer", "001"], "$attribute": selected}
        )
    )


def _reference_contract_check(
    kind, path, context, producer, attribute=None, value="link"
):
    protect = Mock(side_effect=lambda symbol, prop: symbol)
    if value == "link":
        forms = contract(kind + "." + path, context).get(producer, ())
        selected = (
            attribute
            if attribute is not None
            else forms[0]
            if len(forms) == 1
            else "Unknown"
        )
        value = ResourceReference(
            {
                "$resource": ["producer", "001"],
                "$attribute": reference_attribute(producer, selected),
            }
        )
    result = desired_reference(
        "consumer",
        value,
        kind,
        path,
        attribute,
        context,
        local_comparison=True,
        reference=_mock_reference,
        resource_type=lambda symbol: producer,
        forms_for=lambda kind, path: None,
        protect_import=protect,
    )
    assert protect.call_count == 1
    assert protect.call_args.args[1] == kind + "." + path
    return result


_build_path = "Environment.EnvironmentVariables[].Value"
for _value in (
    "link",
    ResourceReference({"$resource": ["producer", "001"], "$attribute": "Name"}),
):
    for _producer in ("SecretsManager.Secret", "SSM.Parameter"):
        try:
            _reference_contract_check(
                "CodeBuild.Project",
                _build_path,
                {"Type": "PLAINTEXT"},
                _producer,
                "Name",
                _value,
            )
        except Blocked as _error:
            assert "PLAINTEXT" in str(_error)
        else:
            raise AssertionError("PLAINTEXT link accepted")
for _kind, _path, _context, _producer, _expected in (
    (
        "CodeBuild.Project",
        _build_path,
        {"Type": "SECRETS_MANAGER"},
        "SecretsManager.Secret",
        "Id",
    ),
    (
        "CodeBuild.Project",
        _build_path,
        {"Type": "PARAMETER_STORE"},
        "SSM.Parameter",
        "Name",
    ),
    (
        "CloudTrail.Trail",
        "EventSelectors[].DataResources[].Values[]",
        {"Type": "AWS::Lambda::Function"},
        "Lambda.Function",
        "Arn",
    ),
    ("EC2.FlowLog", "ResourceId", {"ResourceType": "VPC"}, "EC2.VPC", "VpcId"),
    (
        "CodePipeline.Pipeline",
        "Stages[].Actions[].Configuration.ProjectName",
        {
            "ActionTypeId": {
                "Category": "Build",
                "Owner": "AWS",
                "Provider": "CodeBuild",
                "Version": "1",
            }
        },
        "CodeBuild.Project",
        "Name",
    ),
):
    _symbol = _reference_contract_check(_kind, _path, _context, _producer, _expected)
    assert _symbol["$attribute"] == reference_attribute(_producer, _expected)
    try:
        _reference_contract_check(_kind, _path, _context, "wrong")
    except Blocked:
        pass
    else:
        raise AssertionError("wrong producer accepted")
try:
    _reference_contract_check(
        "CodeBuild.Project", _build_path, {"Type": "UNKNOWN"}, "SecretsManager.Secret"
    )
except Blocked:
    pass
else:
    raise AssertionError("unknown context accepted")

_trail = "EventSelectors[].DataResources[].Values[]"
_s3 = _reference_contract_check(
    "CloudTrail.Trail", _trail, {"Type": "AWS::S3::Object"}, "S3.Bucket", "ObjectArn"
)
assert isinstance(_s3, Expression) and _s3.operation == "Join"
for _kind, _path, _context, _producer in (
    ("EC2.FlowLog", "ResourceId", {"ResourceType": "VPC"}, "EC2.VPC"),
    (
        "CodePipeline.Pipeline",
        "Stages[].Actions[].Configuration.ProjectName",
        {
            "ActionTypeId": {
                "Category": "Build",
                "Owner": "AWS",
                "Provider": "CodeBuild",
                "Version": "1",
            }
        },
        "CodeBuild.Project",
    ),
):
    try:
        _reference_contract_check(_kind, _path, _context, _producer, "wrong")
    except Blocked:
        pass
    else:
        raise AssertionError("invalid explicit attribute accepted")

# A valid contract reaches IMPORT protection; an invalid one never does.
for _producer, _reason in (
    ("SSM.Parameter", "pending import"),
    ("S3.Bucket", "reference target must be"),
):
    _protect = Mock(side_effect=Blocked("pending import"))
    try:
        desired_reference(
            "consumer",
            ResourceReference({"$resource": ["producer", "001"], "$attribute": "Name"}),
            "CodeBuild.Project",
            _build_path,
            context={"Type": "PARAMETER_STORE"},
            local_comparison=True,
            reference=_mock_reference,
            resource_type=Mock(return_value=_producer),
            forms_for=Mock(return_value=None),
            protect_import=_protect,
        )
    except Blocked as _error:
        assert _reason in str(_error)
        assert _protect.called == (_producer == "SSM.Parameter")
    else:
        raise AssertionError("invalid or pending reference accepted")
