#!/usr/bin/env python3
"""Environment properties, fixed references and derived fields over synthetic sources."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import io
import json
from contextlib import redirect_stdout

import support.model_parameter_inputs_fixtures as _exports_support_model_parameter_inputs_fixtures
import sync_runtime
from model.files import trace_model
from model.format import serialize
from model.operations import CandidateReads
from model import dependency_index
from model.references import incoming
from model.references import usages as usages
from model.sources import design_source_digest, load_model
from support.import_model_fixtures import (
    reference_fields,
    resource_values,
    service_values,
)
from support.model_parameter_inputs_fixtures import fixture as fixture
from support.model_sources import write_model
from support.service_fixtures import authored_service, topology
from utils.source_reads import FileReads

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

# Preserve shared fixtures and compatibility exports under their historical names.
root = _exports_support_model_parameter_inputs_fixtures.root


def check_human(root):
    environments, paths = fixture(root)
    before = {env: load_model(path) for env, path in paths.items()}
    original = {p: p.read_bytes() for p in (root / "model").rglob("*") if p.is_file()}
    for env in environments:
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, env, "team", services=["vpc"]) == 0
    views = {
        p: p.read_bytes() for p in (root / "docs/designs").rglob("*") if p.is_file()
    }
    for env in environments:
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, env, "team", services=["vpc"]) == 0
            assert sync_runtime.sync(root, False, env, "team", services=["vpc"]) == 0
    assert all(p.read_bytes() == raw for p, raw in {**original, **views}.items())
    snapshot = before["preview"]
    values = dict(snapshot.authoritative)
    values["desired.row.017-002.value"] = "`10.11.0.0/23`"
    after = load_model(
        snapshot.scope,
        CandidateReads(FileReads(), {paths["preview"]: serialize(values)}),
    )
    assert {
        key
        for key in snapshot.authoritative
        if snapshot.authoritative[key] != after.authoritative[key]
    } == {"desired.row.017-002.value"}
    assert load_model(paths["prod"]).authoritative == before["prod"].authoritative
    for field in ("logicalId", "resourceMode", "resourceType"):
        assert (
            after.authoritative["desired.resource.017." + field]
            == snapshot.authoritative["desired.resource.017." + field]
        )
    key = "desired.row.017-001.value"
    trace = trace_model(paths["preview"], key)
    assert (
        trace["file"] == str(paths["preview"])
        and trace["value"] == snapshot.authoritative[key]
    )
    assert root / "project.json" in snapshot.dependencies
    assert all(p.read_bytes() == raw for p, raw in original.items())


def check_kms_alias(root):
    fixture(root)
    producer = root / "model/preview/team/kms.properties"
    values = service_values("kms", ["KMS.Key", "KMS.Alias"])
    values.update(
        resource_values(
            "011",
            "KMS.Key",
            "kms-material-key",
            "CREATE",
            [("KeyId", "[KMS_Key_011](kms.md#kms-material-key)")],
        )
    )
    values.update(
        resource_values(
            "012",
            "KMS.Alias",
            "kms-alias-app-preview-material-one",
            "CREATE",
            [
                ("AliasName", "`alias/app-preview-material-one`"),
                ("TargetKeyId", "[KMS_Key_011](kms.md#kms-material-key)"),
            ],
        )
    )
    values["desired.resource.012.parentProperty"] = "KMS.Alias.TargetKeyId"
    values["desired.resource.012.parentReference"] = (
        "[KMS_Key_011](kms.md#kms-material-key)"
    )
    values["desired.service.identity.lastAllocated"] = json.dumps(
        {"KMS.Key": 11, "KMS.Alias": 12}
    )
    write_model(producer, values)
    path = producer.with_name("codecommit.properties")
    link = "[KMS_Alias_012](kms.md#kms-alias-app-preview-material-one)"
    consumer = service_values("codecommit", ["CodeCommit.Repository"])
    consumer.update(
        resource_values(
            "021",
            "CodeCommit.Repository",
            "codecommit-repository",
            "CREATE",
            [
                ("KmsKeyId", link),
                ("RepositoryDescription", "alias/app-preview-material-one"),
            ],
        )
    )
    consumer.update(
        reference_fields(
            "link",
            "desired.row.021-001.value",
            link,
            "preview/team/kms/012",
            kind="KMS.Alias",
            mode="link",
        )
    )
    consumer["desired.reference.link.labelPolicy"] = "display-name"
    consumer.update(
        reference_fields(
            "raw-name",
            "desired.row.021-002.value",
            "alias/app-preview-material-one",
            "preview/team/kms/012",
            kind="KMS.Alias",
            prop="KMS.Alias.AliasName",
        )
    )
    write_model(path, consumer)
    before = load_model(path)
    assert not before.warnings and producer in before.dependencies
    assert before.authoritative["desired.row.021-001.value"] == link
    saved, digest = path.read_bytes(), design_source_digest(path)
    for changed in (producer.read_text().replace("material-one", "material-two"),):
        after = load_model(path, CandidateReads(FileReads(), {producer: changed}))
        assert after.authoritative == before.authoritative and after.warnings
    assert path.read_bytes() == saved and design_source_digest(path) == digest


def check_external_instances(root):
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": env,
                        "alias": "team",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                    for env in ("dev", "stg")
                ]
            }
        )
    )
    consumers = {}
    for env, rid in [("dev", "017"), ("stg", "083")]:
        name, kind = "secret-" + env, "SecretsManager.Secret"
        producer = root / "model" / env / "team/secrets-manager.properties"
        values = service_values("secrets-manager", [kind])
        values.update(
            resource_values(
                rid, kind, "secret-" + rid, "CREATE", [("Name", "`" + name + "`")]
            )
        )
        write_model(producer, values)
        consumer = service_values("quicksight", ["QuickSight.DataSource"])
        consumer.update(
            resource_values(
                "001",
                "QuickSight.DataSource",
                "quicksight-source",
                "CREATE",
                [
                    ("Name", "`" + name + "`"),
                    (
                        "Credentials.CredentialPair.Password",
                        "`{{resolve:secretsmanager:" + name + ":SecretString:token}}`",
                    ),
                ],
            )
        )
        for identity, key in [
            ("name", "desired.row.001-001.value"),
            ("password", "desired.row.001-002.value"),
        ]:
            consumer.update(
                reference_fields(
                    identity,
                    key,
                    name,
                    env + "/team/secrets-manager/" + rid,
                    kind=kind,
                    prop=kind + ".Name",
                )
            )
        path = producer.with_name("quicksight.properties")
        write_model(path, consumer)
        snapshot = load_model(path)
        assert not snapshot.warnings and producer in snapshot.dependencies
        dependency_index.rebuild(root)
        assert len(incoming(load_model(producer), rid)) == 2
        assert (
            snapshot.authoritative["desired.reference.name.producerLogicalId"]
            == "SecretsManager_Secret_" + rid
        )
        consumers[env] = (path, snapshot, producer)
    path, before, producer = consumers["dev"]
    changed = producer.read_text().replace("secret-dev", "secret-dev-updated")
    after = load_model(path, CandidateReads(FileReads(), {producer: changed}))
    assert after.authoritative == before.authoritative and after.warnings
    assert (
        load_model(consumers["stg"][0]).authoritative
        == consumers["stg"][1].authoritative
    )


def check_service_contracts(tmp_path):
    topology(tmp_path, ("dev",))
    producers = [
        ("lambda", "Lambda.Function", "FunctionName", "fixture"),
        ("glue", "Glue.Job", "Name", "fixture-job"),
        ("iam", "IAM.Role", "RoleName", "fixture-role"),
        ("codebuild", "CodeBuild.Project", "Name", "fixture"),
        ("mwaa", "MWAA.Environment", "Name", "fixture"),
        ("cloudtrail", "CloudTrail.Trail", "TrailName", "fixture"),
    ]
    values = service_values("cloudwatch-logs", ["Logs.LogGroup"])
    values.update(
        resource_values(
            "001", "Logs.LogGroup", "logs", "CREATE", [("LogGroupName", "`fixture`")]
        )
    )
    for service, kind, prop, name in producers:
        authored_service(
            tmp_path,
            "dev",
            service,
            [("001", kind, service, [(prop, "`" + name + "`")])],
        )
        key = "desired.note." + service + ".text"
        values[key] = name
        values.update(
            reference_fields(
                service,
                key,
                name,
                "dev/team/" + service + "/001",
                kind=kind,
                prop=kind + "." + prop,
            )
        )
    path = tmp_path / "model/dev/team/cloudwatch-logs.properties"
    write_model(path, values)
    before = load_model(path)
    assert not before.warnings
    for service, _, _, _ in producers:
        producer = path.with_name(service + ".properties")
        original = producer.read_bytes()
        producer.write_bytes(original.replace(b"value=`", b"value=`changed-", 1))
        after = load_model(path, FileReads())
        assert after.authoritative == before.authoritative and after.warnings
        producer.write_bytes(original)
    assert path.read_bytes() == serialize(before.authoritative).encode("utf-8")


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__, message="Explicit environment properties: PASS"))
