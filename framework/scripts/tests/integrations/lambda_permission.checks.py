#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.lambda_permission_fixtures import *

from support.it_workspace import copy_framework

@it_case
def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        copy_framework(root / 'framework')
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [
            {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/lambda.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "iam.md").write_text('# IAM\n\n- Design service ID: `iam`\n- Owned catalog resource types: `IAM.Role`\n\n<a id="iam-app-dev-worker-role"></a>\n### IAM.Role: app-dev-worker-role\n\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n| 1 | RoleName | `app-dev-worker-role` | ロールの名前 |\n', encoding="utf-8")
        for parents, children, deployed in ((1, 0, False), (1, 1, False), (2, 2, False), (2, 2, True)):
            values = fixture(parents, children, deployed)
            output = HELPERS.roundtrip(path, values, root)
            sync_views.validate_views(root, root, [path], {path: values})
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
                assert model_projection.linked_resource(path, "[permission-1-1](#resource-Lambda_Permission_001)") == (PERMISSION, "Lambda_Permission_001")

        values = fixture(1, 2)
        output = HELPERS.roundtrip(path, values, root)
        for field in ("parentProperty", "parentReference"):
            bad = dict(values)
            del bad[f"desired.resource.002.{field}"]
            rejects(lambda: markdown_for(path, bad, root), field)
        bad = dict(values)
        bad["desired.row.002-004.value"] = "[Wrong](#lambda-wrong)"
        rejects(lambda: markdown_for(path, bad, root), "grouped formal row does not match parentReference")
        bad = dict(values)
        del bad["desired.row.002-001.property"]
        del bad["observed.row.002-001.property"]
        rejects(lambda: markdown_for(path, bad, root), "invalid resource row")
        for text, message in (
            (output.replace("Permission.Action", "Permission.Id", 1), "must not be displayed"),
            (output.replace("Permission.Action", "Permission.FunctionName", 1), "must not be displayed"),
            (output.replace("<!-- lambda-permission: [", "<!-- lambda-permission: broken[", 1), "invalid Lambda Permission metadata"),
            (output.replace("Permission.Action", "Lambda.Permission.Action", 1), "Permission.*"),
            (output.replace("<!-- lambda-permission:", "<!-- invalid-permission:", 1), "complete identity"),
            (output.replace("<!-- logical-id: Lambda_Permission_001 -->", "", 1), "complete identity"),
            (output.replace("<!-- logical-id: Lambda_Permission_002 -->", "<!-- logical-id: Lambda_Permission_001 -->", 1), "duplicate grouped"),
            (output.replace("Permission.Principal", "Permission.Action", 1), "duplicate Lambda Permission"),
            (output.replace("[app-dev-worker-1]\\u0028#resource-Lambda_Function_001\\u0029", "[Wrong]\\u0028#lambda-wrong\\u0029", 1), "must reference enclosing"),
            (output.replace('"Lambda.Permission.Id"', '"Wrong.Id"', 1), "invalid Lambda Permission metadata"),
        ):
            rejects(lambda: expanded_design(text.splitlines()), message)
        source = root / "model/dev/123456789012/lambda.properties"
        source.parent.mkdir(parents=True, exist_ok=True)
        write_model(source, HELPERS.text(values))
        SYNC.sync(root, True, "dev", "123456789012", services=["lambda"])
        SYNC.sync(root, False, "dev", "123456789012", services=["lambda"])
        assert properties(read_model(source)) == properties(HELPERS.text(values))
        saved = path.read_bytes()
        bad = dict(values)
        del bad["desired.resource.002.parentReference"]
        write_model(source, HELPERS.text(bad))
        rejects(lambda: SYNC.sync(root, True, "dev", "123456789012", services=["lambda"]), "parentReference")
        assert path.read_bytes() == saved
    print("Lambda Permission: PASS (same table, short properties, hidden rows, multiple parents/children, namespaces, links, rejection and saved view protection)")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()

