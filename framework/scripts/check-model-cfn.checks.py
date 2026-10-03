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
    root = Path(temporary).resolve()
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
    documents = {str(template): document}

    def run(services=("logs",)):
        return M.Comparison(root, "dev", "blue", list(services), lambda path: (documents[path], [])).run()

    assert run()["status"] == "PASS"
    assert run()["checked_properties"] == 2
    document["Resources"]["Trail"] = {"Type": "AWS::CloudTrail::Trail", "Properties": {
        "TrailName": "app-dev", "CloudWatchLogsLogGroupArn": "arn:aws:logs:ap-northeast-1:123456789012:log-group:/app/dev:*"}}
    save(base / "cloudtrail.properties", model("cloudtrail", [("Trail", "CloudTrail.Trail", [
        ("TrailName", "app-dev"), ("CloudWatchLogsLogGroupArn", "[Group](logs.md#group)")])]))
    assert run(("cloudtrail", "logs"))["status"] == "PASS"  # Literal ARN and GetAtt identify exactly the same named LogGroup.
    document["Resources"]["Trail"]["Properties"]["CloudWatchLogsLogGroupArn"] = "arn:aws:logs:ap-northeast-1:123456789012:log-group:/wrong:*"
    assert any(f["status"] == "mismatch" and f["property"].endswith("LogGroupArn") for f in run(("cloudtrail",))["findings"])
    del document["Resources"]["Trail"]
    result = run(("unrelated", "logs"))
    assert result["service_results"]["unrelated"]["status"] == "FAIL"
    assert result["service_results"]["logs"]["status"] == "PASS"
    props = document["Resources"]["Group"]["Properties"]
    class MarkedString(str):
        pass

    class MarkedInteger(int):
        pass

    props["LogGroupName"], props["RetentionInDays"] = MarkedString("/app/dev"), MarkedInteger(14)
    assert run()["status"] == "PASS"  # Decoder source marks must not turn equal scalars into drift.
    props["LogGroupName"], props["RetentionInDays"] = {"Fn::Sub": "/app/${Environment}"}, {"Ref": "Days"}
    document["Mappings"] = {"LogNames": {"dev": {"Name": "/app/dev", "Names": ["/app/dev"]}},
                            "Keys": {"dev": {"Field": "Name"}}}
    lookup = ["LogNames", {"Ref": "Environment"}, "Name"]
    props["LogGroupName"] = {"Fn::FindInMap": lookup}
    assert run()["status"] == "PASS"
    lookup[2] = {"Fn::FindInMap": ["Keys", {"Ref": "Environment"}, "Field"]}
    assert run()["status"] == "PASS"
    props["LogGroupName"] = {"Fn::Select": [0, {"Fn::FindInMap": ["LogNames", "dev", "Names"]}]}
    assert run()["status"] == "PASS"
    props["LogGroupName"] = {"Fn::FindInMap": ["LogNames", "dev", "Name", {"DefaultValue": {"Fn::Unsupported": "unused"}}]}
    assert run()["status"] == "PASS"  # DefaultValue is lazy when the key exists.
    props["LogGroupName"] = {"Fn::FindInMap": ["LogNames", "missing", "Name", {"DefaultValue": "/app/dev"}]}
    assert run()["status"] == "PASS"
    for bad in (["LogNames", "dev", "Missing"], ["MissingMap", "dev", "Name", {"DefaultValue": "/app/dev"}],
                ["LogNames", "dev"], ["LogNames", 1, "Name"], ["LogNames", "dev", "Name", {"Wrong": "value"}]):
        props["LogGroupName"] = {"Fn::FindInMap": bad}
        assert any(f["status"] == "unverified" and "FindInMap" in f["reason"] for f in run()["findings"])
    props["LogGroupName"] = {"Fn::Sub": "/app/${Environment}"}
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
    result = run()
    assert result["status"] == "FAIL" and any("missing parameter" in f["reason"] for f in result["stack_findings"])
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

    policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "logs:*",
              "Resource": {"Fn::Sub": "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/app/${Environment}:*"},
              "Condition": {"StringEquals": {"aws:SourceAccount": "123456789012"}}}]}
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

    # A different stack's parameter, export and condition failures must not stop healthy services.
    stacks = base / "cloudformation-stacks.properties"
    original_stacks = stacks.read_text(encoding="utf-8")
    save(stacks, original_stacks + "desired.stack.002.name=Storage\ndesired.stack.002.template=storage.yaml\n"
         "desired.stack.002.parameters=storage.json\ndesired.stack.002.deployOrder=2\n")
    storage = root / "infra/cloudformation/templates/blue/storage.yaml"
    save(storage, "# storage\n")
    storage_inputs = root / "infra/cloudformation/parameters/dev/blue/storage.json"
    save(storage_inputs, "[]")
    storage_doc = {"Parameters": {"Required": {"Type": "String"}}, "Resources": {
        "Bucket": {"Type": "AWS::S3::Bucket", "Properties": {"BucketName": "app-data"}}}}
    documents[str(storage)] = storage_doc
    save(base / "s3.properties", model("s3", [("Bucket", "S3.Bucket", [("BucketName", "`app-data`")])]))
    result = run(("s3", "logs"))
    assert result["status"] == "FAIL" and result["stack_findings"][0]["stack"] == "Storage"
    assert result["service_results"]["s3"]["status"] == "FAIL"
    assert result["service_results"]["logs"] == {"status": "PASS", "checked_properties": 2}
    save(storage_inputs, '[{"ParameterKey":"Required","ParameterValue":"value"}]')
    storage_doc["Outputs"] = {"Broken": {"Value": "unused", "Export": {"Name": {"Fn::Unsupported": "bad"}}}}
    result = run(("s3", "logs"))
    assert result["stack_findings"] and all(r["status"] == "PASS" for r in result["service_results"].values())
    props["RetentionInDays"] = {"Fn::ImportValue": "SomeValue"}
    assert any("Export names are incomplete" in f["reason"] for f in run()["findings"])
    props["RetentionInDays"] = 14
    del storage_doc["Outputs"]
    storage_doc["Resources"]["Bucket"]["Condition"] = "MissingCondition"
    result = run(("s3", "logs"))
    assert result["service_results"]["s3"]["status"] == "FAIL"
    assert result["service_results"]["logs"]["status"] == "PASS"
    del storage_doc["Resources"]["Bucket"]["Condition"]
    assert run(("s3", "logs"))["status"] == "PASS"
    good_resources = storage_doc["Resources"]
    storage_doc["Resources"] = {"Bucket": "invalid resource"}
    result = run()
    assert result["status"] == "FAIL" and result["checked_properties"] == 2
    assert result["stack_findings"][0]["resource_types"] is None
    storage_doc["Resources"] = good_resources
    # Unknown stack coverage stays unverified, but successfully compared values survive.
    del documents[str(storage)]
    result = run()
    assert result["status"] == "FAIL" and result["checked_properties"] == 2
    assert result["stack_findings"][0]["resource_types"] is None
    save(stacks, original_stacks)

    # Alias names resolve locally; the Key's identity and the Alias's parent are both checked.
    key = model("kms", [("DesignKey", "KMS.Key", [("Enabled", "true")]),
                        ("DesignAlias", "KMS.Alias", [("AliasName", "alias/app-dev")])])
    key += "desired.resource.002.parentProperty=KMS.Alias.TargetKeyId\n"
    key += "desired.resource.002.parentReference=[Key](#designkey)\n"
    save(base / "kms.properties", key)
    encryption = "BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID"
    bucket_policy = {"Statement": [{"Effect": "Allow", "Resource": "arn:aws:s3:::app-dev/*"}]}
    bucket = model("s3", [("DesignBucket", "S3.Bucket", [("BucketName", "app-dev"),
                          (encryption, "[alias/app-dev](kms.md#designalias)"), ("PolicyDocument", bucket_policy)])])
    bucket = bucket.replace("property=S3.Bucket.PolicyDocument", "property=S3.BucketPolicy.PolicyDocument")
    save(base / "s3.properties", bucket)
    document = {"Parameters": {"Environment": {"Type": "String"}}, "Resources": {
        "ActualKey": {"Type": "AWS::KMS::Key", "Properties": {"Enabled": True}},
        "ActualAlias": {"Type": "AWS::KMS::Alias", "Properties": {
            "AliasName": {"Fn::Sub": "alias/app-${Environment}"}, "TargetKeyId": {"Ref": "ActualKey"}}},
        "ActualBucket": {"Type": "AWS::S3::Bucket", "Properties": {
            "BucketName": "app-dev", "BucketEncryption": {"ServerSideEncryptionConfiguration": [{
                "ServerSideEncryptionByDefault": {"KMSMasterKeyID": {"Ref": "ActualAlias"}}}]}}},
        "Policy": {"Type": "AWS::S3::BucketPolicy", "Properties": {"Bucket": {"Ref": "ActualBucket"},
            "PolicyDocument": {"Statement": [{"Effect": "Allow", "Resource": {
                "Fn::Sub": "arn:${AWS::Partition}:s3:::${ActualBucket}/*"}}]}}}}}
    documents[str(template)] = document
    result = run(("kms", "s3"))
    assert result["status"] == "PASS" and result["checked_properties"] == 6, result
    assert not result["findings"] and not result["stack_findings"]
    cf = document["Resources"]
    cf["WrongKey"] = {"Type": "AWS::KMS::Key", "Properties": {"Enabled": True}}
    cf["WrongAlias"] = {"Type": "AWS::KMS::Alias", "Properties": {"AliasName": "alias/wrong", "TargetKeyId": {"Ref": "WrongKey"}}}
    cf["ActualBucket"]["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["KMSMasterKeyID"] = "alias/wrong"
    result = run(("kms", "s3"))
    assert result["status"] == "FAIL" and any(f["status"] == "mismatch" and f["property"].endswith("KMSMasterKeyID") for f in result["findings"])
    cf["ActualBucket"]["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["KMSMasterKeyID"] = "alias/app-dev"
    del cf["WrongAlias"], cf["WrongKey"]
    assert run(("kms", "s3"))["status"] == "PASS"  # CFn correction restores agreement.
    cf["ActualBucket"]["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["KMSMasterKeyID"] = "alias/external"
    result = run(("s3",))
    assert result["service_results"]["s3"]["checked_properties"] == 2
    assert any(f["status"] == "unverified" and f.get("actual") == ["alias/external"] for f in result["findings"])
    cf["ActualBucket"]["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["KMSMasterKeyID"] = "alias/app-dev"
    cf["ActualBucket"]["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["KMSMasterKeyID"] = {"Fn::GetAtt": ["ActualKey", "Arn"]}
    assert run(("kms", "s3"))["status"] == "PASS"  # The Alias and its exact target Key identify the same encryption key.
    cf["ActualBucket"]["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["KMSMasterKeyID"] = "alias/app-dev"
    cf["ActualKey"]["Properties"]["Enabled"] = False
    assert any(f["status"] == "mismatch" and f["property"] == "KMS.Key.Enabled" for f in run(("kms",))["findings"])
    cf["ActualKey"]["Properties"]["Enabled"] = True
    assert run(("kms", "s3"))["status"] == "PASS"
    cf["ActualAlias"]["Properties"]["TargetKeyId"] = {"Fn::GetAtt": ["ActualKey", "Arn"]}
    assert run(("kms", "s3"))["status"] == "PASS"  # TargetKeyId accepts the same Key's ID or ARN.
    cf["ActualAlias"]["Properties"]["TargetKeyId"] = {"Ref": "ActualKey"}
    save(base / "kms.properties", key.replace("desired.resource.002.parentReference=[Key](#designkey)\n", ""))
    assert any(f["status"] == "unverified" and "parentReference" in f["reason"] for f in run(("kms",))["findings"])
    save(base / "kms.properties", key)
    cf["OtherKey"] = {"Type": "AWS::KMS::Key", "Properties": {"Enabled": True}}
    save(base / "kms.properties", key.replace("logicalId=DesignKey", "logicalId=ActualKey"))
    cf["ActualAlias"]["Properties"]["TargetKeyId"] = {"Ref": "OtherKey"}
    assert any(f["status"] == "mismatch" and f["property"] == "KMS.Alias.TargetKeyId" for f in run(("kms",))["findings"])
    cf["ActualAlias"]["Properties"]["TargetKeyId"] = {"Ref": "ActualKey"}
    del cf["OtherKey"]
    save(base / "kms.properties", key)
    cf["DuplicateAlias"] = dict(cf["ActualAlias"])
    assert any(f["status"] == "unverified" and "correspondence" in f["reason"] for f in run(("kms",))["findings"])
    del cf["DuplicateAlias"]
    cf["Policy"]["Properties"]["PolicyDocument"] = {"Statement": []}
    assert any(f["status"] == "mismatch" and f["property"] == "S3.BucketPolicy.PolicyDocument" and f["cfn"]["path"].endswith("app.yaml") for f in run(("s3",))["findings"])
    cf["Policy"]["Properties"]["PolicyDocument"] = bucket_policy
    assert run(("kms", "s3"))["status"] == "PASS"
    cf["DuplicatePolicy"] = dict(cf["Policy"])
    assert any(f["status"] == "unverified" and "inline resource correspondence" in f["reason"] for f in run(("s3",))["findings"])
    del cf["DuplicatePolicy"]
    cf["ExtraPolicy"] = {"Type": "AWS::S3::BucketPolicy", "Properties": {"Bucket": "another-bucket", "PolicyDocument": bucket_policy}}
    assert any(f["status"] == "mismatch" and f["resource"] == "ExtraPolicy" for f in run(("s3",))["findings"])
    del cf["ExtraPolicy"]

    comparison = M.Comparison(root, "dev", "blue", ["kms"], lambda path: (documents[path], []))
    comparison.load_stacks()
    assert comparison.resolve({"Condition": {"StringEquals": {"aws:SourceAccount": "123456789012"}}}, "App") == {
        "Condition": {"StringEquals": {"aws:SourceAccount": "123456789012"}}}
    for region, partition in (("ap-northeast-1", "aws"), ("cn-north-1", "aws-cn"), ("us-gov-west-1", "aws-us-gov")):
        comparison.target["awsRegion"] = region
        assert comparison.resolve({"Ref": "AWS::Partition"}, "App") == partition
        assert comparison.resolve({"Fn::Sub": "arn:${AWS::Partition}:kms"}, "App") == "arn:" + partition + ":kms"
    comparison.target["awsRegion"] = "us-iso-east-1"
    try:
        comparison.resolve({"Ref": "AWS::Partition"}, "App")
    except M.Unknown:
        pass
    else:
        raise AssertionError("unknown partition treated as commercial AWS")

    # The Subnet's inline association is selected by its parent, not by child logical ID.
    vpc = model("vpc", [("Net", "EC2.VPC", [("Name", "net-dev")]),
                        ("Subnet", "EC2.Subnet", [("Name", "subnet-dev"), ("VpcId", "[Net](#net)"),
                          ("SubnetRouteTableAssociation.RouteTableId", "[Routes](#routes)")]),
                        ("Routes", "EC2.RouteTable", [("Name", "routes-dev"), ("VpcId", "[Net](#net)")])])
    vpc = vpc.replace("EC2.Subnet.SubnetRouteTableAssociation.", "EC2.SubnetRouteTableAssociation.")
    save(base / "vpc.properties", vpc)
    document["Resources"] = {
        "Net": {"Type": "AWS::EC2::VPC", "Properties": {"Tags": [{"Key": "Name", "Value": "net-dev"}]}},
        "Subnet": {"Type": "AWS::EC2::Subnet", "Properties": {"VpcId": {"Ref": "Net"}, "Tags": [{"Key": "Name", "Value": "subnet-dev"}]}},
        "Routes": {"Type": "AWS::EC2::RouteTable", "Properties": {"VpcId": {"Ref": "Net"}, "Tags": [{"Key": "Name", "Value": "routes-dev"}]}},
        "Association": {"Type": "AWS::EC2::SubnetRouteTableAssociation", "Properties": {"SubnetId": {"Ref": "Subnet"}, "RouteTableId": {"Ref": "Routes"}}}}
    assert run(("vpc",))["status"] == "PASS"
    document["Resources"]["Association"]["Properties"]["RouteTableId"] = {"Ref": "Net"}
    assert any(f["status"] == "mismatch" and f["property"] == "EC2.SubnetRouteTableAssociation.RouteTableId" for f in run(("vpc",))["findings"])
    document["Resources"]["Association"]["Properties"]["RouteTableId"] = {"Ref": "Routes"}
    assert run(("vpc",))["status"] == "PASS"
    document["Parameters"]["CloudTrailHomeRegion"] = {"Type": "String"}
    assert run(("vpc",))["status"] == "FAIL" and any("missing parameter" in f["reason"] for f in run(("vpc",))["stack_findings"])
    save(inputs, '[{"ParameterKey":"Environment","ParameterValue":"dev"},{"ParameterKey":"CloudTrailHomeRegion","ParameterValue":"ap-northeast-1"}]')
    assert run(("vpc",))["status"] == "PASS"

    save(base / "ec2.properties", model("ec2", [("DesignInstance", "EC2.Instance", [
        ("Tags[].Key", "Name"), ("Tags[].Value", "app-dev")])]))
    document["Resources"] = {"ActualInstance": {"Type": "AWS::EC2::Instance", "Properties": {
        "Tags": [{"Key": "Name", "Value": "app-dev"}]}}}
    assert run(("ec2",))["status"] == "PASS"  # Name tag establishes identity despite different logical IDs.
    document["Resources"]["DuplicateInstance"] = dict(document["Resources"]["ActualInstance"])
    assert any(f["status"] == "unverified" and "correspondence" in f["reason"] for f in run(("ec2",))["findings"])

    save(base / "s3.properties", model("s3", [("Bucket", "S3.Bucket", [("BucketName", "app-dev"), ("Region", "ap-northeast-1")])]))
    document["Resources"] = {"Bucket": {"Type": "AWS::S3::Bucket", "Properties": {"BucketName": "app-dev"}}}
    assert run(("s3",))["status"] == "PASS"
    save(base / "s3.properties", model("s3", [("Bucket", "S3.Bucket", [("BucketName", "app-dev"), ("Region", "us-east-1")])]))
    assert any(f["status"] == "mismatch" and f["property"] == "S3.Bucket.Region" for f in run(("s3",))["findings"])

    save(base / "glue.properties", model("glue", [("DesignConnection", "Glue.Connection", [
        ("ConnectionInput.Name", "app-dev"), ("Name", "[Connection](#designconnection)")])]))
    document["Resources"] = {"ActualConnection": {"Type": "AWS::Glue::Connection", "Properties": {"ConnectionInput": {"Name": "app-dev"}}}}
    assert run(("glue",))["status"] == "PASS"  # Generated Name output is not a second configured name.

    # Absence requires complete type coverage, not merely zero matching candidates.
    shutil.rmtree(base / "logs")
    save(base / "logs.properties", model("logs", [("Group", "Logs.LogGroup", rows)]))
    result = run()
    missing = result["findings"][0]
    assert missing["status"] == "mismatch" and missing["coverage"]["complete"], result
    assert missing["expected"]["resource_type"] == "AWS::Logs::LogGroup" and missing["actual"] == []
    assert missing["coverage"]["stacks"][0]["cfn"]["path"].endswith("app.yaml")
    document["Resources"] = {"ActualGroup": {"Type": "AWS::Logs::LogGroup", "Properties": {
        "LogGroupName": "/wrong", "RetentionInDays": 14}}}
    result = run()
    assert result["findings"][0]["expected"]["value"] == "/app/dev"
    assert result["findings"][0]["actual"][0]["value"] == "/wrong"
    actual_group = document["Resources"]["ActualGroup"]
    for name in (None, {"Fn::Unsupported": "unknown"}, "PENDING_DEPLOY"):
        if name is None:
            actual_group["Properties"].pop("LogGroupName")
        else:
            actual_group["Properties"]["LogGroupName"] = name
        assert run()["findings"][0]["status"] == "unverified"
    actual_group["Properties"]["LogGroupName"] = "/app/dev"
    assert run()["status"] == "PASS"  # Correcting CFn restores correspondence and comparison.
    save(base / "logs.properties", model("logs", [("Group", "Logs.LogGroup", [
        ("LogGroupName", "PENDING_DEPLOY")])]))
    assert run()["findings"][0]["status"] == "unverified"
    save(base / "logs.properties", model("logs", [("Group", "Logs.LogGroup", rows)]))
    actual_group["Condition"] = "Disabled"
    document["Conditions"] = {"Disabled": {"Fn::Equals": [1, 2]}}
    assert run()["findings"][0]["status"] == "mismatch"  # A confirmed false Condition means no active resource.
    actual_group["Condition"] = "MissingCondition"
    assert all(f["status"] == "unverified" for f in run()["findings"])
    del actual_group["Condition"]

    save(stacks, original_stacks + "desired.stack.002.name=Storage\ndesired.stack.002.template=storage.yaml\n"
         "desired.stack.002.parameters=storage.json\ndesired.stack.002.deployOrder=2\n")
    storage_doc["Resources"] = {"MaybeGroup": {"Type": "AWS::Logs::LogGroup", "Properties": {"LogGroupName": "/app/dev"}}}
    storage_doc["Parameters"] = {"Missing": {"Type": "String"}}
    documents[str(storage)] = storage_doc
    actual_group["Properties"]["LogGroupName"] = "/wrong"
    assert all(f["status"] == "unverified" for f in run()["findings"])
    # An unrelated known resource type does not prevent proving a LogGroup absence.
    storage_doc["Resources"] = {"Bucket": {"Type": "AWS::S3::Bucket"}}
    assert any(f["status"] == "mismatch" and f.get("coverage", {}).get("complete") for f in run()["findings"])
    del documents[str(storage)]
    assert all(f["status"] == "unverified" for f in run()["findings"])
    save(stacks, original_stacks)

    document["Resources"] = {"Trail": {"Type": "AWS::CloudTrail::Trail", "Properties": {
        "TrailName": "app-dev", "CloudWatchLogsLogGroupArn": "unused"}}}
    result = run(("cloudtrail",))
    assert any(f["status"] == "mismatch" and f["property"].endswith("LogGroupArn") and
               f["expected"]["resource_type"] == "AWS::Logs::LogGroup" for f in result["findings"])

    for directory in ("other", "../blue"):
        try:
            M.Comparison(root, "dev", directory, ["logs"], lambda _: (document, []))
        except M.Unknown:
            pass
        else:
            raise AssertionError("unknown target accepted")

assert not M.equal(True, 1)
assert not M.equal([1], [1, 2])
generated = M.Reference("App", "Key", "Arn")
for left, right in ((generated, "arn:aws:kms:unknown"), ([generated], ["arn:aws:kms:unknown"]),
                    (generated, M.Reference("App", "Key")), ("PENDING_DEPLOY", "PENDING_DEPLOY"),
                    ("PENDING_DEPLOY", "10.10.0.0/23")):
    try:
        M.equal(left, right)
    except M.Unknown:
        pass
    else:
        raise AssertionError("an unresolved comparison was declared equal or unequal")
assert M.equal(generated, generated)
assert not M.equal(generated, M.Reference("App", "OtherKey", "Arn"))
assert not M.equal({"unknown": generated, "known": 1}, {"unknown": "generated", "known": 2})
assert not M.equal({"known": 1, "unknown": generated}, {"known": 2, "unknown": "generated"})
assert M.at_path({"Tags": [{"Key": "A"}, {"Key": "B"}]}, "Tags[].Key") == ["A", "B"]
print("model-cfn: PASS (Partition, Alias/Key identity, grouped resources, CFn correction/recomparison, Name tags, FindInMap, isolation, missing inputs, drift, policy, scope, parts)")
