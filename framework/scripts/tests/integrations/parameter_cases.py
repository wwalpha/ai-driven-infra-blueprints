#!/usr/bin/env python3
"""Offline YAML service inputs, identity, reference and update-path regression."""
import copy
from support.model_sources import write_model
import os
from unittest.mock import patch
import tempfile
from pathlib import Path
import model_templates as t
from model_projection import document_sha256
from model_files import load_model, model_parts
from model_parameter_inputs import parameter_text, yaml_read
from support.model_sources import write_fixture_files as save_files

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
ROOT = Path(__file__).resolve().parents[4]


def rejected(call):
    try:
        call()
    except (ValueError, OSError, KeyError, TypeError):
        return
    raise AssertionError('invalid migration input accepted')


def check(root, alias, SERVICE):
    template = root/'model/templates'/alias/(SERVICE+'.properties.tpl')
    original_template = ROOT/'model/templates'/alias/template.name
    save_files({root/p.relative_to(ROOT):p.read_bytes().decode('utf-8') for p in {original_template,*model_parts(original_template)}})
    definitions = t.parse_template(template)[0]
    names = ([n for n in definitions if n.startswith('component_') and not n.endswith('_stg')][:2] if SERVICE in {'athena','sqs'} else ['group_1','group_2','group_3','group_4','group_5','group_6'] if SERVICE=='datazone'
             else [next(n for n,d in definitions.items() if d.resources)])
    binding = {'instances':{}}
    human = {'instances':{}}
    for number,name in enumerate(names,1):
        d = definitions[name];identity = name.removesuffix('_dev')
        alternatives={selector for _,_,selector in d.choices}
        rid = f'{number*17:03d}'
        internal = {n:((n not in alternatives) if s['type']=='boolean' else
                      'fixture-'+SERVICE+'-'+rid if n=='Anchor' else 'Fixture'+rid if n=='LogicalId' else
                      'cfn-stack-fixture-Resource'+rid if n=='Placement' else '0'*64)
                    for n,s in d.parameters.items() if isinstance(s,dict) and s.get('internal')}
        binding['instances'][identity] = {'definition':name,'resources':{r:rid for r in d.resources},
            'rows':{r:rid+'-'+f'{j:03d}' for j,r in enumerate(d.rows,1)},'parameters':internal}
        local = {n:((n not in alternatives) if s['type']=='boolean' else 'fixture repository description') for n,s in d.parameters.items()
                 if isinstance(s,dict) and not s.get('source') and not s.get('internal')}
        d=t.bound_definition(d,{**internal,**local})
        binding['instances'][identity]['parameters']={n:v for n,v in internal.items() if n in d.parameters}
        binding['instances'][identity]['resources']={n:v for n,v in binding['instances'][identity]['resources'].items() if n in d.resources}
        binding['instances'][identity]['rows']={n:v for n,v in binding['instances'][identity]['rows'].items() if n in d.rows}
        local={n:v for n,v in local.items() if n in d.parameters}
        if local:human['instances'][identity]={'parameters':local}
    shared = {n for d in definitions.values() for n,s in d.parameters.items() if isinstance(s,dict) and s.get('source')=='service'}
    if shared:human['parameters']={n:'-one' if n=='Suffix' else '123456789012' for n in shared}
    refs = {n:s for d in definitions.values() for n,s in d.parameters.items() if isinstance(s,dict) and s.get('service')=='kms'}
    if refs:
        rows = ['desired.resource.001.resourceType=KMS.Key','desired.resource.001.anchor=kms-fixture-key',
                'desired.row.001-001.property=KMS.Key.KeyId','desired.row.001-001.value=[001](#kms-fixture-key)']
        for s in refs.values():
            rid=s['target'];rows += [f'desired.resource.{rid}.resourceType=KMS.Alias',f'desired.resource.{rid}.anchor=kms-fixture-alias-{rid}',
                f'desired.resource.{rid}.parentProperty=KMS.Alias.TargetKeyId',f'desired.resource.{rid}.parentReference=[001](#kms-fixture-key)',
                f'desired.row.{rid}-001.property=KMS.Alias.AliasName',f'desired.row.{rid}-001.value=`alias/fixture-{rid}`',
                f'desired.row.{rid}-002.property=KMS.Alias.TargetKeyId',f'desired.row.{rid}-002.value=[001](#kms-fixture-key)']
        producer=root/'model/preview'/alias/'kms.properties';producer.parent.mkdir(parents=True)
        write_model(producer, '\n'.join(rows)+'\n')
    if SERVICE == "athena":
        buckets = {s['target'] for d in definitions.values() for s in d.parameters.values()
                   if isinstance(s,dict) and s.get('service')=='s3'}
        bucket_producer=root/'model/preview'/alias/'s3.properties'
        bucket_text=''.join(f'desired.resource.{rid}.resourceType=S3.Bucket\ndesired.resource.{rid}.anchor=bucket-{rid}\n'
            f'desired.row.{rid}-001.property=S3.Bucket.BucketName\ndesired.row.{rid}-001.value=`fixture-bucket-{rid}-one`\n'
            for rid in sorted(buckets))
        save_files({bucket_producer:bucket_text})
    if SERVICE == 'sqs':
        project=root/'project.json'
        topology={'targets':[{'environment':env,'alias':alias,'awsAccountId':'111111111111',
            'awsExecutionAccountId':account,'awsRegion':'ap-northeast-1','iacEngine':'cloudformation'}
            for env,account in [('preview','123456789012'),('prod','210987654321')]]}
        project_text=t.json_text(topology);save_files({project:project_text})
    observed={'version':1,'values':{}}
    values,_,_=t.expand(template,human,observed,binding,'preview')
    path=root/'model/preview'/alias/(SERVICE+'.properties');directory=root/'model/parameters/preview'/alias/SERVICE
    serialized=parameter_text(human,definitions,binding)
    outputs={
        directory/'parameters.yaml':serialized,directory/'bindings.json':t.json_text(binding)+'\n',directory/'observed.json':t.json_text(observed)}
    save_files(outputs)
    other = root/'model/prod'/alias/(SERVICE+'.properties')
    other_directory = root/'model/parameters/prod'/alias/SERVICE
    if refs:
        other_producer=root/'model/prod'/alias/'kms.properties';other_producer.parent.mkdir(parents=True);write_model(other_producer, load_model(producer).values)
    if SERVICE == 'athena':
        save_files({root/'model/prod'/alias/'s3.properties':bucket_text})
    other_values = t.expand(template,human,observed,binding,'prod')[0]
    save_files({
        **{other_directory/p.name:text for p,text in outputs.items() if p.parent==directory}})
    (root/'tasks').mkdir()
    (root/'tasks/active.md').write_text('## Task contract\n- Task type: `migration`\n## Allowed paths\n- `'+(directory/'parameters.yaml').relative_to(root).as_posix()+'`\n',encoding='utf-8')
    assert load_model(path).values==values
    trace=t.load_expansion(path)
    assert all(s['inputs'][n]['description'] and s['inputs'][n]['modelKey'] for s in trace.provenance.values() for n in s.get('inputs',{}))
    assert yaml_read(serialized) == human and 'definition:' not in serialized
    assert all(bool(human['instances'].get(identity))==any(not s.get('internal') and not s.get('source') for s in definitions[b['definition']].parameters.values()) for identity,b in binding['instances'].items())
    if SERVICE == 'athena':
        def locations(values):
            return {k:v for k,v in values.items() if k.endswith('.value') and
                    values.get(k.removesuffix('.value')+'.property','').endswith('.OutputLocation')}
        assert set(load_model(bucket_producer).files) <= set(t.source_inputs(path))
        assert ('preview',alias,SERVICE) in t.affected(root,[bucket_producer.relative_to(root)])
        assert all('ResultBucket' in source['references'] for key,source in trace.provenance.items() if key in locations(values))
    old_digest=t.design_source_digest(path)
    assert t.affected(root,[template.relative_to(root)])=={(env,alias,SERVICE) for env in ('preview','prod')}
    for filename in ('parameters.yaml','bindings.json'):
        assert t.affected(root,[(directory/filename).relative_to(root)])=={('preview',alias,SERVICE)}
    for _ in range(2):
        t.save_parameters(path,yaml_read(serialized))
        assert (directory/'parameters.yaml').read_text()==serialized
        assert load_model(path).values==values
    if shared:
        changed=copy.deepcopy(human);field='Suffix' if 'Suffix' in shared else next(iter(shared));changed['parameters'][field]='-two' if field=='Suffix' else '210987654321'
        t.save_parameters(path,changed);new_values=load_model(path).values
        assert new_values!=values and t.design_source_digest(path)!=old_digest
        if SERVICE == "athena": assert locations(new_values)==locations(values)
        assert load_model(other).values==other_values
        assert {k:v for k,v in values.items() if k.startswith('desired.resource.')}=={k:v for k,v in new_values.items() if k.startswith('desired.resource.')}
        t.save_parameters(path,human)
        for badvalue in (True,'INVALID'):
            bad=copy.deepcopy(human);bad['parameters'][field]=badvalue;rejected(lambda:t.save_parameters(path,bad))
        bad=copy.deepcopy(human);bad['parameters'].pop(field);rejected(lambda:t.save_parameters(path,bad))
    if SERVICE=='sqs':
        doc=next(t.json_read(v) for k,v in values.items() if k.endswith('.document'))
        statement=doc['Statement'][0];assert isinstance(doc['Statement'],list) and statement['Action']=='sqs:SendMessage'
        assert statement['Resource']['Fn::GetAtt']==['HulftRetrievalDetectDlq','Arn']
        assert any('[017](#fixture-sqs-017)'==v for k,v in values.items() if k.endswith('.value'))
        key=next(k for k in values if k.endswith('.document'))
        hash_key=key.removesuffix('.document')+'.artifactSha256'
        assert values[hash_key]==document_sha256(doc)
        assert statement['Condition']['StringEquals']['aws:SourceAccount']=='123456789012'
        assert 'ArtifactSha256' not in t.json_text(binding)
        rejected(lambda:t.save_parameters(path,{'instances':{},'parameters':{'SourceAccountId':'999999999999'}}))
        assert project in t.source_inputs(path) and ('preview',alias,SERVICE) in t.affected(root,['project.json'])
        account_trace=trace.provenance[key]['inputs']['SourceAccountId']
        assert account_trace['value']=='123456789012' and account_trace['source']=='consumer.executionAccountId'
        changed=copy.deepcopy(topology);changed['targets'][0]['awsExecutionAccountId']='999999999999'
        save_files({project:t.json_text(changed)})
        updated=load_model(path).values;doc=t.json_read(updated[key])
        assert doc['Statement'][0]['Condition']['StringEquals']['aws:SourceAccount']=='999999999999'
        assert updated[hash_key]==document_sha256(doc) and updated[hash_key]!=values[hash_key]
        assert load_model(other).values==other_values
        assert {k:v for k,v in values.items() if k.startswith('desired.resource.')}=={k:v for k,v in updated.items() if k.startswith('desired.resource.')}
        save_files({project:project_text})
        original=template.read_text();template.write_text(original.replace('"Action":"sqs:SendMessage"','"Action":["sqs:SendMessage","sqs:GetQueueUrl"]'))
        updated=load_model(path).values;doc=t.json_read(updated[key])
        assert doc['Statement'][0]['Action']==['sqs:SendMessage','sqs:GetQueueUrl']
        assert updated[hash_key]==document_sha256(doc) and updated[hash_key]!=values[hash_key]
        assert load_model(other).values!=other_values
        assert load_model(path).values==updated
        template.write_text(original)
    if SERVICE=='security-hub':
        assert any(v=='`SECURITY_CONTROL`' for v in values.values()) and any(v=='`true`' for v in values.values())
    if SERVICE == 'athena':
        write_model(bucket_producer, bucket_text.replace('-one','-two'))
        updated=load_model(path).values
        assert locations(updated)!=locations(values) and t.design_source_digest(path)!=old_digest
        assert load_model(other).values==other_values
        assert {k:v for k,v in values.items() if k.startswith('desired.resource.')}=={k:v for k,v in updated.items() if k.startswith('desired.resource.')}
        write_model(bucket_producer, bucket_text)
        if 'ResultBucketAccountId' in shared:
            changed=copy.deepcopy(human);changed['parameters']['ResultBucketAccountId']='210987654321'
            owner_changed=t.expand(template,changed,observed,binding,'preview')[0]
            assert locations(owner_changed)==locations(values) and owner_changed!=values
        t.source_paths(bucket_producer)[2].joinpath('parameters.yaml').unlink();rejected(lambda:load_model(path));save_files({bucket_producer:bucket_text})
    reordered=copy.deepcopy(binding);reordered['instances']=dict(reversed(list(binding['instances'].items())))
    assert t.expand(template,human,observed,reordered,'preview')[0]==values
    first=next(iter(binding['instances']));renamed=copy.deepcopy(binding);renamed['instances']['renamed']=renamed['instances'].pop(first)
    new_human=copy.deepcopy(human)
    if first in new_human['instances']:new_human['instances']['renamed']=new_human['instances'].pop(first)
    template_files={p:p.read_bytes().decode('utf-8') for p in {template,*model_parts(template)}}
    save_files({p:text.replace('"instance":"'+first+'"','"instance":"renamed"') for p,text in template_files.items()})
    assert t.expand(template,new_human,observed,renamed,'preview')[0]==values
    save_files(template_files)
    binding_path=directory/'bindings.json';binding_text=binding_path.read_text()
    binding_path.write_text(binding_text+'\n');assert t.design_source_digest(path)!=old_digest;binding_path.write_text(binding_text)
    comment=next(k for k in definitions[names[0]].values if k.endswith('.comment'))
    template_part,line=definitions[names[0]].locations[comment]
    original=template_files[template_part];lines=original.splitlines(keepends=True);lines[line-1]=lines[line-1].replace('.comment=','.comment=更新確認 ',1);template_part.write_text(''.join(lines))
    assert t.design_source_digest(path)!=old_digest
    assert load_model(path).values!=values and load_model(other).values!=other_values
    template_part.write_text(original)
    bad=copy.deepcopy(binding);bad['instances'][first]['resources']=dict.fromkeys(bad['instances'][first]['resources'],'999')
    rejected(lambda:t.expand(template,human,observed,bad,'preview'))
    bad=copy.deepcopy(binding);bad['instances'][first].pop('definition');rejected(lambda:t.expand(template,human,observed,bad,'preview'))
    bad=copy.deepcopy(human);bad['instances'][first]={'definition':'unknown','parameters':{}};rejected(lambda:t.save_parameters(path,bad))
    bad=copy.deepcopy(human);bad['unknown']=1;rejected(lambda:t.save_parameters(path,bad))
    rejected(lambda:yaml_read(serialized+'instances: {}\n'))
    fallback=directory/'parameters.json';fallback.write_text('{}');rejected(lambda:load_model(path));fallback.unlink()
    (directory/'parameters.yaml').write_text('invalid: [');rejected(lambda:load_model(path));(directory/'parameters.yaml').write_text(serialized)
    assert t.design_source_digest(path)==old_digest
    print(SERVICE,alias,'PASS (input responsibilities; trace; save/update/hash/impact; binding-only instances; order/rename/fixed IDs; strict rejection)')


def run(service):
    from support.service_fixtures import input_templates
    with tempfile.TemporaryDirectory(prefix='input-templates-') as source:
        source = Path(source)
        input_templates(source)
        with patch(__name__+'.ROOT', source):
            aliases = [p.parent.name for p in sorted((source/'model/templates').glob('*/'+service+'.properties.tpl'))]
            assert aliases, 'no service template test cases'
            for alias in aliases:
                with tempfile.TemporaryDirectory(prefix=service+'-inputs-') as directory, patch.dict(os.environ, {'BLUEPRINT_TASK_FILE':'tasks/active.md'}):
                    check(Path(directory), alias, service)
