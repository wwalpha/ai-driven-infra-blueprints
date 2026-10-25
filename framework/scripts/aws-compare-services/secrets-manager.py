"""secrets-manager: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import Unresolved

APIS = {("secretsmanager", "describe_secret")}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    parent = r.parent() if r.kind.endswith("RotationSchedule") else r
    record = ctx.call(
        "secretsmanager", "describe_secret", SecretId=parent.value("Name")
    )
    if r.kind.endswith("RotationSchedule") and r.value(
        "SecretId", "name"
    ) != parent.value("Name"):
        raise Unresolved("rotation schedule SecretId does not identify its parent")
    return record
