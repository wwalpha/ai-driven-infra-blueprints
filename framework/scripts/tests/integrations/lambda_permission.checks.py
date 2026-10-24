#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.it_case_receipt import it_case
from support.lambda_permission_fixtures import (
    HELPERS,
    SYNC,
    Path,
    fixture,
    json,
    properties,
    read_model,
    rejects,
    sys,
    tempfile,
    write_model,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@it_case
def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [
            {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/lambda.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "iam.md").write_text('# IAM\n\n- Design service ID: `iam`\n- Owned catalog resource types: `IAM.Role`\n\n<a id="iam-app-dev-worker-role"></a>\n### IAM.Role: app-dev-worker-role\n\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n| 1 | RoleName | `app-dev-worker-role` | ロールの名前 |\n', encoding="utf-8")
        values = fixture(1, 2)
        HELPERS.roundtrip(path, values, root)
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



if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()
