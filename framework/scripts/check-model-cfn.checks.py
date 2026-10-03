#!/usr/bin/env python3
"""Observable drift, scope and fail-closed checks on a synthetic local target."""
if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("model_cfn_check", Path(__file__).with_name("check-model-cfn.py"))
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)


def save(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def model(service, resources):
    lines = [f"desired.service.{service}.serviceId={service}"]
    for number, (logical, kind, rows) in enumerate(resources, 1):
        identity = f"{number:03d}"
        lines += [f"desired.resource.{identity}.resourceType={kind}",
                  f"desired.resource.{identity}.logicalId={logical}",
                  f"desired.resource.{identity}.anchor={logical.lower()}"]
        for index, (field, value) in enumerate(rows, 1):
            prefix = f"desired.row.{identity}-{index:03d}."
            lines += [prefix + "property=" + kind + "." + field,
                      prefix + "value=" + ("[policy.json](logs/policy.json)" if isinstance(value, dict) else value),
                      prefix + "comment=設定値"]
            if isinstance(value, dict):
                lines.append(prefix + "document=" + json.dumps(value))
    return "\n".join(lines) + "\n"


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    for name in ("cloudformation-schema", "aws", "api"):
        shutil.copytree(ROOT / "framework/materials" / name, root / "framework/materials" / name)
    save(root / "project.json", json.dumps({"targets": [{"environment": "dev", "alias": "blue",
        "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}))
    base = root / "model/dev/blue"
    save(base / "cloudformation-stacks.properties", "desired.stack.001.name=App\ndesired.stack.001.template=app.yaml\n"
         "desired.stack.001.parameters=app.json\ndesired.stack.001.deployOrder=1\n")
    inputs = root / "infra/cloudformation/parameters/dev/blue/app.json"
    save(inputs, '[{"ParameterKey":"Environment","ParameterValue":"dev"}]')
    template = root / "infra/cloudformation/templates/blue/app.yaml"
    save(template, "# Synthetic template decoded below; separate native-decoder check follows.\n")
    document = {"Parameters": {"Days": {"Type": "Number", "Default": 14}, "Environment": {"Type": "String"}},
                "Resources": {"Group": {"Type": "AWS::Logs::LogGroup", "Properties": {
                    "LogGroupName": {"Fn::Sub": "/app/${Environment}"}, "RetentionInDays": {"Ref": "Days"}}}}}
    rows = [("LogGroupName", "`/app/dev`"), ("RetentionInDays", "`14`")]
    save(base / "logs.properties", model("logs", [("Group", "Logs.LogGroup", rows)]))
    # An unrelated service error must not broaden selected-service validation.
    save(base / "unrelated.properties", "invalid\n")

    def run(services=("logs",)):
        return M.Comparison(root, "dev", "blue", list(services), lambda _: (document, [])).run()

    assert run()["status"] == "PASS"
    assert run()["checked_properties"] == 2
    props = document["Resources"]["Group"]["Properties"]
    props["RetentionInDays"] = 7
    result = run()
    assert result["status"] == "FAIL" and result["findings"][0]["expected"] == [14]
    assert result["findings"][0]["actual"] == [7]
    assert result["findings"][0]["model"]["line"] > 1
    del props["RetentionInDays"]
    assert any("absent" in f["reason"] for f in run()["findings"])
    props["RetentionInDays"] = {"Fn::Unsupported": "anything"}
    assert any(f["status"] == "unverified" for f in run()["findings"])
    props["RetentionInDays"] = True
    assert any(f["status"] == "mismatch" for f in run()["findings"])
    props["RetentionInDays"] = {"Ref": "Days"}
    del document["Parameters"]["Days"]["Default"]
    try:
        run()
    except M.Unknown as error:
        assert "missing parameter" in str(error)
    else:
        raise AssertionError("missing parameter passed")
    document["Parameters"]["Days"]["Default"] = 14

    document["Conditions"] = {"Dev": {"Fn::Equals": [{"Ref": "Environment"}, "dev"]}}
    props["RetentionInDays"] = {"Fn::If": ["Dev", 14, 7]}
    assert run()["status"] == "PASS"
    document["Conditions"]["Dev"] = {"Fn::If": ["Dev", True, False]}
    assert any("cyclic" in f["reason"] for f in run()["findings"])
    document["Conditions"]["Dev"] = {"Fn::Equals": [{"Ref": "Environment"}, "dev"]}
    props["RetentionInDays"] = {"Ref": "Days"}
    props["Tags"] = [{"Key": "A", "Value": "first"}, {"Key": "B", "Value": "second"}]
    tag_rows = [("Tags[].Key", "`A`"), ("Tags[].Value", "`first`"),
                ("Tags[].Key", "`B`"), ("Tags[].Value", "`second`")]
    save(base / "logs.properties", model("logs", [("Group", "Logs.LogGroup", rows + tag_rows)]))
    assert run()["status"] == "PASS"
    props["Tags"].reverse()
    assert any(f["property"].endswith("Tags[].Key") for f in run()["findings"])
    props["Tags"].pop()
    assert run()["status"] == "FAIL"
    del props["Tags"]

    policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "logs:*", "Resource": "*"}]}
    save(base / "logs.properties", model("logs", [("Group", "Logs.LogGroup", rows + [
        ("ResourcePolicyDocument", policy)])]))
    props["ResourcePolicyDocument"] = dict(reversed(list(policy.items())))
    assert run()["status"] == "PASS"
    props["ResourcePolicyDocument"] = {**policy, "Statement": []}
    assert any(f["property"].endswith("ResourcePolicyDocument") for f in run()["findings"])
    del props["ResourcePolicyDocument"]
    save(base / "logs.properties", model("logs", [("Group", "Logs.LogGroup", rows)]))

    vpc = model("vpc", [("Net", "EC2.VPC", [("Name", "`net-dev`"), ("CidrBlock", "`10.0.0.0/16`")]),
                        ("Subnet", "EC2.Subnet", [("Name", "`subnet-dev`"), ("VpcId", "[Net](#net)")])])
    save(base / "vpc.properties", vpc)
    document["Resources"].update({"Net": {"Type": "AWS::EC2::VPC", "Properties": {
        "CidrBlock": "10.0.0.0/16", "Tags": [{"Key": "Name", "Value": "net-dev"}]}},
        "Subnet": {"Type": "AWS::EC2::Subnet", "Properties": {"Tags": [{"Key": "Name", "Value": "subnet-dev"}],
            "VpcId": {"Ref": "Net"}}}})
    assert run(("vpc",))["status"] == "PASS"
    document["Resources"]["Subnet"]["Properties"]["VpcId"] = {"Ref": "Subnet"}
    assert any(f["property"].endswith("VpcId") for f in run(("vpc",))["findings"])
    document["Resources"]["Subnet"]["Properties"]["VpcId"] = {"Ref": "Net"}
    document["Resources"]["Net"]["Properties"]["Tags"][0]["Value"] = "wrong"
    assert any(f["property"].endswith("Name") for f in run(("vpc",))["findings"])
    document["Resources"]["Net"]["Properties"]["Tags"][0]["Value"] = "net-dev"

    document["Outputs"] = {"VpcId": {"Value": {"Ref": "Net"}, "Export": {"Name": "VpcId"}}}
    document["Resources"]["Subnet"]["Properties"]["VpcId"] = {"Fn::ImportValue": "VpcId"}
    assert run(("vpc",))["status"] == "PASS"
    document["Resources"]["Subnet"]["Properties"]["VpcId"] = {"Fn::ImportValue": "UnknownVpc"}
    assert any(f["status"] == "unverified" for f in run(("vpc",))["findings"])

    document["Resources"]["Extra"] = {"Type": "AWS::Logs::LogGroup", "Properties": {"LogGroupName": "extra"}}
    assert any(f["resource"] == "Extra" for f in run()["findings"])
    del document["Resources"]["Extra"]
    imported = model("logs", [("Group", "Logs.LogGroup", rows)])
    save(base / "logs.properties", imported + "desired.resource.001.resourceMode=IMPORT\n")
    resource = document["Resources"].pop("Group")
    assert run()["status"] == "NOT_APPLICABLE" and run()["excluded"][0]["reason"] == "IMPORT"
    document["Resources"]["Group"] = resource
    assert run()["status"] == "FAIL"  # An IMPORT must not silently remain in Resources.
    save(base / "logs.properties", "# model-index: 1\n# part: logs/part-001.properties\n")
    save(base / "logs/part-001.properties", model("logs", [("Group", "Logs.LogGroup", rows)]))
    assert run()["status"] == "PASS"
    props["RetentionInDays"] = 7
    assert run()["findings"][0]["model"]["path"].endswith("logs/part-001.properties")
    props["RetentionInDays"] = 14

    for directory in ("other", "../blue"):
        try:
            M.Comparison(root, "dev", directory, ["logs"], lambda _: (document, []))
        except M.Unknown:
            pass
        else:
            raise AssertionError("unknown target accepted")

assert not M.equal(True, 1)
assert not M.equal([1], [1, 2])
assert M.at_path({"Tags": [{"Key": "A"}, {"Key": "B"}]}, "Tags[].Key") == ["A", "B"]
print("model-cfn: PASS (parameter/default, drift, missing, typed comparison, policy, tag, reference, export, scope, parts)")
