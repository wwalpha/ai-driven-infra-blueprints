"""Synthetic Secret and RotationSchedule data shared by integration cases."""

import json

from support import model_design_fixtures as HELPERS
from support.model_reference_fixtures import reference

ROTATION = "SecretsManager.RotationSchedule"
SECRET = "SecretsManager.Secret"


def fixture(count=1):
    values = {
        "desired.service.secretsmanager.serviceId": "secretsmanager",
        "desired.service.secretsmanager.ownedCatalogResourceTypes": SECRET
        + ","
        + ROTATION,
        "display.service.title": "# Secrets Manager 詳細設計",
    }
    values["desired.service.identity.lastAllocated"] = json.dumps(
        {SECRET: count, ROTATION: count}
    )
    for number in range(count):
        parent, child = f"{2 * number + 1:03d}", f"{2 * number + 2:03d}"
        name, logical = (
            f"app-dev-secret-{number + 1}",
            f"SecretsManager_Secret_{number + 1:03d}",
        )
        child_name, child_id = (
            name + "_rotate",
            f"SecretsManager_RotationSchedule_{number + 1:03d}",
        )
        for identity, kind, identifier in (
            (parent, SECRET, logical),
            (child, ROTATION, child_id),
        ):
            values.update(
                {
                    f"desired.resource.{identity}.resourceType": kind,
                    f"desired.resource.{identity}.logicalId": identifier,
                    f"desired.resource.{identity}.anchor": HELPERS.resource_anchor(
                        "secretsmanager", name if kind == SECRET else child_name, kind
                    ),
                    f"desired.resource.{identity}.cfn-logicalId": "fixture-"
                    + (
                        f"Secret{number + 1}"
                        if kind == SECRET
                        else f"Secret{number + 1}Rotation"
                    ),
                }
            )
        values.update(
            {
                f"display.resource.{parent}.comment": "アプリケーション用secret",
                f"display.resource.{child}.label": child_name,
                f"desired.resource.{child}.parentProperty": ROTATION + ".SecretId",
                f"desired.resource.{child}.parentReference": json.dumps(
                    reference(logical, "Id")
                ),
            }
        )
        for identity, kind, rows in (
            (parent, SECRET, [("Name", f"`{name}`", None)]),
            (
                child,
                ROTATION,
                [
                    ("RotateImmediatelyOnUpdate", "`false`", None),
                    ("RotationRules.AutomaticallyAfterDays", "`30`", None),
                    (
                        "SecretId",
                        "`" + json.dumps(reference(logical, "Id")) + "`",
                        None,
                    ),
                ],
            ),
        ):
            for index, (field, value, observed) in enumerate(rows, 1):
                key = f"{identity}-{index:03d}"
                for namespace, rendered in (("desired", value), ("observed", observed)):
                    if rendered is not None:
                        values.update(
                            {
                                f"{namespace}.row.{key}.property": kind + "." + field,
                                f"{namespace}.row.{key}.value": rendered,
                                f"{namespace}.row.{key}.comment": "属性の設定値",
                            }
                        )
    return values
