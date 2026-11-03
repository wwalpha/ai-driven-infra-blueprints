"""Offline Glue audit projection, formal references and redacted standalone output."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aws_mapping_compare import comparison
from support.model_sources import write_model
from support.model_test_references import ReferenceFixture
from support.model_test_runner import CLI, generated, load_fixture, snapshot
from support.pytest_cli import run

from model import audit as generator

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


SECRET_ARN = "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:fixture-AbCd12"
SECRET_PROP = "Glue.Connection.ConnectionInput.AuthenticationConfiguration.SecretArn"
ATHENA_PROP = "Glue.Connection.ConnectionInput.AthenaProperties"


def glue_snapshot(root, observed=SECRET_ARN, attribute="Arn"):
    project = load_fixture("audit/base")[0]["project"]
    (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    consumer = ReferenceFixture.model(
        "Glue.Connection",
        "Glue_Connection_001",
        {
            "CatalogId": "123456789012",
            "ConnectionInput.Name": "fixture-connection",
            "ConnectionInput.ConnectionType": "JDBC",
            "ConnectionInput.AthenaProperties": {"workgroup": "primary"},
            "ConnectionInput.AuthenticationConfiguration.SecretArn": ReferenceFixture.ref(
                "SecretsManager_Secret_001", attribute
            ),
        },
    )
    producer = ReferenceFixture.model(
        "SecretsManager.Secret",
        "SecretsManager_Secret_001",
        {
            "Name": "fixture",
            "Id": ReferenceFixture.ref("SecretsManager_Secret_001", "Id"),
        },
    )
    if observed is not None:
        producer["observed.row.001-002.value"] = "`" + observed + "`"
    write_model(root / "model/dev/cde/glue.properties", consumer)
    write_model(root / "model/dev/cde/secrets-manager.properties", producer)
    before = {p: p.read_bytes() for p in (root / "model").rglob("*.properties")}
    # Any attempted subprocess during generation is a test failure, including AWS CLI.
    with patch("subprocess.run", side_effect=AssertionError("offline generation")):
        source, _, _ = generator.generate(root, "dev", "cde", "glue")
    embedded = snapshot(source)
    assert {p: p.read_bytes() for p in before} == before
    assert "dev/cde/secrets-manager" not in embedded["models"]
    return source, embedded


def glue_cli(athena=None, secret=SECRET_ARN):
    connection = {
        "Name": "fixture-connection",
        "ConnectionType": "JDBC",
        "AuthenticationConfiguration": {"SecretArn": secret},
        "ConnectionProperties": {"PASSWORD": "secret-value-never-print"},
    }
    if athena is not None:
        connection["AthenaProperties"] = athena
    return CLI({("glue", "get-connection"): {"Connection": connection}})


@pytest.mark.parametrize("attribute", ["Arn", "Id"])
def test_glue_confirmed_secret_reference(tmp_path, attribute):
    source, snapshot = glue_snapshot(tmp_path, attribute=attribute)
    row = snapshot["referenceRows"]["dev/cde/glue"]["001-005"]
    assert (row["status"], row["value"]) == ("resolved", SECRET_ARN)
    namespace = generated(source, tmp_path)
    cli = glue_cli({"workgroup": "primary"})
    _, _, records = namespace["audit"](snapshot, None, cli)
    assert {r["propertiesKey"]: r["status"] for r in records} == {
        "Glue.Connection.CatalogId": "match",
        "Glue.Connection.ConnectionInput.Name": "match",
        "Glue.Connection.ConnectionInput.ConnectionType": "match",
        ATHENA_PROP: "match",
        SECRET_PROP: "match",
    }
    assert [(api, args) for api, args, _ in cli.calls] == [
        (("sts", "get-caller-identity"), {}),
        (
            ("glue", "get-connection"),
            {
                "CatalogId": "123456789012",
                "Name": "fixture-connection",
                "HidePassword": True,
            },
        ),
    ]


@pytest.mark.parametrize(
    "observed, status",
    [
        (None, "logical_only"),
        ("PENDING_DEPLOY", "pending_deploy"),
        ("not-an-arn", "unresolved"),
    ],
)
def test_glue_unconfirmed_secret_remains_error(tmp_path, observed, status):
    source, snapshot = glue_snapshot(tmp_path, observed)
    row = snapshot["referenceRows"]["dev/cde/glue"]["001-005"]
    assert row["status"] == status
    assert row["value"] is None
    namespace = generated(source, tmp_path)
    cli = glue_cli({"workgroup": "primary"})
    _, _, records = namespace["audit"](snapshot, None, cli)
    item = next(r for r in records if r["propertiesKey"] == SECRET_PROP)
    assert item["status"] == "design_unresolved"
    assert "Design reference unresolved" in item["reason"]
    assert {api for api, _, _ in cli.calls} <= {
        ("sts", "get-caller-identity"),
        ("glue", "get-connection"),
    }


@pytest.mark.parametrize(
    "athena, status",
    [
        ({"workgroup": "primary"}, "match"),
        ({"workgroup": "other"}, "difference"),
        ({}, "difference"),
        (None, "difference"),
    ],
)
def test_glue_athena_sdk_projection(tmp_path, athena, status):
    source, snapshot = glue_snapshot(tmp_path)
    field = snapshot["mappings"]["glue"]["properties"][ATHENA_PROP]["field"]
    assert (field["getter"], field["path"], field["classification"]) == (
        "base",
        "AthenaProperties",
        "supported",
    )
    # Ordinary Compare and the immutable catalog keep their original classification.
    original = comparison(generator.ROOT, "glue")[1][ATHENA_PROP].field
    assert original.classification == "sdk_unavailable"
    assert "cloudcontrol.get_resource" in original.reason
    namespace = generated(source, tmp_path)
    _, _, records = namespace["audit"](snapshot, None, glue_cli(athena))
    item = next(r for r in records if r["propertiesKey"] == ATHENA_PROP)
    assert item["status"] == status


def test_glue_projection_requires_sdk_shape(tmp_path):
    original = generator._imports_aws_mapping.response_shape

    def unavailable(shape, path):
        if path == "Connection.AthenaProperties":
            raise ValueError("unknown SDK response path: " + path)
        return original(shape, path)

    with patch.object(generator._imports_aws_mapping, "response_shape", unavailable):
        with pytest.raises(ValueError, match="Connection.AthenaProperties"):
            glue_snapshot(tmp_path)


@pytest.mark.parametrize(
    "observed, secret, code",
    [
        (SECRET_ARN, SECRET_ARN, 0),
        (SECRET_ARN, SECRET_ARN + "-different", 1),
        (None, SECRET_ARN, 2),
        ("PENDING_DEPLOY", SECRET_ARN, 1),  # Explicit pending state follows report policy.
        ("not-an-arn", SECRET_ARN, 2),
    ],
)
def test_glue_standalone_redacts_console_and_log(
    tmp_path, capsys, observed, secret, code
):
    source, _ = glue_snapshot(tmp_path, observed)
    namespace = generated(source, tmp_path)
    script = tmp_path / "tests/dev/cde/glue.py"
    cli = glue_cli({"workgroup": "primary"}, secret)
    assert namespace["main"]([], cli_runner=cli, script_path=script) == code
    text = capsys.readouterr().out
    logs = list((tmp_path / "tests/results/dev/cde").glob("glue-*.log"))
    assert len(logs) == 1
    assert logs[0].read_text(encoding="utf-8") == text
    assert "[REDACTED]" in text
    for private in (SECRET_ARN, secret, "secret-value-never-print"):
        assert private not in text


if __name__ == "__main__":
    raise SystemExit(run(__file__))
