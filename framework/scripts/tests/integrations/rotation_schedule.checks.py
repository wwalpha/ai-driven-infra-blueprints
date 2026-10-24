#!/usr/bin/env python3
"""RotationSchedule identity, parent references and transactional service generation."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import tempfile

from design.layout import expanded_design as expanded_design
from design.layout_schema import resource_anchor as resource_anchor
from model.core import properties
from model.files import read_model
from support import model_design_fixtures as HELPERS
from support.it_case_receipt import it_case
from support.model_sources import write_model
from support.rotation_schedule_fixtures import fixture
from support.validator import load as load

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]

SYNC = HELPERS.SYNC
ROTATION = "SecretsManager.RotationSchedule"
SECRET = "SecretsManager.Secret"




def rejects(action, *messages):
    try:
        action()
    except ValueError as error:
        assert all(message in str(error) for message in messages), str(error)
        return str(error)
    raise AssertionError(f"invalid input accepted: {messages}")


def _callback_main_save(key, models, values, /):
    write_model(models / "kms.properties", HELPERS.text(key))
    write_model(models / "secretsmanager.properties", HELPERS.text(values))


@it_case
def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [
            {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
        ]}) + "\n")
        path = root / "docs/designs/dev/123456789012/secretsmanager.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        values = fixture(2)
        HELPERS.roundtrip(path, values, root)
        models = root / "model/dev/123456789012"
        models.mkdir(parents=True, exist_ok=True)
        key = HELPERS.model("kms", "KMS.Key", "app-dev-key", [
            ("KeyId", "[KMS_Key_001](kms.md#kms-app-dev-key)", "鍵のID")], "Key", "app-dev-key")
        key.update({"observed.row.001-001.property": "KMS.Key.KeyId",
                    "observed.row.001-001.value": "`PENDING_DEPLOY`", "observed.row.001-001.comment": "鍵のID"})
        for identity in ("001", "003"):
            for namespace, value in (("desired", "[KMS_Key_001](kms.md#kms-app-dev-key)"), ("observed", "PENDING_DEPLOY")):
                values.update({f"{namespace}.row.{identity}-002.property": SECRET + ".KmsKeyId",
                               f"{namespace}.row.{identity}-002.value": value,
                               f"{namespace}.row.{identity}-002.comment": "暗号化する鍵"})

        save = _bind_framework_callback(_callback_main_save, key, models, values)

        save()
        SYNC.sync(root, True, "dev", "123456789012")
        SYNC.sync(root, False, "dev", "123456789012")
        key["observed.row.001-001.value"] = "`key-current`"
        for identity in ("001", "003"):
            values[f"observed.row.{identity}-002.value"] = "key-current"
        save()
        SYNC.sync(root, True, "dev", "123456789012")
        assert path.read_text().count("[key-current](kms.md#kms-app-dev-key)") == 2
        saved = {file: file.read_bytes() for file in path.parent.glob("*.md")}
        # Rejected Secret generation retains its old link, while valid KMS saves.
        del values["desired.resource.002.parentReference"]
        key["display.resource.001.label"] = "app-dev-renamed"
        save()
        rejects(lambda: SYNC.sync(root, True, "dev", "123456789012"), "SecretsManager_RotationSchedule_001", "parentReference")
        assert path.read_bytes() == saved[path]
        assert (path.parent / "kms.md").read_bytes() != saved[path.parent / "kms.md"]
        assert "app-dev-renamed" in (path.parent / "kms.md").read_text()
        assert 'id="kms-app-dev-key"' in (path.parent / "kms.md").read_text()
        assert properties(read_model(models / 'secretsmanager.properties')) == properties(HELPERS.text(values))
        # Repair only the source in a later task against the already saved KMS view.
        values["desired.resource.002.parentReference"] = "[Secret1](#secretsmanager-app-dev-secret-1)"
        save()
        SYNC.sync(root, True, "dev", "123456789012", services=["secretsmanager"])
        SYNC.sync(root, False, "dev", "123456789012")
        assert "kms-app-dev-key" in path.read_text()
        assert path.read_text().count("[key-current](kms.md#kms-app-dev-key)") == 2
    print("rotation-schedule: PASS (single/multiple parents, identity, formal rows, invalid references, projection, KMS updates and deferred source repair)")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()
