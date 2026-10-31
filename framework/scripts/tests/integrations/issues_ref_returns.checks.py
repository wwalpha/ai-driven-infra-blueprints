#!/usr/bin/env python3
"""Documented Ref attributes retain resource identity across local exports."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json
import tempfile
from unittest.mock import patch

from support import issues_scan_fixtures as fixtures
from support.it_case_receipt import it_case
from support.validator import load as load
from utils.iac_values import ResourceReference, same

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def main_checks():
    with tempfile.TemporaryDirectory(prefix="issues-ref-returns-") as temporary:
        root = Path(temporary) / "project"
        _, template = fixtures.fixture(root, stacks=2, services=("s3",))
        consumer, producer = "cfn-stack-app-dev-data1", "cfn-stack-app-dev-data2"
        specs = [
            ("glue", "Glue.SecurityConfiguration", "SecurityConfiguration", "Name"),
            ("athena", "Athena.WorkGroup", "WorkGroup", "Name"),
            ("iam", "IAM.ManagedPolicy", "ManagedPolicy", "PolicyArn"),
            ("quicksight", "QuickSight.VPCConnection", "Unknown", None),
        ]
        template["Outputs"] = {}
        for service, kind, logical, _attribute in specs:
            model = {f"desired.service.{service}.serviceId": service}
            for number, stack in enumerate((consumer, producer), 1):
                identity = f"{number:03d}"
                model.update(
                    {
                        f"desired.resource.{identity}.resourceType": kind,
                        f"desired.resource.{identity}.logicalId": kind.replace(".", "_")
                        + "_"
                        + identity,
                        f"desired.resource.{identity}.anchor": "resource-"
                        + (kind.replace(".", "_") + "_" + identity),
                        "desired.service.identity.lastAllocated": json.dumps(
                            {kind: number}
                        ),
                        f"desired.resource.{identity}.cfn-logicalId": stack
                        + "-"
                        + logical,
                    }
                )
            fixtures.write(
                root / f"model/dev/123456789012/{service}.properties",
                "\n".join(f"{key}={value}" for key, value in model.items()) + "\n",
            )
            # Identical names do not make resources in distinct stacks identical.
            template["Resources"][logical] = {
                "Type": "AWS::" + kind.replace(".", "::"),
                "Properties": {
                    "ManagedPolicyName" if service == "iam" else "Name": "same-name"
                },
            }
            template["Outputs"][logical] = {
                "Value": {"Ref": logical},
                "Export": {"Name": {"Fn::Sub": "${Name}-" + logical}},
            }
        fixtures.mutate_template(root, template)
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            comparison, _ = fixtures.compare(root, ["s3"])
            for service, kind, logical, attribute in specs:
                imported = {"Fn::ImportValue": "app-dev-data2-" + logical}
                if attribute is None:
                    fixtures.expect_error(
                        lambda *, logical=logical: comparison.evaluate(
                            consumer, {"Ref": logical}
                        ),
                        "Ref return attribute is unproven",
                    )
                    fixtures.expect_error(
                        lambda *, imported=imported: comparison.evaluate(
                            consumer, imported
                        ),
                        "Ref return attribute is unproven",
                    )
                    fixtures.expect_error(
                        lambda *, service=service: comparison.reference(
                            service,
                            ResourceReference(
                                {
                                    "$resource": ["quicksight", "001"],
                                    "$attribute": "Ref",
                                }
                            ),
                        ),
                        "unsupported JSON Resource attribute: QuickSight.VPCConnection.Ref",
                    )
                    continue
                expected = {"$resource": [service, "001"], "$attribute": attribute}
                direct = comparison.evaluate(consumer, {"Ref": logical})
                assert direct == expected, direct
                desired = comparison.reference(
                    service,
                    ResourceReference(
                        {"$resource": [service, "001"], "$attribute": attribute}
                    ),
                )
                assert same(desired, direct)
                exported = comparison.evaluate(consumer, imported)
                assert exported == {
                    "$resource": [service, "002"],
                    "$attribute": attribute,
                }, exported
                other = comparison.reference(
                    service,
                    ResourceReference(
                        {"$resource": [service, "002"], "$attribute": attribute}
                    ),
                )
                assert same(other, exported)
                assert not same(desired, exported)
                expected_comparison = (
                    False if kind == "Glue.SecurityConfiguration" else None
                )
                assert (
                    comparison.reference_same(
                        desired, exported, "Glue.Job", "SecurityConfiguration"
                    )
                    is expected_comparison
                )
                # Provider primary identifiers cannot redefine the documented Ref return.
                comparison.catalog.schema(kind)["primaryIdentifier"] = [
                    "/properties/DeliberatelyWrong"
                ]
                comparison.symbols.clear()
                assert comparison.evaluate(consumer, {"Ref": logical}) == expected
                if service == "iam":
                    assert same(
                        direct,
                        comparison.evaluate(
                            consumer, {"Fn::GetAtt": [logical, "PolicyArn"]}
                        ),
                    )
                    assert not same(direct, "same-name")
                    assert not same(
                        direct, dict(direct, **{"$attribute": "ManagedPolicyName"})
                    )
                    assert not same(direct, dict(direct, **{"$attribute": "Arn"}))
                    assert (
                        comparison.reference_literal(direct)
                        == "arn:aws:iam::123456789012:policy/same-name"
                    )
                else:
                    assert comparison.reference_literal(direct) == "same-name"
    print(
        "Ref return checks: PASS (3 types, local exports/imports, distinct resources, unsupported Ref, no primary/name inference)"
    )


if __name__ == "__main__":
    from support.model_sources import catalog_display

    with catalog_display():
        main_checks()
