#!/usr/bin/env python3
"""Regression checks for explicit scope, isolated services, and parallel targets."""
from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import model_projection
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from test_support.validator import load
import shutil
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

from validation_scope import active_scope, scoped_files
from design_catalog import DesignSchemaCatalog
from validation_cache import PassCache
from model_design import resource_anchor

ROOT = Path(__file__).resolve().parents[2]



VALIDATOR = load('validate-blueprint')
SYNC = load('sync-model')


def check_single_target_cache(root):
    docs, models = root / "docs/designs/dev/cde", root / "model/dev/cde"
    services = {"codecommit": ("CodeCommit.Repository", "RepositoryName", "repo-app-dev-cde"),
                "sqs": ("SQS.Queue", "QueueName", "queue-app-dev-cde"),
                "cloudwatch-logs": ("Logs.LogGroup", "LogGroupName", "logs-app-dev-cde")}
    for service, (kind, prop, name) in services.items():
        values = {f"desired.service.{service}.serviceId": service,
                  f"desired.service.{service}.ownedCatalogResourceTypes": kind,
                  "desired.resource.001.resourceType": kind, "desired.resource.001.logicalId": "FixtureResource",
                  "desired.resource.001.anchor": resource_anchor(service, name, kind),
                  "desired.row.001-001.property": f"{kind}.{prop}", "desired.row.001-001.value": f"`{name}`",
                  "desired.row.001-001.comment": "検証用の名前", "display.service.title": "# 詳細設計",
                  "display.resource.001.comment": "サービス単位の検証対象"}
        for number, output in enumerate(sorted(model_projection.identifier_outputs(root).get(kind, set())), 2):
            row = f"row.001-{number:03d}"
            values.update({f"desired.{row}.property": output,
                           f"desired.{row}.value": f"[FixtureResource](#{values['desired.resource.001.anchor']})",
                           f"desired.{row}.comment": "生成される識別子",
                           f"observed.{row}.property": output, f"observed.{row}.value": "PENDING_DEPLOY",
                           f"observed.{row}.comment": "生成される識別子"})
        (models / f"{service}.properties").write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    scope = {("dev", "cde", service) for service in ["ec2", *services]}
    active = root / "tasks/active.md"
    saved_contract = active.read_text(encoding="utf-8")
    active.write_text("## Validation scope\n" + "".join(f"- `{'/'.join(entry)}`\n" for entry in sorted(scope)), encoding="utf-8")
    with redirect_stdout(io.StringIO()):
        SYNC.sync(root, True, "dev", "cde", services=[entry[2] for entry in sorted(scope)])

    def validate(workers=4, cache=None):
        validator = VALIDATOR.Validator(root, scope, workers=workers)
        validator.cache = cache
        validator.check_project_topology()
        with redirect_stdout(io.StringIO()):
            validator.check_scoped_designs()
        return validator

    serial = validate(1)
    barrier = threading.Barrier(4, timeout=10)
    original = VALIDATOR.Validator.check_designs
    def overlap(worker):
        barrier.wait()
        original(worker)
    with patch.object(VALIDATOR.Validator, "check_designs", overlap):
        parallel = validate()
    assert not serial.errors and not parallel.errors, serial.errors + parallel.errors
    assert serial.checks == parallel.checks
    with tempfile.TemporaryDirectory() as directory:
        cold = validate(cache=PassCache(root, directory=directory))
        assert not cold.errors, cold.errors
        with patch.object(VALIDATOR.Validator, "check_generated_service_models", side_effect=AssertionError("unchanged generation reran")), \
             patch.object(VALIDATOR.Validator, "check_designs", side_effect=AssertionError("unchanged service reran")):
            warm = validate(cache=PassCache(root, directory=directory))
        assert not warm.errors and cold.checks == warm.checks, warm.errors
        # An out-of-scope reference remains shallow, but changing its anchor invalidates its consumer.
        reference = docs / "vpc.md"
        saved = reference.read_text(encoding="utf-8")
        reference.write_text(saved.replace('id="vpc-subnet-app-dev-cde"', 'id="changed-anchor"'), encoding="utf-8")
        invalid = validate(cache=PassCache(root, directory=directory))
        assert invalid.errors and "anchor" in "\n".join(invalid.errors), invalid.errors
        reference.write_text(saved, encoding="utf-8")
        # Newly introduced JSON must never disappear behind an unchanged Markdown cache hit.
        artifact = docs / "codecommit/orphan.json"
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text("invalid JSON", encoding="utf-8")
        invalid = validate(cache=PassCache(root, directory=directory))
        assert invalid.errors and "orphan" in "\n".join(invalid.errors), invalid.errors
        artifact.unlink()
        # Mid-validation edits fail and do not persist the service's old key.
        cache = PassCache(root, fresh=True, directory=directory)
        model = models / "sqs.properties"
        saved = model.read_text(encoding="utf-8")
        old_key = cache.service_key(("dev", "cde", "sqs"))
        (Path(directory) / f"{old_key}.json").unlink()
        def changed(worker):
            original(worker)
            if ("dev", "cde", "sqs") in worker.scope:
                model.write_text(saved + "# input changed during validation\n", encoding="utf-8")
        with patch.object(VALIDATOR.Validator, "check_designs", changed):
            invalid = validate(cache=cache)
        assert any("inputs changed" in error for error in invalid.errors), invalid.errors
        assert not (Path(directory) / f"{old_key}.json").exists()
        model.write_text(saved, encoding="utf-8")
    active.write_text(saved_contract, encoding="utf-8")


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
        check_single_target_cache(root)
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
    print("validation-scope: PASS (4 parallel targets/services, serial equality, cache invalidation, excluded errors, references, schema/naming/JSON, missing scope, explicit all)")


if __name__ == "__main__":
    main()
