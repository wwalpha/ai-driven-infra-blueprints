#!/usr/bin/env python3
"""Regression checks for explicit scope, isolated services, and parallel targets."""
from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

from validation_scope import active_scope, scoped_files
from design_catalog import DesignSchemaCatalog

ROOT = Path(__file__).resolve().parents[2]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "framework/scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load("scoped_validator", "validate-blueprint.py")
SYNC = load("scoped_sync", "sync-model.py")


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "tasks").mkdir()
        active = root / "tasks/active.md"
        for text in ("", "## Validation scope\n- `dev/cde`\n", "## Validation scope\n- `ec2`\n"):
            active.write_text(text)
            try:
                active_scope(root)
            except ValueError:
                pass
            else:
                raise AssertionError("missing/incomplete scope accepted")
        assert active_scope(root, True) is None
        active.write_text("## Validation scope\n- `all`\n")
        assert active_scope(root) is None
        scope = {(env, target, "ec2") for env in ("dev", "stg") for target in ("cde", "non-cde")}
        contract = "## Validation scope\n" + "".join(f"- `{'/'.join(item)}`\n" for item in sorted(scope))
        active.write_text(contract)
        assert active_scope(root) == scope
        project = {"projectName": "app", "targets": []}
        for env in ("dev", "prod", "stg"):
            for target in ("cde", "non-cde"):
                project["targets"].append({"environment": env, "alias": target, "awsAccountId": "123456789012",
                                           "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"})
                docs = root / f"docs/designs/{env}/{target}"
                models = root / f"model/{env}/{target}"
                docs.mkdir(parents=True)
                models.mkdir(parents=True)
                (docs / "logs.md").write_text("invalid unrelated service\n")
                (models / "logs.properties").write_text("observed.bad=arn:aws:logs:invalid\nnot properties\n")
                if env == "prod":
                    (models / "ec2.properties").write_text("invalid excluded EC2\n")
                    (docs / "ec2.md").write_text("invalid excluded EC2\n")
                    continue
                # A reference target with intentionally invalid schema/metadata must supply only link information.
                anchor = f"vpc-subnet-app-{env}-{target}"
                (docs / "vpc.md").write_text(f'''# Reference only
<a id="{anchor}"></a>
### EC2.Subnet: subnet-app-{env}-{target}
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `subnet-app-{env}-{target}` | 名前 |
| 2 | SubnetId | `PENDING_DEPLOY` | ID |
| 3 | CidrBlock | `not-a-cidr` | 無効な対象外設定 |
<a id="vpc-unrelated"></a>
### EC2.VPC: unrelated
| No. | Property | Value | Source / Comment |
invalid unrelated table alignment
''')
                name = f"{env}-app-{target}-01"
                values = {"desired.service.ec2.serviceId": "ec2", "desired.service.ec2.ownedCatalogResourceTypes": "EC2.Instance",
                          "desired.resource.001.resourceType": "EC2.Instance", "desired.resource.001.logicalId": "AppInstance",
                          "desired.resource.001.anchor": f"ec2-{name}", "display.service.title": "# EC2 詳細設計",
                          "display.resource.001.comment": "アプリケーションの仮想マシン"}
                for index, (prop, value) in enumerate((
                    ("InstanceId", f"[AppInstance](#ec2-{name})"), ("ImageId", "`ami-0123456789abcdef0`"),
                    ("InstanceType", "`t3.micro`"), ("SubnetId", f"[subnet-app-{env}-{target}](vpc.md#{anchor})"),
                    ("Tags[].Key", "`Name`"), ("Tags[].Value", f"`{name}`")), 1):
                    key = f"row.001-{index:03d}"
                    values[f"desired.{key}.property"] = f"EC2.Instance.{prop}"
                    values[f"desired.{key}.value"] = value
                    values[f"desired.{key}.comment"] = "仮想マシンの設定"
                    if prop in {"InstanceId", "SubnetId"}:
                        values[f"observed.{key}.property"] = f"EC2.Instance.{prop}"
                        values[f"observed.{key}.value"] = "PENDING_DEPLOY"
                        values[f"observed.{key}.comment"] = "仮想マシンの設定"
                (models / "ec2.properties").write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        (root / "project.json").write_text(json.dumps(project) + "\n")
        # Generate exactly four EC2 views; neither invalid prod nor invalid Logs may block them.
        with redirect_stdout(io.StringIO()):
            for env, target, service in sorted(scope):
                SYNC.sync(root, True, env, target, services=[service])
        assert len(scoped_files(root, "model", ".properties", scope)) == 4
        validator = VALIDATOR.Validator(root, scope)
        validator.check_project_topology()
        validator.check_validation_scope()
        assert not validator.errors, validator.errors
        # Barrier proves four target workers overlap, instead of checking elapsed time.
        barrier = threading.Barrier(4, timeout=10)
        original = VALIDATOR.Validator.check_designs
        workers = set()
        def overlapping(worker):
            workers.add(threading.get_ident())
            barrier.wait()
            original(worker)
        with patch.object(VALIDATOR.Validator, "check_designs", overlapping), redirect_stdout(io.StringIO()):
            validator.check_scoped_designs()
        assert len(workers) == 4 and not validator.errors, validator.errors
        assert validator.generated_models_checked
        # Missing/unknown selectors and changes outside scope fail before service checks.
        for invalid in ({("unknown", "cde", "ec2")}, {("dev", "cde", "missing")}):
            rejected = VALIDATOR.Validator(root, invalid)
            rejected.accounts = validator.accounts
            rejected.check_validation_scope()
            assert rejected.errors
        validator.changed_paths = {"model/prod/cde/ec2.properties"}
        validator.check_validation_scope()
        assert any("outside validation scope" in error for error in validator.errors)
        design = root / "docs/designs/dev/cde/ec2.md"
        saved = design.read_text()
        design.write_text(saved.replace("vpc.md#vpc-subnet-app-dev-cde", "vpc.md#missing-anchor"))
        rejected = VALIDATOR.Validator(root, {("dev", "cde", "ec2")})
        rejected.accounts = validator.accounts
        rejected.schema_catalog = DesignSchemaCatalog(root)
        rejected.check_design_links(rejected.catalog_design_properties()[2])
        assert any("missing design anchor" in error for error in rejected.errors), rejected.errors
        design.write_text(saved)
        # Selected schema, naming, JSON, and generation errors remain failures.
        model = root / "model/dev/cde/ec2.properties"
        source = model.read_text()
        for bad, token in ((source.replace('EC2.Instance.InstanceType', 'EC2.Instance.EbsOptimized'), 'EbsOptimized'),
                           (source.replace('`dev-app-cde-01`', '`UNSET`'), 'Name')):
            model.write_text(bad)
            try:
                with redirect_stdout(io.StringIO()):
                    SYNC.sync(root, False, "dev", "cde", services=["ec2"])
            except ValueError as error:
                assert token in str(error), error
            else:
                raise AssertionError("selected invalid design accepted")
        model.write_text(source)
        artifact = design.with_suffix("") / "orphan.json"
        artifact.parent.mkdir()
        artifact.write_text("bad JSON")
        rejected = VALIDATOR.Validator(root, {("dev", "cde", "ec2")})
        rejected.accounts = validator.accounts
        rejected.check_design_artifacts(rejected.design_files())
        assert any("invalid design JSON" in error for error in rejected.errors)
        artifact.unlink()
        with redirect_stdout(io.StringIO()):
            full = VALIDATOR.Validator(root)
            full.check_generated_service_models()
        assert full.errors and "logs" in "\n".join(full.errors)
        # CLI sync must also stop on absent scope; it cannot silently select everything.
        active.write_text("# no scope\n")
        result = subprocess.run([sys.executable, str(ROOT / "framework/scripts/sync-model.py"), "--repository-root", str(root)], capture_output=True, text=True)
        assert result.returncode and "validation scope missing" in result.stderr
        active.write_text(contract)
        result = subprocess.run([sys.executable, str(ROOT / "framework/scripts/sync-model.py"), "--repository-root", str(root),
                                 "--environment", "prod", "--alias", "cde", "--service", "ec2"], capture_output=True, text=True)
        assert result.returncode and "outside active task validation scope" in result.stderr
    print("validation-scope: PASS (4 parallel EC2 targets, excluded errors, references, schema/naming/JSON, missing scope, explicit all)")


if __name__ == "__main__":
    main()
