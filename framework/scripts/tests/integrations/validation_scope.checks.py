#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.validation_scope_fixtures import *

from support.it_workspace import copy_framework

@it_case
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
        write_model(models / f"{service}.properties", "".join(f"{key}={value}\n" for key, value in values.items()))
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
        assert not invalid.errors and any("anchor" in warning["message"] for warning in invalid.findings.warnings), invalid.findings.warnings
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
        saved = read_model(model)
        old_key = cache.service_key(("dev", "cde", "sqs"))
        (Path(directory) / f"{old_key}.json").unlink()
        def changed(worker):
            original(worker)
            if ("dev", "cde", "sqs") in worker.scope:
                write_model(model, saved + "# input changed during validation\n")
        with patch.object(VALIDATOR.Validator, "check_designs", changed):
            invalid = validate(cache=cache)
        assert any("inputs changed" in error for error in invalid.errors), invalid.errors
        write_model(model, saved)
    active.write_text(saved_contract, encoding="utf-8")


@it_case
def check_template_consumers(root):
    from support import model_templates_fixtures as source_checks
    source_checks.fixture(root, ('dev', 'stg'))
    values = source_checks.config_model()
    for env in ('dev', 'stg'):
        source_checks.write_fixture(root, env, 'config', values)
    scope = {(env, 'team', 'config') for env in ('dev', 'stg')}
    contract = root/'tasks/active.md'
    contract.write_text('## Task contract\n- Task type: `migration`\n## Validation scope\n' +
                        ''.join(f'- `{"/".join(entry)}`\n' for entry in sorted(scope)) +
                        '## Allowed paths\n- `model/**`\n- `model/parameters/**`\n- `model/templates/**`\n- `docs/designs/**`\n')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    command = [sys.executable, str(ROOT/'framework/scripts/sync-model.py'), '--repository-root', str(root)]
    for selection, expected in ((['--scope', 'dev/team/config', '--scope', 'stg/team/config'], 0),
                                (['--scope', 'dev/team/config'], 1),
                                (['--scope', 'dev/other/config'], 1),
                                (['--scope', '../team/config'], 1),
                                (['--scope', 'dev/team/config', '--all'], 2)):
        result = subprocess.run(command + selection, capture_output=True, text=True)
        assert result.returncode == expected, (selection, result.stdout, result.stderr)
        if selection == ['--scope', 'dev/team/config']:
            assert 'stg/team/config' in result.stderr
    # A parameter-only change still permits just that consumer; no template guard is weakened.
    run = subprocess.run
    def parameter_diff(args, *a, **kw):
        if args[0] == 'git' and args[1] in ('diff', 'ls-files'):
            changed = 'model/parameters/dev/team/config/parameters.yaml\0' if args[1:3] == ['diff', '--name-only'] else ''
            return subprocess.CompletedProcess(args, 0, stdout=changed, stderr='')
        return run(args, *a, **kw)
    with patch.object(sys, 'argv', command[1:] + ['--scope', 'dev/team/config']), \
         patch.object(subprocess, 'run', parameter_diff), redirect_stdout(io.StringIO()):
        assert SYNC.active_scope(root) == scope, (SYNC.active_scope(root), contract.read_text(), sys.argv)
        assert SYNC.main() == 0
    with tempfile.TemporaryDirectory() as directory:
        def validate():
            validator = VALIDATOR.Validator(root, scope, workers=1)
            validator.cache = PassCache(root, directory=directory)
            validator.check_project_topology()
            with redirect_stdout(io.StringIO()):
                validator.check_scoped_designs()
            assert not validator.errors, validator.errors
            return validator
        cold = validate()
        dev_key = cold.service_keys[('dev', 'team', 'config')]
        (Path(directory)/f'{dev_key}.json').unlink()
        import sync_runtime
        with patch.object(sync_runtime, 'compare_generation', wraps=sync_runtime.compare_generation) as generate:
            partial = validate()
        assert generate.call_count == 1, generate.call_args_list
        assert generate.call_args.args == (root, scope), generate.call_args
        options = generate.call_args.kwargs
        assert options.keys() == {'jobs', 'definitions_root', 'findings'}
        assert options['jobs'] == 1 and options['definitions_root'] == root
        assert isinstance(options['findings'], type(partial.findings))
        assert options['findings'].canonical_root == root
        assert partial.checks == cold.checks
        with patch.object(VALIDATOR.Validator, 'check_generated_service_models', side_effect=AssertionError('unchanged generation reran')):
            warm = validate()
        assert warm.checks == cold.checks


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        copy_framework(root / 'framework')
        (root / "tasks").mkdir()
        active = root / "tasks/active.md"
        scope = {(env, target, 'ec2') for env in ('dev', 'stg') for target in ('cde', 'non-cde')}
        contract = '## Validation scope\n' + ''.join(f"- `{'/'.join(item)}`\n" for item in sorted(scope))
        active.write_text(contract)
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
                write_model(models / 'logs.properties', 'observed.bad=arn:aws:logs:invalid\n')
                if env == "prod":
                    write_model(models / 'ec2.properties', 'invalid=excluded EC2\n')
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
                write_model(models / "ec2.properties", "".join(f"{key}={value}\n" for key, value in values.items()))
        (root / "project.json").write_text(json.dumps(project) + "\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], cwd=root, check=True)
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
        for invalid in ({("unknown", "cde", "ec2")}, {("dev", "999999999999", "ec2")}, {("dev", "cde", "missing")}):
            rejected = VALIDATOR.Validator(root, invalid)
            rejected.accounts = validator.accounts
            rejected.check_validation_scope()
            assert rejected.errors
            if next(iter(invalid))[:2] not in validator.accounts:
                assert any("validation target is not defined" in error for error in rejected.errors)
        validator.changed_paths = {"model/prod/cde/ec2.properties"}
        validator.check_validation_scope()
        assert any("outside validation scope" in error for error in validator.errors)
        design = root / "docs/designs/dev/cde/ec2.md"
        saved = design.read_text()
        design.unlink()
        rejected = VALIDATOR.Validator(root, {("dev", "cde", "ec2")})
        rejected.accounts = validator.accounts
        rejected.check_validation_scope()
        assert any("validation input missing" in error for error in rejected.errors), rejected.errors
        assert not design.exists(), "scope validation regenerated missing Markdown"
        design.write_text(saved)
        design.write_text(saved.replace("vpc.md#vpc-subnet-app-dev-cde", "vpc.md#missing-anchor"))
        rejected = VALIDATOR.Validator(root, {("dev", "cde", "ec2")})
        rejected.accounts = validator.accounts
        rejected.schema_catalog = DesignSchemaCatalog(root)
        rejected.check_design_links(rejected.catalog_design_properties()[2])
        assert not rejected.errors
        assert any("missing design anchor" in warning["message"] for warning in rejected.findings.warnings), rejected.findings.warnings
        design.write_text(saved)
        # Selected schema, naming, JSON, and generation errors remain failures.
        model = root / "model/dev/cde/ec2.properties"
        source = read_model(model)
        for bad, token in ((source.replace('EC2.Instance.InstanceType', 'EC2.Instance.EbsOptimized'), 'EbsOptimized'),
                           (source.replace('`dev-app-cde-01`', '`UNSET`'), 'Name')):
            write_model(model, bad)
            try:
                with redirect_stdout(io.StringIO()):
                    SYNC.sync(root, False, "dev", "cde", services=["ec2"])
            except ValueError as error:
                assert token in str(error), error
            else:
                raise AssertionError("selected invalid design accepted")
        write_model(model, source)
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
    with tempfile.TemporaryDirectory() as directory:
        check_template_consumers(Path(directory).resolve())
    print("validation-scope: PASS (4 parallel targets/services, serial equality, cache invalidation, excluded errors, references, schema/naming/JSON, missing scope, explicit all)")


if __name__ == "__main__":
    main()

