#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sys
from pathlib import Path

import pytest
from support.lambda_permission_fixtures import (
    FUNCTION,
    PERMISSION,
    ROOT,
    Path,
    expanded_design,
    fixture,
    formal_property,
    json,
    layout_errors,
    markdown_for,
    model_projection,
    re,
    rejects,
    sync_views,
    sys,
    tempfile,
)
from support.model_design_fixtures import STACK_VALUES
from support.model_sources import write_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_permission_catalog():
    assert not layout_errors(ROOT)
    assert formal_property("Permission.Action", FUNCTION) == PERMISSION + ".Action"




pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

def check_permission_inputs():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [
            {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/lambda.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "iam.md").write_text('# IAM\n\n- Design service ID: `iam`\n- Owned catalog resource types: `IAM.Role`\n\n<a id="iam-app-dev-worker-role"></a>\n### IAM.Role: app-dev-worker-role\n\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n| 1 | RoleName | `app-dev-worker-role` | ロールの名前 |\n', encoding="utf-8")
        write_model(root / 'model/dev/123456789012/cloudformation-stacks.properties', STACK_VALUES)
        for parents, children, deployed in ((1, 0, False), (1, 1, False), (2, 2, False), (2, 2, True)):
            values = fixture(parents, children, deployed)
            output = markdown_for(path, values, root)
            path.write_text(output, encoding="utf-8")
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
                assert model_projection.linked_resource(path, "[permission-1-1](#" + values["desired.resource.002.anchor"] + ")") == (PERMISSION, "Lambda_Permission_001")

        values = fixture(1, 2)
        output = markdown_for(path, values, root)
        path.write_text(output, encoding="utf-8")
        for field in ("parentProperty", "parentReference"):
            bad = dict(values)
            del bad[f"desired.resource.002.{field}"]
            rejects(lambda *, bad=bad: markdown_for(path, bad, root), field)
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
            (output.replace("[app-dev-worker-1]\\u0028#lambda-app-dev-worker-1\\u0029", "[Wrong]\\u0028#lambda-wrong\\u0029", 1), "must reference enclosing"),
            (output.replace('"Lambda.Permission.Id"', '"Wrong.Id"', 1), "invalid Lambda Permission metadata"),
        ):
            rejects(lambda *, text=text: expanded_design(text.splitlines()), message)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
