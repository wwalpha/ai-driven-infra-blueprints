#!/usr/bin/env python3
"""Acquisition/source validation units; all Models and AWS facts below are synthetic."""

import hashlib
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from functools import partial as _bind_framework_callback
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
from types import SimpleNamespace
from unittest.mock import patch

import import_guard
import model.dependency_index as dependency_index
import model.format as _imports_model_format
import model.sources as _imports_model_sources
import pytest
import support.import_model_fixtures as _imports_support_import_model_fixtures
import support.model_sources as _imports_support_model_sources
import support.repository_fixtures as _imports_support_repository_fixtures
import task_contract_core as _imports_task_contract
from aws_mapping import readonly
from aws_mapping_compare import comparison
from aws_mapping_compare import value as mapped_value
from generation_inputs import GenerationInputs
from model.adapters.task import edit_write_context, source_write_context
from model.cli import main
from model.format import owner, serialize
from model.identity import COUNTERS
from model.importing import cli as m
from model.importing import inventory as import_inventory
from model.importing.evidence import FORMAT_FIELDS
from model.importing.inventory import (
    ImportInventory,
    import_comparison,
    inventory_for,
    properties_json,
)
from model.importing.sources import (
    property_values,
    selection_records,
    typed_equal,
    typed_row,
    verify_values,
)
from model.operations import (
    CandidateReads,
    operation_rows,
    operation_values,
    prepare_edit,
    publish_edit,
    validate_candidates,
    verify_model_operation,
    verify_model_refactor,
)
from model.projection import resource_rows
from model.references import Reference, incoming, symbolic, usages
from model.sources import Scope, candidate_sources, load_model
from support.import_model_fixtures import (
    ACCOUNT,
    SERVICES,
    AwsCli,
    CloudControlCli,
    aws,
    batch_operation_fixture,
    build_seed,
    dependency_contract,
    dependency_fixture,
    dependency_refactor,
    operation_candidate,
    operation_contract,
    operation_fixture,
    project_fixture,
    reference_fields,
    resource_values,
    review_proof_fixture,
)
from support.model_sources import write_model
from support.model_v2_fixtures import value_snapshot as Expansion
from task_contract import complete
from task_contract_core import model_operation, model_refactor, selected_task
from utils import sealed_evidence
from utils.input_cache import input_context
from utils.json_format import document_sha256
from utils.script_loader import module as module
from utils.source_reads import FileReads
from utils.yaml_format import yaml_read as yaml_read

from model import sources

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def schema_for(prop):
    return {
        "type": "boolean"
        if prop.endswith("EnableDnsSupport")
        else "integer"
        if prop.endswith("RetentionInDays")
        else "string"
    }


def resource(
    number="001",
    kind="EC2.VPC",
    identity="vpc-confirmed",
    cidr="10.10.0.0/23",
    mode="IMPORT",
):
    values = {
        f"desired.resource.{number}.resourceType": kind,
        f"desired.resource.{number}.anchor": "vpc-" + number,
        f"desired.resource.{number}.resourceMode": mode,
        f"desired.resource.{number}.logicalId": kind.replace(".", "_")
        + ("_001" if number == "001" else "_002"),
        "desired.service.identity.lastAllocated": json.dumps(
            {kind: 1 if number == "001" else 2}
        ),
    }
    for n, (prop, value) in enumerate(
        [
            ("VpcId", f"[vpc](vpc.md#vpc-{number})"),
            ("CidrBlock", "`" + cidr + "`"),
            ("Name", "`main-vpc`"),
        ],
        1,
    ):
        key = f"desired.row.{number}-{n:03d}."
        values.update(
            {
                key + "property": kind + "." + prop,
                key + "value": value,
                key + "comment": "合成入力",
            }
        )
    if identity:
        values[f"observed.row.{number}-001.value"] = "`" + identity + "`"
    return values


def record(identity="vpc-confirmed", cidr="10.11.0.0/23", record_id="record-1"):
    return {
        "record": record_id,
        "kind": "EC2.VPC",
        "identity": identity,
        "identityProperty": "EC2.VPC.VpcId",
        "properties": {
            key: {"status": "captured", "value": value}
            for key, value in [
                ("EC2.VPC.VpcId", identity),
                ("EC2.VPC.CidrBlock", cidr),
                ("EC2.VPC.Name", "main-vpc"),
            ]
        },
    }


def selection(record_id="record-1", rid="001", action="add", basis=()):
    return {
        "resources": [
            {
                "record": record_id,
                "resource": rid,
                "action": action,
                "reason": "合成projectで管理範囲を確認したfixture",
                "basis": list(basis),
            }
        ],
        "excluded": [],
        "unreflected": [],
    }


def expansion(values):
    result = Expansion(values, {}, {})
    result.scope = Scope(Path("/fixture"), "dev", "cde", "vpc")
    return result


def check_null_parameter():
    assert (
        typed_row({"property": "Example.Resource.Value"}, "`null`", {"type": "null"})
        is None
    )
    assert m.model_literal(None) == "`null`"


@pytest.mark.parametrize(
    "value",
    [False, 0, "false", "001", None, ["one", "two"], {"Enabled": False, "Count": 2}],
)
def check_yaml_edits(value):
    FORMAT = _imports_model_format.FORMAT
    parse = _imports_model_format.parse
    patch = _imports_model_format.patch
    original = (
        FORMAT
        + '\n# keep header\ndesired.row.001-001.value="10.10.0.0/23" # keep CIDR\n# keep comment\ndesired.row.001-002.value=old\n'
    )
    raw = m.model_literal(value)
    edited = patch(
        parse(original),
        {"desired.row.001-002.value": raw, "desired.row.009-001.value": "new-subnet"},
    )
    assert parse(edited).values == {
        **parse(original).values,
        "desired.row.001-002.value": raw,
        "desired.row.009-001.value": "new-subnet",
    }
    assert "# keep header\n" in edited and "# keep comment\n" in edited
    assert 'desired.row.001-001.value="10.10.0.0/23" # keep CIDR' in edited
    assert patch(parse(edited), {"desired.row.001-002.value": raw}) == edited


def check_yaml_empty_and_order():
    FORMAT = _imports_model_format.FORMAT
    parse = _imports_model_format.parse
    patch = _imports_model_format.patch
    assert (
        patch(parse(FORMAT + "\n"), {"desired.row.001-001.value": "`true`"})
        == FORMAT + "\ndesired.row.001-001.value=`true`\n"
    )
    original = (
        FORMAT
        + "\n# unchanged\ndesired.row.001-002.value=2\ndesired.row.001-001.value=1\n"
    )
    assert patch(parse(original), dict(parse(original).values)) == original


@pytest.mark.parametrize("alias", [False, True])
def check_physical_identity_wins_over_mutable_settings(alias):
    old = resource()
    captured = record()
    captured["properties"]["EC2.VPC.Name"]["value"] = "renamed-vpc"
    if alias:
        old["desired.row.001-001.property"] = "EC2.VPC.Id"
        captured["identityProperties"] = ["EC2.VPC.VpcId", "EC2.VPC.Id"]
    new = {**old, **resource("009")}
    with pytest.raises(ValueError, match="duplicate identity"):
        selection_records(selection(rid="009"), [captured], old, new, schema_for)
    picked = {
        "resources": [],
        "excluded": [
            {"record": captured["record"], "reason": "already registered physical ID"}
        ],
        "unreflected": [],
    }
    assert selection_records(picked, [captured], old, old, schema_for) == {}
    assert verify_values(expansion(old), expansion(old), {}, schema_for) == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("desired.row.001-002.value", "`10.11.0.0/23`"),
        ("desired.resource.001.anchor", "renamed"),
        ("desired.resource.001.logicalId", "Renamed"),
        ("desired.resource.001.resourceMode", "CREATE"),
        ("desired.row.001-001.value", "`vpc-confirmed`"),
        ("observed.row.001-001.value", "`vpc-invented`"),
        ("desired.row.001-002.property", "EC2.VPC.Name"),
        ("desired.row.001-003.value", "`renamed-vpc`"),
        ("desired.row.001-003.comment", "changed"),
        ("desired.row.001-003.document", "{}"),
        ("observed.row.001-002.value", "`10.11.0.0/23`"),
        ("desired.row.001-004.value", "`true`"),
    ],
)
def check_invalid_candidates(key, value):
    old = resource()
    new = {**old, key: value}
    with pytest.raises(
        ValueError,
        match="preserved|existing|observed value requires a desired logical reference|acquired|Row requires|unknown Model field|logicalId requires",
    ):
        verify_values(expansion(old), expansion(new), {"001": record()}, schema_for)


def check_unacquired_and_create_protection():
    old = resource(mode="CREATE")
    new = {**old, **resource("009", identity="vpc-new", cidr="10.11.0.0/23")}
    unavailable = record("vpc-new")
    unavailable["properties"]["EC2.VPC.CidrBlock"] = {"status": "missing"}
    with pytest.raises(ValueError, match="unacquired"):
        verify_values(expansion(old), expansion(new), {"009": unavailable}, schema_for)
    with pytest.raises(ValueError, match="no selected acquisition|unselected Resource"):
        verify_values(expansion(old), expansion(new), {}, schema_for)
    with pytest.raises(ValueError, match="CREATE"):
        selection_records(selection(), [record()], old, old, schema_for)
    with pytest.raises(
        ValueError,
        match="deleting an existing resource|deleting existing Resource|lastAllocated cannot",
    ):
        verify_values(expansion(old), expansion({}), {}, schema_for)


@pytest.mark.parametrize(
    "kind,identity_prop", [("EC2.VPC", "VpcId"), ("Logs.LogGroup", "LogGroupName")]
)
@pytest.mark.parametrize("hide_observed", [False, True])
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def check_duplicate_add_uses_baseline(kind, identity_prop, hide_observed, mode):
    old = resource(kind=kind, mode=mode)
    if kind == "Logs.LogGroup":
        old["desired.row.001-001.property"] = kind + "." + identity_prop
        old["desired.row.001-001.value"] = "`fixture-001`"
        old.pop("observed.row.001-001.value")
    identity = "fixture-001" if kind == "Logs.LogGroup" else "vpc-confirmed"
    captured = {
        **record(identity),
        "kind": kind,
        "identityProperty": kind + "." + identity_prop,
    }
    new = {**old, **resource("009", kind=kind)}
    if hide_observed:
        new.pop("observed.row.001-001.value", None)
        new["desired.row.001-001.value"] = "`hidden-in-candidate`"
    with pytest.raises(ValueError, match="record-1.*009.*001"):
        selection_records(
            selection(rid="009", action="add"), [captured], old, new, schema_for
        )


def check_selection_identity_duplicate():
    captured = record("vpc-new")
    duplicate = {**captured, "record": "record-2"}
    new = {**resource("008", identity="vpc-new"), **resource("009", identity="vpc-new")}
    picked = selection(rid="008", action="add")
    picked["resources"].extend(selection("record-2", "009", "add")["resources"])
    with pytest.raises(ValueError, match="duplicate identity"):
        selection_records(picked, [captured, duplicate], {}, new, schema_for)


def check_existing_identity_ambiguity_is_local():
    old = {**resource(), **resource("008")}
    captured = record()
    with pytest.raises(ValueError, match="001,008"):
        selection_records(
            selection(rid="009"),
            [captured],
            old,
            {**old, **resource("009")},
            schema_for,
        )
    fresh = record("vpc-new")
    new = {**old, **resource("009", identity="vpc-new")}
    assert selection_records(
        selection(rid="009", action="add"), [fresh], old, new, schema_for
    )
    # An unrelated old resource with multiple identity rows is not a global gate.
    old.update(
        {
            "desired.row.008-004.property": "EC2.VPC.VpcId",
            "desired.row.008-004.value": "`vpc-other`",
        }
    )
    assert selection_records(
        selection(rid="009", action="add"), [fresh], old, new, schema_for
    )
    assert (
        selection_records(
            {
                "resources": [],
                "excluded": [],
                "unreflected": [{"record": captured["record"], "reason": "ambiguous"}],
            },
            [captured],
            old,
            old,
            schema_for,
        )
        == {}
    )


@pytest.mark.parametrize("unknown", [None, "", "UNSET", "PENDING_DEPLOY"])
def check_unknown_identity_does_not_block_add(unknown):
    old = resource(identity=unknown)
    new = {**old, **resource("009")}
    warnings = []
    assert selection_records(
        selection(rid="009", action="add"), [record()], old, new, schema_for, warnings
    )
    assert warnings[0]["existingResources"] == ["001"]


def check_new_resource_and_explicit_dispositions():
    old = resource()
    new = {**old, **resource("009", identity="vpc-new", cidr="10.11.0.0/23")}
    acquired = record("vpc-new")
    picked = selection(rid="009", action="add")
    chosen = selection_records(picked, [acquired], old, new, schema_for)
    assert chosen.keys() == {"009"}
    assert len(verify_values(expansion(old), expansion(new), chosen, schema_for)) == 3
    with pytest.raises(ValueError, match="differs from the acquired"):
        verify_values(
            expansion(old),
            expansion({**new, "desired.row.009-002.value": "`10.99.0.0/16`"}),
            chosen,
            schema_for,
        )
    invalid = {**new, "desired.row.009-001.value": "[vpc](vpc.md#vpc-001)"}
    warnings = []
    verify_values(
        expansion(old), expansion(invalid), chosen, schema_for, warnings=warnings
    )
    assert any("own Resource" in w["message"] for w in warnings)
    picked["resources"][0]["action"] = "update"
    with pytest.raises(ValueError, match="add only"):
        selection_records(picked, [acquired], old, new, schema_for)
    with pytest.raises(ValueError, match="explicit disposition"):
        selection_records(
            {"resources": [], "excluded": [], "unreflected": []},
            [acquired],
            old,
            old,
            schema_for,
        )
    assert (
        selection_records(
            {
                "resources": [],
                "excluded": [],
                "unreflected": [{"record": "record-1", "reason": "ownership unknown"}],
            },
            [acquired],
            old,
            old,
            schema_for,
        )
        == {}
    )


def check_binding_identity_and_addition():
    original = resource()
    candidate = {**original, **resource("009", identity="vpc-new", cidr="10.11.0.0/23")}
    verify_values(
        expansion(original),
        expansion(candidate),
        {"009": record("vpc-new")},
        schema_for,
    )
    for key, value in [
        ("desired.resource.001.logicalId", "Renamed"),
        ("desired.resource.001.anchor", "changed"),
        ("desired.resource.001.resourceMode", "CREATE"),
        ("desired.resource.001.resourceType", "EC2.Subnet"),
        ("desired.row.001-002.property", "EC2.VPC.Name"),
    ]:
        changed = {**candidate, key: value}
        with pytest.raises(
            ValueError,
            match="preserved|fixed identity|logicalId requires|unknown Model field",
        ):
            verify_values(
                expansion(original),
                expansion(changed),
                {"009": record("vpc-new")},
                schema_for,
            )
    renamed = {
        key.replace("desired.row.001-002.", "desired.row.001-099."): value
        for key, value in candidate.items()
    }
    with pytest.raises(ValueError, match="Row IDs"):
        verify_values(
            expansion(original),
            expansion(renamed),
            {"009": record("vpc-new")},
            schema_for,
        )


def check_shared_property_typed_preservation():
    old = resource()
    old.update(
        {
            "desired.row.001-004.property": "EC2.VPC.EnableDnsSupport",
            "desired.row.001-004.value": "`false`",
            "desired.row.001-004.comment": "合成 boolean",
        }
    )
    capture = record()
    capture["properties"]["EC2.VPC.EnableDnsSupport"] = {
        "status": "captured",
        "value": False,
    }
    selected = selection_records(
        selection(action="refresh"), [capture], old, old, schema_for
    )
    new = {**old, "desired.row.001-004.value": "false"}
    verify_values(expansion(old), expansion(new), selected, schema_for)
    assert (
        property_values(new, "001", "EC2.VPC.EnableDnsSupport", {"type": "boolean"})
        is False
    )
    new["desired.row.001-004.value"] = '`"false"`'
    with pytest.raises(ValueError, match="acquired|native type"):
        verify_values(expansion(old), expansion(new), selected, schema_for)


def check_shared_reference_is_symbolic(tmp_path):
    root = tmp_path
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": "dev",
                        "alias": "cde",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    scope = Scope(root, "dev", "cde", "vpc")
    values = resource()
    for field, value in {
        "consumerKey": "desired.row.001-003.value",
        "text": "main-vpc",
        "occurrence": "1",
        "producerKind": "resource",
        "producerScope": "dev/cde/vpc",
        "producerLogicalId": "EC2_VPC_001",
        "resourceType": "EC2.VPC",
        "format": "name",
        "property": "EC2.VPC.Name",
        "labelPolicy": "none",
    }.items():
        values["desired.reference.fixed." + field] = value
    scope.path.parent.mkdir(parents=True)
    scope.path.write_text(serialize(values), encoding="utf-8")
    actual = symbolic(load_model(scope))["desired.row.001-003.value"]
    assert actual == (
        "`",
        Reference(
            "dev/cde/vpc/001",
            "resource",
            "EC2.VPC",
            "name",
            "EC2.VPC.Name",
            None,
            "none",
        ),
        "`",
    )


def check_typed_property_values():
    values = resource()
    values.update(
        {
            "desired.row.001-004.property": "EC2.VPC.EnableDnsSupport",
            "desired.row.001-004.value": "`false`",
        }
    )
    assert (
        property_values(
            values,
            "001",
            "EC2.VPC.EnableDnsSupport",
            schema_for("EC2.VPC.EnableDnsSupport"),
        )
        is False
    )
    assert (
        property_values(values, "001", "EC2.VPC.VpcId", {"type": "string"})
        == "vpc-confirmed"
    )
    row = {"property": "Logs.LogGroup.RetentionInDays"}
    assert typed_equal(typed_row(row, "`90`", {"type": "integer"}), 90)
    assert not typed_equal(typed_row(row, '`"90"`', {"type": "integer"}), 90)


def check_shape_round_trip_and_display(tmp_path):
    project_fixture(tmp_path)
    values = resource()
    values.update(
        {
            "desired.row.001-004.property": "EC2.VPC.Tags[].Value",
            "desired.row.001-004.value": '`["A","B"]`',
            "desired.row.001-004.comment": "取得列",
            "desired.row.001-004.valueShape": "projection",
        }
    )
    path = tmp_path / "model/dev" / ACCOUNT / "vpc.properties"
    write_model(path, values)
    saved = load_model(path)
    assert dict(saved.authoritative) == values
    assert saved.values["desired.row.001-004.valueShape"] == "projection"
    rows = resource_rows(saved.values, "001", "EC2.VPC", m.ROOT)
    assert all(len(row) == 4 for row in rows)
    assert "projection" not in str(rows)
    assert property_values(
        saved.values, "001", "EC2.VPC.Tags[].Value", {"type": "string"}
    ) == ["A", "B"]


@pytest.mark.parametrize("shape", ["leaf", "projection"])
def check_import_array_leaf_comparison(shape):
    kind = "QuickSight.DataSource"
    prop = kind + ".Permissions[].Actions"
    value = ["ActionA", "ActionB"]
    raw = value if shape == "leaf" else [value]
    candidate = resource_values(
        "001",
        kind,
        "source",
        "IMPORT",
        [("Permissions[].Actions", m.model_literal(raw))],
    )
    candidate["desired.row.001-001.valueShape"] = shape
    captured = {
        "record": "source",
        "kind": kind,
        "identity": "source",
        "identityProperty": None,
        "identityProperties": [],
        "properties": {
            prop: {"status": "captured", "value": [value], "valueShape": "projection"},
        },
    }
    assert verify_values(
        expansion({}), expansion(candidate), {"001": captured}, m.property_schema
    )
    assert property_values(candidate, "001", prop, m.property_schema(prop)) == [value]


def check_invalid_shape_is_rejected(tmp_path):
    project_fixture(tmp_path)
    values = resource()
    values["desired.row.001-002.valueShape"] = "auto"
    path = tmp_path / "model/dev" / ACCOUNT / "vpc.properties"
    write_model(path, values)
    with pytest.raises(ValueError, match="valueShape"):
        load_model(path)


def check_candidate_scope_and_changed_files(tmp_path):
    root, stage = tmp_path / "repository", tmp_path / "candidate"
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": "dev",
                        "alias": "cde",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    original = root / "model/dev/cde/vpc.properties"
    write_model(original, resource())
    before = load_model(original)
    candidate = stage / original.relative_to(root)
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(original.read_bytes())
    changes, after = candidate_sources(root, stage, before)
    assert not changes and after.authoritative == before.authoritative
    candidate.write_bytes(
        b"# model-format: 2\n# added\n" + original.read_bytes().split(b"\n", 1)[1]
    )
    assert set(candidate_sources(root, stage, before)[0]) == {original}
    (stage / "project.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="outside|path"):
        candidate_sources(root, stage, before)


def check_sealed_evidence_tamper(tmp_path):
    file = tmp_path / "acquisition.json"
    value = {
        "scope": ["dev", "cde", "vpc"],
        "records": [record()],
        "sts": {"verified": True},
    }
    with patch.object(sealed_evidence, "seal_key", return_value=b"x" * 32):
        file.write_text(sealed_evidence.sealed(tmp_path, value), encoding="utf-8")
        assert sealed_evidence.read_sealed(tmp_path, file) == value
        data = json.loads(file.read_text(encoding="utf-8"))
        data["payload"]["records"][0]["identity"] = "fabricated"
        file.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError, match="modified"):
            sealed_evidence.read_sealed(tmp_path, file)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--environment", "dev", "--service", "vpc"],
        ["--environment", "dev", "--service", "vpc", "--phase", "publish"],
        [
            "--environment",
            "dev",
            "--service",
            "vpc",
            "--phase",
            "publish",
            "--evidence",
            "/tmp/a",
            "--no-profile",
        ],
    ],
)
def check_cli_never_falls_back(args):
    with (
        patch.object(sys, "argv", ["import-model", *args]),
        pytest.raises(SystemExit) as failure,
    ):
        m.main()
    assert failure.value.code == 2


def check_cli_phase_dispatch(tmp_path):
    arguments = [
        "--repository-root",
        str(tmp_path),
        "--environment",
        "dev",
        "--service",
        "vpc",
    ]
    result = {"status": "acquired", "markdown": "not-run"}
    with (
        patch.object(m, "acquire", return_value=result) as acquire,
        patch.object(m, "publish_acquisition") as publish,
    ):
        assert m.main(["acquire", *arguments, "--no-profile"]) == 0
        assert acquire.call_args.args == (tmp_path, "dev", "vpc")
        assert acquire.call_args.kwargs == {
            "selector": None,
            "dry_run": False,
            "no_profile": True,
            "resource_types": None,
        }
        publish.assert_not_called()
    for result, code in [
        ({"status": "complete", "markdown": "generated"}, 0),
        ({"status": "incomplete", "markdown": "generated"}, 2),
        ({"status": "display-failed", "markdown": "failed"}, 3),
    ]:
        with (
            patch.object(m, "publish_acquisition", return_value=result),
            patch.object(m, "acquire") as acquire,
        ):
            assert (
                m.main(
                    [
                        "publish",
                        *arguments,
                        "--evidence",
                        str(tmp_path / "acquisition.json"),
                    ]
                )
                == code
            )
            acquire.assert_not_called()


def check_native_equality_and_singleton():
    assert typed_equal({"a": False, "b": 2}, {"b": 2, "a": False})
    assert not typed_equal(False, 0)
    old = {
        "desired.resource.001.resourceType": "SecurityHub.Hub",
        "desired.resource.001.resourceMode": "IMPORT",
    }
    captured = {
        "record": "hub",
        "kind": "SecurityHub.Hub",
        "identity": "confirmed-hub",
        "identityProperty": None,
        "properties": {},
    }
    with pytest.raises(ValueError, match="add only"):
        selection_records(
            selection("hub", action="update", basis=["$scope"]),
            [captured],
            old,
            old,
            schema_for,
        )
    new = {
        **old,
        "desired.resource.009.resourceType": "SecurityHub.Hub",
        "desired.resource.009.resourceMode": "IMPORT",
    }
    assert selection_records(
        selection("hub", rid="009"), [captured], old, new, schema_for
    ) == {"009": captured}


def check_adapter_inventory_normalization(tmp_path):
    target = {
        "environment": "dev",
        "directory": "cde",
        "awsAccountId": ACCOUNT,
        "awsRegion": "ap-northeast-1",
        "awsProfile": "confirmed",
    }
    for service in SERVICES:
        cli = aws(service)
        ctx = m.import_context(m.ROOT, target, cli, service)
        ctx.verify()
        records = m.normalize_records(ctx, service, m.inventory(ctx, service))
        assert records and all(
            "properties" in record and "getters" not in record for record in records
        )
        assert cli.calls[0] == ("sts", "get-caller-identity", {})
        if service == "vpc":
            vpc = next(r for r in records if r["kind"] == "EC2.VPC")
            assert vpc["properties"]["EC2.VPC.EnableDnsSupport"]["value"] is True
            subnets = [r for r in records if r["kind"] == "EC2.Subnet"]
            assert len(subnets) == 7
            assert all(
                r["properties"]["EC2.Subnet.VpcId"]["value"] == vpc["identity"]
                for r in subnets
            )
        if service == "config":
            recorder = next(
                r for r in records if r["kind"] == "Config.ConfigurationRecorder"
            )
            assert (
                recorder["properties"][
                    "Config.ConfigurationRecorder.RecordingGroup.AllSupported"
                ]["value"]
                is False
            )
            assert recorder["properties"][
                "Config.ConfigurationRecorder.RecordingGroup.ResourceTypes"
            ]["value"] == ["AWS::EC2::VPC"]
            assert (
                "Config.ConfigurationRecorder.RecordingMode.RecordingModeOverrides[].Description"
                not in recorder["properties"]
            )
        if service == "quicksight":
            assert all(r["kind"] == "QuickSight.DataSource" for r in records)
            assert all(
                r["properties"]["QuickSight.DataSource.Name"]["value"] == r["identity"]
                for r in records
            )
            assert all(
                inputs.get("AwsAccountId") == ACCOUNT
                for api, _, inputs in cli.calls
                if api == "quicksight"
            )
    for cli, error_type, code in [
        (
            AwsCli(account="999999999999"),
            m.comparator().IdentityError,
            "AccountMismatch",
        ),
        (
            AwsCli(
                fail="An error occurred (AccessDenied) when calling STS: PRIVATE-CREDENTIAL"
            ),
            m.comparator().AcquisitionError,
            "AccessDenied",
        ),
    ]:
        ctx = m.import_context(m.ROOT, target, cli, "cloudwatch-logs")
        with pytest.raises(error_type) as caught:
            ctx.verify()
        assert caught.value.code == code and len(cli.calls) == 1


def check_shared_source_preservation_boundary(tmp_path):
    build_seed(tmp_path)
    for service in SERVICES:
        assert load_model(
            tmp_path / "model/dev/cde" / (service + ".properties")
        ).authoritative
    path = tmp_path / "model/dev/cde/cloudwatch-logs.properties"
    before = load_model(path)
    foreign = tmp_path / "model/stg/cde/cloudwatch-logs.properties"
    preserved = foreign.read_bytes()
    # A source-only comment refactor retains all canonical values and every other environment.
    output = {path: path.read_text() + "# retained comment\n"}
    after = load_model(path, CandidateReads(FileReads(), output))
    assert after.authoritative == before.authoritative and not verify_values(
        before, after, {}, schema_for
    )
    assert foreign.read_bytes() == preserved
    changed = {
        **before.authoritative,
        "desired.row.001-004.value": "`INFREQUENT_ACCESS`",
    }
    after = load_model(path, CandidateReads(FileReads(), {path: serialize(changed)}))
    with pytest.raises(ValueError, match="unselected Resource"):
        verify_values(before, after, {}, schema_for)
    stage = tmp_path / "candidate"
    file = stage / foreign.relative_to(tmp_path)
    file.parent.mkdir(parents=True)
    file.write_bytes(preserved)
    with pytest.raises(ValueError, match="outside"):
        candidate_sources(tmp_path, stage, before)


@pytest.mark.parametrize("action", ["update", "add"])
@pytest.mark.parametrize("identity", ["vpc-confirmed", None])
def check_existing_resource_action_rejected(action, identity):
    old = resource(identity=identity)
    with pytest.raises(ValueError, match="add only"):
        selection_records(
            selection(action=action, basis=["EC2.VPC.Name", "EC2.VPC.CidrBlock"]),
            [record()],
            old,
            old,
            schema_for,
        )


def check_new_anchor_and_reference_preservation():
    old = resource()
    new = {**old, **resource("009", identity="vpc-new", cidr="10.11.0.0/23")}
    new["desired.row.009-001.value"] = old["desired.row.001-001.value"]
    warnings = []
    verify_values(
        expansion(old),
        expansion(new),
        {"009": record("vpc-new")},
        schema_for,
        warnings=warnings,
    )
    assert any("own Resource" in w["message"] for w in warnings)
    for field, value in {
        "consumerKey": "desired.row.001-003.value",
        "text": "main-vpc",
        "occurrence": "1",
        "producerKind": "resource",
        "producerScope": "dev/cde/vpc",
        "producerLogicalId": "EC2_VPC_001",
        "resourceType": "EC2.VPC",
        "format": "name",
        "property": "EC2.VPC.Name",
        "labelPolicy": "none",
    }.items():
        old["desired.reference.fixed." + field] = value
    new = {**old, "desired.reference.fixed.producerLogicalId": "EC2_VPC_002"}
    with pytest.raises(ValueError, match="unselected Resource"):
        verify_values(expansion(old), expansion(new), {}, schema_for)


def _lambda_check_authored_vpc_append_candidate_captured_schema_507(prop):
    return {"type": "boolean" if ".EnableDns" in prop else "string"}


@pytest.mark.parametrize("unknown", [False, True])
def check_authored_vpc_append_candidate(tmp_path, unknown):
    build_seed(tmp_path)
    path = tmp_path / "model/dev/cde/vpc.properties"
    if unknown:
        values = dict(load_model(path).authoritative)
        del values["observed.row.001-001.value"]
        write_model(path, values)
    before = load_model(path)
    original_bytes = {
        p: p.read_bytes() for p in (tmp_path / "model").rglob("*") if p.is_file()
    }
    addition = resource("009", identity="vpc-new", cidr="10.11.0.0/23")
    state = json.loads(before.authoritative[COUNTERS])
    state["EC2.VPC"] += 1
    addition[COUNTERS] = json.dumps(state)
    addition["desired.row.009-001.value"] = "[vpc](vpc.md#vpc-009)"
    for index, prop in enumerate(("EnableDnsHostnames", "EnableDnsSupport"), 4):
        addition.update(
            {
                f"desired.row.009-{index:03d}.property": "EC2.VPC." + prop,
                f"desired.row.009-{index:03d}.value": "`true`",
                f"desired.row.009-{index:03d}.comment": "取得値",
            }
        )
    after = load_model(
        path,
        CandidateReads(
            FileReads(), {path: serialize({**before.authoritative, **addition})}
        ),
    )
    acquired = record("vpc-new")
    for prop in ("EC2.VPC.EnableDnsHostnames", "EC2.VPC.EnableDnsSupport"):
        acquired["properties"][prop] = {"status": "captured", "value": True}
    captured_schema = _lambda_check_authored_vpc_append_candidate_captured_schema_507
    warnings = []
    selected = selection_records(
        selection(rid="009"),
        [acquired],
        before.values,
        after.values,
        captured_schema,
        warnings,
    )
    assert len(verify_values(before, after, selected, captured_schema)) == 5
    assert bool(warnings) == unknown
    assert all(
        after.authoritative[key] == value
        for key, value in before.authoritative.items()
        if key != COUNTERS
    )
    assert after.authoritative["observed.row.009-001.value"] == "`vpc-new`"
    assert after.authoritative["desired.row.009-001.value"] == "[vpc](vpc.md#vpc-009)"
    assert after.authoritative["desired.resource.009.resourceMode"] == "IMPORT"
    assert all(p.read_bytes() == raw for p, raw in original_bytes.items())


@pytest.mark.parametrize(
    "relative",
    [
        "model/stg/cde/vpc.properties",
        "model/stg/cde/vpc/part-001.properties",
        "model/stg/another/vpc.properties",
        "model/dev/cde/config.properties",
        "model/dev/another/vpc.properties",
        "model/dev/cde/config/part-001.properties",
        "model/templates/cde/vpc.properties.tpl",
    ],
)
def check_foreign_candidate_scope(tmp_path, relative):
    root, directory = tmp_path / "repository", tmp_path / "candidate"
    operation_fixture(root)
    before = load_model(root / "model/dev/cde/vpc.properties")
    file = directory / relative
    file.parent.mkdir(parents=True)
    file.write_text("# model-format: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside|invalid authoritative Model path"):
        candidate_sources(root, directory, before)


@pytest.mark.parametrize("action", ["import-merge", "import-delete"])
def check_model_operation_preserves_consumers(tmp_path, action):
    before, after = tmp_path / "before", tmp_path / "after"
    operation_fixture(before)
    sources = operation_candidate(before, after, action)
    verify_model_operation(
        before, after, model_operation(operation_contract(action)), sources
    )
    dev = "model/dev/cde/vpc.properties"
    assert load_model(before / dev).values == load_model(after / dev).values
    stg = load_model(after / "model/stg/cde/vpc.properties").values
    assert "desired.resource.009.resourceType" not in stg
    assert stg["desired.resource.001.resourceMode"] == "IMPORT"
    assert stg["observed.row.001-001.value"] == (
        "vpc-source" if action == "import-merge" else "vpc-stg"
    )
    assert not (after / ".blueprint").exists()


@pytest.mark.parametrize(
    "change",
    [
        "cidr",
        "observation",
        "mode",
        "row-id",
        "dev",
        "binding",
        "missing-row",
        "extra-delete",
        "reference",
    ],
)
def check_model_operation_rejects_unproved_changes(tmp_path, change):
    before, after = tmp_path / "before", tmp_path / "after"
    operation_fixture(before)
    sources = operation_candidate(before, after)
    file = after / (
        "model/dev/cde/vpc.properties"
        if change == "dev"
        else "model/stg/cde/vpc.properties"
    )
    values = dict(load_model(file).authoritative)
    if change == "cidr":
        values["desired.row.001-002.value"] = "`10.8.0.0/16`"
    elif change == "observation":
        values["observed.row.001-001.value"] = "fabricated"
    elif change == "mode":
        values["desired.resource.001.resourceMode"] = "CREATE"
    elif change == "dev":
        values["desired.row.001-002.value"] = "`10.2.0.0/16`"
        sources.add("model/dev/cde/vpc.properties")
    elif change == "row-id":
        for key in list(values):
            if key.startswith("desired.row.001-002."):
                values[key.replace("001-002", "001-099")] = values.pop(key)
    elif change == "binding":
        values["desired.resource.001.anchor"] = "new-anchor"
    elif change == "extra-delete":
        del values["desired.service.vpc.serviceId"]
    elif change == "missing-row":
        values["desired.row.001-002.property"] = "EC2.VPC.Other"
    else:
        values["desired.note.001.text"] = "[009](#vpc-imported)"
    write_model(file, values)
    with pytest.raises(ValueError):
        verify_model_operation(
            before, after, model_operation(operation_contract()), sources
        )


@pytest.mark.parametrize(
    "change",
    [
        "cross-env",
        "same-id",
        "missing-target",
        "normal-task",
        "aws",
        "create-source",
        "create-destination",
        "wrong-source",
    ],
)
def check_model_operation_contract_scope(tmp_path, change):
    text = operation_contract()
    if change == "cross-env":
        text = text.replace("stg/cde/vpc/001", "dev/cde/vpc/001")
    elif change == "same-id":
        text = text.replace("stg/cde/vpc/001", "stg/cde/vpc/009")
    elif change == "missing-target":
        text = text[: text.index("## Model merge pairs")]
    elif change == "normal-task":
        text = text.replace("- Workflow: `update`", "- Workflow: `ordinary`")
    elif change == "aws":
        text = text.replace("`forbidden`", "`allowed`")
    else:
        before, after = tmp_path / "before", tmp_path / "after"
        operation_fixture(before)
        if change in {"create-source", "create-destination"}:
            load_model = _imports_model_sources.load_model
            write_model = _imports_support_model_sources.write_model
            file = before / "model/stg/cde/vpc.properties"
            values = dict(load_model(file).authoritative)
            values[
                "desired.resource."
                + ("001" if change == "create-destination" else "009")
                + ".resourceMode"
            ] = "CREATE"
            write_model(file, values)
        action = (
            "import-merge"
            if change in {"create-source", "create-destination"}
            else "import-delete"
        )
        sources = operation_candidate(before, after, action)
        with pytest.raises(ValueError):
            verify_model_operation(
                before,
                after,
                model_operation(
                    operation_contract(
                        action,
                        source="stg/cde/vpc/"
                        + ("001" if change == "wrong-source" else "009"),
                    )
                ),
                sources,
            )
        return
    with pytest.raises(ValueError):
        model_operation(text)


def check_model_operation_row_correspondence():
    values = resource()
    values.update(
        {
            "desired.row.001-010.property": "EC2.VPC.Tags[].Key",
            "desired.row.001-010.value": "`A`",
            "desired.row.001-011.property": "EC2.VPC.Tags[].Value",
            "desired.row.001-011.value": "`one`",
            "desired.row.001-020.property": "EC2.VPC.Tags[].Key",
            "desired.row.001-020.value": "`B`",
            "desired.row.001-021.property": "EC2.VPC.Tags[].Value",
            "desired.row.001-021.value": "`two`",
        }
    )
    rows = operation_rows(values, "001")
    assert rows["EC2.VPC.Tags[1].Value"][0] == "001-011"
    assert rows["EC2.VPC.Tags[2].Key"][0] == "001-020"
    values["desired.row.001-030.property"] = "EC2.VPC.CidrBlock"
    values["desired.row.001-030.value"] = "`10.3.0.0/16`"
    with pytest.raises(ValueError, match="ambiguous"):
        operation_rows(values, "001")


@pytest.mark.parametrize(
    "properties, expected",
    [
        (
            ["IAM.Role.ManagedPolicyArns"] * 2,
            ["IAM.Role.ManagedPolicyArns[1]", "IAM.Role.ManagedPolicyArns[2]"],
        ),
        (
            ["IAM.Role.ManagedPolicyArns[]"] * 2,
            ["IAM.Role.ManagedPolicyArns[1]", "IAM.Role.ManagedPolicyArns[2]"],
        ),
        (
            ["IAM.Role.ManagedPolicyArns[1]", "IAM.Role.ManagedPolicyArns[2]"],
            ["IAM.Role.ManagedPolicyArns[1]", "IAM.Role.ManagedPolicyArns[2]"],
        ),
        (
            ["IAM.Role.Policies[].PolicyDocument.Statement[].Effect"] * 2,
            [
                "IAM.Role.Policies[1].PolicyDocument.Statement[1].Effect",
                "IAM.Role.Policies[1].PolicyDocument.Statement[2].Effect",
            ],
        ),
        (["IAM.Role.RoleName"] * 2, None),
        (["IAM.Role.ManagedPolicyArns[1]"] * 2, None),
    ],
)
def check_model_operation_catalog_arrays(tmp_path, properties, expected):
    values = {"desired.resource.001.resourceType": "IAM.Role"}
    for rid, prop, value in zip(
        ("001-004", "001-007"),
        properties,
        ("[first](#first)", "[second](#second)"),
        strict=False,
    ):
        values.update(
            {f"desired.row.{rid}.property": prop, f"desired.row.{rid}.value": value}
        )
    fixture = tmp_path / "rows.json"
    fixture.write_text(json.dumps(values))
    values = json.loads(fixture.read_text())
    if expected is None:
        with pytest.raises(ValueError, match="ambiguous Property correspondence"):
            operation_rows(values, "001")
    else:
        rows = operation_rows(values, "001")
        assert list(rows) == expected
        assert [(rid, row["value"]) for rid, row in rows.values()] == [
            ("001-004", "[first](#first)"),
            ("001-007", "[second](#second)"),
        ]


@pytest.mark.parametrize(
    "shape", ["optional", "choice", "optional-json", "document", "untransferred"]
)
def check_model_operation_shape_preservation(tmp_path, shape):
    before, after = tmp_path / "before", tmp_path / "after"
    operation_fixture(before)
    path = before / "model/stg/cde/vpc.properties"
    values = dict(load_model(path).authoritative)
    if shape in {"optional", "choice"}:
        values.update(
            {
                "desired.row.009-050.property": "EC2.VPC.EnableDnsHostnames",
                "desired.row.009-050.value": "`true`",
                "desired.row.009-050.comment": "追加取得値",
            }
        )
    else:
        for rid, rows, statements in [
            ("001", "001-010", []),
            ("009", "009-020", [{"Effect": "Allow"}]),
        ]:
            values.update(
                {
                    f"desired.row.{rows}.property": "EC2.VPC.Document",
                    f"desired.row.{rows}.value": "[JSON](vpc/" + rid + ".json)",
                    f"desired.row.{rows}.document": json.dumps(
                        {"Version": "2012-10-17", "Statement": statements}
                    ),
                    f"desired.row.{rows}.comment": "構造比較の合成入力",
                }
            )
    write_model(path, values)
    sources = operation_candidate(before, after)
    if shape == "untransferred":
        path = after / "model/stg/cde/vpc.properties"
        values = dict(load_model(path).authoritative)
        values["desired.row.001-010.document"] = (
            '{"Version":"2012-10-17","Statement":[]}'
        )
        write_model(path, values)
        with pytest.raises(ValueError, match="changed|retain|transfer"):
            verify_model_operation(
                before, after, model_operation(operation_contract()), sources
            )
    else:
        verify_model_operation(
            before, after, model_operation(operation_contract()), sources
        )
        assert (
            load_model(before / "model/dev/cde/vpc.properties").authoritative
            == load_model(after / "model/dev/cde/vpc.properties").authoritative
        )
        if shape in {"optional", "choice"}:
            assert (
                load_model(after / "model/stg/cde/vpc.properties").authoritative[
                    "desired.row.001-050.value"
                ]
                == "`true`"
            )
        else:
            assert json.loads(
                load_model(after / "model/stg/cde/vpc.properties").authoritative[
                    "desired.row.001-010.document"
                ]
            )["Statement"] == [{"Effect": "Allow"}]


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "tamper",
        "missing",
        "expired",
        "task",
        "base",
        "scope",
        "binding-task",
        "binding-worktree",
        "binding-risk",
        "completion",
        "legacy-receipt",
    ],
)
def check_external_completion_proof(tmp_path, monkeypatch, failure):
    root = tmp_path / "repository"
    root.mkdir()
    monkeypatch.setattr(import_guard.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        import_guard, "task_path", lambda root: root / "tasks/example.md"
    )
    monkeypatch.setattr(import_guard, "workflow", lambda root: "tasks/example.md")
    monkeypatch.setattr(import_guard, "base_revision", lambda root: "base")
    monkeypatch.setattr(
        "model.importing.scope.selected", lambda root: ("stg", "cde", "vpc")
    )
    proof = {
        "version": 3,
        "task": "tasks/example.md",
        "base": "base",
        "scope": ["stg", "cde", "vpc"],
        "acquisition": "receipt",
        "sources": {},
        "plan": "verified",
        "complete": True,
        "model": "unchanged",
        "markdown": "unchanged",
        "ownedArtifacts": [],
        "acquiredAt": datetime.now(timezone.utc).isoformat(),
    }
    review_proof_fixture(root, proof)
    if failure == "completion":
        proof["completion"]["acquisition"] = False
    elif failure == "legacy-receipt":
        proof["version"] = 6
    elif failure == "expired":
        proof["acquiredAt"] = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat()
    elif failure in {"task", "base"}:
        proof[failure] = "wrong"
    elif failure == "scope":
        proof["scope"] = ["dev", "cde", "vpc"]
    elif failure.startswith("binding-"):
        field = {
            "binding-task": "task",
            "binding-worktree": "worktree",
            "binding-risk": "recordsDigest",
        }[failure]
        proof["reviewBinding"][field] = "f" * 64
        if failure != "binding-risk":
            proof["reviewBindingDigest"] = document_sha256(proof["reviewBinding"])
    file = import_guard.proof_path(root)
    assert not file.is_relative_to(root)
    sealed_evidence.write_sealed(root, file, proof)
    if failure == "tamper":
        file.write_text(file.read_text().replace("verified", "fabricated"))
    elif failure == "missing":
        file.unlink()
    if failure != "none":
        with pytest.raises(ValueError, match="no verified"):
            import_guard.read_proof(root)
    else:
        assert import_guard.read_proof(root) == proof
        import_guard.discard_import_proof(root, "tasks/example.md")
        assert not file.exists()
    assert not (root / ".blueprint").exists()


@pytest.mark.parametrize("failure", ["incomplete", "unplanned", "hash"])
def check_acquired_plan_completion(tmp_path, monkeypatch, failure):
    relative = "model/stg/cde/vpc.properties"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text("source bytes")
    name = "tasks/example.md"
    text = _imports_support_repository_fixtures.contract("example", [relative]).replace(
        "- Task type: `governance`", "- Task type: `design`\n- Workflow: `import`"
    )
    proof = dict(
        sources={relative: hashlib.sha256(b"source bytes").hexdigest()},
        model="reflected",
        complete=failure != "incomplete",
    )
    if failure == "unplanned":
        proof["sources"] = {}
    if failure == "hash":
        proof["sources"][relative] = "0" * 64
    monkeypatch.setattr("model.importing.repository.has_baseline", lambda root: True)
    monkeypatch.setattr(
        import_guard,
        "task_snapshot",
        lambda *a, **k: SimpleNamespace(path=tmp_path / name, text=text),
    )
    monkeypatch.setattr(_imports_task_contract, "validate_contract", lambda *a: None)
    monkeypatch.setattr(import_guard, "read_proof", lambda *a, **k: proof)
    expected = {
        "incomplete": "incomplete",
        "unplanned": "no acquired change plan",
        "hash": "differs from acquired",
    }
    with pytest.raises(ValueError, match=expected[failure]):
        import_guard.require_import_changes(
            tmp_path, supplied={relative}, contract_file=name
        )


def check_snapshot_proof_resigning_and_cleanup(tmp_path, monkeypatch):
    root, snapshot = tmp_path / "repository", tmp_path / "snapshot"
    root.mkdir()
    snapshot.mkdir()
    monkeypatch.setattr(import_guard.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        import_guard, "task_path", lambda root: root / "tasks/example.md"
    )
    monkeypatch.setattr(import_guard, "workflow", lambda root: "tasks/example.md")
    monkeypatch.setattr(import_guard, "base_revision", lambda root: "base")
    monkeypatch.setattr(
        "model.importing.scope.selected", lambda root: ("stg", "cde", "vpc")
    )
    monkeypatch.setattr(import_guard, "require_import_changes", lambda root: None)
    proof = {
        "version": 3,
        "task": "tasks/example.md",
        "base": "base",
        "scope": ["stg", "cde", "vpc"],
        "acquisition": "receipt",
        "sources": {},
        "plan": "verified",
        "complete": True,
        "model": "unchanged",
        "markdown": "unchanged",
        "ownedArtifacts": [],
        "acquiredAt": datetime.now(timezone.utc).isoformat(),
    }
    review_proof_fixture(root, proof)
    sealed_evidence.write_sealed(root, import_guard.proof_path(root), proof)
    import_guard.copy_import_proof(root, snapshot)
    with pytest.raises(ValueError, match="no verified"):
        import_guard.read_proof(snapshot)
    assert (
        import_guard.proof_path(root).read_bytes()
        != import_guard.proof_path(snapshot).read_bytes()
    )
    import_guard.discard_import_proof(snapshot, "tasks/example.md")
    assert (
        not import_guard.proof_path(snapshot).exists()
        and import_guard.read_proof(root) == proof
    )
    assert not (root / ".blueprint").exists() and not (snapshot / ".blueprint").exists()
    import_guard.discard_import_proof(root, "tasks/example.md")


def generic_context(service="datazone", resources=None, **kwargs):
    cli = CloudControlCli(resources or {}, **kwargs)
    target = {
        "environment": "dev",
        "directory": "synthetic",
        "awsAccountId": ACCOUNT,
        "awsRegion": "ap-northeast-1",
    }
    ctx = m.import_context(m.ROOT, target, cli, service)
    ctx.verify()
    return ctx, cli


def domain(identifier="dzd-one"):
    return {
        "identifier": identifier,
        "properties": {
            "Id": identifier,
            "Name": "fixture",
            "DomainVersion": "V2",
            "SingleSignOn": {"Type": "DISABLED"},
        },
    }


def _callback_check_inventory_singleflight_and_isolation_acquire(ctx, /, _):
    assert inventory_for(ctx) is ImportInventory(ctx)
    return m.normalize_records(
        ctx, "datazone", m.inventory(ctx, "datazone", ["DataZone.Domain"])
    )


def check_inventory_singleflight_and_isolation():
    resources = {"DataZone.Domain": [domain(), domain("dzd-two")]}
    ctx, cli = generic_context(resources=resources)
    original = m._normalize_records
    with (
        patch(
            "model.importing.inventory.import_comparison", wraps=import_comparison
        ) as mapping,
        patch.object(m, "_normalize_records", wraps=original) as normalize,
    ):
        acquire = _bind_framework_callback(
            _callback_check_inventory_singleflight_and_isolation_acquire, ctx
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(acquire, range(16)))
        assert all(result == results[0] for result in results)
        assert mapping.call_count == 1 and normalize.call_count == 2
    calls = Counter((s, o, json.dumps(i, sort_keys=True)) for s, o, i in cli.calls)
    assert len(calls) == 5 and set(calls.values()) == {
        1
    }  # STS + two list pages + two detail reads.
    assert ctx.metrics["api_calls"] == 5
    assert (
        ctx.metrics["inventory_normalize_runs"]
        == ctx.metrics["inventory_identity_runs"]
        == 2
    )
    assert ctx.metrics["inventory_mapping_runs"] == 1
    assert inventory_for(ctx).statuses == {"DataZone.Domain": {"status": "complete"}}
    results[0][0]["properties"]["DataZone.Domain.Name"]["value"] = "mutated"
    assert acquire(0)[0]["properties"]["DataZone.Domain.Name"]["value"] == "fixture"
    other, other_cli = generic_context(resources=resources)
    assert inventory_for(other) is not inventory_for(ctx)
    assert (
        len(m.inventory(other, "datazone", ["DataZone.Domain"])) == 2
        and len(other_cli.calls) == 5
    )
    assert results[1][0]["identityComponents"] == [
        {"property": "DataZone.Domain.Id", "value": "dzd-one"}
    ]


def _callback_check_context_api_singleflight_and_failures_call(ctx, /, _):
    return ctx.call(
        "cloudcontrol",
        "get_resource",
        TypeName="AWS::DataZone::Domain",
        Identifier="dzd-one",
    )


def _callback_check_context_api_singleflight_and_failures_denied(failed, /, _):
    with pytest.raises(m.comparator().AcquisitionError, match="AccessDeniedException"):
        failed.call(
            "cloudcontrol",
            "get_resource",
            TypeName="AWS::DataZone::Domain",
            Identifier="dzd-one",
        )


def check_context_api_singleflight_and_failures():
    resources = {"DataZone.Domain": [domain()]}
    ctx, cli = generic_context(resources=resources)
    call = _bind_framework_callback(
        _callback_check_context_api_singleflight_and_failures_call, ctx
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(call, range(32)))
    assert len(cli.calls) == 2
    results[0]["ResourceDescription"]["Identifier"] = "changed"
    assert call(0)["ResourceDescription"]["Identifier"] == "dzd-one"
    failed, failed_cli = generic_context(
        resources=resources,
        fail={("cloudcontrol", "get-resource", "dzd-one"): "AccessDeniedException"},
    )
    denied = _bind_framework_callback(
        _callback_check_context_api_singleflight_and_failures_denied, failed
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(denied, range(16)))
    assert len(failed_cli.calls) == 2
    assert failed.metrics["api_calls"] == 2 and failed.metrics["cache_hits"] >= 15


def check_cloudtrail_all_model_properties():
    ctx, cli = generic_context(
        "cloudtrail",
        {
            "CloudTrail.Trail": [
                {
                    "identifier": "audit",
                    "list": {"TrailName": "audit"},
                    "properties": {"TrailName": "audit"},
                }
            ]
        },
    )
    result = m.normalize_records(ctx, "cloudtrail", m.inventory(ctx, "cloudtrail"))
    assert len(result) == 1 and len(result[0]["properties"]) == 13
    assert all(
        value["status"] == "captured" for value in result[0]["properties"].values()
    )
    assert result[0]["properties"]["CloudTrail.Trail.IsLogging"]["value"] is True
    projected = result[0]["properties"][
        "CloudTrail.Trail.EventSelectors[].DataResources[].Values"
    ]
    assert projected["valueShape"] == "projection"
    assert projected["value"] == [[["arn:aws:s3:::audit-bucket/"]]]
    assert (
        result[0]["properties"]["CloudTrail.Trail.S3BucketName"]["value"]
        == "audit-bucket"
    )
    assert (
        result[0]["properties"]["CloudTrail.Trail.KMSKeyId"]["value"] == "key-confirmed"
    )
    assert len(cli.calls) == 5  # STS, provider discovery, three existing adapter APIs.
    assert not any(operation == "get-resource" for _, operation, _ in cli.calls)
    assert inventory_for(ctx).statuses["CloudTrail.Trail"]["status"] == "complete"


def check_tgw_provider_and_composite_identity():
    resources = {
        "EC2.TransitGateway": [
            {
                "identifier": "tgw-one",
                "properties": {
                    "Id": "tgw-one",
                    "AmazonSideAsn": 64512,
                    "Description": "fixture",
                    "DnsSupport": "enable",
                    "DefaultRouteTableAssociation": "enable",
                    "DefaultRouteTablePropagation": "enable",
                    "AutoAcceptSharedAttachments": "disable",
                    "VpnEcmpSupport": "enable",
                },
            }
        ],
        "EC2.TransitGatewayRouteTable": [
            {
                "identifier": "tgw-rtb-one",
                "properties": {
                    "TransitGatewayRouteTableId": "tgw-rtb-one",
                    "TransitGatewayId": "tgw-one",
                },
            }
        ],
        "EC2.TransitGatewayRoute": [
            {
                "identifier": "opaque-route",
                "properties": {
                    "TransitGatewayRouteTableId": "tgw-rtb-one",
                    "DestinationCidrBlock": "10.0.0.0/16",
                    "TransitGatewayAttachmentId": "tgw-attach-one",
                    "Blackhole": False,
                },
            }
        ],
        "EC2.TransitGatewayRouteTableAssociation": [
            {
                "identifier": "opaque-assoc",
                "properties": {
                    "TransitGatewayRouteTableId": "tgw-rtb-one",
                    "TransitGatewayAttachmentId": "tgw-attach-one",
                },
            }
        ],
        "EC2.TransitGatewayRouteTablePropagation": [
            {
                "identifier": "opaque-propagation",
                "properties": {
                    "TransitGatewayRouteTableId": "tgw-rtb-one",
                    "TransitGatewayAttachmentId": "tgw-attach-one",
                },
            }
        ],
    }
    ctx, cli = generic_context("ec2", resources)
    result = m.normalize_records(ctx, "ec2", m.inventory(ctx, "ec2", list(resources)))
    assert len(result) == 5 and all(
        item["status"] == "complete" for item in inventory_for(ctx).statuses.values()
    )
    assert all(
        value["status"] == "captured"
        for record in result
        for value in record["properties"].values()
    )
    route = next(r for r in result if r["kind"] == "EC2.TransitGatewayRoute")
    assert route["identity"] == "opaque-route" and route["identityProperty"] is None
    assert route["identityComponents"] == [
        {
            "property": "EC2.TransitGatewayRoute.TransitGatewayRouteTableId",
            "value": "tgw-rtb-one",
        },
        {
            "property": "EC2.TransitGatewayRoute.DestinationCidrBlock",
            "value": "10.0.0.0/16",
        },
    ]
    lists = [inputs for _, op, inputs in cli.calls if op == "list-resources"]
    assert len(lists) == 5 and sum("ResourceModel" in inputs for inputs in lists) == 3
    assert len(cli.calls) == 11
    _, compare = comparison(m.ROOT, "ec2")
    assert all(
        compare[prop].field.classification == "supported"
        for record in result
        for prop in record["properties"]
    )


def check_inventory_status_and_partial_retention():
    ctx, cli = generic_context(
        resources={"DataZone.Domain": [domain(), domain("dzd-two")]},
        fail={("cloudcontrol", "get-resource", "dzd-two"): "AccessDeniedException"},
    )
    records = m.normalize_records(
        ctx, "datazone", m.inventory(ctx, "datazone", ["DataZone.Domain"])
    )
    assert len(records) == 1 and records[0]["identity"] == "dzd-one"
    assert (
        inventory_for(ctx).statuses["DataZone.Domain"]["status"] == "permission_denied"
    )
    count = len(cli.calls)
    assert (
        len(m.inventory(ctx, "datazone", ["DataZone.Domain"])) == 1
        and len(cli.calls) == count
    )
    evidence = {
        "version": 3,
        "modelFormat": 2,
        "snapshotVersion": 2,
        "referenceMeaningVersion": 1,
        "inventory": inventory_for(ctx).statuses,
    }
    assert not import_guard.acquisition_complete(evidence)
    empty, _ = generic_context()
    assert m.inventory(empty, "datazone", ["DataZone.Domain"]) == []
    assert inventory_for(empty).statuses["DataZone.Domain"]["status"] == "empty"
    assert import_guard.acquisition_complete(
        {
            "version": 3,
            "modelFormat": 2,
            "snapshotVersion": 2,
            "referenceMeaningVersion": 1,
            "inventory": inventory_for(empty).statuses,
        }
    )
    assert m.inventory(empty, "datazone", ["DataZone.DataSource"]) == []
    assert (
        inventory_for(empty).statuses["DataZone.DataSource"]["status"] == "not_modelled"
    )
    with pytest.raises(ValueError, match="owner"):
        m.inventory(empty, "datazone", ["EC2.TransitGateway"])
    for payload in ({}, {"logGroups": None}, {"logGroups": "invalid"}):
        cli = aws()
        cli.responses["logs", "describe-log-groups"] = payload
        ctx = m.import_context(
            m.ROOT,
            {
                "environment": "dev",
                "directory": "cde",
                "awsAccountId": ACCOUNT,
                "awsRegion": "ap-northeast-1",
                "awsProfile": "confirmed",
            },
            cli,
            "cloudwatch-logs",
        )
        ctx.verify()
        assert m.inventory(ctx, "cloudwatch-logs", ["Logs.LogGroup"]) == []
        assert inventory_for(ctx).statuses["Logs.LogGroup"] == {
            "status": "failed",
            "reason": "InvalidInventoryResponse",
        }
        assert not import_guard.acquisition_complete(
            {"version": 3, **FORMAT_FIELDS, "inventory": inventory_for(ctx).statuses}
        )


def check_cloudcontrol_json_and_readonly_boundary():
    for value in ("null", "[]", '{"Id":1,"Id":2}', '{"Id":NaN}', "{invalid", {}, None):
        with pytest.raises((ValueError, TypeError)):
            properties_json(value)
    target = {
        "environment": "dev",
        "directory": "synthetic",
        "awsAccountId": ACCOUNT,
        "awsRegion": "ap-northeast-1",
    }
    ctx = m.import_context(m.ROOT, target, CloudControlCli({}), "datazone")
    with pytest.raises(ValueError, match="verified"):
        ctx.call("cloudcontrol", "list_resources", TypeName="AWS::DataZone::Domain")
    ctx.verify()
    for operation in ("create_resource", "update_resource", "delete_resource"):
        with pytest.raises(ValueError, match="allowlist"):
            ctx.call("cloudcontrol", operation)
    with pytest.raises(ValueError, match="allowlist"):
        ctx.call("datazone", "get_domain", identifier="unvalidated-selector")
    datazone = m.comparator().Context(m.ROOT, target, services=("datazone",))
    assert datazone.allowed == {
        ("sts", "get_caller_identity"),
        ("datazone", "get_project"),
    }


def _callback_check_composite_identity_same_resource_only_values(
    kind, props, /, rid, table, attachment
):
    result = {
        f"desired.resource.{rid}.logicalId": kind.replace(".", "_") + "_" + rid,
        f"desired.resource.{rid}.resourceType": kind,
        f"desired.resource.{rid}.resourceMode": "IMPORT",
        "desired.service.identity.lastAllocated": json.dumps({kind: int(rid)}),
    }
    for n, (prop, value) in enumerate(zip(props, (table, attachment), strict=False), 1):
        if value is not None:
            result[f"desired.row.{rid}-{n:03d}.property"] = prop
            result[f"desired.row.{rid}-{n:03d}.value"] = "`" + value + "`"
            result[f"desired.row.{rid}-{n:03d}.comment"] = "合成関連付け"
    return result


def check_composite_identity_same_resource_only():
    kind = "EC2.TransitGatewayRouteTableAssociation"
    props = [kind + ".TransitGatewayRouteTableId", kind + ".TransitGatewayAttachmentId"]
    values = _bind_framework_callback(
        _callback_check_composite_identity_same_resource_only_values, kind, props
    )
    captured = {
        "record": "assoc",
        "kind": kind,
        "identity": "opaque",
        "identityProperty": None,
        "identityProperties": props,
        "identityStatus": "known",
        "identityComponents": [
            {"property": p, "value": v}
            for p, v in zip(props, ("table-a", "attachment-b"), strict=False)
        ],
        "properties": {
            p: {"status": "captured", "value": v}
            for p, v in zip(props, ("table-a", "attachment-b"), strict=False)
        },
    }
    old = {
        **values("001", "table-a", "attachment-a"),
        **values("002", "table-b", "attachment-b"),
    }
    new = {**old, **values("009", "table-a", "attachment-b")}
    new["desired.resource.009.logicalId"] = kind.replace(".", "_") + "_003"
    new["desired.service.identity.lastAllocated"] = json.dumps({kind: 3})
    selected = selection_records(
        selection("assoc", "009"), [captured], old, new, schema_for
    )
    assert verify_values(expansion(old), expansion(new), selected, schema_for)
    old_same = values("001", "table-a", "attachment-b")
    with pytest.raises(ValueError, match="duplicate identity"):
        selection_records(
            selection("assoc", "009"),
            [captured],
            old_same,
            {**old_same, **values("009", "table-a", "attachment-b")},
            schema_for,
        )
    partial = values("001", "table-a", None)
    warnings = []
    selection_records(
        selection("assoc", "009"),
        [captured],
        partial,
        {**partial, **values("009", "table-a", "attachment-b")},
        schema_for,
        warnings,
    )
    assert warnings and warnings[0]["existingResources"] == ["001"]
    invalid = {**new, "desired.row.009-002.value": "`wrong`"}
    with pytest.raises(ValueError, match="differs|identity"):
        verify_values(expansion(old), expansion(invalid), selected, schema_for)


# Plain copies of the fixture schema; no static singleton mutation.
def _callback_check_inventory_capability_outcomes_schema(case, /, kind):
    # Plain copies of the fixture schema; no static singleton mutation.
    data = {
        "handlers": {"list": {}, "read": {}},
        "primaryIdentifier": ["/properties/Id"],
        "required": ["Name"],
    }
    if case == "no-list":
        del data["handlers"]["list"]
    elif case == "no-read":
        del data["handlers"]["read"]
    elif case == "filter":
        data["handlers"]["list"]["handlerSchema"] = {"required": ["UnboundScope"]}
    return readonly(data)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("no-list", "unsupported"),
        ("no-read", "unsupported"),
        ("filter", "requires_filter"),
        ("missing", "failed"),
    ],
)
def check_inventory_capability_outcomes(case, expected):
    item = domain()
    if case == "missing":
        del item["properties"]["Name"]
    ctx, cli = generic_context(resources={"DataZone.Domain": [item]})
    inv = inventory_for(ctx)
    schema = _bind_framework_callback(
        _callback_check_inventory_capability_outcomes_schema, case
    )
    with patch.object(inv, "schema", side_effect=schema):
        records = m.normalize_records(
            ctx, "datazone", m.inventory(ctx, "datazone", ["DataZone.Domain"])
        )
    assert inv.statuses["DataZone.Domain"]["status"] == expected
    assert len(records) == (1 if case == "missing" else 0)
    count = len(cli.calls)
    assert len(inv.inventory("datazone", "DataZone.Domain")) == len(records)
    assert len(cli.calls) == count


def _check_fetch_singleflight_and_trace_get(context, resource, getter):
    return context.call(
        "cloudcontrol",
        "get_resource",
        TypeName="AWS::DataZone::Domain",
        Identifier="dzd-one",
    )


def check_fetch_singleflight_and_trace():
    ctx, cli = generic_context(resources={"DataZone.Domain": [domain()]})
    get = _check_fetch_singleflight_and_trace_get
    path = (
        ctx.root
        / "model"
        / ctx.target["environment"]
        / ctx.target["directory"]
        / "datazone.properties"
    )
    resource = SimpleNamespace(
        model=SimpleNamespace(path=path),
        number="one",
        module=SimpleNamespace(fetch=get),
    )
    with patch.object(resource.module, "fetch", wraps=get) as fetch:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(lambda _: ctx.fetch(resource, "provider"), range(16))
            )
        assert fetch.call_count == 1 and len(cli.calls) == 2
    assert results[0] == results[-1]
    assert ctx.fetch_trace[resource.model.path, "one", "provider"] == [
        {
            "api": "cloudcontrol.get_resource",
            "inputs": {"TypeName": "AWS::DataZone::Domain", "Identifier": "dzd-one"},
        }
    ]
    inv = inventory_for(ctx)
    inv.mapping("datazone")
    inv.mapping("datazone")
    assert ctx.metrics["inventory_mapping_runs"] == 1
    record = {
        "kind": "DataZone.Domain",
        "identity": "one",
        "cloudProperties": {"Id": "one"},
    }
    inv.identity("DataZone.Domain", record)
    inv.identity("DataZone.Domain", record)
    assert ctx.metrics["inventory_identity_runs"] == 1
    inv.property_schema("DataZone.Domain.Name")
    inv.property_schema("DataZone.Domain.Name")
    assert ctx.metrics["inventory_property_schema_runs"] == 1
    ctx.target["awsRegion"] = "us-east-1"
    with pytest.raises(ValueError, match="connection changed"):
        ctx.call(
            "cloudcontrol",
            "get_resource",
            TypeName="AWS::DataZone::Domain",
            Identifier="dzd-one",
        )


def check_tgw_compare_provider_evaluation():
    kind = "EC2.TransitGatewayRouteTableAssociation"
    identifier = "table-one|attachment-one"
    payload = {
        "TransitGatewayRouteTableId": "table-one",
        "TransitGatewayAttachmentId": "attachment-one",
    }
    ctx, cli = generic_context(
        "ec2", {kind: [{"identifier": identifier, "properties": payload}]}
    )
    ctx.import_mode = False  # Exercise the unchanged Compare service gate plus the explicit TGW capability.
    model = SimpleNamespace(
        ctx=ctx,
        path=ctx.root / "model/dev/synthetic/ec2.properties",
        service="ec2",
        values={},
    )
    rows = [
        (str(i), {"property": kind + "." + prop, "value": "`" + actual + "`"})
        for i, (prop, actual) in enumerate(payload.items())
    ]
    resource = m.comparator().Resource(model, "001", {"resourceType": kind}, rows)
    mapping, mapped = comparison(m.ROOT, "ec2")
    for prop, expected in payload.items():
        key = kind + "." + prop
        assert mapped_value(ctx, resource, mapping, mapped[key], key)[1] == expected
    assert resource.identity() == identifier
    assert len(cli.calls) == 2 and cli.calls[-1][2]["Identifier"] == identifier
    gateway, gateway_cli = generic_context(
        "ec2",
        {
            "EC2.TransitGateway": [
                {"identifier": "tgw-one", "properties": {"Id": "tgw-one"}}
            ]
        },
    )
    gateway.import_mode = False
    model = SimpleNamespace(
        ctx=gateway,
        path=gateway.root / "model/dev/synthetic/ec2.properties",
        service="ec2",
        values={"observed.row.001-001.value": "`tgw-one`"},
    )
    resource = m.comparator().Resource(
        model,
        "001",
        {
            "resourceType": "EC2.TransitGateway",
            "logicalId": "EC2_TransitGateway_001",
            "anchor": "gateway",
        },
        [
            (
                "001-001",
                {
                    "property": "EC2.TransitGateway.Id",
                    "value": "[gateway](ec2.md#gateway)",
                },
            )
        ],
    )
    assert resource.identity() == "tgw-one" and len(gateway_cli.calls) == 2
    model.values.clear()
    with pytest.raises(m.comparator().Unresolved, match="observation"):
        resource.identity()


def check_import_profile_mode_delegation():
    target = {
        "environment": "dev",
        "directory": "synthetic",
        "awsAccountId": ACCOUNT,
        "awsRegion": "ap-northeast-1",
        "awsProfile": "configured",
    }
    cli = CloudControlCli({})
    with patch.object(m, "import_profile", return_value=None) as select:
        ctx = m.import_context(m.ROOT, target, cli, "datazone", no_profile=True)
        select.assert_called_once_with(target, no_profile=True)
    assert "awsProfile" not in ctx.target and target["awsProfile"] == "configured"
    assert ctx.verify() == ACCOUNT
    assert len(cli.calls) == 1 and cli.calls[0][0:2] == ("sts", "get-caller-identity")


def check_subnet_route_table_association_normalization():
    cli = aws("vpc")
    subnet = cli.responses[("ec2", "describe-subnets")]["Subnets"][0]
    cli.responses[("ec2", "describe-route-tables")] = {
        "RouteTables": [
            {
                "RouteTableId": "rtb-00000000000000001",
                "VpcId": subnet["VpcId"],
                "Associations": [
                    {
                        "RouteTableAssociationId": "rtbassoc-00000000000000001",
                        "SubnetId": subnet["SubnetId"],
                        "AssociationState": {"State": "associated"},
                    }
                ],
            }
        ]
    }
    target = {
        "environment": "dev",
        "directory": "cde",
        "awsAccountId": ACCOUNT,
        "awsRegion": "ap-northeast-1",
        "awsProfile": "confirmed",
    }
    ctx = m.import_context(m.ROOT, target, cli, "vpc")
    ctx.verify()
    records = m.normalize_records(
        ctx, "vpc", m.inventory(ctx, "vpc", ["EC2.Subnet", "EC2.RouteTable"])
    )
    selected = next(r for r in records if r["identity"] == subnet["SubnetId"])
    association = selected["properties"]["EC2.SubnetRouteTableAssociation.RouteTableId"]
    assert association["status"] == "captured"
    assert association["value"] == "rtb-00000000000000001"
    assert inventory_for(ctx).statuses["EC2.Subnet"]["status"] == "complete"


def check_legacy_adapter_api_counts():
    # Baseline counts are physical mock transport invocations on the identical fixture.
    expected = {
        "vpc": 7,
        "config": 3,
        "cloudwatch-logs": 2,
        "data-firehose": 3,
        "quicksight": 8,
        "security-hub": 2,
        "transit-gateway": 2,
    }
    measured = {}
    for service in SERVICES:
        cli = aws(service)
        target = {
            "environment": "dev",
            "directory": "cde",
            "awsAccountId": ACCOUNT,
            "awsRegion": "ap-northeast-1",
            "awsProfile": "confirmed",
        }
        ctx = m.import_context(m.ROOT, target, cli, service)
        ctx.verify()
        records = m.inventory(ctx, service)
        m.normalize_records(ctx, service, records)
        first = len(cli.calls)
        m.normalize_records(ctx, service, m.inventory(ctx, service))
        assert len(cli.calls) == first
        measured[service] = first
    assert measured == expected


@pytest.mark.parametrize(
    "account,region",
    [("999999999999", "ap-northeast-1"), ("123456789012", "us-east-1")],
)
def check_acquisition_account_region_isolation(account, region):
    first, _ = generic_context(resources={"DataZone.Domain": [domain()]})
    first_records = m.inventory(first, "datazone", ["DataZone.Domain"])
    cli = CloudControlCli({"DataZone.Domain": [domain("dzd-other")]}, account=account)
    target = {
        "environment": "dev",
        "directory": "synthetic",
        "awsAccountId": account,
        "awsRegion": region,
    }
    second = m.import_context(m.ROOT, target, cli, "datazone")
    second.verify()
    records = m.inventory(second, "datazone", ["DataZone.Domain"])
    assert (
        records[0]["identity"] == "dzd-other"
        and first_records[0]["identity"] == "dzd-one"
    )
    assert inventory_for(second) is not inventory_for(first) and len(cli.calls) == 3
    with pytest.raises(TypeError):
        inventory_for(second).schema("DataZone.Domain")["primaryIdentifier"] = []


def check_resource_type_cli_selection(tmp_path):
    arguments = [
        "acquire",
        "--repository-root",
        str(tmp_path),
        "--environment",
        "dev",
        "--service",
        "ec2",
        "--resource-type",
        "EC2.TransitGateway",
        "--resource-type",
        "EC2.TransitGatewayRouteTable",
    ]
    with patch.object(
        m, "acquire", return_value={"status": "acquired", "markdown": "not-run"}
    ) as acquire:
        assert m.main(arguments) == 0
        assert acquire.call_args.kwargs["resource_types"] == [
            "EC2.TransitGateway",
            "EC2.TransitGatewayRouteTable",
        ]


def check_unknown_acquired_identity_rejected():
    captured = record()
    captured.update(
        identityStatus="unknown",
        identityComponents=[{"property": "EC2.VPC.VpcId", "value": None}],
    )
    with pytest.raises(ValueError, match="identity is unknown"):
        selection_records(selection(), [captured], {}, resource(), schema_for)
    with pytest.raises(ValueError, match="inventory status"):
        import_guard.acquisition_complete(
            {"version": 3, **FORMAT_FIELDS, "inventory": {}}
        )
    for version in (1, 2, 99):
        with pytest.raises(ValueError, match="format is incompatible"):
            import_guard.acquisition_complete({"version": version})


def check_batch_model_operation(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    contract, sources = batch_operation_fixture(before, after)
    verify_model_operation(before, after, model_operation(contract), sources)
    observed_file = after / "model/stg/cde/vpc.properties"
    observed = dict(load_model(observed_file).authoritative)
    observed["observed.row.013-001.value"] = "not-transferred"
    write_model(observed_file, observed)
    with pytest.raises(ValueError, match="not.*transfer"):
        verify_model_operation(before, after, model_operation(contract), sources)


@pytest.mark.parametrize("action", ["import-merge", "import-delete"])
def check_intermediate_source_context(tmp_path, monkeypatch, action):
    start = _imports_task_contract.start
    operation_fixture(tmp_path)
    path = tmp_path / "model/stg/cde/vpc.properties"
    raw = dict(load_model(path).authoritative)
    name = "tasks/parent.md"
    listed = "\n".join(
        "- `" + value + "`" for value in [name, path.relative_to(tmp_path).as_posix()]
    )
    text = (
        operation_contract(action)
        + "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        + "## Validation scope\n- `stg/cde/vpc`\n## Modified files\n"
        + listed
        + "\n## Allowed paths\n"
        + listed
        + "\n"
    )
    start(tmp_path, name, text)
    if action == "import-delete":
        issues = tmp_path / "issues/stg/cde/issues.md"
        issues.parent.mkdir(parents=True)
        issues.write_text("### vpc\n1. 削除前の既存Issue\n", encoding="utf-8")
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/wrong.md")
    candidate = serialize(raw) + "# intermediate save\n"
    with (
        patch.object(
            GenerationInputs,
            "open_stage",
            side_effect=AssertionError("intermediate save cannot stage"),
        ),
        patch(
            "model.operations.verify_model_operation",
            side_effect=AssertionError(
                "intermediate save cannot run final whole-design proof"
            ),
        ),
    ):
        with source_write_context(tmp_path, name) as first:
            assert publish_edit(
                prepare_edit(
                    load_model(path, first.snapshot), {path: candidate}, first
                ),
                first,
            ) == (path,)
            with pytest.raises(ValueError, match="open authorized source context"):
                prepare_edit(load_model(path), {}, first)
        assert path.read_text() == candidate
        with source_write_context(tmp_path, name) as second:
            assert (
                publish_edit(
                    prepare_edit(
                        load_model(path, second.snapshot), {path: candidate}, second
                    ),
                    second,
                )
                == ()
            )
        with source_write_context(tmp_path, name) as third:
            before = load_model(path, third.snapshot)
            path.write_text(candidate + "# outside edit\n")
            with pytest.raises(ValueError, match="changed"):
                publish_edit(prepare_edit(before, {path: serialize(raw)}, third), third)
        with source_write_context(tmp_path, name) as fourth:
            with pytest.raises(ValueError, match="unregistered"):
                prepare_edit(
                    load_model(path, fourth.snapshot),
                    {tmp_path / "project.json": "{}"},
                    fourth,
                )
        with source_write_context(tmp_path, name) as fifth:
            with pytest.raises(ValueError, match="format|properties"):
                prepare_edit(
                    load_model(path, fifth.snapshot), {path: "invalid\n"}, fifth
                )
        assert path.read_text() == candidate + "# outside edit\n"
    assert __import__("os").environ["BLUEPRINT_TASK_FILE"] == "tasks/wrong.md"


@pytest.mark.parametrize(
    "field",
    ["value", "document", "parentReference", "name", "identifier", "reevaluation"],
)
def check_explicit_reference_operation(tmp_path, field):
    before, after = tmp_path / "before", tmp_path / "after"
    operation_fixture(before)
    file = before / "model/stg/cde/vpc.properties"
    values = dict(load_model(file).authoritative)
    external = field in {"name", "identifier", "reevaluation"}
    if external:
        for rid, name in [("001", "destination-name"), ("009", "source-name")]:
            values.update(
                {
                    f"desired.row.{rid}-004.property": "EC2.VPC.Name",
                    f"desired.row.{rid}-004.value": name,
                    f"desired.row.{rid}-004.comment": "名前",
                }
            )
    source = "001" if field == "reevaluation" else "009"
    raw = (
        "vpc-source"
        if field == "identifier"
        else "destination-name"
        if field == "reevaluation"
        else "source-name"
        if external
        else "[009](#vpc-imported)"
    )
    allocation_state = json.loads(values["desired.service.identity.lastAllocated"])
    values.update(
        resource_values(
            "020",
            "EC2.Subnet",
            "subnet-keep",
            "CREATE",
            [
                (
                    "Policy" if field == "document" else "VpcId",
                    "[JSON](vpc/policy.json)" if field == "document" else raw,
                ),
                ("CidrBlock", "`10.2.0.0/24`"),
            ],
        )
    )
    allocation_state["EC2.Subnet"] = 20
    values["desired.service.identity.lastAllocated"] = json.dumps(allocation_state)
    key = "desired.row.020-001." + ("document" if field == "document" else "value")
    if field == "document":
        values[key] = json.dumps({"Vpc": raw, "Sibling": True})
    mode = "identifier" if field == "identifier" else "name" if external else "link"
    values.update(
        reference_fields(
            "vpc",
            key,
            raw,
            "stg/cde/vpc/" + source,
            kind="EC2.VPC",
            mode=mode,
            prop="EC2.VPC.VpcId" if field == "identifier" else "EC2.VPC.Name",
            pointer="/Vpc" if field == "document" else None,
        )
    )
    if field == "parentReference":
        values["desired.resource.020.parentReference"] = raw
        values["desired.resource.020.parentProperty"] = "EC2.Subnet.VpcId"
        values.update(
            reference_fields(
                "parent",
                "desired.resource.020.parentReference",
                raw,
                "stg/cde/vpc/009",
                kind="EC2.VPC",
                mode="link",
            )
        )
    write_model(file, values)
    assert any(
        usage.metadata_id == "vpc" and usage.producer_id == source
        for usage in usages(load_model(file))
    )
    sources = operation_candidate(before, after)
    file = after / file.relative_to(before)
    values = dict(load_model(file).authoritative)
    updated = (
        "vpc-source"
        if field == "identifier"
        else "source-name"
        if external
        else "[001](#vpc-main)"
    )
    values[key] = (
        json.dumps({"Vpc": updated, "Sibling": True})
        if field == "document"
        else updated
    )
    values["desired.reference.vpc.producerLogicalId"] = "EC2_VPC_001"
    values["desired.reference.vpc.text"] = updated
    if field == "parentReference":
        values["desired.resource.020.parentReference"] = updated
        values["desired.reference.parent.producerLogicalId"] = "EC2_VPC_001"
        values["desired.reference.parent.text"] = updated
    write_model(file, values)
    contract = (
        operation_contract()
        .split("## Model merge pairs")[0]
        .split("## Model delete sources")[0]
        + "## Model merge pairs\n- "
        + json.dumps({"source": "stg/cde/vpc/009", "destination": "stg/cde/vpc/001"})
        + "\n"
    )
    reference = {
        "consumer": "stg/cde/vpc/020",
        "field": "value" if external else field,
        "source": "stg/cde/vpc/" + source,
        "destination": "stg/cde/vpc/001",
    }
    if field != "parentReference":
        reference["property"] = (
            "EC2.Subnet.Policy" if field == "document" else "EC2.Subnet.VpcId"
        )
    if field == "document":
        reference["pointer"] = "/Vpc"
    references = [reference]
    if field == "parentReference":
        references.append(
            {**reference, "field": "value", "property": "EC2.Subnet.VpcId"}
        )
    full_contract = (
        contract
        + "## Model reference changes\n"
        + "".join("- " + json.dumps(item) + "\n" for item in references)
    )
    verify_model_operation(before, after, model_operation(full_contract), sources)
    with pytest.raises(ValueError, match="unspecified|undeclared|parent"):
        verify_model_operation(before, after, model_operation(contract), sources)
    values[key] = (
        json.dumps({"Vpc": "prefix-" + updated, "Sibling": True})
        if field == "document"
        else "prefix-" + updated
    )
    write_model(file, values)
    with pytest.raises(ValueError, match="affix|literal|changed"):
        verify_model_operation(before, after, model_operation(full_contract), sources)


@pytest.mark.parametrize("selection", ["fixed", "instance"])
def check_effective_reference_identity(tmp_path, selection, monkeypatch):
    dependency_fixture(tmp_path)
    before = {p: p.read_bytes() for p in (tmp_path / "model").rglob("*") if p.is_file()}
    # Legacy instance selection is converted to an explicit fixed producer identity.
    with (
        input_context(read_only=True),
        patch.object(sources, "_read_model", wraps=sources._read_model) as body,
    ):
        producer = load_model(tmp_path / "model/stg/cde/service-a.properties")
        consumer = load_model(tmp_path / "model/stg/cde/service-b.properties")
        records = usages(consumer)
        assert len(records) == 1 and records[0].producer_id == "001"
        assert records[0].metadata_id == "origin" and records[0].text == "same-name-stg"
        assert len(incoming(producer, "001")) == 1
        assert incoming(producer, "003") == ()
        count = body.call_count
        assert load_model(consumer.scope) is consumer
        assert body.call_count == count
    assert all(p.read_bytes() == raw for p, raw in before.items())
    after = tmp_path / "after"
    changed = dependency_refactor(tmp_path, after)
    verify_model_refactor(
        tmp_path,
        after,
        model_refactor(dependency_contract()),
        changed,
        {("dev", "cde", "service-b"), ("stg", "cde", "service-b")},
    )


def check_local_reference_effective_identity(tmp_path):
    dependency_fixture(tmp_path)
    file = tmp_path / "model/stg/cde/service-a.properties"
    values = dict(load_model(file).authoritative)
    values["desired.row.001-002.value"] = "[other](service-a.md#other-producer)"
    write_model(file, values)
    model = load_model(file)
    (record,) = usages(model)
    assert (
        record.producer_scope == "stg/cde/service-a"
        and record.logical_id == "ServiceA_Resource_003"
    )
    assert (
        model.values["desired.row.001-002.value"]
        == "[other](service-a.md#other-producer)"
    )


def check_stack_reference_usage_identity(tmp_path):
    dependency_fixture(tmp_path)
    write_model(
        tmp_path / "model/stg/cde/cloudformation-stacks.properties",
        {
            "desired.stack.001.name": "ExampleStack",
            "desired.stack.001.template": "example.yaml",
            "desired.stack.001.parameters": "example.json",
            "desired.stack.001.deployOrder": "1",
        },
    )
    file = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    values["display.resource.002.label"] = "ExampleStack"
    fields = {
        "consumerKey": "display.resource.002.label",
        "text": "ExampleStack",
        "occurrence": "1",
        "producerKind": "stack",
        "producerScope": "stg/cde/cloudformation-stacks",
        "producerId": "001",
        "format": "name",
        "property": "name",
        "labelPolicy": "none",
    }
    values.update(
        {"desired.reference.stack-label." + key: raw for key, raw in fields.items()}
    )
    write_model(file, values)
    model = load_model(file)
    (stack,) = [usage for usage in usages(model) if usage.producer_kind == "stack"]
    assert (
        stack.producer_scope == "stg/cde/cloudformation-stacks"
        and stack.producer_id == "001"
    )
    assert (
        stack.text == "ExampleStack"
        and stack.consumer_key == "display.resource.002.label"
    )
    assert (
        len(
            incoming(load_model(tmp_path / "model/stg/cde/service-a.properties"), "001")
        )
        == 1
    )


@pytest.mark.parametrize("failure", ["missing-id", "type"])
def check_reference_target_diagnostics(tmp_path, failure, capsys, monkeypatch):
    dependency_fixture(tmp_path)
    file = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    field, raw = (
        ("producerLogicalId", "ServiceA_Resource_999")
        if failure == "missing-id"
        else ("resourceType", "Other.Resource")
    )
    values["desired.reference.origin." + field] = raw
    write_model(file, values)
    diagnosis = load_model(file)
    assert (
        diagnosis.warnings
        and diagnosis.values["desired.row.002-001.value"] == "same-name-stg"
    )
    warnings = []
    producer = load_model(tmp_path / "model/stg/cde/service-a.properties")
    assert not incoming(producer, "003", warnings=warnings)
    assert warnings and warnings[0]["scope"] == "stg/cde/service-b"
    assert (
        warnings[0]["consumerKey"] == "desired.row.002-001.value"
        and warnings[0]["reference"] == "origin"
    )
    assert main(["incoming", str(producer.scope.path), "003"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert (
        result["status"] == "incomplete"
        and result["warnings"] == warnings
        and result["references"] == []
    )


@pytest.mark.parametrize(
    "broken", [None, "collision", "missing", "type", "format", "name", "shape"]
)
def check_stack_reference_usage(tmp_path, broken):
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    stack = before / "model/stg/cde/cloudformation-stacks.properties"
    values = {
        "desired.stack.028.name": "fixture-stack",
        "desired.stack.028.template": "stack.yaml",
        "desired.stack.028.parameters": "stack.json",
        "desired.stack.028.deployOrder": "10",
        "desired.stack.028.placementName": "fixed-placement",
    }
    if broken == "collision":
        # Explicit producerKind distinguishes the Resource and Stack namespaces.
        values.update(
            resource_values("028", "CloudFormation.Stack", "collision", "IMPORT", [])
        )
    elif broken == "name":
        values["desired.stack.028.name"] = "changed-stack"
    elif broken == "shape":
        del values["desired.stack.028.template"]
    write_model(stack, values)
    file = before / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    key = "desired.row.002-001.document"
    values[key] = json.dumps(
        {
            "a/b": [
                "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/fixture-stack/*"
            ]
        }
    )
    fields = {
        "consumerKey": key,
        "pointer": "/a~1b/0",
        "text": "fixture-stack",
        "occurrence": "1",
        "producerKind": "stack",
        "producerScope": "stg/cde/cloudformation-stacks",
        "producerId": "028",
        "format": "name",
        "property": "name",
        "labelPolicy": "none",
    }
    if broken == "missing":
        fields["producerId"] = "999"
    elif broken == "type":
        fields["resourceType"] = "IAM.Role"
    elif broken == "format":
        fields["format"] = "link"
    values.update(
        {
            "desired.reference.stack-document." + field: raw
            for field, raw in fields.items()
        }
    )
    write_model(file, values)
    if broken in {"type", "format", "shape", "collision"}:
        with pytest.raises(ValueError):
            load_model(file)
        return
    model = load_model(file)
    records = [usage for usage in usages(model) if usage.producer_kind == "stack"]
    (record,) = records
    assert (
        record.consumer_key == key
        and record.pointer == "/a~1b/0"
        and record.metadata_id == "stack-document"
    )
    assert record.text == "fixture-stack" and record.producer_id == fields["producerId"]
    if broken in {"missing", "name"}:
        assert model.warnings and model.authoritative[key] == values[key]
        return
    assert not model.warnings
    assert incoming(load_model(before / "model/stg/cde/service-a.properties"), "001")
    assert not incoming(
        load_model(before / "model/stg/cde/service-a.properties"), "003"
    )
    origin, line = model.locations[key]
    assert origin == file and file.read_text().splitlines()[line - 1].startswith(
        key + "="
    )
    saved = {p: p.read_bytes() for p in (before / "model").rglob("*") if p.is_file()}
    assert load_model(file).authoritative[key] == values[key]
    assert all(p.read_bytes() == raw for p, raw in saved.items())
    shutil.copytree(before, after)
    file = after / "model/stg/cde/service-a.properties"
    values = dict(load_model(file).authoritative)
    write_model(
        file,
        {
            key: raw
            for key, raw in values.items()
            if owner(key, values) != ("resource", "003")
        },
    )
    verify_model_operation(
        before,
        after,
        model_operation(
            operation_contract("import-delete", source="stg/cde/service-a/003")
        ),
        {file.relative_to(after).as_posix()},
    )


def check_generic_reference_usage(tmp_path):
    dependency_fixture(tmp_path)
    before = {p: p.read_bytes() for p in (tmp_path / "model").rglob("*") if p.is_file()}
    producer = load_model(tmp_path / "model/stg/cde/service-a.properties")
    consumer = load_model(tmp_path / "model/stg/cde/service-b.properties")
    scope, record = incoming(producer, "001")[0]
    assert scope == consumer.scope
    assert (
        record.consumer_key == "desired.row.002-001.value"
        and record.metadata_id == "origin"
    )
    assert record.producer_scope == "stg/cde/service-a" and record.producer_id == "001"
    assert record.text == "same-name-stg"
    file, line = consumer.locations[record.consumer_key]
    assert file.relative_to(tmp_path).as_posix() == "model/stg/cde/service-b.properties"
    assert (
        file.read_text().splitlines()[line - 1]
        == record.consumer_key + "=same-name-stg"
    )
    assert not incoming(producer, "003") and not incoming(producer, "999")
    reverse = [
        usage
        for usage in usages(producer)
        if usage.consumer_key.startswith("desired.row.001-")
    ]
    assert (
        len(reverse) == 1
        and reverse[0].producer_scope == "stg/cde/service-b"
        and reverse[0].logical_id == "ServiceB_Resource_002"
    )
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize("selected", [False, True])
def check_reference_active_shapes_and_documents(tmp_path, selected):
    dependency_fixture(tmp_path)
    file = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    if not selected:
        values = {
            key: raw
            for key, raw in values.items()
            if not key.startswith("desired.reference.origin.")
        }
    values["display.resource.002.comment"] = (
        "説明 [producer](./service-a.md#producer) same-name-stg"
    )
    write_model(file, values)
    records = usages(load_model(file))
    assert len(records) == (1 if selected else 0)
    assert not any(record.consumer_key.startswith("display.") for record in records)
    key = "desired.row.002-001.document"
    values[key] = '{"a/b":["same-name-stg"]}'
    values.update(
        reference_fields(
            "document", key, "same-name-stg", "stg/cde/service-a/001", pointer="/a~1b/0"
        )
    )
    write_model(file, values)
    model = load_model(file)
    (record,) = [record for record in usages(model) if record.pointer is not None]
    assert record.pointer == "/a~1b/0" and record.text == "same-name-stg"
    origin, line = model.locations[key]
    assert origin == file and file.read_text().splitlines()[line - 1].startswith(
        key + "="
    )
    assert model.authoritative[key] == '{"a/b":["same-name-stg"]}'


@pytest.mark.parametrize("broken", ["unknown", "cycle", "link", "missing-input"])
def check_reference_fail_closed(tmp_path, broken):
    dependency_fixture(tmp_path)
    file = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    if broken == "missing-input":
        file.write_text(
            "# model-format: 2\n# model-index: 2\n# part: service-b/part-001.properties\n"
        )
        with pytest.raises(ValueError, match="missing Model part"):
            incoming(load_model(tmp_path / "model/stg/cde/service-a.properties"), "001")
        return
    if broken == "unknown":
        values["desired.reference.origin.producerLogicalId"] = "ServiceA_Resource_999"
    elif broken == "link":
        values["display.resource.002.comment"] = "[missing](service-a.md#missing)"
    else:
        # Saved names may describe cycles; reads do not execute a recursive expansion.
        a = tmp_path / "model/stg/cde/service-a.properties"
        other = dict(load_model(a).authoritative)
        other.update(
            reference_fields(
                "cycle",
                "desired.row.001-001.value",
                "same-name-stg",
                "stg/cde/service-b/002",
                kind="ServiceB.Resource",
                prop="ServiceB.Resource.Name",
            )
        )
        write_model(a, other)
    write_model(file, values)
    model = load_model(file)
    if broken == "cycle":
        assert (
            not model.warnings
            and model.authoritative["desired.row.002-001.value"] == "same-name-stg"
        )
    else:
        assert bool(model.warnings) == (broken == "unknown")
        assert model.authoritative["desired.row.002-001.value"] == "same-name-stg"


def check_value_preserving_detach_and_single_deletions(tmp_path):
    dependency_contract = _imports_support_import_model_fixtures.dependency_contract
    dependency_fixture = _imports_support_import_model_fixtures.dependency_fixture
    dependency_refactor = _imports_support_import_model_fixtures.dependency_refactor
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    sources = dependency_refactor(before, after)
    verify_model_refactor(
        before,
        after,
        model_refactor(dependency_contract()),
        sources,
        {("stg", "cde", "service-b")},
    )
    assert not incoming(load_model(after / "model/stg/cde/service-a.properties"), "001")
    assert incoming(load_model(after / "model/dev/cde/service-a.properties"), "001")
    previous = after
    for service, rid in [("service-a", "001"), ("service-b", "002")]:
        candidate = tmp_path / service
        shutil.copytree(previous, candidate)
        file = candidate / "model/stg/cde" / (service + ".properties")
        values = dict(load_model(file).authoritative)
        write_model(
            file,
            {
                key: value
                for key, value in values.items()
                if owner(key, values) != ("resource", rid)
            },
        )
        operation = model_operation(
            operation_contract("import-delete", source="stg/cde/" + service + "/" + rid)
        )
        verify_model_operation(
            previous, candidate, operation, {file.relative_to(candidate).as_posix()}
        )
        dependency_index.rebuild(candidate)
        previous = candidate


@pytest.mark.parametrize(
    "corrupt",
    [
        "property",
        "mode",
        "anchor",
        "observed",
        "foreign",
        "identity-reference",
        "scope",
        "retained",
        "create",
        "undeclared",
    ],
)
def check_refactor_rejects_changes(tmp_path, corrupt):
    dependency_contract = _imports_support_import_model_fixtures.dependency_contract
    dependency_fixture = _imports_support_import_model_fixtures.dependency_fixture
    dependency_refactor = _imports_support_import_model_fixtures.dependency_refactor
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    sources = dependency_refactor(before, after)
    scope = {("stg", "cde", "service-b")}
    file = after / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    if corrupt in {"property", "mode", "anchor", "observed"}:
        key, raw = {
            "property": ("desired.row.002-001.value", "changed"),
            "mode": ("desired.resource.002.resourceMode", "CREATE"),
            "anchor": ("desired.resource.002.anchor", "changed"),
            "observed": ("observed.row.002-001.value", "changed"),
        }[corrupt]
        values[key] = raw
        write_model(file, values)
    elif corrupt in {"foreign", "identity-reference", "undeclared"}:
        file = after / (
            "model/dev/cde/service-a.properties"
            if corrupt == "foreign"
            else "model/dev/cde/service-b.properties"
        )
        values = dict(load_model(file).authoritative)
        if corrupt == "foreign":
            values["desired.row.001-001.value"] = "changed"
        elif corrupt == "identity-reference":
            values["desired.reference.origin.producerLogicalId"] = (
                "ServiceA_Resource_003"
            )
        else:
            values = {
                key: value
                for key, value in values.items()
                if not key.startswith("desired.reference.origin.")
            }
        write_model(file, values)
    elif corrupt == "scope":
        scope.clear()
    elif corrupt == "retained":
        file.write_bytes((before / file.relative_to(after)).read_bytes())
    elif corrupt == "create":
        for root in (before, after):
            file = root / "model/stg/cde/service-b.properties"
            values = dict(load_model(file).authoritative)
            values["desired.resource.002.resourceMode"] = "CREATE"
            write_model(file, values)
    with pytest.raises(ValueError):
        verify_model_refactor(
            before, after, model_refactor(dependency_contract()), sources, scope
        )


def check_reference_readonly_and_bounded_expansion(tmp_path, monkeypatch):
    dependency_fixture(tmp_path)
    broken = tmp_path / "model/dev/cde/service-b.properties"
    original = broken.read_bytes()
    broken.write_text("invalid\n")
    before = {p: p.read_bytes() for p in (tmp_path / "model").rglob("*") if p.is_file()}
    with input_context():
        producer = load_model(tmp_path / "model/stg/cde/service-a.properties")
        assert incoming(producer, "001")
    assert all(p.read_bytes() == raw for p, raw in before.items())
    broken.write_bytes(original)
    before = {p: p.read_bytes() for p in (tmp_path / "model").rglob("*") if p.is_file()}
    with (
        input_context(),
        patch.object(sources, "_read_model", wraps=sources._read_model) as body,
    ):
        consumer = load_model(tmp_path / "model/stg/cde/service-b.properties")
        assert usages(consumer)
        producer = load_model(tmp_path / "model/stg/cde/service-a.properties")
        assert incoming(producer, "001")
        assert {call.args[0].environment for call in body.call_args_list} == {"stg"}
        assert body.call_count <= 6
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(sources.tempfile, "gettempdir", lambda: str(temporary))
    journal = (
        temporary
        / "blueprint-model-publication"
        / (hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest() + ".json")
    )
    journal.parent.mkdir()
    journal.write_text("pending recovery")
    with pytest.raises(ValueError, match="read-only analysis stopped"):
        incoming(load_model(tmp_path / "model/stg/cde/service-a.properties"), "001")
    assert journal.read_text() == "pending recovery"
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize("broken_type", [False, True])
def check_issues_never_waive_delete_reference_safety(tmp_path, broken_type):
    selected_task = _imports_task_contract.selected_task
    start = _imports_task_contract.start
    dependency_fixture(tmp_path)
    name = "tasks/deletion.md"
    text = (
        operation_contract("import-delete", source="stg/cde/service-a/001")
        + "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        + "## Validation scope\n- `stg/cde/service-a`\n"
    )
    text += f"## Modified files\n- `{name}`\n## Allowed paths\n- `{name}`\n"
    start(tmp_path, name, text)
    issues = tmp_path / "issues/stg/cde/issues.md"
    issues.parent.mkdir(parents=True)
    issues.write_text("### service-a\n1. 既存のIssue\n")
    if broken_type:
        file = tmp_path / "model/stg/cde/service-b.properties"
        values = dict(load_model(file).authoritative)
        values["desired.reference.origin.resourceType"] = "ServiceA.Other"
        write_model(file, values)
    with selected_task(tmp_path, name):
        warnings = []
        assert incoming(
            load_model(tmp_path / "model/stg/cde/service-a.properties"),
            "001",
            warnings=warnings,
        )
        if broken_type:
            assert any("Type differs" in warning["message"] for warning in warnings)


def check_reference_structural_and_remaining_delete(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    file = before / "model/stg/cde/service-a.properties"
    values = dict(load_model(file).authoritative)
    values["desired.resource.001.parentReference"] = (
        "[other](service-a.md#other-producer)"
    )
    values["desired.resource.001.parentProperty"] = "ServiceA.Resource.Peer"
    write_model(file, values)
    (record,) = [
        record
        for record in usages(load_model(file))
        if record.consumer_key.endswith(".parentReference")
    ]
    assert (
        record.producer_scope == "stg/cde/service-a"
        and record.logical_id == "ServiceA_Resource_003"
    )
    shutil.copytree(before, after)
    candidate = after / file.relative_to(before)
    changed = {
        key: raw
        for key, raw in values.items()
        if key != "desired.resource.001.parentReference"
    }
    write_model(candidate, changed)
    declaration = {
        "consumer": "stg/cde/service-a/001",
        "producer": "stg/cde/service-a/003",
        "key": "desired.resource.001.parentReference",
    }
    contract = (
        dependency_contract().split("## Model dependency detach")[0]
        + "## Model dependency detach\n- "
        + json.dumps(declaration)
        + "\n"
    )
    with pytest.raises(ValueError, match="exact consumer|dependency detach"):
        verify_model_refactor(
            before,
            after,
            model_refactor(contract),
            {candidate.relative_to(after).as_posix()},
            {("stg", "cde", "service-a")},
        )
    write_model(
        candidate,
        {
            key: raw
            for key, raw in values.items()
            if owner(key, values) != ("resource", "001")
        },
    )
    assert verify_model_operation(
        before,
        after,
        model_operation(
            operation_contract("import-delete", source="stg/cde/service-a/001")
        ),
        {candidate.relative_to(after).as_posix()},
    )


def check_dependency_json_types_and_exact_detach(tmp_path):
    dependency_contract = _imports_support_import_model_fixtures.dependency_contract
    dependency_fixture = _imports_support_import_model_fixtures.dependency_fixture
    reference_fields = _imports_support_import_model_fixtures.reference_fields
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    file = before / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    key = "desired.row.002-001.document"
    document = {"ref": "same-name-stg", "keep": "same-name-stg", "typed": 1}
    values[key] = json.dumps(document)
    for identity, pointer in [("detach", "/ref"), ("retained", "/keep")]:
        values.update(
            reference_fields(
                identity, key, "same-name-stg", "stg/cde/service-a/001", pointer=pointer
            )
        )
    write_model(file, values)
    shutil.copytree(before, after)
    candidate = after / file.relative_to(before)
    kept = {
        key: raw
        for key, raw in values.items()
        if not key.startswith(
            ("desired.reference.origin.", "desired.reference.detach.")
        )
    }
    write_model(candidate, kept)
    declaration = {
        "consumer": "stg/cde/service-b/002",
        "producer": "stg/cde/service-a/001",
        "key": key,
        "pointer": "/ref",
    }
    contract = dependency_contract() + "- " + json.dumps(declaration) + "\n"
    changed, scope = (
        {candidate.relative_to(after).as_posix()},
        {("stg", "cde", "service-b")},
    )
    verify_model_refactor(before, after, model_refactor(contract), changed, scope)
    assert [record.pointer for record in usages(load_model(candidate))] == ["/keep"]
    with pytest.raises(ValueError, match="undeclared reference"):
        verify_model_refactor(
            before, after, model_refactor(dependency_contract()), changed, scope
        )
    for altered in (True, 1.0, "\x00reference0\x00"):
        mutation = {**kept, key: json.dumps({**document, "typed": altered})}
        write_model(candidate, mutation)
        with pytest.raises(ValueError, match="value|native"):
            verify_model_refactor(
                before, after, model_refactor(contract), changed, scope
            )
        # There is no string reference marker in the new reader; native strings remain strings.
        assert type(
            json.loads(load_model(candidate).authoritative[key])["typed"]
        ) is type(altered)


def check_reference_embedded_link_label(tmp_path):
    dependency_fixture(tmp_path)
    file = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    key = "display.resource.002.comment"
    values[key] = "[same-name-stg](service-a.md#other-producer)"
    values.update(
        reference_fields("label", key, "same-name-stg", "stg/cde/service-a/001")
    )
    write_model(file, values)
    model = load_model(file)
    records = [record for record in usages(model) if record.consumer_key == key]
    assert {(record.producer_id, record.logical_id) for record in records} == {
        ("001", "ServiceA_Resource_001")
    }
    assert model.authoritative[key] == "[same-name-stg](service-a.md#other-producer)"


def check_publication_verifies_only_acquisition_selected_additions():
    before = expansion(resource())
    after = expansion({**before.authoritative, **resource("009", identity="vpc-new")})
    references = Mock()
    verify_values(
        before,
        after,
        {"009": record("vpc-new", cidr="10.10.0.0/23")},
        schema_for,
        references,
    )
    assert references.verify_resource.call_count == 1
    assert references.verify_resource.call_args.args[1] == "009"


def check_existing_hyphenated_fixed_id_cannot_receive_rows():
    original = resource("existing-vpc")
    addition = {
        "desired.row.existing-vpc-999.property": "EC2.VPC.EnableDnsSupport",
        "desired.row.existing-vpc-999.value": "`true`",
        "desired.row.existing-vpc-999.comment": "追加は禁止",
    }
    with pytest.raises(ValueError, match="unselected Resource"):
        verify_values(
            expansion(original), expansion({**original, **addition}), {}, schema_for
        )


@pytest.mark.parametrize("action", ["refresh", "replace"])
def check_selected_overwrite(action):
    old = {**resource(), **resource("002", identity="vpc-other")}
    physical = "vpc-confirmed" if action == "refresh" else "vpc-replacement"
    captured = record(physical)
    new = {
        **old,
        "desired.row.001-002.value": "`10.11.0.0/23`",
        "observed.row.001-001.value": "`" + physical + "`",
    }
    picked = selection(action=action)
    if action == "replace":
        picked["resources"][0]["before"] = {
            "identity": "vpc-confirmed",
            "model": document_sha256(operation_values(old, "001")),
        }
    chosen = selection_records(picked, [captured], old, new, schema_for)
    assert {
        item["resource"]
        for item in verify_values(expansion(old), expansion(new), chosen, schema_for)
    } == {"001"}
    assert operation_values(old, "002") == operation_values(new, "002")
    if action == "replace":
        picked["resources"][0]["before"]["model"] = "stale"
        with pytest.raises(ValueError, match="previous identity/Model state"):
            selection_records(picked, [captured], old, new, schema_for)


@pytest.mark.parametrize("action", ["refresh", "replace"])
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def check_overwrite_identity_and_mode_boundary(action, mode):
    old = resource(mode=mode)
    picked = selection(action=action)
    if action == "replace":
        picked["resources"][0]["before"] = {
            "identity": "vpc-confirmed",
            "model": "invalid",
        }
    with pytest.raises(
        ValueError, match="CREATE|physical identity|previous identity/Model state"
    ):
        selection_records(picked, [record("vpc-different")], old, old, schema_for)


@pytest.mark.parametrize(
    "mutation",
    [
        "unacquired",
        "other",
        "property",
        "comment",
        "anchor",
        "observed",
        "delete",
        "row-owner",
    ],
)
def check_overwrite_does_not_grant_unrelated_edits(mutation):
    old = {**resource(), **resource("002", identity="vpc-other")}
    captured = record()
    captured["properties"]["EC2.VPC.Name"] = {
        "status": "unavailable",
        "reason": "AccessDenied",
    }
    new = {**old, "desired.row.001-002.value": "`10.11.0.0/23`"}
    chosen = selection_records(
        selection(action="refresh"), [captured], old, new, schema_for
    )
    if mutation == "delete":
        del new["desired.row.001-003.value"]
    else:
        key, value = {
            "unacquired": ("desired.row.001-003.value", "`changed`"),
            "other": ("desired.row.002-002.value", "`10.11.0.0/23`"),
            "property": ("desired.row.001-003.property", "EC2.VPC.CidrBlock"),
            "comment": ("desired.row.001-002.comment", "changed"),
            "anchor": ("desired.resource.001.anchor", "changed"),
            "observed": ("observed.row.001-002.value", "`invented`"),
            "row-owner": ("desired.row.002-004.property", "EC2.VPC.CidrBlock"),
        }[mutation]
        new[key] = value
    with pytest.raises(ValueError):
        verify_values(expansion(old), expansion(new), chosen, schema_for)


def check_refresh_new_rows_and_missing_properties():
    old = resource()
    captured = record()
    captured["properties"]["EC2.VPC.Name"] = {"status": "unavailable"}
    captured["properties"]["EC2.VPC.EnableDnsSupport"] = {
        "status": "captured",
        "value": True,
    }
    new = {
        **old,
        "desired.row.001-002.value": "`10.11.0.0/23`",
        "desired.row.001-004.property": "EC2.VPC.EnableDnsSupport",
        "desired.row.001-004.value": "`true`",
        "desired.row.001-004.comment": "取得値",
        "observed.row.001-004.value": "`true`",
    }
    chosen = selection_records(
        selection(action="refresh"), [captured], old, new, schema_for
    )
    with pytest.raises(
        ValueError, match="observed value requires a desired logical reference"
    ):
        verify_values(expansion(old), expansion(new), chosen, schema_for)
    del new["observed.row.001-004.value"]
    changed = verify_values(expansion(old), expansion(new), chosen, schema_for)
    assert {item["property"] for item in changed} == {
        "EC2.VPC.CidrBlock",
        "EC2.VPC.EnableDnsSupport",
    }
    assert new["desired.row.001-003.value"] == old["desired.row.001-003.value"]


def check_overwrite_duplicate_selection_and_destination_identity():
    old = {**resource(), **resource("002", identity="vpc-other")}
    picked = selection(action="refresh")
    picked["resources"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        selection_records(picked, [record()], old, old, schema_for)
    picked = selection(action="replace")
    picked["resources"][0]["before"] = {
        "identity": "vpc-confirmed",
        "model": document_sha256(operation_values(old, "001")),
    }
    with pytest.raises(ValueError, match="duplicate identity"):
        selection_records(picked, [record("vpc-other")], old, old, schema_for)


def check_selected_binding_switch_preserves_fixed_maps():
    old = resource()
    captured = record()
    captured["properties"]["EC2.VPC.EnableDnsSupport"] = {
        "status": "captured",
        "value": True,
    }
    new = {
        **old,
        "desired.row.001-004.property": "EC2.VPC.EnableDnsSupport",
        "desired.row.001-004.value": "`true`",
        "desired.row.001-004.comment": "合成追加",
    }
    chosen = selection_records(
        selection(action="refresh"), [captured], old, new, schema_for
    )
    verify_values(expansion(old), expansion(new), chosen, schema_for)
    foreign = {
        key.replace("desired.row.001-004.", "desired.row.002-004."): value
        for key, value in new.items()
    }
    with pytest.raises(ValueError, match="orphan row|unselected"):
        verify_values(expansion(old), expansion(foreign), chosen, schema_for)


def check_overwrite_reference_permission_is_property_scoped():
    old = {**resource(), **resource("002", identity="vpc-other")}
    captured = record()
    captured["properties"]["EC2.VPC.Name"] = {"status": "unavailable"}
    chosen = selection_records(
        selection(action="refresh"), [captured], old, old, schema_for
    )
    new = dict(old)
    for field, value in {
        "consumerKey": "desired.row.001-003.value",
        "text": "main-vpc",
        "occurrence": "1",
        "producerKind": "resource",
        "producerScope": "dev/cde/vpc",
        "producerId": "002",
        "resourceType": "EC2.VPC",
        "format": "name",
        "property": "EC2.VPC.Name",
        "labelPolicy": "none",
    }.items():
        new["desired.reference.explicit." + field] = value
    verify_values(expansion(old), expansion(new), chosen, schema_for)
    with pytest.raises(ValueError, match="unacquired"):
        verify_values(
            expansion(old),
            expansion({**new, "desired.row.001-003.value": "`changed`"}),
            chosen,
            schema_for,
        )
    new["desired.reference.explicit.consumerKey"] = "desired.row.002-003.value"
    with pytest.raises(ValueError, match="unselected Resource"):
        verify_values(expansion(old), expansion(new), chosen, schema_for)


def check_import_llm_choice_contract():
    prompt = (m.ROOT / "framework/prompts/codex/08_import.md").read_text(
        encoding="utf-8"
    )
    assert "Environment and service must be explicit. Ask for missing inputs" in prompt
    for condition in (
        "Same physical ID on IMPORT",
        "Different ID of the same IMPORT type",
        "No existing Resources",
        "Same physical ID on CREATE",
        "Existing IMPORT physical ID unknown",
        "Multiple matches",
    ):
        assert condition in prompt
    assert (
        "fixed destination" in prompt
        and "publish the combined service candidate once" in prompt
    )
    assert (
        "sequentially" in prompt
        and "independent Task/acquisition/publication" in prompt
    )


def _callback_check_refactor_json_value_structure_encoded(field, /, value):
    raw = json.dumps(value, separators=(",", ":"))
    return "`" + raw + "`" if field == "value" else raw


@pytest.mark.parametrize("field", ["value", "document"])
@pytest.mark.parametrize(
    "document,allowed",
    [
        ({"target": "prefix-<<Name>>-suffix", "timeout": 30, "items": ["keep"]}, True),
        (
            {
                "target": "prefix-<<Name>>-suffix",
                "timeout": 30,
                "items": ["keep"],
                "admin": True,
                "padding": "x",
            },
            False,
        ),
        ({"target": "prefix-<<Name>>-suffix", "items": ["keep"]}, False),
        (
            {
                "target": "prefix-<<Name>>-suffix",
                "timeout": 30,
                "items": ["keep", "extra"],
            },
            False,
        ),
        ({"target": "prefix-<<Name>>-suffix", "timeout": 30, "items": []}, False),
        (
            {"target": "prefix-<<Name>>-suffix", "timeout": True, "items": ["keep"]},
            False,
        ),
        (
            {"target": "prefix-<<Name>>-suffix", "timeout": "30", "items": ["keep"]},
            False,
        ),
        ({"target": "prefix-<<Name>>-suffix", "timeout": 31, "items": ["keep"]}, False),
        (
            {"target": "changed-<<Name>>-suffix", "timeout": 30, "items": ["keep"]},
            False,
        ),
        (
            {"target": "prefix-<<Name>>-changed", "timeout": 30, "items": ["keep"]},
            False,
        ),
        (
            {"target": "prefix-<<Name>>-suffix", "timeout": 30, "items": {"0": "keep"}},
            False,
        ),
    ],
)
def check_refactor_json_value_structure(tmp_path, field, document, allowed):
    dependency_contract = _imports_support_import_model_fixtures.dependency_contract
    dependency_fixture = _imports_support_import_model_fixtures.dependency_fixture
    dependency_refactor = _imports_support_import_model_fixtures.dependency_refactor
    before, after = tmp_path / "before", tmp_path / "after"
    dependency_fixture(before)
    file = before / "model/stg/cde/service-b.properties"
    values = dict(load_model(file).authoritative)
    original = {
        "target": "prefix-same-name-stg-suffix",
        "timeout": 30,
        "items": ["keep"],
    }
    key = "desired.row.002-001." + field
    encoded = _bind_framework_callback(
        _callback_check_refactor_json_value_structure_encoded, field
    )
    values[key] = encoded(original)
    values["desired.reference.origin.consumerKey"] = key
    values["desired.reference.origin.pointer"] = "/target"
    write_model(file, values)
    sources = dependency_refactor(before, after)
    file = after / file.relative_to(before)
    values = dict(load_model(file).authoritative)
    converted = json.loads(json.dumps(document).replace("<<Name>>", "same-name-stg"))
    values[key] = encoded(converted)
    write_model(file, values)
    contract = dependency_contract().replace("desired.row.002-001.value", key)
    if allowed:
        verify_model_refactor(
            before,
            after,
            model_refactor(contract),
            sources,
            {("stg", "cde", "service-b")},
        )
    else:
        with pytest.raises(ValueError, match="value|native"):
            verify_model_refactor(
                before,
                after,
                model_refactor(contract),
                sources,
                {("stg", "cde", "service-b")},
            )


@pytest.mark.parametrize("outer", [False, True])
@pytest.mark.parametrize(
    "change", ["comment", "value", "reference", "mode", "warning", "invalid"]
)
@patch(
    "model.validations.change_inputs.check_change_inputs",
    return_value=SimpleNamespace(
        errors=[],
        warnings=[],
        checks=0,
        diagnostics=[],
        diagnostic_errors={},
        error_contexts={},
        processing_errors=[],
        unverified=[],
        information=[],
    ),
)
@patch("validation.change.validate_producer_inputs")
def check_guard_cache_equivalence(producer_inputs, quality, tmp_path, outer, change):
    dependency_fixture(tmp_path)
    path = tmp_path / (
        "model/stg/cde/service-a.properties"
        if change in ("comment", "value", "invalid")
        else "model/stg/cde/service-b.properties"
    )
    original = path.read_text()
    values = dict(load_model(path).authoritative)
    if change == "value":
        values["desired.row.001-001.value"] = "changed-name"
    elif change == "reference":
        values["desired.reference.origin.producerLogicalId"] = "ServiceA_Resource_003"
    elif change == "mode":
        values["desired.resource.002.resourceMode"] = "CREATE"
    elif change == "warning":
        values["desired.reference.origin.producerLogicalId"] = "ServiceA_Resource_999"
    candidate = serialize(values)
    if change == "comment":
        candidate = original + "# retained comment\n"
    elif change == "invalid":
        candidate = "invalid\n"
    relative = path.relative_to(tmp_path).as_posix()
    results = []
    for _ in range(2):
        with input_context() if outer else nullcontext():
            try:
                warnings = validate_candidates(
                    tmp_path,
                    {relative},
                    {path: candidate},
                    {("stg", "cde", "service-a"), ("stg", "cde", "service-b")},
                )
                result = ("ok", warnings)
            except ValueError as error:
                result = ("error", str(error))
            results.append(result)
    assert results[0] == results[1]
    if change in ("warning", "invalid"):
        assert result[0] == "error"
    else:
        assert result[0] == "ok"
    assert path.read_text() == original


def _callback_check_repair_invalid_model_save(
    broken, candidate, failure, name, path, target, /
):
    with edit_write_context(target, {("stg", "cde", "service-b")}, name) as context:
        plan = prepare_edit(path, {path: candidate}, context)
        if failure == "race":
            path.write_bytes(
                (broken + "# external edit\n").encode("utf-8", errors="surrogateescape")
            )
        if failure == "rollback":
            with patch(
                "sync_files.save_files", side_effect=OSError("injected save failure")
            ):
                return publish_edit(plan, context)
        return publish_edit(plan, context)


def _callback_check_repair_invalid_model_final_only(
    calls, saved_load, /, scope, reads=None
):
    calls.append(scope)
    assert reads is not None, "candidate must use its overlay, never old source bytes"
    return saved_load(scope, reads)


@pytest.mark.parametrize(
    "old_error", ["reference", "syntax", "identity", "duplicate", "encoding"]
)
@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "reference",
        "duplicate",
        "allowed",
        "scope",
        "race",
        "rollback",
        "anchor",
    ],
)
@patch(
    "model.validations.change_inputs.check_change_inputs",
    return_value=SimpleNamespace(
        errors=[],
        warnings=[],
        checks=0,
        diagnostics=[],
        diagnostic_errors={},
        error_contexts={},
        processing_errors=[],
        unverified=[],
        information=[],
    ),
)
@patch("validation.change.validate_producer_inputs")
def check_repair_invalid_model(producer_inputs, quality, tmp_path, old_error, failure):
    fixture = _imports_support_repository_fixtures.fixture
    git = _imports_support_repository_fixtures.git
    start = _imports_support_repository_fixtures.start
    with fixture() as root:
        dependency_fixture(root)
        relative = "model/stg/cde/service-b.properties"
        path = root / relative
        valid = path.read_text()
        broken = valid
        if old_error == "syntax":
            broken = "broken properties\n"
        elif old_error == "reference":
            broken = valid.replace(
                "desired.row.002-001.value", "desired.row.999-001.value"
            )
        elif old_error == "identity":
            broken = valid.replace("ServiceB_Resource_002", "invalid")
        elif old_error == "duplicate":
            broken += "desired.resource.002.logicalId=duplicate\n"
        if old_error == "encoding":
            broken = "\udcff invalid old UTF-8\n"
        path.write_bytes(broken.encode("utf-8", errors="surrogateescape"))
        report = root / "issues/stg/cde/issues.md"
        report.parent.mkdir(parents=True)
        report.write_text(
            "### service-b\n1. Existing validation issue\n", encoding="utf-8"
        )
        git(root, "add", "model", "project.json", "issues")
        git(root, "commit", "-qm", "broken baseline")
        with patch.object(
            _imports_support_repository_fixtures.dependency_index, "rebuild"
        ):
            target, state = start(root, files=(relative,))
        path = target / relative
        name = state["task_file"]
        task = (
            (target / name)
            .read_text()
            .replace("`governance`", "`design`")
            .replace("- `framework`", "- `stg/cde/service-a`\n- `stg/cde/service-b`")
        )
        task = task.replace(
            "## Task contract\n", "## Task contract\n- Workflow: `update`\n"
        )
        if failure == "allowed":
            task = task.replace(
                "## Allowed paths\n- `" + name + "`\n- `" + relative + "`",
                "## Allowed paths\n- `" + name + "`",
            )
        elif failure == "scope":
            task = task.replace("- `stg/cde/service-a`\n", "")
        (target / name).write_text(task)
        # Correct both the broken baseline and a formerly fixed IMPORT logicalId.
        candidate = (
            valid.replace("ServiceB_Resource_002", "ServiceB_Resource_007")
            .replace('"ServiceB.Resource":2', '"ServiceB.Resource":7')
            .replace('"ServiceB.Resource": 2', '"ServiceB.Resource": 7')
        )
        if failure == "reference":
            candidate = candidate.replace(
                "ServiceA_Resource_001", "ServiceA_Resource_999"
            )
        elif failure == "duplicate":
            candidate += "desired.resource.002.logicalId=duplicate\n"
        elif failure == "anchor":
            candidate = candidate.replace("anchor=consumer", 'anchor=unsafe"anchor')
        saved_load = load_model
        calls = []
        final_only = _bind_framework_callback(
            _callback_check_repair_invalid_model_final_only, calls, saved_load
        )
        with (
            selected_task(target, name),
            patch("model.operations.load_model", side_effect=final_only),
            patch("model.dependency_index.change_consumers", return_value=[]),
        ):
            save = _bind_framework_callback(
                _callback_check_repair_invalid_model_save,
                broken,
                candidate,
                failure,
                name,
                path,
                target,
            )
            if failure in {"none", "scope"}:
                assert save() == (path,)
                assert path.read_text() == candidate and quality.called
                import_guard.require_import_changes(target)
                task_runtime = module(
                    "task_contract_runtime.py", "task_contract_runtime"
                )
                with patch.object(task_runtime, "Validator") as validator:
                    validator.return_value.report.return_value = 0
                    complete(target, name)
                    validator.return_value.run.assert_called_once()
                assert (
                    _imports_task_contract.status((target / name).read_text())
                    == "completed"
                )
            else:
                with pytest.raises((ValueError, OSError)):
                    save()
                expected = broken
                if failure == "race":
                    expected += "# external edit\n"
                assert (
                    path.read_bytes().decode("utf-8", errors="surrogateescape")
                    == expected
                )
        assert (root / relative).read_bytes().decode(
            "utf-8", errors="surrogateescape"
        ) == broken


@pytest.fixture
def generation_model_guard(tmp_path, monkeypatch):
    dependency_fixture(tmp_path)
    model = tmp_path / "model/stg/cde/service-b.properties"
    values = dict(load_model(model).authoritative)
    issues = tmp_path / "issues/stg/cde/issues.md"
    issues.parent.mkdir(parents=True)
    issues.write_text("### service-b\n1. 既存のIssue\n", encoding="utf-8")
    git = _bind_framework_callback(_imports_support_repository_fixtures.git, tmp_path)
    git("init", "--quiet", "--initial-branch=master")
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "initial",
    )
    name = "tasks/generation.md"
    sources = {p.relative_to(tmp_path).as_posix() for p in load_model(model).files}
    listed = "".join(f"- `{p}`\n" for p in sorted(sources | {name}))
    text = (
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
        "- Workflow: `update`\n"
        "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        "## Validation scope\n"
        "- `stg/cde/service-a`\n- `stg/cde/service-b`\n"
        "## Modified files\n" + listed + "## Allowed paths\n" + listed
    )
    _imports_task_contract.start(tmp_path, name, text)
    monkeypatch.setenv(_imports_task_contract.SELECTOR, name)
    values["display.resource.002.comment"] = "生成対象の変更"
    write_model(model, values)
    changed = import_guard.changed_sources(tmp_path)
    assert changed and changed <= sources
    assert set(git("diff", "--name-only").splitlines()) == changed
    return tmp_path / name, model, values, issues


@pytest.mark.parametrize("failure", ["allowed", "scope", "reference"])
def check_generation_preserves_model_guards(generation_model_guard, failure):
    path, model, values, issues = generation_model_guard
    root = path.parent.parent
    original = issues.read_bytes()
    if failure == "allowed":
        path.write_text(
            path.read_text(encoding="utf-8").split("## Allowed paths")[0]
            + f"## Allowed paths\n- `{path.relative_to(root).as_posix()}`\n",
            encoding="utf-8",
        )
        diagnostic = "Modified file is outside Allowed paths"
    elif failure == "scope":
        path.write_text(
            path.read_text(encoding="utf-8").replace("- `stg/cde/service-b`\n", ""),
            encoding="utf-8",
        )
        diagnostic = "changed Model services require Validation scope"
    elif failure == "reference":
        values["desired.reference.origin.producerLogicalId"] = "ServiceA_Resource_999"
        write_model(model, values)
        diagnostic = "invalid candidate reference"
    with pytest.raises(ValueError, match=diagnostic):
        import_guard.require_import_changes(root, generation=True)
    assert issues.read_bytes() == original


def test_macie_inventory_pairs_list_and_detail(monkeypatch):
    mapping, _ = import_comparison(m.ROOT, "macie")
    monkeypatch.setattr(
        import_inventory,
        "inventory_for",
        lambda ctx: SimpleNamespace(mapping=lambda service: (mapping, {})),
    )
    ctx = SimpleNamespace(
        allowed=set(),
        pages=Mock(return_value={"items": [{"jobId": "one"}, {"jobId": "two"}]}),
        call=Mock(side_effect=[{"jobId": "one"}, {"jobId": "two"}]),
    )
    records = import_inventory.adapter_inventory(
        ctx, "macie", ("Macie.ClassificationJob",)
    )
    assert [record["identity"] for record in records] == ["one", "two"]
    assert ctx.call.call_count == 2
    ctx.call = Mock(return_value={"jobId": "other"})
    with pytest.raises(ValueError, match="identifier mismatch"):
        import_inventory.adapter_inventory(ctx, "macie", ("Macie.ClassificationJob",))


def test_codebuild_inventory_batches_and_rejects_incomplete():
    names = [f"project-{i}" for i in range(101)]
    ctx = SimpleNamespace(
        call=Mock(
            side_effect=[
                {"projects": [{"name": n} for n in names[:100]]},
                {"projects": [{"name": names[100]}]},
            ]
        )
    )
    assert len(import_inventory.codebuild_details(ctx, names)) == 101
    assert [len(call.kwargs["names"]) for call in ctx.call.call_args_list] == [100, 1]
    ctx.call = Mock(
        side_effect=[
            {"projects": [{"name": name} for name in names[:100]]},
            m.comparator().AcquisitionError(
                "codebuild.batch_get_projects", "AccessDenied"
            ),
        ]
    )
    with pytest.raises(m.comparator().AcquisitionError):
        import_inventory.codebuild_details(ctx, names)
    for response in (
        {"projects": []},
        {"projects": [{"name": "a"}, {"name": "a"}]},
        {"projects": [{"name": "a"}], "projectsNotFound": ["a"]},
    ):
        ctx.call = Mock(return_value=response)
        with pytest.raises(ValueError):
            import_inventory.codebuild_details(ctx, ["a"])
    with pytest.raises(ValueError, match="duplicate"):
        import_inventory.codebuild_details(ctx, ["a", "a"])


def test_glue_connection_uses_only_verified_target_account():
    ctx = SimpleNamespace(
        target={"awsAccountId": ACCOUNT},
        pages=Mock(return_value={"ResourceDescriptions": []}),
    )
    inventory = SimpleNamespace(
        ctx=ctx,
        schema=lambda kind: {
            "handlers": {"list": {"handlerSchema": {"required": ["CatalogId"]}}}
        },
        mapping=lambda service: (None, {}),
    )
    assert (
        ImportInventory.cloud_inventory(inventory, "glue", "Glue.Connection", None)
        == []
    )
    assert json.loads(ctx.pages.call_args.kwargs["ResourceModel"]) == {
        "CatalogId": ACCOUNT
    }
    ctx.target["awsExecutionAccountId"] = "999999999999"
    with pytest.raises(m.comparator().AcquisitionError):
        ImportInventory.cloud_inventory(inventory, "glue", "Glue.Connection", None)
    assert ctx.pages.call_count == 1

    ctx.target.pop("awsExecutionAccountId")
    with pytest.raises(m.comparator().AcquisitionError):
        ImportInventory.cloud_inventory(
            inventory, "glue", "Glue.Connection", {"CatalogId": "999999999999"}
        )
    assert ctx.pages.call_count == 1
    ctx.pages.return_value = {"ResourceDescriptions": [{}]}
    inventory.failure = Mock()
    inventory.cloud_record = Mock(
        return_value={
            "kind": "Glue.Connection",
            "identity": "connection",
            "cloudProperties": {"CatalogId": "999999999999"},
        }
    )
    assert (
        ImportInventory.cloud_inventory(inventory, "glue", "Glue.Connection", None)
        == []
    )
    assert inventory.failure.call_args.args[1].code == "CatalogScopeMismatch"
    inventory.cloud_record.return_value["cloudProperties"]["CatalogId"] = ACCOUNT
    record = ImportInventory.cloud_inventory(
        inventory, "glue", "Glue.Connection", None
    )[0]
    assert record["selectorProperties"] == {"Glue.Connection.CatalogId": ACCOUNT}
    assert record["provenance"]["selectors"] == {"CatalogId": ACCOUNT}


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))


def test_route53_identity_matching_respects_zone_and_set_identifier():
    kind = "Route53.RecordSet"
    props = [
        kind + "." + name for name in ("HostedZoneId", "Name", "Type", "SetIdentifier")
    ]
    captured = {
        "record": "route",
        "kind": kind,
        "identity": "synthetic-record",
        "identityProperty": None,
        "identityProperties": props,
        "identityStatus": "known",
        "identityComponents": [
            {"property": p, "value": v}
            for p, v in zip(props, ("Z1", "example.com", "A", "blue"), strict=True)
        ],
        "properties": {},
    }
    old = {
        "desired.resource.001.resourceType": kind,
        "desired.resource.001.resourceMode": "IMPORT",
    }
    for index, (prop, value) in enumerate(
        zip(props, ("/hostedzone/Z1", "EXAMPLE.com.", "A", "blue"), strict=True), 1
    ):
        old[f"desired.row.001-{index:03d}.property"] = prop
        old[f"desired.row.001-{index:03d}.value"] = f"`{value}`"
    matching = {}
    empty = {
        "resources": [],
        "excluded": [{"record": "route", "reason": "fixture"}],
        "unreflected": [],
    }
    selection_records(empty, [captured], old, old, schema_for, matching=matching)
    assert matching["route"]["existingResources"] == ["001"]
    old["desired.row.001-004.value"] = "`other`"
    matching.clear()
    selection_records(empty, [captured], old, old, schema_for, matching=matching)
    assert matching["route"]["status"] == "no-match"
    del old["desired.row.001-004.value"]
    del old["desired.row.001-004.property"]
    matching.clear()
    selection_records(empty, [captured], old, old, schema_for, matching=matching)
    assert matching["route"]["status"] == "unresolved"
