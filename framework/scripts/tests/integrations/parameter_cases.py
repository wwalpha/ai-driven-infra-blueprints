"""Explicit environment properties retain identities, policy types and reference meanings."""

import json
import os
from functools import partial as _bind_framework_callback
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import support.it_fixture_bundle as _imports_support_it_fixture_bundle
from model.files import trace_model
from model.format import parse, serialize
from model.format import patch as patch_properties
from model.operations import CandidateReads
from model.projection import document_sha256
from model.references import declarations
from model.sources import design_source_digest, list_models, load_model
from support.it_workspace import populate
from support.model_sources import write_model as write_model
from utils.source_reads import FileReads

ROOT = Path(__file__).resolve().parents[4]


def _callback_check_proposed(
    before, fixed, original, other, other_before, path, /, changes, dependencies=None
):
    values = {**before.authoritative, **changes}
    values = {key: value for key, value in values.items() if value is not None}
    text = serialize(values)
    result = load_model(
        before.scope, CandidateReads(FileReads(), {path: text, **(dependencies or {})})
    )
    assert {
        key: value
        for key, value in result.authoritative.items()
        if key.startswith("desired.resource.")
    } == fixed
    assert load_model(other).authoritative == other_before.authoritative
    assert all(p.read_bytes() == raw for p, raw in original.items())
    return result


def check(root, alias, service):
    populate("input_templates", root)
    path = root / "model/preview" / alias / (service + ".properties")
    other = root / "model/prod" / alias / (service + ".properties")
    before, other_before = load_model(path), load_model(other)
    original = {p: p.read_bytes() for p in (root / "model").rglob("*") if p.is_file()}
    assert before.authoritative and not before.warnings
    fixed = {
        key: value
        for key, value in before.authoritative.items()
        if key.startswith("desired.resource.")
    }
    digest = design_source_digest(path)
    for key in before.authoritative:
        trace = trace_model(path, key)
        file = Path(trace["file"])
        assert (
            file in before.files
            and trace["key"] == key
            and trace["value"] == before.authoritative[key]
        )
        assert file.read_text().splitlines()[trace["line"] - 1].startswith(key + "=")
    assert all(not key.endswith(".artifactSha256") for key in before.authoritative)
    assert all(
        not key.startswith("observed.") or key.endswith(".value")
        for key in before.authoritative
    )

    proposed = _bind_framework_callback(
        _callback_check_proposed, before, fixed, original, other, other_before, path
    )

    # Initial values/order survive a serializer round trip and a byte-local no-op.
    assert (
        load_model(
            before.scope,
            CandidateReads(FileReads(), {path: serialize(before.authoritative)}),
        ).authoritative
        == before.authoritative
    )
    assert patch_properties(parse(path.read_text()), {}) == path.read_text()
    (comment,) = [
        key
        for key in before.authoritative
        if key.endswith(".comment") and key.startswith("desired.row.")
    ][:1]
    result = proposed({comment: "更新確認 " + before.authoritative[comment]})
    assert result.authoritative[comment].startswith("更新確認 ")
    if service == "athena":
        producer = path.with_name("s3.properties")
        assert producer in before.dependencies
        (spec,) = declarations(before.authoritative).values()
        assert (
            spec["producerLogicalId"] == "S3_Bucket_001"
            and spec["format"] == "name"
            and spec["property"] == "S3.Bucket.BucketName"
        )
        changed_producer = producer.read_text().replace(
            "fixture-bucket-001-one", "fixture-bucket-001-two"
        )
        stale = proposed({}, {producer: changed_producer})
        assert stale.authoritative == before.authoritative and stale.warnings
        assert stale.dependencies[producer] != before.dependencies[producer]
        assert design_source_digest(path) == digest
        key = spec["consumerKey"]
        after = proposed(
            {
                key: before.authoritative[key].replace("-one", "-two"),
                "desired.reference.result.text": "fixture-bucket-001-two",
            },
            {producer: changed_producer},
        )
        assert (
            not after.warnings and after.authoritative[key] != before.authoritative[key]
        )
    elif service == "sqs":
        (key,) = [key for key in before.authoritative if key.endswith(".document")]
        document = json.loads(before.authoritative[key])
        statement = document["Statement"][0]
        assert (
            isinstance(document["Statement"], list)
            and statement["Action"] == "sqs:SendMessage"
        )
        assert statement["Resource"]["Fn::GetAtt"] == ["HulftRetrievalDetectDlq", "Arn"]
        assert any(
            raw == "[fixture-one](#fixture-sqs-017)"
            for raw in before.authoritative.values()
        )
        assert (
            statement["Condition"]["StringEquals"]["aws:SourceAccount"]
            == "123456789012"
        )
        checksum = key.removesuffix(".document") + ".artifactSha256"
        assert (
            before.values[checksum] == document_sha256(document)
            and checksum not in before.authoritative
        )
        (spec,) = declarations(before.authoritative).values()
        assert (
            spec["producerKind"] == "context"
            and spec["contextProperty"] == "executionAccountId"
        )
        assert (
            spec["pointer"] == "/Statement/0/Condition/StringEquals/aws:SourceAccount"
        )
        project = root / "project.json"
        topology = json.loads(project.read_text())
        topology["targets"][0]["awsExecutionAccountId"] = "999999999999"
        stale = proposed({}, {project: json.dumps(topology)})
        assert stale.authoritative == before.authoritative and stale.warnings
        assert stale.values[checksum] == before.values[checksum]
        changed_document = json.loads(before.authoritative[key])
        changed_document["Statement"][0]["Condition"]["StringEquals"][
            "aws:SourceAccount"
        ] = "999999999999"
        after = proposed(
            {
                key: json.dumps(changed_document),
                "desired.reference.account.text": "999999999999",
            },
            {project: json.dumps(topology)},
        )
        assert not after.warnings and after.values[checksum] != before.values[checksum]
        changed_document["Statement"][0]["Action"] = [
            "sqs:SendMessage",
            "sqs:GetQueueUrl",
        ]
        after = proposed(
            {
                key: json.dumps(changed_document),
                "desired.reference.account.text": "999999999999",
            },
            {project: json.dumps(topology)},
        )
        assert json.loads(after.authoritative[key])["Statement"][0]["Action"] == [
            "sqs:SendMessage",
            "sqs:GetQueueUrl",
        ]
    assert (
        load_model(path).authoritative == before.authoritative
        and design_source_digest(path) == digest
    )
    assert all(p.read_bytes() == raw for p, raw in original.items())


def run(service):
    source = _imports_support_it_fixture_bundle.source
    with patch(__name__ + ".ROOT", source("input_templates")):
        aliases = sorted(
            {scope.target for scope in list_models(ROOT) if scope.service == service}
        )
        assert aliases, "no explicit service fixture cases"
        for alias in aliases:
            with (
                TemporaryDirectory(prefix=service + "-properties-") as directory,
                patch.dict(os.environ, {"BLUEPRINT_TASK_FILE": ""}),
            ):
                check(Path(directory), alias, service)
