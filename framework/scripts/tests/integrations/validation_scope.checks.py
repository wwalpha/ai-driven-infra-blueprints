#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import model.sources as _imports_model_sources
import sync_runtime as _imports_sync_runtime
from support import model_templates_fixtures as source_checks
from support.it_case_receipt import it_case
from support.validation_scope_fixtures import (
    ROOT,
    SYNC,
    VALIDATOR,
    DesignSchemaCatalog,
    PassCache,
    Path,
    io,
    json,
    model_projection,
    patch,
    read_model,
    redirect_stdout,
    scoped_files,
    subprocess,
    sys,
    tempfile,
    threading,
    write_model,
)
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.input_cache import input_context
from utils.reference_contracts import reference_attribute

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_single_target_cache_overlap(barrier, original, /, worker):
    barrier.wait()
    original(worker)


def _callback_check_single_target_cache_changed(model, original, saved, /, worker):
    original(worker)
    if ("dev", "cde", "sqs") in worker.scope:
        write_model(model, saved + "# input changed during validation\n")


def _callback_check_single_target_cache_pending(
    calls, expected_scope, original, worker
):
    if worker.scope != expected_scope:
        raise AssertionError("resolved unchanged service reran")
    calls.append(original.__name__)
    return original(worker)


def _callback_check_single_target_cache_validate(root, scope, /, workers=4, cache=None):
    validator = VALIDATOR.Validator(root, scope, workers=workers)
    validator.cache = cache
    if cache:
        cache.common = cache.common_key()
    validator.check_project_topology()
    with redirect_stdout(io.StringIO()):
        validator.check_scoped_designs()
    if cache and not validator.errors:
        VALIDATOR.verify_contract_reads(root)
        validator.finalize_service_cache(cache.common_key())
    return validator


@it_case
def check_single_target_cache(root):
    docs, models = root / "docs/designs/dev/cde", root / "model/dev/cde"
    services = {
        "codecommit": ("CodeCommit.Repository", "RepositoryName", "repo-app-dev-cde"),
        "sqs": ("SQS.Queue", "QueueName", "queue-app-dev-cde"),
        "cloudwatch-logs": ("Logs.LogGroup", "LogGroupName", "logs-app-dev-cde"),
    }
    for service, (kind, prop, name) in services.items():
        values = {
            f"desired.service.{service}.serviceId": service,
            f"desired.service.{service}.ownedCatalogResourceTypes": kind,
            "desired.resource.001.resourceType": kind,
            "desired.resource.001.logicalId": kind.replace(".", "_") + "_001",
            "desired.resource.001.anchor": "resource-"
            + (kind.replace(".", "_") + "_001"),
            "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
            "desired.resource.001.cfn-logicalId": "fixture-FixtureResource",
            "desired.row.001-001.property": f"{kind}.{prop}",
            "desired.row.001-001.value": f"`{name}`",
            "desired.row.001-001.comment": "検証用の名前",
            "display.service.title": "# 詳細設計",
            "display.resource.001.comment": "サービス単位の検証対象",
        }
        for number, output in enumerate(
            sorted(model_projection.identifier_outputs(root).get(kind, set())), 2
        ):
            row = f"row.001-{number:03d}"
            values.update(
                {
                    f"desired.{row}.property": output,
                    f"desired.{row}.value": "`"
                    + json.dumps(
                        {
                            "$modelRef": {
                                "logicalId": values["desired.resource.001.logicalId"],
                                "attribute": reference_attribute(
                                    kind, output.removeprefix(kind + ".")
                                ),
                            }
                        }
                    )
                    + "`",
                    f"desired.{row}.comment": "生成される識別子",
                    f"observed.{row}.property": output,
                    f"observed.{row}.value": "https://sqs.ap-northeast-1.amazonaws.com/123456789012/queue-app-dev-cde"
                    if kind == "SQS.Queue"
                    else "12345678-1234-1234-1234-123456789012",
                    f"observed.{row}.comment": "生成される識別子",
                }
            )
        write_model(
            models / f"{service}.properties",
            "".join(f"{key}={value}\n" for key, value in values.items()),
        )
    instance = models / "ec2.properties"
    instance_values = _imports_model_sources.load_model(instance).authoritative
    instance_values = dict(instance_values)
    instance_values["observed.row.001-001.value"] = "`i-0123456789abcdef0`"
    write_model(instance, instance_values)
    scope = {("dev", "cde", service) for service in ["ec2", *services]}
    active = root / "tasks/example.md"
    saved_contract = active.read_text(encoding="utf-8")
    active.write_text(
        saved_contract.split("## Modified files")[0]
        + "## Validation scope\n"
        + "".join(f"- `{'/'.join(entry)}`\n" for entry in sorted(scope))
        + "## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n- `model/**`\n- `docs/designs/**`\n",
        encoding="utf-8",
    )
    planned = [
        *models.glob("*.properties"),
        *(docs / (service + ".md") for service in ["ec2", *services]),
    ]
    active.write_text(
        active.read_text().replace(
            "## Modified files\n",
            "## Modified files\n"
            + "".join(
                "- `" + file.relative_to(root).as_posix() + "`\n" for file in planned
            ),
        )
    )
    with redirect_stdout(io.StringIO()):
        SYNC.sync(
            root, True, "dev", "cde", services=[entry[2] for entry in sorted(scope)]
        )

    validate = _bind_framework_callback(
        _callback_check_single_target_cache_validate, root, scope
    )

    serial = validate(1)
    barrier = threading.Barrier(4, timeout=10)
    original = VALIDATOR.Validator.check_designs
    overlap = _bind_framework_callback(
        _callback_check_single_target_cache_overlap, barrier, original
    )
    with patch.object(VALIDATOR.Validator, "check_designs", overlap):
        parallel = validate()
    assert not serial.errors and not parallel.errors, serial.errors + parallel.errors
    assert serial.checks == parallel.checks
    with tempfile.TemporaryDirectory() as directory:
        shared_cache = PassCache(root, directory=directory)
        cold = validate(cache=shared_cache)
        assert not cold.errors, cold.errors
        # Pending typed references rerun; the other three resolved services reuse their PASS.
        calls = []
        with (
            patch.object(
                VALIDATOR.Validator,
                "check_generated_service_models",
                _bind_framework_callback(
                    _callback_check_single_target_cache_pending,
                    calls,
                    scope,
                    VALIDATOR.Validator.check_generated_service_models,
                ),
            ),
            patch.object(
                VALIDATOR.Validator,
                "check_designs",
                _bind_framework_callback(
                    _callback_check_single_target_cache_pending,
                    calls,
                    {("dev", "cde", "ec2")},
                    original,
                ),
            ),
        ):
            warm = validate(cache=shared_cache)
        assert not warm.errors and cold.checks == warm.checks, warm.errors
        TestCase().assertCountEqual(
            calls, ["check_generated_service_models", "check_designs"]
        )
        # An out-of-scope reference remains shallow, but changing its anchor invalidates its consumer.
        reference = docs / "vpc.md"
        saved = reference.read_text(encoding="utf-8")
        reference.write_text(
            saved.replace('id="resource-EC2_Subnet_001"', 'id="changed-anchor"'),
            encoding="utf-8",
        )
        invalid = validate(cache=shared_cache)
        assert not invalid.errors and any(
            "anchor" in warning["message"] for warning in invalid.findings.warnings
        ), invalid.findings.warnings
        reference.write_text(saved, encoding="utf-8")
        # Newly introduced JSON must never disappear behind an unchanged Markdown cache hit.
        artifact = docs / "codecommit/orphan.json"
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text("invalid JSON", encoding="utf-8")
        invalid = validate(cache=shared_cache)
        assert invalid.errors and "orphan" in "\n".join(invalid.errors), invalid.errors
        artifact.unlink()
        # Mid-validation edits fail and do not persist the service's old key.
        cache = PassCache(root, fresh=True, directory=directory)
        model = models / "sqs.properties"
        saved = read_model(model)
        changed = _bind_framework_callback(
            _callback_check_single_target_cache_changed, model, original, saved
        )
        with patch.object(VALIDATOR.Validator, "check_designs", changed):
            invalid = validate(cache=cache)
        assert any("inputs changed" in error for error in invalid.errors), (
            invalid.errors
        )
        write_model(model, saved)
    for service in services:
        (models / (service + ".properties")).unlink()
        (docs / (service + ".md")).unlink()
    active.write_text(saved_contract, encoding="utf-8")


def _callback_check_template_consumers_validate(directory, root, scope, /):
    validator = VALIDATOR.Validator(root, scope, workers=1)
    validator.cache = PassCache(root, directory=directory)
    validator.check_project_topology()
    with redirect_stdout(io.StringIO()):
        validator.check_scoped_designs()
    assert not validator.errors, validator.errors
    VALIDATOR.verify_contract_reads(root)
    validator.finalize_service_cache(validator.cache.common_key())
    return validator


@it_case
def check_template_consumers(root):
    source_checks.fixture(root, ("dev", "stg"))
    values = source_checks.config_model()
    for env in ("dev", "stg"):
        source_checks.write_fixture(root, env, "config", values)
    scope = {(env, "team", "config") for env in ("dev", "stg")}
    contract = root / "tasks/example.md"
    contract.write_text(
        "## Task contract\n- Task type: `migration`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Validation scope\n"
        + "".join(f"- `{'/'.join(entry)}`\n" for entry in sorted(scope))
        + "## Allowed paths\n- `tasks/example.md`\n- `model/**`\n- `docs/designs/**`\n"
    )
    planned = [
        "project.json",
        "model/dev/team/config.properties",
        "model/stg/team/config.properties",
        "docs/designs/dev/team/config.md",
        "docs/designs/stg/team/config.md",
    ]
    contract.write_text(
        contract.read_text()
        .replace(
            "## Modified files\n",
            "## Modified files\n" + "".join("- `" + path + "`\n" for path in planned),
        )
        .replace("## Allowed paths\n", "## Allowed paths\n- `project.json`\n")
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    dependency_index.rebuild(root)
    command = [
        sys.executable,
        str(ROOT / "framework/scripts/sync-model.py"),
        "--repository-root",
        str(root),
    ]
    for selection, expected in (
        (["--scope", "dev/team/config", "--scope", "stg/team/config"], 0),
        (["--scope", "dev/team/config"], 1),
        (["--scope", "dev/other/config"], 1),
        (["--scope", "../team/config"], 1),
        (["--scope", "dev/team/config", "--all"], 2),
    ):
        result = subprocess.run(command + selection, capture_output=True, text=True)
        assert result.returncode == expected, (selection, result.stdout, result.stderr)
        if selection == ["--scope", "dev/team/config"]:
            assert "stg/team/config" in result.stderr
    # A committed baseline makes the environment-specific change real rather than mocking Git.
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "synthetic scope baseline",
        ],
        cwd=root,
        check=True,
    )
    model = root / "model/dev/team/config.properties"
    model.write_text(
        model.read_text(encoding="utf-8") + "# dev input changed\n", encoding="utf-8"
    )
    with (
        patch.object(sys, "argv", command[1:] + ["--scope", "dev/team/config"]),
        redirect_stdout(io.StringIO()),
    ):
        assert SYNC.active_scope(root) == scope
        assert SYNC.main() == 0
    with tempfile.TemporaryDirectory() as directory, input_context():
        validate = _bind_framework_callback(
            _callback_check_template_consumers_validate, directory, root, scope
        )
        cold = validate()
        dev_key = cold.service_keys[("dev", "team", "config")]
        cold.cache._results().pop(dev_key)
        sync_runtime = _imports_sync_runtime
        with patch.object(
            sync_runtime, "compare_generation", wraps=sync_runtime.compare_generation
        ) as generate:
            partial = validate()
        assert generate.call_count == 1, generate.call_args_list
        assert generate.call_args.args == (root, scope), generate.call_args
        options = generate.call_args.kwargs
        assert options.keys() == {"jobs", "definitions_root", "findings"}
        assert options["jobs"] == 1 and options["definitions_root"] == __import__(
            "utils.aws_mappings", fromlist=["definition_root"]
        ).definition_root(root)
        assert isinstance(options["findings"], type(partial.findings))
        assert options["findings"].canonical_root == root
        assert partial.checks == cold.checks
        with patch.object(
            VALIDATOR.Validator,
            "check_generated_service_models",
            side_effect=AssertionError("unchanged generation reran"),
        ):
            warm = validate()
        assert warm.checks == cold.checks


def _callback_main_overlapping(barrier, original, workers, /, worker):
    workers.add(threading.get_ident())
    barrier.wait()
    original(worker)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        (root / "tasks").mkdir()
        active = root / "tasks/example.md"
        scope = {
            (env, target, "ec2")
            for env in ("dev", "stg")
            for target in ("cde", "non-cde")
        }
        contract = (
            "## Task contract\n- Task type: `governance`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n- `README.md`\n## Allowed paths\n- `tasks/example.md`\n- `README.md`\n## Validation scope\n"
            + "".join(f"- `{'/'.join(item)}`\n" for item in sorted(scope))
        )
        contract = contract.replace(
            "## Modified files\n",
            "## Modified files\n"
            + "".join(
                f"- `docs/designs/{env}/{target}/{service}.md`\n"
                for env, target, service in sorted(scope)
            ),
        )
        contract = contract.replace(
            "## Allowed paths\n", "## Allowed paths\n- `docs/designs/**`\n"
        )
        active.write_text(contract)
        project = {"projectName": "app", "targets": []}
        for env in ("dev", "prod", "stg"):
            for target in ("cde", "non-cde"):
                project["targets"].append(
                    {
                        "environment": env,
                        "alias": target,
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                )
                docs = root / f"docs/designs/{env}/{target}"
                models = root / f"model/{env}/{target}"
                docs.mkdir(parents=True)
                models.mkdir(parents=True)
                (docs / "logs.md").write_text("invalid unrelated service\n")
                (models / "logs.properties").write_text(
                    "# model-format: 2\nobserved.bad=arn:aws:logs:invalid\n"
                )
                if env == "prod":
                    (models / "ec2.properties").write_text(
                        "# model-format: 2\ninvalid=excluded EC2\n"
                    )
                    (docs / "ec2.md").write_text("invalid excluded EC2\n")
                    continue
                # A reference target with intentionally invalid schema/metadata must supply only link information.
                anchor = "resource-EC2_Subnet_001"
                (docs / "vpc.md").write_text(f'''# Reference only
<!-- resource-logical-id: EC2_Subnet_001 -->
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
                write_model(
                    models / "vpc.properties",
                    {
                        "display.service.title": "# 参照先VPC",
                        "display.resource.001.comment": "参照するサブネット",
                        "desired.service.vpc.serviceId": "vpc",
                        "desired.service.vpc.ownedCatalogResourceTypes": "EC2.Subnet",
                        "desired.resource.001.resourceType": "EC2.Subnet",
                        "desired.resource.001.logicalId": "EC2_Subnet_001",
                        "desired.resource.001.anchor": "resource-EC2_Subnet_001",
                        "desired.service.identity.lastAllocated": '{"EC2.Subnet":1}',
                        "desired.row.001-001.property": "EC2.Subnet.Name",
                        "desired.row.001-001.value": "`subnet-app-"
                        + env
                        + "-"
                        + target
                        + "`",
                        "desired.row.001-001.comment": "参照先のみを読む合成値",
                        "desired.row.001-002.property": "EC2.Subnet.SubnetId",
                        "desired.row.001-002.value": "`subnet-0123456789abcdef0`",
                        "desired.row.001-002.comment": "取得済み識別子",
                    },
                )
                name = f"{env}-app-{target}-01"
                values = {
                    "desired.service.ec2.serviceId": "ec2",
                    "desired.service.ec2.ownedCatalogResourceTypes": "EC2.Instance",
                    "desired.resource.001.resourceType": "EC2.Instance",
                    "desired.resource.001.logicalId": "EC2_Instance_001",
                    "desired.resource.001.anchor": "resource-EC2_Instance_001",
                    "desired.resource.001.cfn-logicalId": "fixture-AppInstance",
                    "desired.service.identity.lastAllocated": '{"EC2.Instance":1}',
                    "display.service.title": "# EC2 詳細設計",
                    "display.resource.001.comment": "アプリケーションの仮想マシン",
                }
                for index, (prop, value) in enumerate(
                    (
                        (
                            "InstanceId",
                            '`{"$modelRef":{"logicalId":"EC2_Instance_001","attribute":"InstanceId"}}`',
                        ),
                        ("ImageId", "`ami-0123456789abcdef0`"),
                        ("InstanceType", "`t3.micro`"),
                        (
                            "SubnetId",
                            '`{"$modelRef":{"logicalId":"EC2_Subnet_001","attribute":"SubnetId"}}`',
                        ),
                        ("Tags[].Key", "`Name`"),
                        ("Tags[].Value", f"`{name}`"),
                    ),
                    1,
                ):
                    key = f"row.001-{index:03d}"
                    values[f"desired.{key}.property"] = f"EC2.Instance.{prop}"
                    values[f"desired.{key}.value"] = value
                    values[f"desired.{key}.comment"] = "仮想マシンの設定"
                    if prop in {"InstanceId", "SubnetId"}:
                        values[f"observed.{key}.property"] = f"EC2.Instance.{prop}"
                        values[f"observed.{key}.value"] = "PENDING_DEPLOY"
                        values[f"observed.{key}.comment"] = "仮想マシンの設定"
                write_model(
                    models / "cloudformation-stacks.properties",
                    {
                        "desired.stack.001.name": "fixture",
                        "desired.stack.001.placementName": "fixture",
                        "desired.stack.001.template": "fixture.yaml",
                        "desired.stack.001.parameters": "fixture.json",
                        "desired.stack.001.deployOrder": "1",
                        "display.stack.001.comment": "合成Stack",
                    },
                )
                write_model(
                    models / "ec2.properties",
                    "".join(f"{key}={value}\n" for key, value in values.items()),
                )
        (root / "project.json").write_text(json.dumps(project) + "\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        dependency_index.rebuild(root)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=root,
            check=True,
        )
        dependency_index.rebuild(root)
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
        overlapping = _bind_framework_callback(
            _callback_main_overlapping, barrier, original, workers
        )
        with (
            patch.object(VALIDATOR.Validator, "check_designs", overlapping),
            redirect_stdout(io.StringIO()),
        ):
            validator.check_scoped_designs()
        assert len(workers) == 4 and not validator.errors, validator.errors
        assert validator.generated_models_checked
        check_single_target_cache(root)
        # Missing/unknown selectors and changes outside scope fail before service checks.
        validator.model_validation = "change"
        validator.changed_paths = {"model/prod/cde/ec2.properties"}
        validator.check_validation_scope()
        assert any("outside validation scope" in error for error in validator.errors)
        design = root / "docs/designs/dev/cde/ec2.md"
        saved = design.read_text()
        design.unlink()
        rejected = VALIDATOR.Validator(root, {("dev", "cde", "ec2")})
        rejected.accounts = validator.accounts
        rejected.check_validation_scope()
        assert any("validation input missing" in error for error in rejected.errors), (
            rejected.errors
        )
        assert not design.exists(), "scope validation regenerated missing Markdown"
        design.write_text(saved)
        design.write_text(
            saved.replace("vpc.md#resource-EC2_Subnet_001", "vpc.md#missing-anchor")
        )
        rejected = VALIDATOR.Validator(root, {("dev", "cde", "ec2")})
        rejected.accounts = validator.accounts
        rejected.schema_catalog = DesignSchemaCatalog(root)
        rejected.check_design_links(rejected.catalog_design_properties()[2])
        assert len(rejected.errors) == 1 and rejected.errors[0].startswith(
            "design.display.mismatch:"
        ), rejected.errors
        assert any(
            "missing design anchor" in warning["message"]
            for warning in rejected.findings.warnings
        ), rejected.findings.warnings
        design.write_text(saved)
        # Selected schema, naming, JSON, and generation errors remain failures.
        model = root / "model/dev/cde/ec2.properties"
        source = read_model(model)
        active = root / "tasks/example.md"
        active.write_text(
            active.read_text()
            .replace(
                "## Modified files\n",
                "## Modified files\n- `model/dev/cde/ec2.properties`\n",
            )
            .replace(
                "## Allowed paths\n",
                "## Allowed paths\n- `model/dev/cde/ec2.properties`\n",
            )
        )
        for bad, token in (
            (
                source.replace(
                    "EC2.Instance.InstanceType", "EC2.Instance.EbsOptimized"
                ),
                "provider schema",
            ),
            (source.replace("`dev-app-cde-01`", "`UNSET`"), "Name"),
        ):
            write_model(model, bad)
            try:
                with redirect_stdout(io.StringIO()):
                    SYNC.sync(root, False, "dev", "cde", services=["ec2"])
            except ValueError as error:
                assert token in str(error), error
            else:
                raise AssertionError("selected invalid design accepted")
        write_model(model, source)
        with redirect_stdout(io.StringIO()):
            full = VALIDATOR.Validator(root)
            full.check_generated_service_models()
        assert full.errors, (
            "overall validation accepted invalid out-of-scope authorities"
        )
        # CLI sync must also stop on absent scope; it cannot silently select everything.
        active.write_text(contract.split("## Validation scope")[0])
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "framework/scripts/sync-model.py"),
                "--repository-root",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode and "validation scope missing" in result.stderr
        active.write_text(contract)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "framework/scripts/sync-model.py"),
                "--repository-root",
                str(root),
                "--environment",
                "prod",
                "--alias",
                "cde",
                "--service",
                "ec2",
            ],
            capture_output=True,
            text=True,
        )
        assert (
            result.returncode
            and "outside active task validation scope" in result.stderr
        )
    with tempfile.TemporaryDirectory() as directory:
        check_template_consumers(Path(directory).resolve())
    print(
        "validation-scope: PASS (4 parallel targets/services, serial equality, cache invalidation, excluded errors, references, schema/naming/JSON, missing scope, explicit all)"
    )


if __name__ == "__main__":
    main()
