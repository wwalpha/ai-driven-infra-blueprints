"""secrets-manager: selected properties -> read-only SDK responses; inputs in fetch()."""

import json

from model.adapters.aws import Unresolved, is_reference, literal, parse_model_reference

APIS = {("secretsmanager", "describe_secret")}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    parent = r.parent() if r.kind.endswith("RotationSchedule") else r
    if r.kind.endswith("RotationSchedule"):
        rows = r.rows_for("SecretId")
        raw = literal(rows[0][1]["value"]) if len(rows) == 1 else ""
        try:
            reference = json.loads(raw)
        except ValueError:
            reference = None
        if is_reference(reference):
            node = parse_model_reference(reference)
            producer = r.reference(reference)
            if (
                node.attribute != "Id"
                or producer.kind != "SecretsManager.Secret"
                or (producer.model.path, producer.number)
                != (parent.model.path, parent.number)
            ):
                raise Unresolved(
                    "rotation schedule SecretId does not identify its parent"
                )
        elif r.value("SecretId", "name") != parent.value("Name"):
            raise Unresolved("rotation schedule SecretId does not identify its parent")
    record = ctx.call(
        "secretsmanager", "describe_secret", SecretId=parent.value("Name")
    )
    return record
