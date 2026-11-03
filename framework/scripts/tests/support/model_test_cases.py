"""Pure Audit case executors; resource/SDK/generation procedures stay in their suites."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

import pytest
from design.layout import confirmed_display_name
from model.adapters.aws import Unresolved
from model.audit import disambiguate_names
from model.reference_values import confirmed
from support.fixture_cases import load_case

from model import audit_runtime as audit


def display_case(case):
    data = case["data"]
    before = deepcopy(data)
    names = dict(data["names"])
    primary = {kind: tuple(fields) for kind, fields in data["primary"].items()}
    disambiguate_names(names, data["kinds"], data["identities"], primary)
    TestCase().assertNotIn("Internal_", " ".join(names.values()))
    TestCase().assertEqual(data, before)
    return {"names": list(names.values())}


def guardduty_report_case(case):
    data = case["data"]
    value = audit.masked(data["value"])
    masked = audit.masked(data["secret"])
    TestCase().assertIs(type(value), str)
    TestCase().assertIs(type(masked), str)
    if data["secret_value"] in masked:
        pytest.fail("Audit secret exposed before snapshot", pytrace=False)
    TestCase().assertEqual(json.loads(masked)["password"], "[REDACTED]")
    return {
        "value": value,
        "paths": audit.different_paths([data["value"]], ["build-artifact/"]),
        "masked_secret": masked,
    }


def identifier_state():
    data = load_case("model_test_identifiers", "identifier-match")["data"]
    m = SimpleNamespace(
        ROOT=Path("/snapshot"),
        catalog_outputs=lambda root, kind: [kind + ".VpcId"],
        literal=lambda raw: raw.strip("`"),
        confirmed_display_name=confirmed_display_name,
        confirmed=confirmed,
        normalize=normalize_identifier,
        stable=lambda value: (type(value).__name__, value),
        redacted=lambda value: value,
        AcquisitionError=RuntimeError,
        Unresolved=ValueError,
    )
    resource = SimpleNamespace(
        kind="EC2.VPC",
        rows_for=Mock(
            return_value=[
                ("001-001", {"property": "EC2.VPC.VpcId", "value": "[VPC](#vpc)"})
            ]
        ),
        model=SimpleNamespace(
            values={"observed.row.001-001.value": data["observed"]}, service="vpc"
        ),
        parse=Mock(side_effect=lambda row, norm: row["value"].strip("`")),
        module=SimpleNamespace(sensitive=lambda prop: False),
    )
    ctx = SimpleNamespace(
        comparison=lambda service: (
            None,
            {"EC2.VPC.VpcId": SimpleNamespace(field=SimpleNamespace(norm="typed"))},
        )
    )
    return SimpleNamespace(m=m, resource=resource, ctx=ctx, item=data["item"])


def normalize_identifier(ctx, value, norm):
    return int(value) if norm == "number" else value


def identifier_result(state):
    return audit.identifier_result(state.m, state.ctx, state.resource, state.item)


def identifier_case(state, case):
    data = case["data"]
    state.item["awsValue"] = data["aws"]
    state.resource.model.values["observed.row.001-001.value"] = data["observed"]
    if data["duplicate"]:
        state.resource.rows_for.return_value *= 2
    state.ctx.comparison = Mock(
        return_value=(
            None,
            {
                "EC2.VPC.VpcId": SimpleNamespace(
                    field=SimpleNamespace(norm=data["norm"])
                )
            },
        )
    )
    state.resource.module.sensitive = Mock(return_value=data["sensitive"])
    before = deepcopy(state.item)
    result = identifier_result(state)
    TestCase().assertEqual(state.item, before)
    if data["sensitive"] and (
        result["designValue"] != "[REDACTED]" or result["awsValue"] != "[REDACTED]"
    ):
        pytest.fail("Audit identifier secret exposed before snapshot", pytrace=False)
    return {"result": result}


def queue_exclusion_case(case):
    item = deepcopy(case["data"]["item"])
    result = audit.classify_exclusion(None, {}, None, item)
    TestCase().assertEqual(item, case["data"]["item"])
    return {"result": result}


def sensitive_exclusion_case(case):
    data = case["data"]
    resource = Mock()
    resource.module.sensitive.return_value = True
    resource.rows_for.return_value = [("001", {"value": data["secret"]})]
    resource.parse.return_value = data["secret"]
    if data["parse_error"]:
        resource.parse.side_effect = Unresolved(data["secret"])
    m = SimpleNamespace(Unresolved=Unresolved, redacted=lambda value: value)
    snapshot = {"exclusions": {"credential": "write-only"}} if data["candidate"] else {}
    item = deepcopy(data["item"])
    result = audit.classify_exclusion(m, snapshot, resource, item)
    if data["secret"] in json.dumps(result):
        pytest.fail("Audit exclusion secret exposed before snapshot", pytrace=False)
    TestCase().assertEqual(item, data["item"])
    if not data["candidate"] or item["status"] != "local_metadata":
        resource.parse.assert_not_called()
    return {"result": result}
