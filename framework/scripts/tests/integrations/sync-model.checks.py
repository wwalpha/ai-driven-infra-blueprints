#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.sync_model_fixtures import *

from support.it_workspace import copy_framework

@pytest.mark.parametrize('fault', ['source', 'mapping', 'project', 'part', 'consumer', 'extra'])
def check_publication_boundary(generated_policy, fault):
    root, model, values, design, artifact, register = generated_policy
    values['desired.note.001.text'] = '保存前の一括照合を確認する。'
    write_model(model, values)
    env = register([design, artifact])
    originals = {file: file.read_bytes() for file in (design, artifact)}
    validate = sync_runtime.validate_candidates
    concurrent = None

    def mutate_before_save(*args, **kwargs):
        nonlocal concurrent
        result = validate(*args, **kwargs)
        template = next(file for file in load_model(model).files if file.suffix == '.tpl')
        target = {'source': template, 'mapping': root/'framework/mappings/aws/iam.yaml',
                  'project': root/'project.json', 'part': template.with_suffix('')/'unlisted.properties',
                  'consumer': root/'model/parameters/dev/other/new/parameters.yaml',
                  'extra': artifact.parent/'unexpected.json'}[fault]
        concurrent = target, (target.read_bytes() if target.exists() else b'') + b'\n'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(concurrent[1])
        return result
    with patch.dict(os.environ, env), patch.object(sync_runtime, 'validate_candidates', side_effect=mutate_before_save), \
         patch.object(sync_runtime, '_publish_transaction', side_effect=AssertionError('published before input comparison')):
        with pytest.raises(ValueError, match='inputs changed'):
            MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert {file: file.read_bytes() for file in originals} == originals
    assert concurrent[0].read_bytes() == concurrent[1]


def check_normal_writer_contents(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    values['desired.note.001.text'] = '保存された内容をテストで確認する。'
    document = json.loads(values['desired.row.001-002.document'])
    document['Statement'][0]['Sid'] = 'WrittenOnce'
    values['desired.row.001-002.document'] = json.dumps(document)
    write_model(model, values)
    with patch.dict(os.environ, register([design, artifact])), \
         patch.object(sync_runtime, 'verify_saved', side_effect=AssertionError('normal runtime readback')):
        assert MODULE.sync(root, True, 'dev', '123456789012', ['iam']) == 0
    assert values['desired.note.001.text'] in design.read_text()
    assert json.loads(artifact.read_text()) == document


@pytest.mark.parametrize('note', [False, True])
def check_unchanged_sidecar(generated_policy, note):
    root, model, values, design, artifact, register = generated_policy
    if note:
        values['desired.note.001.text'] = '利用開始前に実行主体の権限を確認する。'
        write_model(model, values)
    env = register([design] if note else [])
    before = artifact.read_bytes(), artifact.stat().st_mtime_ns
    with patch.dict(os.environ, env), patch.object(sync_runtime, '_publish_transaction', wraps=sync_runtime._publish_transaction) as publish, \
         patch.object(sync_runtime, 'validate_candidates', wraps=sync_runtime.validate_candidates) as validate:
        assert MODULE.sync(root, True, 'dev', '123456789012', ['iam']) == 0
    assert validate.call_count == 1, 'no-op outputs still require candidate validation'
    assert publish.call_count == int(note)
    if note:
        assert set(publish.call_args.args[1]) == {design}, 'unchanged JSON must not enter publication'
        assert values['desired.note.001.text'] in design.read_text(encoding='utf-8')
    assert (artifact.read_bytes(), artifact.stat().st_mtime_ns) == before
    with patch.dict(os.environ, env):
        assert MODULE.sync(root, False, 'dev', '123456789012', ['iam']) == 0


@pytest.mark.parametrize('change', ['model', 'stale', 'missing'])
def check_changed_sidecar_publication(generated_policy, change):
    root, model, values, design, artifact, register = generated_policy
    if change == 'model':
        document = json.loads(values['desired.row.001-002.document'])
        document['Statement'][0]['Sid'] = 'Changed'
        values['desired.row.001-002.document'] = json.dumps(document)
        write_model(model, values)
    elif change == 'stale':
        artifact.write_text('{}\n', encoding='utf-8')
    else:
        artifact.unlink()
    env = register([design])
    with patch.dict(os.environ, env):
        assert MODULE.sync(root, True, 'dev', '123456789012', ['iam']) == 0
    assert json.loads(artifact.read_text()) == json.loads(values['desired.row.001-002.document'])



@pytest.mark.parametrize('note', [False, True])
@pytest.mark.parametrize('drift', ['sidecar', 'source', 'task'])
def check_publication_rechecks_excluded_outputs(generated_policy, note, drift):
    root, model, values, design, artifact, register = generated_policy
    if note:
        values['desired.note.001.text'] = '公開前に変更の競合を確認する。'
        write_model(model, values)
    env = register([design] if note else [])
    original = design.read_bytes()
    changed = (artifact if drift == 'sidecar' else root / env['BLUEPRINT_TASK_FILE'] if drift == 'task'
               else next(file for file in load_model(model).files if file.suffix == '.tpl'))
    content = ('{}\n' if drift == 'sidecar' else '# concurrent change\n' + changed.read_text(encoding='utf-8'))
    validate = sync_runtime.validate_candidates
    def mutate(*args, **kwargs):
        result = validate(*args, **kwargs)
        changed.write_text(content, encoding='utf-8')
        return result
    with patch.dict(os.environ, env), patch.object(sync_runtime, 'validate_candidates', side_effect=mutate):
        with pytest.raises(ValueError, match='inputs changed'):
            MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert design.read_bytes() == original
    assert changed.read_text(encoding='utf-8') == content



@pytest.mark.parametrize('note', [False, True])
def check_changed_sidecar_publication_rollback(generated_policy, note):
    root, model, values, design, artifact, register = generated_policy
    before = {file: file.read_bytes() for file in (design, artifact)}
    if note:
        values['desired.note.001.text'] = '注記だけの公開もロールバックする。'
    else:
        document = json.loads(values['desired.row.001-002.document'])
        document['Statement'][0]['Sid'] = 'Changed'
        values['desired.row.001-002.document'] = json.dumps(document)
    write_model(model, values)
    env = register([design] if note else [design, artifact])
    write = Path.write_text

    def fail_markdown(path, *args, **kwargs):
        if path == design:
            if note:
                write(artifact, '{}\n', encoding='utf-8')
            else:
                assert artifact.read_bytes() != before[artifact]
            write(path, 'partial Markdown', encoding='utf-8')
            raise OSError('injected Markdown publication failure')
        return write(path, *args, **kwargs)

    with patch.dict(os.environ, env), patch.object(Path, 'write_text', fail_markdown):
        with pytest.raises(ValueError, match='injected Markdown publication failure'):
            MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert design.read_bytes() == before[design]
    assert artifact.read_bytes() == (b'{}\n' if note else before[artifact])
    if note:
        artifact.write_bytes(before[artifact])
    with patch.dict(os.environ, env):
        assert MODULE.sync(root, True, 'dev', '123456789012', ['iam']) == 0
        assert MODULE.sync(root, False, 'dev', '123456789012', ['iam']) == 0


def check_unchanged_sidecar_path_safety(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    env = register([])
    external = root / 'external-policy.json'
    external.write_bytes(artifact.read_bytes())
    artifact.unlink()
    artifact.symlink_to(external)
    with patch.dict(os.environ, env), pytest.raises(ValueError, match='unsafe Model source path'):
        MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert artifact.is_symlink()


def check_unchanged_sidecar_validation(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    env = register([])
    before = {file: file.read_bytes() for file in (design, artifact)}
    with patch.dict(os.environ, env), \
         patch.object(sync_views, 'validate_views', side_effect=ValueError('injected candidate validation failure')), \
         patch.object(sync_runtime, 'publish', side_effect=AssertionError('invalid candidate published')):
        with pytest.raises(ValueError, match='injected candidate validation failure'):
            MODULE.sync(root, True, 'dev', '123456789012', ['iam'])
    assert {file: file.read_bytes() for file in before} == before


def check_failure_counts(framework_root) -> None:
    from types import SimpleNamespace
    from validation.findings import Findings
    root = framework_root
    models = root / "model/dev/non-cde"
    docs = root / "docs/designs/dev/non-cde"
    models.mkdir(parents=True)
    docs.mkdir(parents=True)
    for number in range(17):
        write_model(models / f"service-{number:02d}.properties", "fixture.value=test\n")
        (docs / f"service-{number:02d}.md").write_text("generated\n")

    def render(path, values, stage):
        if int(path.stem.removeprefix("service-")) < 9:
            raise ValueError("fixture render failure")
        return "generated\n"

    # Retained references warn without adding a failed service or failure diagnostics.
    broken = {f"reference-{number}": docs / "service-09.md" for number in range(5)}
    def context(stage, source, generated, destinations, accounts=None):
        findings = Findings(stage)
        scope = {(*p.relative_to(root / 'docs/designs').parts[:2], p.stem) for p in generated}
        for name in ('design.collections', 'design.ownership', 'design.stacks', 'framework.policy-tables'):
            findings.evaluate(name, scope, lambda: None)
        return SimpleNamespace(errors=[], findings=findings)
    def checked(stage, source, paths, sources, **kwargs):
        findings = Findings(stage)
        findings.candidate = kwargs['context'].findings.candidate
        scope = {(*p.relative_to(stage / 'docs/designs').parts[:2], p.stem) for p in paths}
        for name in ('design.projection', 'design.names', 'design.tables', 'design.overviews', 'design.links', 'design.artifacts', 'design.observed'):
            findings.evaluate(name, scope, lambda: None)
        return findings
    for extra_inputs in (False, True):
        if extra_inputs:
            write_model(models / 'invalid.properties', 'invalid properties\n')
            (docs / "orphan.md").write_text("saved Markdown\n")
        for write in (False, True):
            warnings = io.StringIO()
            with redirect_stderr(warnings), patch.object(sync_runtime, "validate_required_properties"), \
                 patch.object(sync_runtime, "markdown_for", side_effect=render), \
                 patch.object(sync_runtime, "rendered_design", return_value="generated\n"), \
                 patch.object(sync_views, "validate_views", side_effect=checked if write else None), \
                 patch.object(sync_views, "validation_context", side_effect=context), \
                 patch.object(sync_views, "broken_design_links", side_effect=[{}, broken, {}]), \
                 redirect_stdout(io.StringIO()):
                try:
                    MODULE.sync(root, write, "dev", "non-cde")
                except ValueError as error:
                    failed, diagnostics = (11, 11) if extra_inputs else (9, 9)
                    assert str(error).splitlines()[0] == f"8 services succeeded; {failed} services failed; {diagnostics} diagnostics", error
                    assert len(str(error).splitlines()) == diagnostics + 1, error
                    assert "saved reference" not in str(error), error
                    assert warnings.getvalue().count("saved reference needs repair") == (5 if write else 0)
                    if extra_inputs:
                        assert "invalid or duplicate model property" in str(error), error
                        assert "YAML Model inputs missing" in str(error), error
                else:
                    raise AssertionError("partial generation failure accepted")
    print("Failure counts: PASS (17 models, 8 successes, 9 failed services, 9 diagnostics, invalid/missing models, read/write)")


@pytest.mark.parametrize("write", [False, True])
def check_incoming_reference_models(framework_root, tmp_path, write) -> None:
    root = framework_root
    models = root / "model/dev/123456789012"
    docs = root / "docs/designs/dev/123456789012"
    docs.mkdir(parents=True)
    for service in ("s3", "kms"):
        write_model(models / f"{service}.properties", f"desired.service.{service}.serviceId={service}\n")
        (docs / f"{service}.md").write_text(f"# {service}\n### {service}\n", encoding="utf-8")
    selected = docs / "s3.md"
    incoming = docs / "kms.md"
    stage = tmp_path / "stage"
    stage.mkdir()

    def check_snapshot(stage, root, paths):
        assert stage / incoming.relative_to(root) in paths
        assert read_model(stage / (models / "kms.properties").relative_to(root)) == read_model(models / "kms.properties")
        return {}

    with patch.object(sync_views, "broken_design_links", side_effect=check_snapshot) as check:
        saved, _ = sync_runtime.stage_inputs(stage, root, {selected: {}},
                                            [models / "s3.properties"], [selected], ["s3"], write)
    assert (incoming in saved) == write
    assert check.call_count == int(write)
    if write:
        assert (stage / incoming.relative_to(root)).exists()


def check_required_preflight(framework_root) -> None:
    root = framework_root
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
        "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
    model = root / "model/dev/123456789012/quicksight.properties"
    model.parent.mkdir(parents=True)
    values = {
        "desired.service.quicksight.serviceId": "quicksight",
        "desired.service.quicksight.ownedCatalogResourceTypes": "QuickSight.DataSource",
        "desired.resource.001.resourceType": "QuickSight.DataSource",
        "desired.resource.001.logicalId": "AthenaSource",
        "desired.resource.001.anchor": "quicksight-qs-app-dev-athena",
        "display.service.title": "# QuickSight 詳細設計",
        "display.resource.001.comment": "分析用データソース",
        "desired.row.001-001.property": "QuickSight.DataSource.Name",
        "desired.row.001-001.value": "`qs-app-dev-athena`",
        "desired.row.001-001.comment": "データソースの名前",
        "desired.row.001-002.property": "QuickSight.DataSource.Credentials.KeyPairCredentials",
        "desired.row.001-002.value": "[設定](quicksight/credentials.json)",
        "desired.row.001-002.document": '{"KeyPairUsername":"test","PrivateKey":"test"}',
        "desired.row.001-002.comment": "接続の認証設定",
    }
    source = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    write_model(model, source)
    source = read_model(model)
    design = root / "docs/designs/dev/123456789012/quicksight.md"
    artifact = design.with_suffix("") / "credentials.json"
    for existing in (False, True):
        if existing:
            artifact.parent.mkdir(parents=True)
            design.write_text("existing Markdown\n")
            artifact.write_text("existing JSON\n")
        for write in (False, True):
            # Neither the renderer nor artifact writer may run for this service.
            with patch.object(sync_runtime, "markdown_for", side_effect=AssertionError("rendered before preflight")), \
                 patch.object(sync_runtime, "save_files", side_effect=AssertionError("wrote before preflight")):
                with pytest.raises(ValueError) as error:
                    MODULE.sync(root, write, "dev", "123456789012")
                assert "AthenaSource: required provider schema property missing: QuickSight.DataSource.Type" in str(error.value)
            assert read_model(model) == source
            if existing:
                assert design.exists() and artifact.exists()
                assert design.read_text() == "existing Markdown\n"
                assert artifact.read_text() == "existing JSON\n"
    with pytest.raises(ValueError) as error:
        model_design.markdown_for(design, values, root)
    assert "QuickSight.DataSource.Type" in str(error.value)
    complete = values | {
        "desired.row.001-003.property": "QuickSight.DataSource.Type",
        "desired.row.001-003.value": "`ATHENA`",
        "desired.row.001-003.comment": "データソースの接続方式",
    }
    model_design.validate_required_properties(complete, root)
    for empty in ("", "``", '`""`', "`UNSET`"):
        with pytest.raises(ValueError) as error:
            model_design.validate_required_properties(complete | {"desired.row.001-003.value": empty}, root)
        assert "QuickSight.DataSource.Type" in str(error.value)
    grouped = complete | {
        "desired.resource.001.resourceType": "S3.Bucket",
        "desired.row.001-001.property": "S3.Bucket.BucketName",
        "desired.row.001-002.property": "S3.BucketPolicy.PolicyDocument",
        "desired.row.001-002.value": "",
    }
    with pytest.raises(ValueError) as error:
        model_design.validate_required_properties(grouped, root)
    assert "S3.BucketPolicy.PolicyDocument" in str(error.value)
    assert "S3.BucketPolicy.Bucket" not in str(error.value)
    # An unrelated valid service still saves while the incomplete one fails.
    stack = model.with_name("cloudformation-stacks.properties")
    write_model(stack, "desired.stack.001.name=cfn-stack-app-dev-general-01\n"
                     "desired.stack.001.template=app.yaml\n"
                     "desired.stack.001.parameters=app.json\n"
                     "desired.stack.001.deployOrder=10\n"
                     "display.stack.001.comment=アプリケーションのstack\n")
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True, "dev", "123456789012")
        assert "1 services succeeded; 1 services failed; 1 diagnostics" in str(error.value), error.value
    assert design.with_name("cloudformation-stacks.md").is_file()
    assert design.read_text() == "existing Markdown\n" and artifact.read_text() == "existing JSON\n"
    print("Required-property preflight: PASS (new/existing, read/write, direct renderer, partial success)")


def check_required_property_parents(tmp_path) -> None:
    root = tmp_path
    copy_framework(root / 'framework')
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
        "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
    model = root / "model/dev/123456789012/glue.properties"
    model.parent.mkdir(parents=True)
    values = {
        "desired.service.glue.serviceId": "glue",
        "desired.service.glue.ownedCatalogResourceTypes": "Glue.Connection",
        "desired.resource.001.resourceType": "Glue.Connection",
        "desired.resource.001.logicalId": "Connection",
        "desired.resource.001.anchor": "glue-sample",
        "display.service.title": "# AWS Glue 詳細設計",
        "display.resource.001.comment": "データ取得に使用する接続",
    }
    for number, (field, value) in enumerate((
        ("ConnectionInput.Name", "`sample`"),
        ("Name", "[Connection](#glue-sample)"),
        ("CatalogId", "`123456789012`"),
        ("ConnectionInput.ConnectionType", "`JDBC`"),
        ("ConnectionInput.PhysicalConnectionRequirements.AvailabilityZone", "`ap-northeast-1a`"),
        ("ConnectionInput.ValidateCredentials", "`true`"),
    ), 1):
        key = f"001-{number:03d}"
        comment = "一意に識別するID" if field == "Name" else "接続の設定"
        values.update({f"desired.row.{key}.property": "Glue.Connection." + field,
                       f"desired.row.{key}.value": value, f"desired.row.{key}.comment": comment})
    values.update({"observed.row.001-002.property": "Glue.Connection.Name",
                   "observed.row.001-002.value": "`sample`", "observed.row.001-002.comment": "一意に識別するID"})
    source = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    write_model(model, source)
    source = read_model(model)
    design = root / "docs/designs/dev/123456789012/glue.md"
    model_design.validate_required_properties(values, root)
    assert MODULE.sync(root, True, "dev", "123456789012") == 0
    assert read_model(model) == source
    assert "| ConnectionInput |" not in design.read_text()  # Presence is inferred without inventing a row.

    def design_errors(content):
        design.write_text(content)
        validator = sync_views.view_validator(root, root)
        validator.check_design_tables({design: ("glue", ("Glue.Connection",))}, *validator.catalog_design_properties())
        return validator.errors

    original = design.read_text()
    assert not design_errors(original), design_errors(original)
    for missing in ("ConnectionInput", "CatalogId"):
        removed = {key.rsplit(".", 1)[0] for key, value in values.items()
                   if key.endswith(".property") and (value == f"Glue.Connection.{missing}" or value.startswith(f"Glue.Connection.{missing}."))}
        incomplete = {key: value for key, value in values.items() if key.rsplit(".", 1)[0] not in removed}
        with pytest.raises(ValueError) as error:
            model_design.validate_required_properties(incomplete, root)
        assert f"required provider schema property missing: Glue.Connection.{missing}" in str(error.value)
        content = "\n".join(line for line in original.splitlines()
                            if f" | {missing} |" not in line and f" | {missing}." not in line) + "\n"
        assert any(f"Glue.Connection.{missing}" in error and "required provider schema property missing" in error for error in design_errors(content))
    assert any("provider schema violation" in error for error in design_errors(original.replace("`true`", "`not-a-boolean`")))
    print("Required-property parents: PASS (Glue generation, design validation and true missing inputs)")


def check_workflow(tmp_path) -> None:
    root = tmp_path
    copy_framework(root / "framework/mappings", relative="mappings")
    materials = root / "framework" / "materials" / "aws"
    materials.mkdir(parents=True)
    (materials / 'EC2_VPC.properties').write_text('EC2.VPC.VpcId=IDENTIFIER_OUTPUT\n',encoding="utf-8")
    (materials / 'EC2_Subnet.properties').write_text('EC2.Subnet.SubnetId=IDENTIFIER_OUTPUT\nEC2.Subnet.VpcId=\n',encoding="utf-8")
    (materials / 'S3_Bucket.properties').write_text('S3.Bucket.BucketName=\nS3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID=\nS3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm=\nS3.Bucket.VersioningConfiguration.Status=\n',encoding="utf-8")
    (materials / 'S3_BucketPolicy.properties').write_text('S3.BucketPolicy.Bucket=\nS3.BucketPolicy.PolicyDocument=\n',encoding="utf-8")
    (materials / 'KMS_Alias.properties').write_text('KMS.Alias.AliasName=\nKMS.Alias.TargetKeyId=\n',encoding="utf-8")
    design = root / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
    artifact = design.parent / "vpc" / "vpc01-policy.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
        encoding="utf-8",
    )
    design.write_text(
        """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`

## リソース詳細

<a id="vpc-vpc-app-dev"></a>

### EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | PENDING_DEPLOY | VPCを一意に識別するID |
| 2 | CidrBlock | 10.1.0.0/16 | VPCで使用するIPv4アドレス範囲 |
| 3 | Name | vpc-app-dev | VPCを識別するNameタグの値 |
| 4 | PolicyDocument | [policy](vpc/vpc01-policy.json) | VPCに適用するpolicy文書 |

<a id="vpc-sbnt-app-dev-private-01"></a>

### EC2.Subnet: sbnt-app-dev-private-01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | SubnetId | PENDING_DEPLOY | Subnetを一意に識別するID |
| 2 | VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
| 3 | Name | sbnt-app-dev-private-01 | Subnetを識別するNameタグの値 |
""",
        encoding="utf-8",
    )
    model = model_projection.model_for(design, root)
    assert "desired.service.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet" in model
    assert "desired.resource.001.logicalId=vpc-app-dev" in model
    assert "desired.row.001-001.value=[vpc-app-dev](#vpc-vpc-app-dev)" in model
    assert "observed.row.001-001.value=PENDING_DEPLOY" in model
    assert "desired.row.001-002.value=10.1.0.0/16" in model
    assert "desired.row.001-003.property=EC2.VPC.Name" in model
    assert "desired.row.001-004.artifactSha256=" in model
    assert "desired.row.002-001.value=[sbnt-app-dev-private-01](#vpc-sbnt-app-dev-private-01)" in model
    assert "observed.row.002-001.value=PENDING_DEPLOY" in model
    assert "desired.row.002-002.value=[vpc-app-dev](#vpc-vpc-app-dev)" in model
    assert "desired.row.002-003.property=EC2.Subnet.Name" in model
    assert model == model_projection.model_for(design, root)

    s3_design = design.with_name("s3.md")
    s3_artifact = s3_design.parent / "s3" / "app-data-bucket-policy.json"
    s3_artifact.parent.mkdir(parents=True)
    s3_artifact.write_text(
        '{"Version":"2012-10-17","Statement":[]}\n', encoding="utf-8"
    )
    kms_design = design.with_name("kms.md")
    kms_design.write_text(
        """# AWS KMS 詳細設計

- Design service ID: `kms`
- Owned catalog resource types: `KMS.Key`, `KMS.Alias`

## リソース詳細

<a id="kms-appdatakey"></a>

### KMS.Key: AppDataKey

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | 1234abcd-12ab-34cd-56ef-1234567890ab | KMS keyを識別するID |
| 2 | KMS.Alias.AliasName | alias/app-data | <a id="kms-appdatakeyalias"></a><!-- logical-id: AppDataKeyAlias --> application data用keyを識別するalias |
""",
        encoding="utf-8",
    )
    s3_design.write_text(
        """# Amazon S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`, `S3.BucketPolicy`

## リソース一覧

### S3.Bucket

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |

## リソース詳細

<a id="s3-app-dev-data-123456789012"></a>

### S3.Bucket: app-dev-data-123456789012

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | app-dev-data-123456789012 | application dataを格納するbucketの名前 |
| 2 | Region | us-east-1 | bucketを配置するAWS region |
| 3 | BucketEncryption[].KMSMasterKeyID | [alias/app-data](kms.md#kms-appdatakeyalias) | 新規objectのdefault暗号化に使用するKMS key alias |
| 4 | BucketEncryption[].SSEAlgorithm | aws:kms | 暗号化方式 |
| 5 | VersioningConfiguration.Status | Enabled | objectのversion保持状態 |
| 6 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |
""",
        encoding="utf-8",
    )
    s3_model = model_projection.model_for(s3_design, root)
    assert "desired.resource.001.resourceType=S3.Bucket" in s3_model
    assert "desired.resource.001.logicalId=app-dev-data-123456789012" in s3_model
    assert "desired.resource.002." not in s3_model
    assert "desired.row.001-001.property=S3.Bucket.BucketName" in s3_model
    assert "desired.row.001-002.property=S3.Bucket.Region" in s3_model
    assert "desired.row.001-002.value=us-east-1" in s3_model
    assert "desired.row.001-003.value=[alias/app-data](kms.md#kms-appdatakeyalias)" in s3_model
    assert "desired.row.001-003.property=S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID" in s3_model
    assert "desired.row.001-004.property=S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm" in s3_model
    assert "observed.row.001-003" not in s3_model
    assert "S3.BucketPolicy.Bucket" not in s3_model
    assert "desired.row.001-006.property=S3.BucketPolicy.PolicyDocument" in s3_model
    assert "desired.row.001-006.artifactSha256=" in s3_model
    assert "リソース一覧" not in s3_model
    assert "リソース詳細" not in s3_model
    assert "BucketName | Region" not in s3_model
    original_digest = model_projection.json_sha256(artifact)
    artifact.write_text(
        '{\r\n  "Action": [\r\n    "s3:GetObject"\r\n  ],\r\n'
        '  "Version": "2012-10-17"\r\n}',
        encoding="utf-8",
        newline="",
    )
    assert model_projection.json_sha256(artifact) == original_digest
    artifact.write_text(
        '{"Version":"2012-10-17","Action":["s3:PutObject"]}\n',
        encoding="utf-8",
    )
    assert model_projection.json_sha256(artifact) != original_digest
    artifact.write_text(
        '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
        encoding="utf-8",
    )
    design.write_text(
        design.read_text(encoding="utf-8")
        .replace("VpcId | PENDING_DEPLOY", "VpcId | vpc-0123456789abcdef0")
        .replace("[PENDING_DEPLOY](#vpc-vpc-app-dev)", "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)")
        .replace("SubnetId | PENDING_DEPLOY", "SubnetId | subnet-0123456789abcdef0"),
        encoding="utf-8",
    )
    deployed = model_projection.model_for(design, root)
    assert "observed.row.001-001.value=vpc-0123456789abcdef0" in deployed
    assert "observed.row.002-001.value=subnet-0123456789abcdef0" in deployed
    assert "observed.row.002-002.value=vpc-0123456789abcdef0" in deployed
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True)
        assert "YAML Model inputs missing" in str(error.value)

    alias_design = root / "docs" / "designs" / "dev" / "cde" / "vpc.md"
    alias_design.parent.mkdir(parents=True)
    alias_artifact = alias_design.parent / "vpc" / "vpc01-policy.json"
    alias_artifact.parent.mkdir(parents=True)
    alias_artifact.write_text(
        '{"Version":"2012-10-17","Action":["s3:GetObject"]}\n',
        encoding="utf-8",
    )
    alias_design.write_text(
        design.read_text(encoding="utf-8").replace(
            "vpc-0123456789abcdef0", "vpc-11111111111111111"
        ),
        encoding="utf-8",
    )
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True, "dev", "cde")
        assert "YAML Model inputs missing" in str(error.value)
    assert sync_runtime.selected(alias_design, root / "docs" / "designs", "dev", "cde")
    assert not sync_runtime.selected(alias_design, root / "docs" / "designs", "dev", "123456789012")
    stacks = design.with_name("cloudformation-stacks.md")
    stacks.write_text(
        """# CloudFormation stack 詳細設計

<!-- max-concurrent-stacks: 2 -->

## Stack一覧
| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 10 | stack-job-01 | job.yaml | job-01.json | 日次jobを配置するstack |
| 2 | 10 | stack-job-02 | job.yaml | job-02.json | 月次jobを配置するstack |
""",
        encoding="utf-8",
    )
    stack_model = model_projection.model_for(stacks, root)
    assert "desired.stack.001.template=job.yaml" in stack_model
    assert "desired.stack.002.template=job.yaml" in stack_model
    assert "desired.stack.002.parameters=job-02.json" in stack_model
    assert "日次jobを配置するstack" not in stack_model and ".comment=" not in stack_model
    assert "desired.deployment.maxConcurrentStacks=2" in stack_model
    assert "desired.stack.002.deployOrder=10" in stack_model
    assert "dependsOn" not in stack_model and ".resource." not in stack_model
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True, "dev", "123456789012")
        assert "YAML Model inputs missing" in str(error.value)



def main():
    return run(__file__, message='sync-model: PASS (generation, changed outputs, publication drift and rollback)')


import threading
import task_contract as tasks
import sync_progress as progress


def check_publication_lock_wait(tmp_path):
    import model_templates
    output = io.StringIO()
    waiting = threading.Event()
    reporter = progress.Progress()
    errors = []
    emit = reporter.emit
    def notify(state, event):
        emit(state, event)
        if state[5] == 'lock-wait':
            waiting.set()
    reporter.emit = notify
    def worker():
        try:
            with reporter.worker('dev/team/iam'), model_templates.publication_lock(tmp_path):
                with model_templates.publication_lock(tmp_path):
                    pass
        except BaseException as error:
            errors.append(error)
    with redirect_stderr(output):
        with model_templates.publication_lock(tmp_path):
            thread = threading.Thread(target=worker)
            thread.start()
            observed = waiting.wait(5)
        thread.join(5)
    assert observed and not thread.is_alive() and not errors
    assert 'lock-wait' in output.getvalue()


def check_generation_output_compatibility(generated_policy):
    root, _, _, design, artifact, register = generated_policy
    before = {p: p.read_bytes() for p in (design, artifact)}
    plain, observed, diagnostics = io.StringIO(), io.StringIO(), io.StringIO()
    with patch.dict(os.environ, register([design, artifact])):
        with redirect_stdout(plain):
            assert sync_runtime.sync(root, True, 'dev', '123456789012', ['iam']) == 0
        @progress.reported_main
        def generate():
            return sync_runtime.sync(root, True, 'dev', '123456789012', ['iam'])
        with redirect_stdout(observed), redirect_stderr(diagnostics):
            assert generate() == 0
    assert observed.getvalue() == plain.getvalue()
    assert before == {p: p.read_bytes() for p in before}
    for stage in ['snapshot', 'dependency-model', 'stage-placement', 'candidate-generation', 'candidate-validation', 'publication', 'completed=1/1']:
        assert stage in diagnostics.getvalue()


def check_two_consumer_cli(generated_policy):
    import json
    import shutil
    import subprocess
    from support.validator import load
    root, _, _, design, artifact, register = generated_policy
    shutil.copytree(root / 'model/parameters/dev', root / 'model/parameters/stg')
    shutil.copytree(root / 'docs/designs/dev', root / 'docs/designs/stg')
    project = json.loads((root / 'project.json').read_text())
    project['targets'].append({**project['targets'][0], 'environment': 'stg'})
    (root / 'project.json').write_text(json.dumps(project) + '\n')
    for arguments in [('init', '-q'), ('add', '.'),
                      ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'baseline')]:
        subprocess.run(['git', *arguments], cwd=root, check=True, capture_output=True)
    outputs = [design, artifact, root / 'docs/designs/stg/123456789012/iam.md',
               root / 'docs/designs/stg/123456789012/iam/app-role-trust-policy.json']
    environment = register(outputs)
    name = environment[tasks.SELECTOR]
    (root / name).write_text((root / name).read_text().replace(
        '- `dev/123456789012/iam`', '- `dev/123456789012/iam`\n- `stg/123456789012/iam`'))
    tasks.refresh(root, name)
    template = root / 'model/templates/123456789012/iam.properties.tpl'
    template.write_text(template.read_text().replace('アプリケーションの実行権限', '更新後の処理権限'))
    cli = load('sync-model')
    arguments = ['sync-model.py', '--repository-root', str(root), '--scope', 'dev/123456789012/iam',
                 '--scope', 'stg/123456789012/iam', '--jobs', '2']
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, environment), redirect_stdout(stdout), redirect_stderr(stderr):
        with patch.object(sys, 'argv', [*arguments, '--write']):
            assert cli.main() == 0
        written = {file: file.read_bytes() for file in outputs}
        with patch.object(sys, 'argv', arguments):
            assert cli.main() == 0
        assert written == {file: file.read_bytes() for file in outputs}
        with patch.object(sys, 'argv', ['sync-model.py', '--repository-root', str(root), '--scope', 'prod/123456789012/iam']):
            assert cli.main() == 1
    assert 'sync-model progress:' not in stdout.getvalue()
    assert 'stage=impact-scope' in stderr.getvalue()
    assert 'completed=2/2' in stderr.getvalue()
    assert 'state=failed' in stderr.getvalue()
    for document in (outputs[0], outputs[2]):
        assert '更新後の処理権限' in document.read_text()


@pytest.mark.parametrize('filename', ['parameters.yaml', 'bindings.json', 'observed.json', 'template'])
@pytest.mark.parametrize('mutation', ['change', 'delete', 'add'])
def check_input_mutation(generated_policy, filename, mutation):
    root, model, _, design, artifact, register = generated_policy
    directory = root / 'model/parameters/dev/123456789012/iam'
    source = root / 'model/templates/123456789012/iam.properties.tpl' if filename == 'template' else directory / filename
    if mutation == 'add' and filename != 'observed.json':
        source = (source.with_suffix('') / 'added.properties' if filename == 'template' else directory / 'new' / filename)
    if filename == 'observed.json' and mutation != 'add' and not source.exists():
        source.write_text('{"version":1,"values":{}}\n')
    original = {p: p.read_bytes() for p in (design, artifact)}
    validate = sync_runtime.validate_candidates
    def mutate(*args, **kwargs):
        validate(*args, **kwargs)
        if mutation == 'delete':
            source.unlink()
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes((source.read_bytes() if source.exists() else b'') + b'\n')
    with patch.dict(os.environ, register([design, artifact])), patch.object(sync_runtime, 'validate_candidates', side_effect=mutate):
        with pytest.raises(ValueError, match='inputs changed'):
            sync_runtime.sync(root, True, 'dev', '123456789012', ['iam'])
    assert original == {p: p.read_bytes() for p in original}



if __name__ == "__main__":
    raise SystemExit(main())

