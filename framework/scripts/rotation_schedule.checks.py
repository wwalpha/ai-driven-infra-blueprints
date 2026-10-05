#!/usr/bin/env python3
"""RotationSchedule identity, parent references and transactional service generation."""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

from design_layout import expanded_design, resource_anchor
from model_design import markdown_for, properties

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("model_checks", Path(__file__).with_name("model_design.checks.py"))
HELPERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPERS)
SYNC = HELPERS.SYNC
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


def rejects(action, *messages):
    try:
        action()
    except ValueError as error:
        assert all(message in str(error) for message in messages), str(error)
        return str(error)
    raise AssertionError(f"invalid input accepted: {messages}")


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [
            {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
        ]}) + "\n")
        path = root / "docs/designs/dev/123456789012/secretsmanager.md"
        path.parent.mkdir(parents=True)
        for count in (1, 2):
            values = fixture(count)
            output = HELPERS.roundtrip(path, values, root)
            _, children = expanded_design(output.splitlines())
            assert len(children) == count
            assert properties(SYNC.imported_model(path, root)) == values
            assert "### SecretsManager.RotationSchedule" not in output
            assert "app-dev-secret-1_rotate：属性の設定値" in output
            SYNC.validate_views(root, root, [path], {path: values})
            assert SYNC.linked_resource(path, "[PENDING_DEPLOY](#secretsmanager-app-dev-secret-1_rotate)") == (ROTATION, "Secret1Rotation")

        comments = dict(values)
        comments["desired.row.002-001.comment"] = "属性：設定値"
        HELPERS.roundtrip(path, comments, root)
        path.write_text(output)

        metadata = fixture()
        for key in list(metadata):
            if key.startswith("desired.row.002-"):
                row, field = key.removeprefix("desired.row.002-").split(".", 1)
                metadata[f"desired.row.002-{int(row) + 4:03d}.{field}"] = metadata.pop(key)
        for index, (field, value) in enumerate((("Key", "first"), ("Value", "one"), ("Key", "second"), ("Value", "two")), 1):
            prefix = f"desired.row.002-{index:03d}."
            metadata.update({prefix + "property": ROTATION + ".ExternalSecretRotationMetadata[]." + field,
                             prefix + "value": f"`{value}`", prefix + "comment": "外部ローテーションの設定値"})
        metadata_output = HELPERS.roundtrip(path, metadata, root)
        for index, (field, value) in enumerate((("Key", "first"), ("Value", "one"), ("Key", "second"), ("Value", "two"))):
            assert f"| RotationSchedule.ExternalSecretRotationMetadata[{index // 2 + 1}].{field} | `{value}` |" in metadata_output
        assert "| SecretsManager.RotationSchedule.ExternalSecretRotationMetadata" not in metadata_output
        assert properties(SYNC.imported_model(path, root)) == metadata
        SYNC.validate_views(root, root, [path], {path: metadata})
        path.write_text(output)

        # Both desired metadata and the formal property are authoritative.
        for field in ("parentReference", "parentProperty"):
            bad = dict(values)
            del bad[f"desired.resource.002.{field}"]
            rejects(lambda: markdown_for(path, bad, root), "Secret1Rotation", field, ROTATION + ".SecretId")
        for reference in ("[Missing](#missing)", "[Secret1](elsewhere.md#secretsmanager-app-dev-secret-1)",
                          "[WrongLogicalId](#secretsmanager-app-dev-secret-1)",
                          "[Secret1Rotation](#secretsmanager-app-dev-secret-1_rotate)"):
            bad = {**values, "desired.resource.002.parentReference": reference}
            rejects(lambda: markdown_for(path, bad, root), "Secret1Rotation", "parentReference", ROTATION + ".SecretId")
        for key, value in (("desired.resource.002.parentProperty", ROTATION + ".Id"),
                           ("desired.row.002-003.value", "[Secret2](#secretsmanager-app-dev-secret-2)"),
                           ("desired.row.002-003.value", "[Wrong](#secretsmanager-app-dev-secret-1)")):
            bad = {**values, key: value}
            rejects(lambda: markdown_for(path, bad, root), "Secret1Rotation", "SecretId")
        for row in ("002-003",):
            bad = {key: value for key, value in values.items() if not key.startswith((f"desired.row.{row}.", f"observed.row.{row}."))}
            rejects(lambda: markdown_for(path, bad, root), "Secret1Rotation", ".SecretId")
        bad = dict(values)
        for key, value in list(values.items()):
            if key.startswith("desired.row.002-003."):
                bad[key.replace("002-003", "002-004")] = value
        rejects(lambda: markdown_for(path, bad, root), "Secret1Rotation", "exactly one formal row")
        bad = {**values, "desired.resource.004.parentReference": values["desired.resource.002.parentReference"],
               "desired.row.004-003.value": values["desired.row.002-003.value"]}
        rejects(lambda: markdown_for(path, bad, root), "Secret2Rotation", "too many grouped children", "Secret1")

        # Parsing must reject edits independently of model generation.
        invalid_views = [
            (output.replace("[app-dev-secret-1](#secretsmanager-app-dev-secret-1)", "[app-dev-secret-2](#secretsmanager-app-dev-secret-2)"), "must reference enclosing"),
            (output.replace("[app-dev-secret-1](#secretsmanager-app-dev-secret-1)", "[app-dev-secret-1](other.md#secretsmanager-app-dev-secret-1)"), "must reference enclosing"),
            ("\n".join(line for line in output.splitlines() if ROTATION + ".SecretId" not in line), "required property missing"),
            (output.replace("<!-- logical-id: Secret1Rotation -->", ""), "require anchor and logical ID"),
            (output.replace("app-dev-secret-1_rotate：", ""), "confirmed display name required"),
            (output.replace("SecretsManager.Secret:", "S3.Bucket:"), "wrong parent"),
            (output.replace("<!-- logical-id: Secret2Rotation -->", "<!-- logical-id: Secret1Rotation -->"), "duplicate grouped logical ID"),
        ]
        for invalid, message in invalid_views:
            rejects(lambda: expanded_design(invalid.splitlines()), message)
        lines = output.splitlines()
        child_rows = [line for line in lines if ROTATION + "." in line][:3]
        second_child = [line.replace("secret-1_rotate", "secret-3_rotate").replace("Secret1Rotation", "Secret3Rotation") for line in child_rows]
        insertion = lines.index(child_rows[-1]) + 1
        rejects(lambda: expanded_design(lines[:insertion] + second_child + lines[insertion:]), "too many grouped children")
        for kind, identity in ((SECRET, "001"), (ROTATION, "002")):
            legacy = {**values, f"desired.row.{identity}-099.property": kind + ".Id",
                      f"desired.row.{identity}-099.value": "`PENDING_DEPLOY`",
                      f"desired.row.{identity}-099.comment": "旧識別子"}
            rejects(lambda: markdown_for(path, legacy, root), "hidden property", kind + ".Id")
        path.write_text(output)
        mismatch = {**values, "desired.resource.002.parentReference": "[Secret2](#secretsmanager-app-dev-secret-2)"}
        rejects(lambda: SYNC.validate_views(root, root, [path], {path: mismatch}), "model/display projection mismatch", "parentReference")

        # Real sync: simultaneous KMS and Secrets Manager updates and rollback.
        models = root / "model/dev/123456789012"
        models.mkdir(parents=True)
        key = HELPERS.model("kms", "KMS.Key", "app-dev-key", [
            ("KeyId", "[Key](#kms-app-dev-key)", "鍵のID")], "Key", "app-dev-key")
        key.update({"observed.row.001-001.property": "KMS.Key.KeyId",
                    "observed.row.001-001.value": "`PENDING_DEPLOY`", "observed.row.001-001.comment": "鍵のID"})
        for identity in ("001", "003"):
            for namespace, value in (("desired", "[Key](kms.md#kms-app-dev-key)"), ("observed", "PENDING_DEPLOY")):
                values.update({f"{namespace}.row.{identity}-002.property": SECRET + ".KmsKeyId",
                               f"{namespace}.row.{identity}-002.value": value,
                               f"{namespace}.row.{identity}-002.comment": "暗号化する鍵"})

        def save():
            (models / "kms.properties").write_text(HELPERS.text(key))
            (models / "secretsmanager.properties").write_text(HELPERS.text(values))

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
        key = {name: value.replace("kms-app-dev-key", "kms-app-dev-renamed") for name, value in key.items()}
        key["display.resource.001.label"] = "app-dev-renamed"
        save()
        rejects(lambda: SYNC.sync(root, True, "dev", "123456789012"), "Secret1Rotation", "parentReference")
        assert path.read_bytes() == saved[path]
        assert (path.parent / "kms.md").read_bytes() != saved[path.parent / "kms.md"]
        assert "kms-app-dev-renamed" in (path.parent / "kms.md").read_text()
        assert (models / "secretsmanager.properties").read_text() == HELPERS.text(values)
        # Repair only the source in a later task against the already saved KMS view.
        values["desired.resource.002.parentReference"] = "[Secret1](#secretsmanager-app-dev-secret-1)"
        values = {name: value.replace("kms-app-dev-key", "kms-app-dev-renamed") for name, value in values.items()}
        save()
        SYNC.sync(root, True, "dev", "123456789012", services=["secretsmanager"])
        SYNC.sync(root, False, "dev", "123456789012")
        assert "kms-app-dev-key" not in path.read_text()
        assert path.read_text().count("[key-current](kms.md#kms-app-dev-renamed)") == 2
    print("rotation-schedule: PASS (single/multiple parents, identity, formal rows, invalid references, projection, KMS updates and deferred source repair)")


if __name__ == "__main__":
    main()
