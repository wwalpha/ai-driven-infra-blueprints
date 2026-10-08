#!/usr/bin/env python3
"""Lambda Permission grouping, hidden identity and lossless view checks."""
import sync_views
import model_projection
import json
import re
import shutil
import tempfile
from pathlib import Path
from test_support.validator import load

from design_layout import expanded_design, formal_property, layout_errors, resource_anchor
from model_design import markdown_for
from model_core import properties

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[2]
HELPERS = load('model_design.checks')
SYNC = HELPERS.SYNC
FUNCTION, PERMISSION = "Lambda.Function", "Lambda.Permission"


def fixture(parents=1, children=1, deployed=False):
    values = {"desired.service.lambda.serviceId": "lambda",
              "desired.service.lambda.ownedCatalogResourceTypes": FUNCTION + "," + PERMISSION,
              "display.service.title": "# Lambda 詳細設計"}
    number = 0
    for parent in range(parents):
        number += 1
        identity = f"{number:03d}"
        name, logical = f"app-dev-worker-{parent + 1}", f"Worker{parent + 1}"
        anchor = resource_anchor("lambda", name)
        values.update({f"desired.resource.{identity}.resourceType": FUNCTION,
                       f"desired.resource.{identity}.logicalId": logical,
                       f"desired.resource.{identity}.anchor": anchor,
                       f"display.resource.{identity}.comment": "業務データを処理する関数"})
        rows = [("FunctionName", f"`{name}`"),
                ("Code.ImageUri", "`123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/worker:latest`"),
                ("PackageType", "`Image`"),
                ("Role", "[app-dev-worker-role](iam.md#iam-app-dev-worker-role)")]
        for index, (field, value) in enumerate(rows, 1):
            key = f"desired.row.{identity}-{index:03d}"
            values.update({key + ".property": FUNCTION + "." + field,
                           key + ".value": value, key + ".comment": "属性の設定値"})
        for child in range(children):
            number += 1
            child_id = f"{number:03d}"
            child_name, child_logical = f"app-dev-invoke-{parent + 1}-{child + 1}", f"Invoke{parent + 1}_{child + 1}"
            child_anchor = resource_anchor("lambda", child_name)
            reference = f"[{logical}](#{anchor})"
            values.update({f"desired.resource.{child_id}.resourceType": PERMISSION,
                           f"desired.resource.{child_id}.logicalId": child_logical,
                           f"desired.resource.{child_id}.anchor": child_anchor,
                           f"desired.resource.{child_id}.parentProperty": PERMISSION + ".FunctionName",
                           f"desired.resource.{child_id}.parentReference": reference,
                           f"display.resource.{child_id}.label": child_name})
            rows = [("Id", f"[{child_logical}](#{child_anchor})"),
                    ("Action", "`lambda:InvokeFunction`"),
                    ("EventSourceToken", "`source-token`"),
                    ("FunctionName", reference),
                    ("Principal", "`events.amazonaws.com`"),
                    ("SourceAccount", "`123456789012`")]
            for index, (field, value) in enumerate(rows, 1):
                key = f"{child_id}-{index:03d}"
                values.update({f"desired.row.{key}.property": PERMISSION + "." + field,
                               f"desired.row.{key}.value": value,
                               f"desired.row.{key}.comment": f"許可属性{index}の設定値"})
                if field == "Id":
                    values.update({f"observed.row.{key}.property": PERMISSION + ".Id",
                                   f"observed.row.{key}.value": f"`permission-{parent + 1}-{child + 1}`" if deployed else "`PENDING_DEPLOY`",
                                   f"observed.row.{key}.comment": f"許可属性{index}の設定値"})
    return values


def rejects(action, message):
    try:
        action()
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError(f"invalid input accepted: {message}")


def main():
    assert not layout_errors(ROOT)
    assert formal_property("Permission.Action", FUNCTION) == PERMISSION + ".Action"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [
            {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/lambda.md"
        path.parent.mkdir(parents=True)
        (path.parent / "iam.md").write_text('# IAM\n\n- Design service ID: `iam`\n- Owned catalog resource types: `IAM.Role`\n\n<a id="iam-app-dev-worker-role"></a>\n### IAM.Role: app-dev-worker-role\n\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n| 1 | RoleName | `app-dev-worker-role` | ロールの名前 |\n', encoding="utf-8")
        for parents, children, deployed in ((1, 0, False), (1, 1, False), (2, 2, False), (2, 2, True)):
            values = fixture(parents, children, deployed)
            output = HELPERS.roundtrip(path, values, root)
            assert properties(model_projection.imported_model(path, root)) == values
            sync_views.validate_views(root, root, [path], {path: values})
            _, grouped = expanded_design(output.splitlines())
            assert len(grouped) == parents * children
            assert "### Lambda.Permission" not in output
            visible = re.sub(r"<!--.*?-->|<a[^>]*></a>", "", output)
            assert "Permission.Id" not in visible and "Permission.FunctionName" not in visible
            assert visible.count("Permission.Action") == parents * children
            assert "Permission.Principal" in visible or children == 0
            assert output.count("| No. | Property | Value | Source / Comment |") == parents
            if children:
                assert model_projection.linked_resource(path, "[permission-1-1](#lambda-app-dev-invoke-1-1)") == (PERMISSION, "Invoke1_1")

        values = fixture(1, 2)
        output = HELPERS.roundtrip(path, values, root)
        for field in ("parentProperty", "parentReference"):
            bad = dict(values)
            del bad[f"desired.resource.002.{field}"]
            rejects(lambda: markdown_for(path, bad, root), field)
        bad = dict(values)
        bad["desired.row.002-004.value"] = "[Wrong](#lambda-wrong)"
        rejects(lambda: markdown_for(path, bad, root), "exactly one formal row")
        bad = dict(values)
        del bad["desired.row.002-001.property"]
        rejects(lambda: markdown_for(path, bad, root), "invalid resource row")
        for text, message in (
            (output.replace("Permission.Action", "Permission.Id", 1), "must not be displayed"),
            (output.replace("Permission.Action", "Permission.FunctionName", 1), "must not be displayed"),
            (output.replace("<!-- lambda-permission: [", "<!-- lambda-permission: broken[", 1), "invalid Lambda Permission metadata"),
            (output.replace("Permission.Action", "Lambda.Permission.Action", 1), "Permission.*"),
            (output.replace("<!-- lambda-permission:", "<!-- invalid-permission:", 1), "complete identity"),
            (output.replace("<!-- logical-id: Invoke1_1 -->", "", 1), "complete identity"),
            (output.replace("<!-- logical-id: Invoke1_2 -->", "<!-- logical-id: Invoke1_1 -->", 1), "duplicate grouped"),
            (output.replace("Permission.Principal", "Permission.Action", 1), "duplicate Lambda Permission"),
            (output.replace("[Worker1]\\u0028#lambda-app-dev-worker-1\\u0029", "[Wrong]\\u0028#lambda-wrong\\u0029", 1), "must reference enclosing"),
            (output.replace('"Lambda.Permission.Id"', '"Wrong.Id"', 1), "invalid Lambda Permission metadata"),
        ):
            rejects(lambda: expanded_design(text.splitlines()), message)
        source = root / "model/dev/123456789012/lambda.properties"
        source.parent.mkdir(parents=True)
        source.write_text(HELPERS.text(values), encoding="utf-8")
        SYNC.sync(root, True, "dev", "123456789012", services=["lambda"])
        SYNC.sync(root, False, "dev", "123456789012", services=["lambda"])
        assert source.read_text(encoding="utf-8") == HELPERS.text(values)
        saved = path.read_bytes()
        bad = dict(values)
        del bad["desired.resource.002.parentReference"]
        source.write_text(HELPERS.text(bad), encoding="utf-8")
        rejects(lambda: SYNC.sync(root, True, "dev", "123456789012", services=["lambda"]), "parentReference")
        assert path.read_bytes() == saved
    print("Lambda Permission: PASS (same table, short properties, hidden rows, multiple parents/children, namespaces, links, rejection and saved view protection)")


if __name__ == "__main__":
    main()
