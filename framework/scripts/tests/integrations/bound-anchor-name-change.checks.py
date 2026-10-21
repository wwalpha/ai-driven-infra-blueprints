#!/usr/bin/env python3
"""Name edits preserve fixed Resource anchors, groups, observations and references."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from support.it_case_receipt import it_case
import io
import tempfile
from contextlib import redirect_stdout
import pytest
from model.core import entries
from model.sources import load_model
from model.projection import bound_resource_anchors
from model.render import markdown_for
from design_document import DesignIndex
from support.model_sources import write_model
from support.validator import schema_validator
from support import model_parameter_inputs_fixtures as INPUTS
from support import model_design_fixtures as MODELS
import sync_runtime


def validated(root, path):
    doc = root / 'docs/designs' / path.relative_to(root / 'model').with_suffix('.md')
    values = load_model(path).values
    metadata = {doc: (path.stem, tuple(next(raw for key, raw in values.items() if key.endswith('.ownedCatalogResourceTypes')).split(',')))}
    validator = schema_validator(root)
    validator.check_resource_names(metadata, [doc])
    validator.check_design_tables(metadata, *validator.catalog_design_properties(), [doc])
    validator.check_design_links(validator.catalog_design_properties()[2], [doc])
    assert not validator.errors, validator.errors
    assert not sync_runtime.compare_generation(root, {(path.parent.parent.name, path.parent.name, path.stem)})
    return doc


@it_case
def check(root):
    INPUTS.fixture(root)
    build = MODELS.model('codebuild', 'CodeBuild.Project', 'cbld-app-preview-build', [
        ('Name', '`cbld-app-preview-build`', '名前'), ('Artifacts.Type', '`NO_ARTIFACTS`', '成果物'),
        ('Environment.ComputeType', '`BUILD_GENERAL1_SMALL`', '容量'), ('Environment.Image', '`aws/codebuild/standard:7.0`', 'イメージ'),
        ('Environment.Type', '`LINUX_CONTAINER`', '方式'), ('ServiceRole', '`build-role`', '実行role'), ('Source.Type', '`NO_SOURCE`', '入力'),
        ('Id', '[BuildProject](#codebuild-cbld-app-preview-build)', '識別子')], 'BuildProject')
    build['observed.row.001-008.value'] = '`PENDING_DEPLOY`'
    anchor = 'kms-app-preview-data'
    kms = MODELS.model('kms', 'KMS.Key', 'app-preview-data', [('KeyId', f'[Key](#{anchor})', '識別子')], 'Key')
    kms.update({'desired.service.kms.ownedCatalogResourceTypes': 'KMS.Key,KMS.Alias',
        'desired.resource.002.resourceType': 'KMS.Alias', 'desired.resource.002.logicalId': 'Alias',
        'desired.resource.002.anchor': 'kms-alias-app-preview-data', 'desired.resource.002.parentProperty': 'KMS.Alias.TargetKeyId',
        'desired.resource.002.parentReference': f'[Key](#{anchor})', 'desired.row.002-001.property': 'KMS.Alias.AliasName',
        'desired.row.002-001.value': '`alias/app-preview-data`', 'desired.row.002-001.comment': 'キーの別名',
        'observed.row.001-001.value': '`PENDING_DEPLOY`'})
    build_path = root / 'model/preview/team/codebuild.properties'
    kms_path = build_path.with_name('kms.properties')
    write_model(build_path, build)
    write_model(kms_path, kms)
    contract = root / 'tasks/active.md'
    contract.write_text(contract.read_text().replace('## Modified files', '- `preview/team/codebuild`\n- `preview/team/kms`\n## Modified files'))
    assert sync_runtime.sync(root, True, 'preview', 'team', services=['codebuild']) == 0
    vpc_path = build_path.with_name('vpc.properties')
    vpc = dict(load_model(vpc_path).authoritative)
    vpc['desired.note.001.text'] = '参照: [ビルド](codebuild.md#codebuild-cbld-app-preview-build)'
    write_model(vpc_path, vpc)
    for path, key in [(vpc_path, 'desired.row.017-001.value'), (build_path, 'desired.row.001-001.value'), (kms_path, 'desired.row.002-001.value')]:
        assert sync_runtime.sync(root, True, 'preview', 'team', services=[path.stem]) == 0
        before = load_model(path)
        values = dict(before.authoritative)
        values[key] = values[key][:-1] + '-changed`'
        write_model(path, values)
        assert sync_runtime.sync(root, True, 'preview', 'team', services=[path.stem]) == 0
        after = load_model(path)
        assert {key for key in before.authoritative if before.authoritative[key] != after.authoritative[key]} == {key}
        assert bound_resource_anchors(path) == {(resource['resourceType'], resource['logicalId']): resource['anchor'] for _, resource in entries(before.authoritative, 'desired.resource.')}
        doc = validated(root, path)
        saved = {p: p.read_bytes() for base in ('model', 'docs/designs') for p in (root / base).rglob('*') if p.is_file()}
        write_model(path, values)
        assert sync_runtime.sync(root, True, 'preview', 'team', services=[path.stem]) == 0
        assert sync_runtime.sync(root, False, 'preview', 'team', services=[path.stem]) == 0
        assert all(p.read_bytes() == raw for p, raw in saved.items())
        if path.stem == 'kms':
            assert doc.read_text() == markdown_for(doc, dict(after.values), root)
            assert DesignIndex().get(doc).view().expanded[1]
        original, fixed = doc.read_text(), next(iter(bound_resource_anchors(path).values()))
        doc.write_text(original.replace(fixed, fixed + '-tampered'))
        validator = schema_validator(root)
        validator.check_resource_names({doc: (path.stem, tuple(resource['resourceType'] for _, resource in entries(after.authoritative, 'desired.resource.')))}, [doc])
        assert not validator.errors and validator.findings.warnings
        doc.write_text(original)
    values = dict(load_model(vpc_path).authoritative)
    original = vpc_path.read_bytes()
    values['desired.row.083-001.value'] = values['desired.row.042-001.value']
    write_model(vpc_path, values)
    saved = {p: p.read_bytes() for base in ('model', 'docs/designs') for p in (root / base).rglob('*') if p.is_file()}
    with redirect_stdout(io.StringIO()) as warnings:
        assert sync_runtime.sync(root, True, 'preview', 'team', services=['vpc']) == 0
    assert 'unique and match its name' in warnings.getvalue()
    assert all(p.read_bytes() == raw for p, raw in saved.items())
    vpc_path.write_bytes(original)
    original = build_path.read_bytes()
    for anchor in ('codebuild-bad"anchor', 'codebuild-bad<anchor', 'codebuild/bad', ''):
        invalid = dict(load_model(build_path).authoritative)
        invalid['desired.resource.001.anchor'] = anchor
        write_model(build_path, invalid)
        with pytest.raises(ValueError, match='anchor'):
            bound_resource_anchors(build_path)
        build_path.write_bytes(original)
    for raw in (b'# model-format: 99\n', b'# model-format: 2\ninvalid\n', original + b'desired.resource.001.anchor=duplicate\n'):
        build_path.write_bytes(raw)
        with pytest.raises(ValueError):
            bound_resource_anchors(build_path)
    build_path.unlink()
    assert bound_resource_anchors(build_path) == {}
    build_path.write_bytes(original)
    legacy = root / 'model/parameters'
    legacy.mkdir()
    with pytest.raises(ValueError, match='explicit migration'):
        bound_resource_anchors(build_path)
    print('Fixed anchors: PASS (CodeBuild/VPC/grouped KMS rename; IDs/refs/observed; projection/validation; byte-identical rerun; malformed/legacy rejection)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        with redirect_stdout(io.StringIO()) as output:
            check(Path(directory).resolve())
        print(output.getvalue().strip().splitlines()[-1])
