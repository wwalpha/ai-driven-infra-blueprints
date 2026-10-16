#!/usr/bin/env python3
"""Small offline group-05 fixtures; no real Model/observed/secret data is copied."""
from model_files import read_model
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import math
import tempfile
from test_support.model_sources import write_model, write_fixture_files
from pathlib import Path
import model_templates as t
from model_files import load_model, model_parts, model_file_contents
from model_core import entries
from model_parameter_inputs import parameter_text, yaml_read, check_value
from test_support.model_sources import write_fixture_files as save_files

ROOT = Path(__file__).resolve().parents[2]
SERVICES = {'cloudtrail', 'secrets-manager', 'vpc-endpoint'}


def rejected(call):
    try:
        call()
    except (ValueError, OSError):
        return
    raise AssertionError('invalid group-05 inputs accepted')


def fixture_values(spec):
    constraints = spec.get('constraints', {})
    candidates = list(constraints.get('enum', []))
    if 'default' in spec:
        candidates.append(spec['default'])
    candidates += {
        'string': ['-fixture-01', '', 'ap-northeast-1', 'us-west-2',
                   'vpc-01234567', 'vpc-89abcdef',
                   '198.51.100.0/24', '203.0.113.0/24', '2001:db8::/32',
                   'com.amazonaws.vpce.ap-northeast-1.vpce-svc-fixture01',
                   'com.amazonaws.vpce.ap-northeast-1.vpce-svc-fixture02',
                   'a' * constraints.get('minLength', 1), 'b' * constraints.get('minLength', 1)],
        'integer': [math.ceil(constraints.get('minimum', 0)), math.floor(constraints.get('maximum', 1)), 0, 1],
        'number': [constraints.get('minimum', 0), constraints.get('maximum', 1), 0, 1],
        'boolean': [True, False], 'null': [None],
        'array': [[], ['fixture']], 'object': [{}, {'fixture': True}],
    }[spec['type']]
    values = []
    for value in candidates:
        try:
            check_value(spec, value, 'fixture')
        except ValueError:
            continue
        if not any(type(value) is type(old) and value == old for old in values):
            values.append(copy.deepcopy(value))
    assert values, ('no fixture value satisfies declaration', spec)
    return values


def check(root, alias, service):
    original = ROOT/'model/templates'/alias/(service+'.properties.tpl')
    template = root/original.relative_to(ROOT)
    template_files = {root/p.relative_to(ROOT):p.read_bytes().decode('utf-8') for p in {original,*model_parts(original)}}
    write_fixture_files(template_files)
    definitions = t.parse_template(template)[0]
    # Cover each public input, resource kind, reference kind and identifier format with the fewest definitions.
    chosen, covered = [], set()
    for name,d in definitions.items():
        features = {('resource',d.values['desired.resource.'+r+'.resourceType']) for r in d.resources}
        features |= {('input',n) for n,s in d.parameters.items() if s.get('source') in (None, 'service') and not s.get('internal')}
        features |= {('reference',s['resourceType'],s.get('format')) for s in d.parameters.values() if s['type']=='reference'}
        if features-covered:
            chosen.append(name);covered |= features
    binding, human = {'instances':{}}, {'instances':{}}
    shared = {n:s for d in definitions.values() for n,s in d.parameters.items() if s.get('source')=='service'}
    if shared:
        human['parameters']={n:fixture_values(s)[0] for n,s in shared.items()}
    targets={}
    counter=0
    for name in chosen:
        d=definitions[name];resources={}
        alternatives={selector for _,_,selector in d.choices}
        selectors=set(d.optional.values()) | set(d.optional_json.values()) | alternatives
        for local in d.resources:
            counter+=1;resources[local]=f'{counter*17:03d}'
        counts={};rows={}
        for local,owner in d.rows.items():
            counts[owner]=counts.get(owner,0)+1;rows[local]=resources[owner]+'-'+f'{counts[owner]:03d}'
        internal={n:((n not in alternatives) if s['type']=='boolean' else
                     '900' if s['type']=='reference' else
                     '0'*64 if n.startswith('ArtifactHash_') else 'fixture note' if n.startswith('Note_') else
                     'cfn-stack-fixture-Resource'+next(iter(resources.values())) if n.endswith('_cfn_logicalId') else
                     'fixture-'+service+'-'+n+'-'+next(iter(resources.values())))
                  for n,s in d.parameters.items() if s.get('internal')}
        public={n:((n not in alternatives) if n in selectors else
                   '900' if s['type']=='reference' else
                   fixture_values(s)[0])
                for n,s in d.parameters.items() if not s.get('source') and not s.get('internal')}
        d=t.bound_definition(d,{**internal,**public})
        internal={n:v for n,v in internal.items() if n in d.parameters}
        public={n:v for n,v in public.items() if n in d.parameters}
        resources={n:v for n,v in resources.items() if n in d.resources}
        rows={n:v for n,v in rows.items() if n in d.rows}
        binding['instances'][name]={'definition':name,'resources':resources,'rows':rows,'parameters':internal,'labels':{}}
        if public:human['instances'][name]={'parameters':public}
        for n,s in d.parameters.items():
            if s['type']=='reference':
                assert s.get('service')
                key=(s['service'],s['target'] if s.get('source')=='template' else internal[n] if s.get('internal') else public[n]);assert key not in targets or targets[key]==s['resourceType']
                targets[key]=s['resourceType']
                if not s.get('source') and not s.get('internal'):targets[s['service'],'901']=s['resourceType']
    name_properties={'KMS.Alias':'AliasName','IAM.Role':'RoleName','Logs.LogGroup':'LogGroupName',
                     'Lambda.Function':'FunctionName','S3.Bucket':'BucketName','EC2.SecurityGroup':'GroupName'}
    producer_values={}
    for (producer,rid),rtype in targets.items():
        values=producer_values.setdefault(producer,{})
        values['desired.resource.'+rid+'.resourceType']=rtype
        values['desired.resource.'+rid+'.anchor']='fixture-'+producer+'-'+rid
        if rtype!='KMS.Key':
            prop=name_properties.get(rtype,'Name')
            values['desired.row.'+rid+'-001.property']=rtype+'.'+prop
            values['desired.row.'+rid+'-001.value']='`'+('alias/' if rtype=='KMS.Alias' else '')+'fixture-'+producer+'-'+rid+'`'
        if rtype=='KMS.Alias':
            values.update({'desired.resource.fixture-key.resourceType':'KMS.Key',
                           'desired.resource.fixture-key.anchor':'fixture-kms-key',
                           'desired.row.fixture-key-001.property':'KMS.Key.KeyId',
                           'desired.row.fixture-key-001.value':'[fixture-key](#fixture-kms-key)',
                           'observed.row.fixture-key-001.property':'KMS.Key.KeyId',
                           'observed.row.fixture-key-001.value':'`fixture-key-id`',
                           'desired.resource.'+rid+'.parentProperty':'KMS.Alias.TargetKeyId',
                           'desired.resource.'+rid+'.parentReference':'[fixture-key](#fixture-kms-key)',
                           'desired.row.'+rid+'-002.property':'KMS.Alias.TargetKeyId',
                           'desired.row.'+rid+'-002.value':'[fixture-key](#fixture-kms-key)'})
        if rtype in {'EC2.VPC','KMS.Key'}:
            prop='VpcId' if rtype=='EC2.VPC' else 'KeyId'
            values['desired.row.'+rid+'-002.property']=rtype+'.'+prop
            values['desired.row.'+rid+'-002.value']='[fixture-'+producer+'-'+rid+'](#fixture-'+producer+'-'+rid+')'
            values['observed.row.'+rid+'-002.property']=rtype+'.'+prop
            values['observed.row.'+rid+'-002.value']='`'+('vpc-fixture-'+rid if rtype=='EC2.VPC' else 'key-fixture01')+'`'
    # Identifier validation reads the existing immutable catalog, never an invented output property.
    if any(s.get('format')=='identifier' for n in chosen for s in definitions[n].parameters.values()):
        catalog=ROOT/'framework/materials/aws/EC2_VPC.properties'
        write_fixture_files({root/catalog.relative_to(ROOT):(catalog).read_text(encoding="utf-8")})
    for environment in ('preview','future'):
        write_fixture_files({root/'model'/environment/alias/(producer+'.properties'):''.join(k+'='+v+'\n' for k,v in values.items()) for producer,values in producer_values.items()})
    empty={'version':1,'values':{}}
    serialized=parameter_text(human,definitions,binding)
    assert 'definition:' not in serialized and yaml_read(serialized) == human
    paths={}
    for environment in ('preview','future'):
        path=root/'model'/environment/alias/(service+'.properties');directory=root/'model/parameters'/environment/alias/service
        values=t.expand(template,human,empty,binding,environment)[0];paths[environment]=(path,directory,values)
        write_fixture_files({

                    directory/'parameters.yaml':serialized,directory/'bindings.json':t.json_text(binding),directory/'observed.json':t.json_text(empty)})
    path,directory,values=paths['preview'];other,_,other_values=paths['future']
    (root/'tasks').mkdir();(root/'tasks/active.md').write_text('## Task contract\n- Task type: `migration`\n## Allowed paths\n- `'+(directory/'parameters.yaml').relative_to(root).as_posix()+'`\n',encoding='utf-8')
    assert load_model(path).values==values
    provenance=t.load_expansion(path).provenance
    assert all(v['description'] and v['modelKey'] for p in provenance.values() for v in p.get('inputs',{}).values())
    assert t.affected(root,[template.relative_to(root)])=={(env,alias,service) for env in paths}
    assert t.affected(root,[(directory/'bindings.json').relative_to(root)])=={('preview',alias,service)}
    before=t.design_source_digest(path)
    for _ in range(2):
        t.save_parameters(path,yaml_read(serialized))
        assert (directory/'parameters.yaml').read_text()==serialized and load_model(path).values==values
    cases=[(None,field) for field in shared]+[(name,field) for name,item in human['instances'].items() for field in item['parameters']]
    for name,field in cases:
        changed=copy.deepcopy(human)
        inputs=changed['parameters'] if name is None else changed['instances'][name]['parameters']
        definition=definitions[binding['instances'][name]['definition']] if name is not None else None
        spec=shared[field] if definition is None else definition.parameters[field]
        selectors=(set(definition.optional.values())|set(definition.optional_json.values())|
                   {selector for _,_,selector in definition.choices}) if definition is not None else set()
        if field in selectors:
            # Shape edits also require matching maps; model_templates.checks.py covers them together.
            bad=copy.deepcopy(human);bad['instances'][name]['parameters'][field]='false'
            rejected(lambda:t.save_parameters(path,bad))
            bad=copy.deepcopy(human);del bad['instances'][name]['parameters'][field]
            rejected(lambda:t.save_parameters(path,bad))
            continue
        alternatives=['901'] if spec['type']=='reference' else fixture_values(spec)
        for replacement in alternatives:
            if type(replacement) is type(inputs[field]) and replacement == inputs[field]:
                continue
            inputs[field]=replacement
            t.save_parameters(path,changed)
            after=load_model(path).values
            expected={k for k,source in provenance.items() if field in source.get('inputs',{}) and (name is None or source['instance']==name)}
            assert {k for k in values if values[k]!=after[k]}==expected
            assert load_model(other).values==other_values and t.design_source_digest(path)!=before
            resource_changes={k for k in values if k.startswith('desired.resource.') and values[k]!=after[k]}
            assert resource_changes==({k for k in expected if k.endswith('.resourceMode')} if field=='ResourceMode' else set())
            if field=='Suffix':
                trail=[row['value'] for _,row in entries(after,'desired.row.') if row['property']=='CloudTrail.Trail.TrailName']
                assert trail==['`ctrail-venusinf-preview`']
            t.save_parameters(path,human)
            break
        for invalid in (None, {}, True, 'INVALID'):
            try:
                check_value(spec, invalid, field)
            except ValueError:
                pass
            else:
                continue
            bad=copy.deepcopy(human)
            (bad['parameters'] if name is None else bad['instances'][name]['parameters'])[field]=invalid
            rejected(lambda:t.save_parameters(path,bad))
        bad=copy.deepcopy(human)
        (bad['parameters'] if name is None else bad['instances'][name]['parameters']).pop(field)
        if spec['required'] or 'default' not in spec:
            rejected(lambda:t.save_parameters(path,bad))
        else:
            t.save_parameters(path,bad)
            assert load_model(other).values==other_values
            t.save_parameters(path,human)
    # ID stability is independent of ordering and explicit instance rename.
    reordered=copy.deepcopy(binding);reordered['instances']=dict(reversed(list(binding['instances'].items())))
    assert t.expand(template,human,empty,reordered,'preview')[0]==values
    first=next(iter(binding['instances']));renamed=copy.deepcopy(binding);renamed['instances']['renamed']=renamed['instances'].pop(first)
    new_human=copy.deepcopy(human)
    if first in new_human['instances']:new_human['instances']['renamed']=new_human['instances'].pop(first)
    assert t.expand(template,new_human,empty,renamed,'preview')[0]==values
    bad=copy.deepcopy(binding);bad['instances'][first]['parameters']['Unknown']='bad';rejected(lambda:t.expand(template,human,empty,bad,'preview'))
    bad=copy.deepcopy(binding);bad['instances'][first].pop('definition');rejected(lambda:t.expand(template,human,empty,bad,'preview'))
    bad=copy.deepcopy(binding);b=next(iter(bad['instances'].values()));b['resources']=dict.fromkeys(b['resources'],'999');rejected(lambda:t.expand(template,human,empty,bad,'preview'))
    for field in ('unknown','Value1','definition'):
        bad=copy.deepcopy(human);bad[field]='obsolete';rejected(lambda:t.save_parameters(path,bad))
    rejected(lambda:yaml_read(serialized+'instances: {}\n'))
    bp=directory/'bindings.json';raw=bp.read_text();bp.write_text(raw+'\n');assert t.design_source_digest(path)!=before;bp.write_text(raw)
    # A template edit reaches both fixture consumers; no environment branch exists.
    d=definitions[chosen[0]];key=next(k for k in d.values if k.endswith('.comment'));part,line=d.locations[key]
    text=part.read_text();lines=text.splitlines(keepends=True);lines[line-1]=lines[line-1].replace('.comment=','.comment=fixture update ',1);part.write_text(''.join(lines))
    assert load_model(path).values!=values and load_model(other).values!=other_values
    part.write_text(text)
    if targets:
        producer,rid=next(iter(targets));pp=root/'model/preview'/alias/(producer+'.properties');raw=read_model(pp)
        write_model(pp, raw+'# fixture producer change\n');assert t.design_source_digest(path)!=before
        assert ('preview',alias,service) in t.affected(root,[pp.relative_to(root)])
        write_model(pp, raw.replace('resourceType='+targets[(producer,rid)],'resourceType=Fixture.Wrong',1));rejected(lambda:load_model(path))
        t.source_paths(pp)[2].joinpath('parameters.yaml').unlink();rejected(lambda:load_model(path));write_model(pp, raw)
    for key,value in values.items():
        if key.endswith('.document'):
            document=t.json_read(value);assert isinstance(document,dict) and isinstance(document['Statement'],list)
        if key.endswith('.property') and value=='EC2.VPCEndpoint.PrivateDnsEnabled':
            assert values[key.removesuffix('.property')+'.value'] in {'`true`','`false`'}
    print(alias,service,'PASS (strict inputs; fragments/types; refs/Policy; identity; hash/impact/trace; repeat save)')


def check_declared_inputs():
    from unittest.mock import patch
    specs = {
        'Value1': {'type':'integer', 'constraints':{'minimum':2.5, 'maximum':4.5}},
        'ValueFlag': {'type':'boolean'},
        'ValueChoice': {'type':'string', 'constraints':{'enum':['first', 'second']}},
        'ValueDefault': {'type':'string', 'required':False, 'default':'default-value'},
        'ValueFixed': {'type':'string', 'constraints':{'enum':['only']}},
        'ValueObject': {'type':'object'}, 'ValueArray': {'type':'array'},
        'ValueNull': {'type':'null'}, 'ValueNumber': {'type':'number'},
        'ValueServiceOnly': {'type':'string', 'constraints':{'enum':['one','two']}},
    }
    with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output:
        source = Path(source)
        inputs = {n:{'description':'宣言された入力', 'required':True, **s} for n,s in specs.items()}
        text = ['# model-template: 1']
        text += ['# input: '+n+' '+t.json_text(s) for n,s in inputs.items()]
        text += ['# definition: Trail', '# resource: trail', '# row: name trail',
                 '# parameter: ValueLocal '+t.json_text({'type':'integer', 'description':'optional入力', 'required':False, 'default':3}),
                 '# parameter: ValueLocalFlag '+t.json_text({'type':'boolean', 'description':'制約付き入力', 'required':True, 'constraints':{'enum':[False]}}),
                 'desired.resource.trail.resourceType=CloudTrail.Trail',
                 'desired.resource.trail.anchor=cloudtrail-fixture',
                 'desired.row.name.property=CloudTrail.Trail.TrailName',
                 'desired.row.name.value=`fixture`', 'desired.row.name.comment=名前',
                 'desired.note.inputs.document='+t.json_text({'Statement':[], 'local':'<<ValueLocal>>', 'flag':'<<ValueLocalFlag>>', **{n:'<<'+n+'>>' for n in inputs if n != 'ValueServiceOnly'}}),
                 '# end-definition', '# definition: SharedOnly',
                 'desired.note.shared.document={"Statement":[],"value":"<<ValueServiceOnly>>"}', '# end-definition']
        write_fixture_files({source/'model/templates/team/cloudtrail.properties.tpl':'\n'.join(text)+'\n'})
        with patch(__name__+'.ROOT', source):
            check(Path(output), 'team', 'cloudtrail')
    print('Declared group-05 inputs: PASS (new names; types; enum/range/default; optional removal)')


if __name__=='__main__':
    units=sorted({(p.parts[-3],p.parent.name) for p in (ROOT/'model/parameters').glob('*/*/*/parameters.yaml') if p.parent.name in SERVICES})
    for alias,service in units:
        with tempfile.TemporaryDirectory() as directory:
            check(Path(directory).resolve(),alias,service)
    check_declared_inputs()
