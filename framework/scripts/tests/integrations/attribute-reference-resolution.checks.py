#!/usr/bin/env python3
"""Saved attribute references, reciprocal dependencies and immutable read snapshots."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from model.format import FORMAT, INDEX
from model.sources import source_inputs
from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import (
    FileReads,
    Path,
    affected,
    dependency_hashes,
    design_source_digest,
    json,
    load_model,
    reference,
    rejected,
    resource,
    serialize,
    setup,
    tempfile,
    trace_model,
    warning,
    write_model,
)
from utils.input_cache import input_context, input_scope
from validation_cache import PassCache

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

KINDS = {
    "s3": ("S3.Bucket", "BucketName"),
    "cloudtrail": ("CloudTrail.Trail", "TrailName"),
    "lambda": ("Lambda.Function", "FunctionName"),
    "eventbridge": ("Events.Rule", "Name"),
}


def prepare(root):
    setup(root, [*KINDS, "iam"], [*(kind for kind, _ in KINDS.values()), "IAM.Role"])


def fixture(root, service, other=None, *, derived=False):
    kind, property_name = KINDS[service]
    path = root / "model/preview/team" / (service + ".properties")
    name = (other if derived else service) + "-original"
    values = resource(
        "001", kind, service + "-original", [(property_name, "`" + name + "`")]
    )
    values["desired.note.input.text"] = "`" + service + "-original`"
    if other:
        producer_kind, producer_property = KINDS[other]
        link = f"[{other}-original]({other}.md#{other}-original)"
        values["desired.note.link.text"] = link
        values["desired.row.001-002.property"] = kind + ".Tags"
        values["desired.row.001-002.value"] = "[config](" + service + "/config.json)"
        values["desired.row.001-002.comment"] = "型と配列順序を保持する合成設定"
        key = "desired.row.001-002.document"
        values[key] = json.dumps(
            {
                "name": other + "-original",
                "count": 2,
                "enabled": False,
                "items": ["a", "b"],
            }
        )
        values.update(
            reference(
                "Other",
                "desired.note.link.text",
                link,
                other,
                "001",
                producer_kind,
                mode="link",
                label="display-name",
            )
        )
        values.update(
            reference(
                "OtherName",
                key,
                other + "-original",
                other,
                "001",
                producer_kind,
                prop=producer_kind + "." + producer_property,
                pointer="/name",
            )
        )
        if derived:
            values.update(
                reference(
                    "name",
                    "desired.row.001-001.value",
                    other + "-original",
                    other,
                    "001",
                    producer_kind,
                    prop=producer_kind + "." + producer_property,
                )
            )
    write_model(path, values)
    return path, values


def rejected_read(root, action, phrase):
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    rejected(action, phrase)
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _callback_check_pair_snapshot(_state_check_pair_77, changed, original, root, /):
    pinned = load_model(_state_check_pair_77.consumer)
    write_model(_state_check_pair_77.producer, changed)
    assert load_model(_state_check_pair_77.consumer) is pinned
    assert (
        pinned.dependencies[_state_check_pair_77.producer]
        == serialize(original).encode()
    )
    reads = FileReads()
    reads.read(_state_check_pair_77.producer)
    _state_check_pair_77.producer.write_bytes(
        _state_check_pair_77.producer.read_bytes() + b"# concurrent source\n"
    )
    rejected_read(root, reads.verify, "input changed")


@it_case
def check_pair(root, first, second):
    _state_check_pair_77 = _CallbackState()
    prepare(root)
    _state_check_pair_77.consumer, values = fixture(root, first, second)
    _state_check_pair_77.producer, original = fixture(root, second, first)
    loaded = load_model(_state_check_pair_77.consumer)
    assert not loaded.warnings, loaded.warnings
    assert (
        loaded.authoritative["desired.note.link.text"]
        == f"[{second}-original]({second}.md#{second}-original)"
    )
    key = "desired.row.001-002.document"
    config = json.loads(loaded.authoritative[key])
    assert config == {
        "name": second + "-original",
        "count": 2,
        "enabled": False,
        "items": ["a", "b"],
    }
    assert type(config["count"]) is int and type(config["enabled"]) is bool
    assert (
        load_model(_state_check_pair_77.producer).authoritative[
            "desired.row.001-001.value"
        ]
        == "`" + second + "-original`"
    )
    assert _state_check_pair_77.producer in loaded.dependencies
    digest, dependencies = (
        design_source_digest(_state_check_pair_77.consumer),
        dependency_hashes(_state_check_pair_77.consumer),
    )
    changed = {**original, "desired.row.001-001.value": "`" + second + "-changed`"}
    write_model(_state_check_pair_77.producer, changed)
    assert (
        warning(_state_check_pair_77.consumer, "differs").authoritative
        == loaded.authoritative
    )
    assert (
        design_source_digest(_state_check_pair_77.consumer) == digest
        and dependency_hashes(_state_check_pair_77.consumer) != dependencies
    )
    assert ("preview", "team", first) in affected(
        root, [_state_check_pair_77.producer.relative_to(root)]
    )
    assert (
        trace_model(_state_check_pair_77.consumer, key)["references"]["OtherName"][
            "producerScope"
        ]
        == "preview/team/" + second
    )
    write_model(_state_check_pair_77.producer, original)
    assert (
        dependency_hashes(_state_check_pair_77.consumer) == dependencies
        and load_model(_state_check_pair_77.consumer).authoritative
        == loaded.authoritative
    )
    snapshot = (input_scope)(
        _bind_framework_callback(
            _callback_check_pair_snapshot, _state_check_pair_77, changed, original, root
        )
    )
    with input_context(read_only=True):
        snapshot()
    write_model(_state_check_pair_77.producer, original)
    # Reciprocal saved names have no evaluator and never recurse or rewrite either side.
    _state_check_pair_77.consumer, reciprocal = fixture(
        root, first, second, derived=True
    )
    _state_check_pair_77.producer, reverse = fixture(root, second, first, derived=True)
    before = {
        p: p.read_bytes()
        for p in (_state_check_pair_77.consumer, _state_check_pair_77.producer)
    }
    assert load_model(_state_check_pair_77.consumer).authoritative == reciprocal
    assert load_model(_state_check_pair_77.producer).authoritative == reverse
    assert before == {
        p: p.read_bytes()
        for p in (_state_check_pair_77.consumer, _state_check_pair_77.producer)
    }


@it_case
def check_fixed_label(root):
    prepare(root)
    consumer, values = fixture(root, "s3", "cloudtrail")
    producer, original = fixture(root, "cloudtrail", "s3")
    values = {
        key: value
        for key, value in values.items()
        if not key.startswith("desired.reference.OtherName.")
    }
    values["desired.note.link.text"] = (
        "[cloudtrail-original](cloudtrail.md#cloudtrail-original)"
    )
    values["desired.reference.Other.text"] = values["desired.note.link.text"]
    values["desired.reference.Other.labelPolicy"] = "fixed"
    write_model(consumer, values)
    write_model(
        producer,
        {
            **original,
            "desired.row.001-001.property": "CloudTrail.Trail.Tags[].Value",
            "desired.row.001-001.value": "[s3-original](s3.md#s3-original)",
        },
    )
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    loaded = load_model(consumer)
    assert not loaded.warnings, loaded.warnings
    assert (
        loaded.authoritative["desired.note.link.text"]
        == "[cloudtrail-original](cloudtrail.md#cloudtrail-original)"
    )
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    dependencies = dependency_hashes(consumer)
    producer.write_bytes(producer.read_bytes() + b"# annotation\n")
    assert (
        load_model(consumer).authoritative == loaded.authoritative
        and dependency_hashes(consumer) != dependencies
    )
    assert ("preview", "team", "s3") in affected(root, [producer.relative_to(root)])
    assert (
        trace_model(consumer, "desired.note.link.text")["references"]["Other"][
            "labelPolicy"
        ]
        == "fixed"
    )
    write_model(
        consumer, {**values, "desired.reference.Other.labelPolicy": "display-name"}
    )
    assert not load_model(consumer).warnings


def fixture_stack(root):
    path = root / "model/preview/team/cloudformation-stacks.properties"
    values = {
        "desired.stack.001.name": "cfn-stack-app-preview-original",
        "desired.stack.001.placementName": "fixed-original",
        "desired.stack.001.template": "network.yaml",
        "desired.stack.001.parameters": "network.json",
        "desired.stack.001.deployOrder": "10",
        "display.stack.001.comment": "-original",
    }
    write_model(path, values)
    return path, values


@it_case
def check_stack(root):
    prepare(root)
    consumer, values = fixture(root, "s3")
    producer, original = fixture_stack(root)
    key = "desired.row.001-002.document"
    values.update(
        {
            "desired.row.001-002.property": "S3.Bucket.PolicyDocument",
            "desired.row.001-002.value": "[permission](s3/permission.json)",
            "desired.row.001-002.comment": "Stack参照",
            key: json.dumps(
                {
                    "Resource": "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/cfn-stack-app-preview-original/*"
                }
            ),
        }
    )
    fields = {
        "consumerKey": key,
        "pointer": "/Resource",
        "text": "cfn-stack-app-preview-original",
        "occurrence": "1",
        "producerKind": "stack",
        "producerScope": "preview/team/cloudformation-stacks",
        "producerId": "001",
        "format": "name",
        "property": "name",
        "labelPolicy": "none",
    }
    values.update(
        {
            "desired.reference.StackName." + field: value
            for field, value in fields.items()
        }
    )
    write_model(consumer, values)
    loaded = load_model(consumer)
    assert not loaded.warnings, loaded.warnings
    assert json.loads(loaded.authoritative[key])["Resource"].endswith(
        "/cfn-stack-app-preview-original/*"
    )
    digest, dependencies = design_source_digest(consumer), dependency_hashes(consumer)
    write_model(
        producer,
        {**original, "desired.stack.001.name": "cfn-stack-app-preview-changed"},
    )
    assert warning(consumer, "Stack name differs").authoritative == loaded.authoritative
    assert (
        design_source_digest(consumer) == digest
        and dependency_hashes(consumer) != dependencies
    )
    assert ("preview", "team", "s3") in affected(root, [producer.relative_to(root)])
    assert (
        trace_model(consumer, key)["references"]["StackName"]["producerKind"] == "stack"
    )
    write_model(producer, original)
    reads = FileReads()
    pinned = load_model(consumer, reads)
    write_model(producer, {**original, "desired.stack.001.name": "changed"})
    assert (
        load_model(consumer, reads) is pinned
        and pinned.dependencies[producer] == serialize(original).encode()
    )
    rejected_read(root, reads.verify, "input changed")
    write_model(producer, original)
    # A Stack name that contains a saved Resource reference remains an explicit string.
    reverse = {**original, "desired.stack.001.name": "s3-original"}
    reverse.update(
        reference(
            "bucket",
            "desired.stack.001.name",
            "s3-original",
            "s3",
            "001",
            "S3.Bucket",
            prop="S3.Bucket.BucketName",
        )
    )
    write_model(producer, reverse)
    assert load_model(consumer).authoritative == values
    assert load_model(producer).authoritative == reverse
    producer.unlink()
    warning(consumer, "Model is absent")


@it_case
def check():
    check_producer_inputs()
    with tempfile.TemporaryDirectory() as directory:
        check_stack(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        check_fixed_label(Path(directory))
    for pair in [("s3", "cloudtrail"), ("lambda", "eventbridge")]:
        with tempfile.TemporaryDirectory() as directory:
            check_pair(Path(directory), *pair)
    print(
        "Attribute references: PASS (reciprocal saved values; exact JSON; Stack fixed placement; warnings; read-only failures; immutable snapshots/cache)"
    )


@it_case
def check_producer_inputs():
    with (
        tempfile.TemporaryDirectory() as temporary,
        tempfile.TemporaryDirectory() as directory,
    ):
        root = Path(temporary).resolve()
        setup(
            root,
            ("lambda", "eventbridge", "cloudtrail", "sqs"),
            ("Lambda.Function", "Events.Rule", "CloudTrail.Trail", "SQS.Queue"),
            environments=("preview", "release"),
        )
        paths = {}
        for environment in ("preview", "release"):
            for service, kind in (
                ("lambda", "Lambda.Function"),
                ("eventbridge", "Events.Rule"),
                ("cloudtrail", "CloudTrail.Trail"),
                ("sqs", "SQS.Queue"),
            ):
                path = root / "model" / environment / "team" / (service + ".properties")
                prop = (
                    "FunctionName"
                    if service == "lambda"
                    else "QueueName"
                    if service == "sqs"
                    else "Name"
                )
                values = resource(
                    "001", kind, service + "-fixture", [(prop, "`fixture`")]
                )
                if service in ("eventbridge", "cloudtrail"):
                    key = "desired.row.001-002.document"
                    text = "[Function](lambda.md#lambda-fixture)"
                    values.update(
                        {
                            "desired.row.001-002.property": kind + ".Target",
                            "desired.row.001-002.comment": "保存済み参照",
                            "desired.row.001-002.value": "`document`",
                            key: '{"Target":"'
                            + text
                            + '","Enabled":false,"Count":1,"Order":["b","a"]}',
                        }
                    )
                    values.update(
                        reference(
                            "target",
                            key,
                            text,
                            "lambda",
                            "001",
                            "Lambda.Function",
                            mode="link",
                            pointer="/Target",
                            environment=environment,
                            label="fixed",
                        )
                    )
                write_model(path, values)
                doc = root / "docs/designs" / environment / "team" / (service + ".md")
                doc.parent.mkdir(parents=True, exist_ok=True)
                doc.write_text("fixture\n")
                paths[environment, "team", service] = path
        producer = paths["preview", "team", "lambda"]
        part = producer.with_suffix("") / "part-001.properties"
        part.parent.mkdir()
        part.write_bytes(producer.read_bytes())
        producer.write_text(
            FORMAT + "\n" + INDEX + "\n# part: lambda/part-001.properties\n"
        )
        cache = PassCache(root, directory=directory)
        before = {entry: cache.service_key(entry) for entry in paths}
        values = {entry: load_model(path).values for entry, path in paths.items()}
        digests = {entry: design_source_digest(path) for entry, path in paths.items()}
        inputs = source_inputs(producer)
        assert part in inputs
        assert inputs <= source_inputs(paths["preview", "team", "eventbridge"])
        for source in sorted(inputs):
            original = source.read_bytes()
            try:
                source.write_bytes(original + b"\n")
                for entry, path in paths.items():
                    changed = (
                        source == root / "project.json"
                        or entry[2] != "sqs"
                        and entry[0] == "preview"
                    )
                    assert (cache.service_key(entry) != before[entry]) == changed, (
                        source,
                        entry,
                    )
                    assert design_source_digest(path) == digests[entry], (source, entry)
                    assert load_model(path).values == values[entry], (source, entry)
            finally:
                source.write_bytes(original)
        assert {entry: cache.service_key(entry) for entry in paths} == before


if __name__ == "__main__":
    check()
