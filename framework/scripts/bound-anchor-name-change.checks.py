#!/usr/bin/env python3
"""Offline fixed-binding rename, grouped identity and legacy rejection checks."""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile

import model_templates as t
from model_core import entries, properties
from model_files import load_model
from model_parameter_inputs import parameter_text, yaml_read
from model_references import bound_resource_anchors
from model_design import markdown_for
from model_projection import model_for
from design_document import DesignIndex
from test_support.model_sources import write_fixture_files as save_files
import sync_runtime
from test_support.validator import load, schema_validator

INPUTS = load('model_parameter_inputs.checks')
MODELS = load('model_design.checks')


def register(root, service, values, edits):
    template = root / 'model/templates/team' / (service + '.properties.tpl')
    resources = dict(entries(values, 'desired.resource.'))
    rows = dict(entries(values, 'desired.row.'))
    binding = {'definition': 'Main', 'resources': {'r'+rid: rid for rid in resources},
               'rows': {'row'+rid.replace('-', '_'): rid for rid in rows}, 'parameters': {}, 'labels': {}}
    lines = ['# model-template: 1', '# definition: Main']
    human = {'instances': {'main': {'parameters': {}}}}
    for key, name in edits.items():
        lines.append(INPUTS.declaration(name, format='literal'))
        human['instances']['main']['parameters'][name] = values[key].strip('`')
    for rid, resource in resources.items():
        lines += ['# resource: r'+rid, '# internal: Anchor'+rid+' string']
        binding['parameters']['Anchor'+rid] = resource['anchor']
    lines += ['# row: row'+rid.replace('-', '_')+' r'+rid.split('-')[0] for rid in rows]
    for key, value in values.items():
        if key.startswith('observed.'):
            continue
        for rid, resource in resources.items():
            key = key.replace('resource.'+rid+'.', 'resource.r'+rid+'.')
            value = value.replace(resource['anchor'], '<<Anchor'+rid+'>>')
        for rid in rows:
            key = key.replace('row.'+rid+'.', 'row.row'+rid.replace('-', '_')+'.')
        original = key
        for rid in rows:
            original = original.replace('row.row'+rid.replace('-', '_')+'.', 'row.'+rid+'.')
        if original in edits:
            value = '<<'+edits[original]+'>>'
        lines.append(key+'='+value)
    lines.append('# end-definition')
    bindings = {'instances': {'main': binding}}
    observed = {'version': 1, 'values': {k:v for k,v in values.items() if k.startswith('observed.') and k.endswith('.value')}}
    path = root/'model/preview/team'/(service+'.properties')
    directory = root/'model/parameters/preview/team'/service
    save_files({template:'\n'.join(lines)+'\n', path:MODELS.text(values)})
    save_files({directory/'parameters.yaml':parameter_text(human, t.parse_template(template)[0], bindings),
                directory/'bindings.json':t.json_text(bindings), directory/'observed.json':t.json_text(observed)})
    return path, directory, template


def validated(root, path):
    doc = root/'docs/designs'/path.relative_to(root/'model').with_suffix('.md')
    values = load_model(path).values
    metadata = {doc: (path.stem, tuple(next(v for k,v in values.items() if k.endswith('.ownedCatalogResourceTypes')).split(',')))}
    validator = schema_validator(root)
    validator.check_resource_names(metadata, [doc])
    validator.check_design_tables(metadata, *validator.catalog_design_properties(), [doc])
    validator.check_design_links(validator.catalog_design_properties()[2], [doc])
    assert not validator.errors, validator.errors
    projected = properties(model_for(doc, root, source=values))
    assert projected == {k:v for k,v in values.items() if not k.startswith('display.') and not k.endswith('.cfn-logicalId')}
    return doc


def check(root):
    INPUTS.fixture(root)
    build = MODELS.model('codebuild', 'CodeBuild.Project', 'cbld-app-preview-build', [
        ('Name','`cbld-app-preview-build`','名前'), ('Artifacts.Type','`NO_ARTIFACTS`','成果物'),
        ('Environment.ComputeType','`BUILD_GENERAL1_SMALL`','容量'), ('Environment.Image','`aws/codebuild/standard:7.0`','イメージ'),
        ('Environment.Type','`LINUX_CONTAINER`','方式'), ('ServiceRole','`build-role`','実行role'), ('Source.Type','`NO_SOURCE`','入力'), ('Id','[BuildProject](#codebuild-cbld-app-preview-build)','識別子')], 'BuildProject')
    build.update({'observed.row.001-008.property':'CodeBuild.Project.Id', 'observed.row.001-008.value':'`PENDING_DEPLOY`', 'observed.row.001-008.comment':'識別子'})
    anchor = 'kms-app-preview-data'
    kms = MODELS.model('kms', 'KMS.Key', 'app-preview-data', [('KeyId',f'[Key](#{anchor})','識別子')], 'Key')
    kms.update({'desired.service.kms.ownedCatalogResourceTypes':'KMS.Key,KMS.Alias',
                'desired.resource.002.resourceType':'KMS.Alias','desired.resource.002.logicalId':'Alias',
                'desired.resource.002.anchor':'kms-alias-app-preview-data','desired.resource.002.parentProperty':'KMS.Alias.TargetKeyId',
                'desired.resource.002.parentReference':f'[Key](#{anchor})','desired.row.002-001.property':'KMS.Alias.AliasName',
                'desired.row.002-001.value':'`alias/app-preview-data`','desired.row.002-001.comment':'キーの別名', 'observed.row.001-001.property':'KMS.Key.KeyId',
                'observed.row.001-001.value':'`PENDING_DEPLOY`', 'observed.row.001-001.comment':'識別子'})
    build_path, build_dir, build_template = register(root, 'codebuild', build, {'desired.row.001-001.value':'Name'})
    kms_path, kms_dir, _ = register(root, 'kms', kms, {'desired.row.002-001.value':'Name'})
    contract=root/'tasks/active.md'
    contract.write_text(contract.read_text().replace('## Allowed paths', '- `preview/team/codebuild`\n- `preview/team/kms`\n## Allowed paths'), encoding='utf-8')
    assert sync_runtime.sync(root,True,'preview','team',services=['codebuild']) == 0
    vpc_template=root/'model/templates/team/vpc.properties.tpl';text=vpc_template.read_text()
    text=text.replace('# definition: Service', '# definition: Service\ndesired.note.001.text=参照: [ビルド](codebuild.md#codebuild-cbld-app-preview-build)')
    vpc_template.write_text(text,encoding='utf-8')
    for path in (root/'model/preview/team/vpc.properties', build_path, kms_path):
        service = path.stem
        assert sync_runtime.sync(root, True, 'preview','team',services=[service]) == 0
        before = load_model(path).values
        directory = root/'model/parameters/preview/team'/service
        source = directory/'parameters.yaml'
        human = yaml_read(source.read_text())
        identity = 'main-vpc' if service=='vpc' else 'main'
        human['instances'][identity]['parameters']['Name'] += '-changed'
        t.save_parameters(path, human)
        assert sync_runtime.sync(root, True, 'preview','team',services=[service]) == 0
        after = load_model(path).values
        changed = {k for k in before if before[k] != after[k]}
        assert changed == {'desired.row.'+('017-001' if service=='vpc' else '002-001' if service=='kms' else '001-001')+'.value'}, changed
        doc = validated(root, path)
        saved = {p:p.read_bytes() for base in ('model','model/parameters','docs/designs') for p in (root/base).rglob('*') if p.is_file()}
        t.save_parameters(path, human)
        assert sync_runtime.sync(root, True, 'preview','team',services=[service]) == 0
        assert sync_runtime.sync(root, False, 'preview','team',services=[service]) == 0
        assert all(p.read_bytes()==data for p,data in saved.items())
        if service=='kms':
            assert model_for(doc,root,source=after)
            assert DesignIndex().get(doc).view().expanded[1]
        original = doc.read_text()
        fixed = next(iter(bound_resource_anchors(path).values()))
        doc.write_text(original.replace(fixed, fixed+'-tampered'))
        validator=schema_validator(root);validator.check_resource_names({doc:(service, tuple(r['resourceType'] for _,r in entries(after,'desired.resource.')))}, [doc])
        assert validator.errors
        doc.write_text(original)
    # Fixed IDs do not permit two resources to acquire the same normalized display name.
    path=root/'model/preview/team/vpc.properties';directory=root/'model/parameters/preview/team/vpc'
    source=directory/'parameters.yaml';old=source.read_text();human=yaml_read(old)
    human['instances']['private-c']['parameters']['Name']=human['instances']['private-a']['parameters']['Name']
    t.save_parameters(path,human)
    saved={p:p.read_bytes() for base in ('model','docs/designs') for p in (root/base).rglob('*') if p.is_file()}
    INPUTS.rejected(lambda:sync_runtime.sync(root,True,'preview','team',services=['vpc']), 'unique and match its name')
    assert all(p.read_bytes()==data for p,data in saved.items())
    source.write_text(old)
    # A legacy source, public anchor, malformed binding and edited projection do not gain an exception.
    doc=root/'docs/designs/preview/team/codebuild.md';values=load_model(build_path).values
    source=build_dir/'bindings.json';stamp=source.read_text();source.write_text('{}')
    INPUTS.rejected(lambda:bound_resource_anchors(build_path), 'instances')
    INPUTS.rejected(lambda:markdown_for(doc,values,root),'instances');source.write_text(stamp)
    yaml_source=build_dir/'parameters.yaml';human=yaml_read(yaml_source.read_text());yaml_bytes=yaml_source.read_bytes()
    bindings=t.json_read((build_dir/'bindings.json').read_text())['instances']['main']
    legacy={'version':1,'instances':[{'id':'main', **{k:bindings[k] for k in ('definition','resources','rows','labels')},
                                    'parameters':{**human['instances']['main']['parameters'], **bindings['parameters']}}]}
    yaml_source.unlink();save_files({build_dir/'parameters.json':t.json_text(legacy)})
    INPUTS.rejected(lambda:bound_resource_anchors(build_path), 'unsupported JSON')
    INPUTS.rejected(lambda:markdown_for(doc,values,root),'unsupported JSON')
    (build_dir/'parameters.json').unlink();yaml_source.write_bytes(yaml_bytes);source.write_text(stamp)
    old=build_template.read_text();build_template.write_text(old.replace('# internal: Anchor001 string', INPUTS.declaration('Anchor001')))
    INPUTS.rejected(lambda:bound_resource_anchors(build_path),'internal parameters');build_template.write_text(old)
    bindings=build_dir/'bindings.json';old=bindings.read_text();bad=t.json_read(old);bad['instances']['main']['parameters']['Anchor001']='codebuild-bad\"anchor';bindings.write_text(t.json_text(bad))
    INPUTS.rejected(lambda:bound_resource_anchors(build_path),'invalid bound resource anchor');bindings.write_text(old)
    old=yaml_source.read_text();yaml_source.write_text('instances: [')
    INPUTS.rejected(lambda:bound_resource_anchors(build_path),'invalid');yaml_source.write_text(old)
    old=bindings.read_text();bindings.unlink();INPUTS.rejected(lambda:bound_resource_anchors(build_path),'missing');bindings.write_text(old)
    invalid=copy.deepcopy(values);invalid['desired.resource.001.anchor']+='-wrong'
    INPUTS.rejected(lambda:markdown_for(doc,invalid,root),'match its name')
    print('Fixed bindings: PASS (CodeBuild/VPC/grouped KMS rename, IDs/refs/observed, projection/validation, byte-identical rerun, legacy and tamper rejection)')


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as directory:
        with redirect_stdout(io.StringIO()) as output:
            check(Path(directory).resolve())
        print(output.getvalue().strip().splitlines()[-1])
