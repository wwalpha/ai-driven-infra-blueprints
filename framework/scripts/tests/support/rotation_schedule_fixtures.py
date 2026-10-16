"""Synthetic Secret and RotationSchedule data shared by integration cases."""
from design_layout import resource_anchor
from support import model_design_fixtures as HELPERS
ROTATION = "SecretsManager.RotationSchedule"
SECRET = "SecretsManager.Secret"

def fixture(count=1):
    values = {
        "desired.service.secretsmanager.serviceId": "secretsmanager",
        "desired.service.secretsmanager.ownedCatalogResourceTypes": SECRET + "," + ROTATION,
        "display.service.title": "# Secrets Manager 詳細設計",
    }
    for number in range(count):
        parent, child = f"{2 * number + 1:03d}", f"{2 * number + 2:03d}"
        name, logical = f"app-dev-secret-{number + 1}", f"Secret{number + 1}"
        child_name, child_id = name + "_rotate", logical + "Rotation"
        anchor, child_anchor = [resource_anchor("secretsmanager", item) for item in (name, child_name)]
        for identity, kind, identifier, fragment in ((parent, SECRET, logical, anchor), (child, ROTATION, child_id, child_anchor)):
            values.update({f"desired.resource.{identity}.resourceType": kind,
                           f"desired.resource.{identity}.logicalId": identifier,
                           f"desired.resource.{identity}.anchor": fragment})
        values.update({f"display.resource.{parent}.comment": "アプリケーション用secret",
                       f"display.resource.{child}.label": child_name,
                       f"desired.resource.{child}.parentProperty": ROTATION + ".SecretId",
                       f"desired.resource.{child}.parentReference": f"[{logical}](#{anchor})"})
        for identity, kind, rows in (
            (parent, SECRET, [("Name", f"`{name}`", None)]),
            (child, ROTATION, [("RotateImmediatelyOnUpdate", "`false`", None),
                               ("RotationRules.AutomaticallyAfterDays", "`30`", None),
                               ("SecretId", f"[{logical}](#{anchor})", None)]),
        ):
            for index, (field, value, observed) in enumerate(rows, 1):
                key = f"{identity}-{index:03d}"
                for namespace, rendered in (("desired", value), ("observed", observed)):
                    if rendered is not None:
                        values.update({f"{namespace}.row.{key}.property": kind + "." + field,
                                       f"{namespace}.row.{key}.value": rendered,
                                       f"{namespace}.row.{key}.comment": "属性の設定値"})
    return values

