#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.raw_bucket_name_reference_fixtures import *

def check(root):
    producer = root/'model/preview/team/s3.properties'
    original = ('desired.service.s3.serviceId=s3\n'
        'desired.resource.017.resourceType=S3.Bucket\n'
        'desired.resource.017.anchor=s3-raw-name\n'
        'desired.row.017-001.property=S3.Bucket.BucketName\n'
        'desired.row.017-001.value=`app-preview-RAW-one`\n')
    template = root/'model/templates/team/macie.properties.tpl'
    ref = {'service':'s3','resource':'017','resourceType':'S3.Bucket'}
    text = '\n'.join(['# model-template: 1','# definition: Job',
        '# reference: Bucket '+t.json_text({**ref,'format':'name'}),
        '# reference: Link '+t.json_text(ref),'# resource: job',
        '# row: document job','# row: link job',
        'desired.resource.job.resourceType=Macie.ClassificationJob',
        'desired.resource.job.anchor=macie-<<Id_job>>',
        'desired.row.document.property=Macie.ClassificationJob.S3JobDefinition',
        'desired.row.document.value=[json](macie/job-<<Id_job>>.json)',
        'desired.row.document.document='+t.json_text({'bucketDefinitions':[
            {'accountId':'111111111111','buckets':['<<Bucket>>','fixed-second']}],
            'scoping':{'includes':{'and':[{'simpleScopeTerm':{'comparator':'EQ','key':'OBJECT_EXTENSION','values':['csv']}}]}}}),
        'desired.row.link.property=Macie.ClassificationJob.Name',
        'desired.row.link.value=<<Link>>','# end-definition',''])
    bindings={'instances':{name:{'definition':'Job','resources':{'job':rid},
        'rows':{'document':rid+'-001','link':rid+'-002'},'parameters':{},
        'labels':{'Link':'PENDING_DEPLOY'}} for name,rid in [('first','003'),('second','088')]}}
    human,observed={'instances':{}},{'version':1,'values':{}}
    write_fixture_files({producer:original,template:text})
    values,_,files=t.expand(template,human,observed,bindings,'preview')
    key='desired.row.003-001.document'
    doc=json.loads(values[key])
    assert doc['bucketDefinitions'][0]['buckets']==['app-preview-RAW-one','fixed-second']
    assert doc['bucketDefinitions'][0]['accountId']=='111111111111'
    assert values['desired.row.003-002.value']=='[PENDING_DEPLOY](s3.md#s3-raw-name)'
    assert set(load_model(producer).files) <= set(files)
    path=root/'model/preview/team/macie.properties'
    directory=root/'model/parameters/preview/team/macie'
    write_fixture_files({path:''.join(k+'='+v+'\n' for k,v in values.items()),

        directory/'parameters.yaml':'instances: {}\n',directory/'bindings.json':t.json_text(bindings),
        directory/'observed.json':t.json_text(observed)})
    assert load_model(path).values==values
    assert set(load_model(producer).files) <= set(t.source_inputs(path))
    assert t.affected(root,[producer.relative_to(root)])=={('preview','team','s3'),('preview','team','macie')}
    digest=t.design_source_digest(path)
    write_model(producer, original+'# annotation\n')
    assert t.design_source_digest(path)!=digest
    assert load_model(path).values==values
    write_model(producer, original.replace('RAW-one','RAW-two'))
    updated=load_model(path).values
    assert json.loads(updated[key])['bucketDefinitions'][0]['buckets'][0]=='app-preview-RAW-two'
    assert updated['desired.row.003-002.value']=='[PENDING_DEPLOY](s3.md#s3-raw-name)'
    assert t.design_source_digest(path)!=digest
    for bad,phrase in [(original.replace('resourceType=S3.Bucket','resourceType=IAM.Role'),'type-mismatched'),
        (original.replace('017','018'),'type-mismatched'),
        (original.replace('S3.Bucket.BucketName','S3.Bucket.Description'),'exactly one name'),
        (original.replace('`app-preview-RAW-one`','``'),'exactly one name'),
        (original+'desired.row.017-002.property=S3.Bucket.BucketName\ndesired.row.017-002.value=`duplicate`\n','exactly one name')]:
        write_model(producer, bad)
        rejected(lambda:load_model(path),phrase)
    write_model(producer, original)
    invalid=copy.deepcopy(bindings)
    invalid['instances']['first']['labels']['Bucket']='override'
    rejected(lambda:t.expand(template,human,observed,invalid,'preview'),'raw name reference cannot override label')
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    rejected(lambda:load_model(path),'missing')
    # Reuse the same named producer path for QuickSight's raw WorkGroup scalar.
    write_fixture_files({root/'model/preview/team/athena.properties':original.replace('s3','athena').replace('S3.Bucket','Athena.WorkGroup').replace('.BucketName','.Name'),
        template:text.replace('"service":"s3"','"service":"athena"').replace('S3.Bucket','Athena.WorkGroup')})
    assert json.loads(t.expand(template,human,observed,bindings,'preview')[0][key])['bucketDefinitions'][0]['buckets'][0]=='app-preview-RAW-one'
    write_fixture_files({root/'model/preview/team/athena.properties':original.replace('s3','athena').replace('S3.Bucket','KMS.Key').replace('.BucketName','.Description'),
        template:text.replace('"service":"s3"','"service":"athena"').replace('S3.Bucket','KMS.Key')})
    rejected(lambda:t.expand(template,human,observed,bindings,'preview'),'exactly one name')
    print('Raw BucketName: PASS (JSON types/order; links/labels; producer hash/impact; rejection)')


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())

