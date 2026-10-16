#!/usr/bin/env python3
"""YAML document digests, input contracts and offline updates."""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import hashlib
from pathlib import Path
import tempfile
import model_templates as t
from model_files import load_model
from model_projection import document_sha256, json_sha256
from model_parameter_inputs import parameter_text
from test_support.model_sources import write_fixture_files as save_files


def check(root):
    template=root/'model/templates/team/vpc-endpoint.properties.tpl'
    text='\n'.join(['# model-template: 1','# definition: Gateway',
        '# parameter: Cidr '+t.json_text({'type':'string','description':'許可するCIDR','required':True,'constraints':{'cidr':'ipv4'}}),
        '# resource: endpoint','# row: policy endpoint',
        'desired.resource.endpoint.resourceType=EC2.VPCEndpoint',
        'desired.resource.endpoint.anchor=gateway',
        'desired.row.policy.property=EC2.VPCEndpoint.PolicyDocument',
        'desired.row.policy.value=[policy](vpc-endpoint/policy.json)',
        'desired.row.policy.artifactSha256=stale',
        'desired.row.policy.document={"Statement":[{"Condition":{"IpAddress":{"aws:VpcSourceIp":"<<Cidr>>"}},"Action":["s3:GetObject","s3:ListBucket"],"Enabled":false,"Count":2,"Text":"日本語"}]}',
        '# end-definition',''])
    save_files({template:text})
    base={'definition':'Gateway','resources':{'endpoint':'017'},'rows':{'policy':'017-004'},'parameters':{},'labels':{}}
    binding={'instances':{'gateway':base}}
    human={'instances':{'gateway':{'parameters':{'Cidr':'198.51.100.0/24'}}}}
    empty={'version':1,'values':{}}
    first=t.expand(template,human,empty,binding,'preview')[0]
    second=t.expand(template,human,empty,binding,'preview')[0]
    assert first==second
    key='desired.row.017-004.';document=t.json_read(first[key+'document'])
    assert document['Statement'][0]['Action']==['s3:GetObject','s3:ListBucket']
    assert document['Statement'][0]['Enabled'] is False and type(document['Statement'][0]['Count']) is int
    assert first[key+'artifactSha256']==document_sha256(document)
    artifact=root/'policy.json';artifact.write_text(t.json_text(document)+'\n',encoding='utf-8')
    assert json_sha256(artifact)==first[key+'artifactSha256']
    sample={'x':'日本語','n':2,'b':False}
    assert t.json_text(sample)=='{"x":"日本語","n":2,"b":false}'
    assert t.digest(sample)==hashlib.sha256(t.json_text(sorted(sample.items())).encode('utf-8')).hexdigest()
    assert t.digest({'n':'2'})!=t.digest({'n':2})
    paths={}
    for environment,inputs in [('preview',human),('release',human)]:
        path=root/'model'/environment/'team/vpc-endpoint.properties';directory=root/'model/parameters'/environment/'team/vpc-endpoint'
        outputs={path:''.join(k+'='+v+'\n' for k,v in first.items()),directory/'observed.json':t.json_text(empty)}
        outputs[directory/'parameters.yaml']=parameter_text(inputs,t.parse_template(template)[0],binding)
        outputs[directory/'bindings.json']=t.json_text(binding)
        save_files(outputs);paths[environment]=(path,directory,inputs)
    (root/'tasks').mkdir();(root/'tasks/active.md').write_text('## Task contract\n- Task type: `migration`\n## Allowed paths\n'+''.join('- `'+(d/'parameters.yaml').relative_to(root).as_posix()+'`\n' for env,(_,d,_) in paths.items()))
    updated=[]
    for environment,(path,directory,inputs) in paths.items():
        before=t.design_source_digest(path)
        changed=copy.deepcopy(inputs)
        item=changed['instances']['gateway']
        item['parameters']['Cidr']='203.0.113.0/24'
        t.save_parameters(path,changed)
        values=load_model(path).values;updated.append(values)
        assert values[key+'artifactSha256']!=first[key+'artifactSha256'] and t.design_source_digest(path)!=before
        assert values[key+'artifactSha256']==document_sha256(t.json_read(values[key+'document']))
        assert t.load_expansion(path).provenance[key+'artifactSha256']['derivedFrom']==key+'document'
        t.save_parameters(path,changed);assert load_model(path).values==values
        assert t.affected(root,[(directory/'parameters.yaml').relative_to(root)])=={(environment,'team','vpc-endpoint')}
    assert updated[0]==updated[1]
    # Object order affects projection bytes/digest as before; the document hash canonicalizes objects only.
    reordered={'Statement':[copy.deepcopy(dict(reversed(list(document['Statement'][0].items()))))]}
    assert document_sha256(reordered)==document_sha256(document)
    reordered['Statement'][0]['Action'].reverse()
    assert document_sha256(reordered)!=document_sha256(document)
    print('JSON/YAML hashes: PASS (same canonical bytes; stale regeneration; types/order; trace; save/rerun; input/projection digest contracts)')


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
