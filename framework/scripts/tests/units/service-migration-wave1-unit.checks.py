"""Wave 1 service registrations and the specialized behavior moved with them."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from contracts.model import RESOURCE_MODE_CREATE, RESOURCE_MODE_IMPORT
from services.contracts import ReferenceMode
from services.reference_engine import ReferenceEngine
from services.registry import REGISTRY
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_service_contracts_keep_declared_forms():
    engine = ReferenceEngine()
    assert REGISTRY.owner("AWS::SQS::Queue") == "sqs"
    assert engine.ref_attribute("SQS.Queue") == "QueueUrl"
    assert engine.has_getatt("SQS.Queue", "QueueName")
    assert engine.has_getatt("SQS.Queue", "Arn", ["/properties/Arn"])
    assert not engine.has_getatt("SQS.Queue", "NotDeclared")
    assert engine.arn_attribute("SNS.Topic") == "TopicArn"
    assert engine.model_attribute("SSM.Association", "AssociationId") == "AssociationId"
    assert engine.model_attribute("SSM.Parameter", "Name") == "Name"
    assert REGISTRY.producer("Config.ConfigurationRecorder").return_types == {
        "ResourceARN": "string"
    }

    assert engine.allows(
        "Config.DeliveryChannel",
        "SnsTopicARN",
        "SNS.Topic",
        "Arn",
        mode=ReferenceMode.IMPORT,
    )
    assert (
        engine.receiver_forms(
            "Config.DeliveryChannel",
            "SnsTopicARN",
            mode=ReferenceMode.COMPARISON,
        )
        is None
    )
    forms = engine.receiver_forms(
        "SQS.QueuePolicy",
        "PolicyDocument.Statement[2].Condition.ArnEquals.aws:SourceArn[]",
        mode=ReferenceMode.IMPORT,
    )
    assert forms == {"Events.Rule": ("Arn",)}
    assert engine.allows(
        "SQS.QueuePolicy",
        "PolicyDocument.Statement[2].Condition.ArnEquals.aws:SourceArn[]",
        "Events.Rule",
        "Arn",
        mode=ReferenceMode.IMPORT,
    )
    assert engine.requires_context("DataZone.Connection", "Props.S3Properties.S3Uri")
    assert engine.requires_context(
        "Organizations.Policy", "Content.Statement[1].Resource"
    )
    assert not engine.requires_context(
        "DataZone.Connection", "Props.IamProperties.RoleArn"
    )


def check_guardduty_feature_display_and_restore():
    kind = "GuardDuty.Detector"
    extension = REGISTRY.display(kind)
    formal = [
        ["01", kind + ".Features[].Name", "`S3_DATA_EVENTS`", ""],
        ["02", kind + ".Features[].Status", "`ENABLED`", ""],
    ]
    shown = extension.render_group(
        formal, 0, mode=RESOURCE_MODE_CREATE, counts={}, references=set()
    )
    assert shown.row == [
        "01",
        "GuardDuty.Detector.Features.S3_DATA_EVENTS",
        "`ENABLED`",
        "",
    ]
    assert shown.consumed == ("01", "02")
    names = set()
    restored = extension.restore_group(
        shown.row,
        "Features.S3_DATA_EVENTS",
        mode=RESOURCE_MODE_CREATE,
        counts={},
        names=names,
        verified=False,
    )
    assert restored.rows == [formal[0], ["01", *formal[1][1:]]]
    assert extension.array_template("GuardDuty.Detector.Features.S3_DATA_EVENTS") == (
        "GuardDuty.Detector.Features[].S3_DATA_EVENTS"
    )
    with pytest.raises(ValueError, match="invalid or duplicate GuardDuty Feature"):
        extension.restore_group(
            shown.row,
            "Features.S3_DATA_EVENTS",
            mode=RESOURCE_MODE_CREATE,
            counts={},
            names=names,
            verified=False,
        )


def check_config_role_display_only_uses_literal_rule_in_import():
    kind = "Config.ConfigurationRecorder"
    extension = REGISTRY.display(kind)
    rows = [["01", kind + ".RoleARN", "arn:aws:iam::123456789012:role/team/config", ""]]
    assert extension.display(rows, kind, mode=RESOURCE_MODE_CREATE) == rows
    shown = extension.display(rows, kind, mode=RESOURCE_MODE_IMPORT)
    assert shown[0][1] == "RoleARN"
    assert extension.restore(shown, kind, mode=RESOURCE_MODE_IMPORT) == rows


def check_macie_bucket_display_restores_account_order(tmp_path):
    kind = "Macie.ClassificationJob"
    extension = REGISTRY.display(kind)
    definitions = [
        {"accountId": "222222222222", "buckets": ["first", "second"]},
        {"accountId": "111111111111", "buckets": ["third"]},
    ]
    name, anchor = "job-name", "job-name-anchor"
    path = tmp_path / "macie.md"
    lines = [
        f'<a id="{anchor}"></a>',
        f"### {kind}: {name}",
        *extension.display_document({"bucketDefinitions": definitions}, name, anchor),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert extension.restore_document(path, require_artifact=False) == {
        name: (None, definitions)
    }
    assert extension.display_document({"bucketCriteria": {}}, name, anchor) == []


if __name__ == "__main__":
    raise SystemExit(run(__file__))
