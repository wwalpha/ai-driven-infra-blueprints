#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import aws_mapping_compare as _imports_aws_mapping_compare
import support.check_model_aws_fixtures as _retained_fixture_offline_network
from support.check_model_aws_fixtures import (
    REPRESENTATIVES,
    FakeResource,
    Path,
    SchemaOffline,
    acquired,
    boto3,
    check,
    expect,
    m,
    patch,
    pytest,
    run,
    sys,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

offline_network = _retained_fixture_offline_network.offline_network


@pytest.fixture
def no_sdk_clients():
    with patch.object(
        boto3,
        "Session",
        side_effect=AssertionError("adapter UT must not create boto3 Session"),
    ):
        yield


@pytest.mark.usefixtures("no_sdk_clients")
def check_service_adapters(tmp_path):
    root = tmp_path
    # Every supported field is extracted from a real botocore-validated SDK
    # response after executing the service's fetch adapter. These are not stubs
    # that simply echo comparator mappings. Unknown SDK paths fail here.
    type_count, field_count = 0, 0
    for service in m.SERVICES:
        module = m.service_module(service)
        if service == "cloudformation-stacks":
            continue
        comparison = _imports_aws_mapping_compare.comparison
        mapping, definitions = comparison(m.ROOT, service)
        for kind in sorted(mapping.adapter_resource_types):
            relevant = {
                prop: item.field
                for prop, item in definitions.items()
                if prop.startswith(kind + ".")
                and item.field.classification == "supported"
                and mapping.getters.get(item.field.getter, {}).get("kind") == "adapter"
            }
            relevant.update(getattr(module, "MODEL_FIELDS", {}))
            relevant = {
                key: field
                for key, field in relevant.items()
                if key.startswith(kind + ".")
            }
            if (
                not relevant
            ):  # Inline types still must have their actual getter exercised below.
                raise AssertionError("resource type without acquisition: " + kind)
            owner = {
                "S3.BucketPolicy": "S3.Bucket",
                "EC2.SubnetRouteTableAssociation": "EC2.Subnet",
            }.get(kind, kind)
            ctx = SchemaOffline(root)
            ctx.egress = False
            ctx.verify()
            resource = FakeResource(ctx, service, owner)
            for prop, field in relevant.items():
                value = m.select(ctx.fetch(resource, field.getter), field.path)
                check(
                    acquired(value), "unreadable mapping " + prop + " -> " + field.path
                )
                field_count += 1
            identity = mapping.identities.get(kind)
            if identity is not None:
                response = ctx.fetch(resource, identity.getter)
                for path in (identity.id_path, identity.arn_path):
                    if path is not None:
                        check(
                            acquired(m.select(response, path)),
                            "unreadable identity " + kind + " -> " + path,
                        )
                getter, id_path, arn_path, name_property = (
                    identity.getter,
                    identity.id_path,
                    identity.arn_path,
                    identity.name_property,
                )
                for mode in ("id", "arn", "name"):
                    start = len(ctx.trace)
                    if mode == "name" and name_property:
                        ctx.fetch(resource, getter)
                        expected = resource.value(name_property, "string")
                    elif path := arn_path if mode == "arn" else id_path:
                        expected = m.select(ctx.fetch(resource, getter), path)
                    else:
                        expect(
                            m.Unresolved,
                            lambda *, mode=mode, resource=resource: m.Resource.identity(
                                resource, mode
                            ),
                        )
                        continue
                    expected_trace = ctx.trace[start:]
                    start = len(ctx.trace)
                    check(
                        m.Resource.identity(resource, mode) == expected,
                        kind + ": Registry " + mode,
                    )
                    check(
                        ctx.trace[start:] == expected_trace,
                        kind + ": identity API trace/cache unchanged",
                    )
            type_count += 1
        kind, prop, expected = REPRESENTATIVES[service]
        for state in ("match", "difference", "missing", "failed"):
            ctx = SchemaOffline(root)
            ctx.egress = False
            ctx.verified = True
            ctx.fault = state if state in {"missing", "failed"} else None
            different = (
                not expected
                if type(expected) is bool
                else expected + 1
                if type(expected) is int
                else "deliberately different"
            )
            resource = FakeResource(
                ctx,
                service,
                kind,
                kind + "." + prop,
                expected if state != "difference" else different,
            )
            results = m.compare_resource(ctx, resource)
            wanted = {
                "missing": "resource_missing",
                "failed": "acquisition_failed",
            }.get(state, state)
            check(
                any(item["status"] == wanted for item in results),
                service + ": " + state + ": " + repr(results),
            )
    check(type_count == 52, "all adapter types exercised")
    print(
        f"Service acquisition/field extraction: {type_count} resource types, {field_count} supported mappings, 27 × 4 comparison cases"
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
