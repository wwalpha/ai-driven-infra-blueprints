#!/usr/bin/env python3
"""Compact authorities preserve observed values, identities and publication safety."""
import copy
import tempfile
from pathlib import Path
from unittest.mock import patch
import model_templates as t
from model_files import load_model
from test_support.model_sources import write_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def rejected(call, message=None):
    try:
        call()
    except (OSError, ValueError, TypeError) as error:
        if message is not None:
            assert message in str(error), error
        return
    raise AssertionError('invalid compact authority accepted')


with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();path=root/'model/preview/team/example.properties'
    desired={'desired.resource.017.resourceType':'S3.Bucket', 'desired.resource.017.anchor':'s3-fixed',
             'desired.row.017-023.property':'S3.Bucket.BucketName', 'desired.row.017-023.value':'`desired-name`',
             'desired.row.017-023.comment':'観測値の説明'}
    write_model(path,desired);_,template,source=t.source_paths(path);observed=source/'observed.json'
    key='observed.row.017-023.value'
    assert not observed.exists() and load_model(path).values==desired
    t.create_service(path)
    assert observed in t.input_snapshot(path) and t.input_snapshot(path)[observed] is None
    # Required identifiers stay unobserved; desired is never substituted for observed.
    assert not any(k.startswith('observed.') for k in t.reference_values(path,'017','S3.Bucket','identifier').values)
    for value in ('false','0','','null','`PENDING_DEPLOY`'):
        observed.write_text(t.json_text({'version':1,'values':{key:value}}))
        values=load_model(path).values
        assert values[key]==value and values[key.removesuffix('value')+'property']==desired['desired.row.017-023.property']
        assert values[key.removesuffix('value')+'comment']==desired['desired.row.017-023.comment']
        expansion=t.load_expansion(path)
        for field in ('property','comment'):
            metadata=key.removesuffix('value')+field
            assert expansion.provenance[metadata]['derivedFrom']=='desired.'+metadata.removeprefix('observed.')
            assert load_model(path).locations[metadata][0].is_relative_to(root/'model/templates')
        assert load_model(path).locations[key][0]==observed
        output=t.observed_outputs(path,values)
        assert t.json_read(output[observed])=={'version':1,'values':{key:value}}
        for _ in range(2):t.publish(root,output,inputs=t.input_snapshot(path))
        assert t.json_read(observed.read_text())['values']=={key:value}
    original=observed.read_bytes()
    for invalid in (False,0,None):
        observed.write_text(t.json_text({'version':1,'values':{key:invalid}}));rejected(lambda:load_model(path),'invalid observed')
    for invalid in ({key:'x','observed.row.017-023.property':'wrong'}, {'observed.row.999-001.value':'x'}, {'observed.row.017-023.state':'unknown'}):
        observed.write_text(t.json_text({'version':1,'values':invalid}));rejected(lambda:load_model(path))
    observed.write_text('{');rejected(lambda:load_model(path));observed.write_bytes(original)
    with patch.object(Path,'read_bytes',side_effect=PermissionError('denied')):rejected(lambda:load_model(path),'denied')
    values=load_model(path).values
    rejected(lambda:t.observed_outputs(path,{**values,'observed.row.017-023.comment':'different'}),'metadata differs')
    marker=root/'marker';marker.write_text('before')
    def interrupted(output):
        marker.write_text('partial');raise OSError('interrupted')
    with patch('sync_files.save_files',side_effect=interrupted):
        rejected(lambda:t.publish(root,{observed:None,marker:'after'}),'interrupted')
    assert observed.read_bytes()==original and marker.read_text()=='before'
    empty=t.observed_outputs(path,desired)
    for _ in range(2):t.publish(root,empty,inputs=t.input_snapshot(path))
    assert not observed.exists() and load_model(path).values==desired
    snapshot=t.input_snapshot(path);observed.write_text(t.json_text({'version':1,'values':{}}))
    rejected(lambda:t.publish(root,empty,inputs=snapshot),'sources changed');observed.unlink()
    binding_file=source/'bindings.json';binding=t.json_read(binding_file.read_text());assert 'labels' not in binding['instances']['fixture']
    explicit=copy.deepcopy(binding);explicit['instances']['fixture']['labels']={};binding_file.write_text(t.json_text(explicit))
    assert load_model(path).values==desired
    for field in ('definition','resources','rows','parameters'):
        bad=copy.deepcopy(binding);del bad['instances']['fixture'][field];binding_file.write_text(t.json_text(bad));rejected(lambda:load_model(path))
    for labels in (None,[],{'Unknown':'x'}):
        bad=copy.deepcopy(binding);bad['instances']['fixture']['labels']=labels;binding_file.write_text(t.json_text(bad));rejected(lambda:load_model(path))
    binding_file.write_text(t.json_text(binding))
    assert load_model(path).values==desired and not path.exists() and not list(root.rglob('source.json'))
print('Compact sources: PASS (optional observed; value/metadata separation; false/zero/empty/null/missing; malformed/orphan/unknown rejection; labels omission; required fields; atomic removal/rollback; missing-input guards; idempotence)')

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();template=root/'model/templates/team/shared.properties.tpl'
    body=('# resource: bucket\n# row: name bucket\n'
          'desired.resource.bucket.resourceType=S3.Bucket\ndesired.resource.bucket.anchor=s3-fixed\n'
          'desired.row.name.property=S3.Bucket.BucketName\ndesired.row.name.value=`fixed-name`\n'
          'desired.row.name.comment=共通定義の説明\n# end-definition\n')
    template.parent.mkdir(parents=True);template.write_text('# model-template: 1\n# definition: Common\n'+body+'# definition: Independent\n'+body.replace('共通定義の説明','独立定義の説明'))
    paths=[]
    for environment,definition in (('preview','Common'),('release','Common'),('independent','Independent')):
        path=root/'model'/environment/'team/shared.properties';source=t.source_paths(path)[2];source.mkdir(parents=True)
        (source/'parameters.yaml').write_text('instances: {}\n')
        (source/'bindings.json').write_text(t.json_text({'instances':{'fixed':{'definition':definition,'resources':{'bucket':'017'},'rows':{'name':'017-023'},'parameters':{}}}}))
        t.create_service(path);paths.append(path)
    before={path:load_model(path).values for path in paths}
    template.write_text(template.read_text().replace('共通定義の説明','共通定義の変更',1))
    for path in paths:
        after=load_model(path).values
        assert after['desired.resource.017.anchor']==before[path]['desired.resource.017.anchor']
        assert set(after)==set(before[path])
        assert (after!=before[path])==(path.parent.parent.name!='independent')
    assert not any(path.exists() for path in paths) and not list(root.rglob('observed.json'))
print('Shared definition consumers: PASS (shared declaration; only bound Model values change; independent definition and fixed IDs preserved)')
