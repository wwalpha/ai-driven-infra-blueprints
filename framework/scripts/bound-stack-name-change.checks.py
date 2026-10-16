#!/usr/bin/env python3
"""Offline stack name edits preserve explicitly bound placement, never rename AWS stacks."""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import io
import shutil
import tempfile
from contextlib import redirect_stdout
from test_support.model_sources import write_model, write_fixture_files
from pathlib import Path

import model_templates as t
from model_core import entries, stack_model
from model_files import load_model
from model_parameter_inputs import parameter_text
from model_references import bound_stack_names
from model_design import markdown_for
from cloudformation_observed import validate_mapping_targets, mappings, destroy_plan
from test_support.model_sources import write_fixture_files as save_files
import sync_runtime
from test_support.validator import load

INPUTS = load('model_parameter_inputs.checks')
MODELS = load('model_design.checks')


def check(root):
    shutil.copytree(Path(__file__).resolve().parents[2] / 'framework', root / 'framework')
    write_fixture_files({root/'project.json':t.json_text({'projectName':'app', 'targets':[
        {'environment':'preview','alias':alias,'awsAccountId':account,
         'awsRegion':'ap-northeast-1','iacEngine':'cloudformation'}
        for alias,account in [('other','210987654321'),('team','123456789012')]]})+'\n',
        root/'tasks/active.md':'- Task type: `migration`\n## Validation scope\n'
        '- `preview/team/vpc`\n- `preview/team/cloudformation-stacks`\n## Allowed paths\n'
        '- `model/**`\n- `model/templates/**`\n- `model/parameters/**`\n- `docs/designs/**`\n'})
    template=root/'model/templates/team/cloudformation-stacks.properties.tpl'
    directory=root/'model/parameters/preview/team/cloudformation-stacks'
    path=root/'model/preview/team/cloudformation-stacks.properties'
    lines=['# model-template: 1', '# input: Suffix '+t.json_text({
        'type':'string','description':'配置のsuffix','required':True,'constraints':{'pattern':'[A-Za-z0-9-]*'}}),
        '# input: Environment '+t.json_text({'type':'string','description':'consumer環境','required':True,'source':'consumer.environment'})]
    bindings={'instances':{},'stacks':{}}
    human={'parameters':{'Suffix':'-original'},'instances':{}}
    for identity,purpose,definition in [('017','network','Network'),('083','empty','Empty')]:
        name='cfn-stack-app-preview-'+purpose+'-original'
        bindings['stacks'][identity]=name
        bindings['instances'][purpose]={'definition':definition,'resources':{},'rows':{},'parameters':{},'labels':{}}
        lines += ['# definition: '+definition,
                  'desired.stack.'+identity+'.name=cfn-stack-app-<<Environment>>-'+purpose+'<<Suffix>>',
                  'desired.stack.'+identity+'.template='+purpose+'.yaml',
                  'desired.stack.'+identity+'.parameters='+purpose+'.json',
                  'desired.stack.'+identity+'.deployOrder=10',
                  'display.stack.'+identity+'.comment=配置注記 '+purpose]
        if identity=='017':
            lines += ['display.service.title=# CloudFormation Stacks 詳細設計','desired.deployment.maxConcurrentStacks=2']
        lines += ['# end-definition']
    observed={'version':1,'values':{}}
    write_fixture_files({template:'\n'.join(lines)+'\n'})
    values=t.expand(template,human,observed,bindings,'preview')[0]
    write_fixture_files({path:MODELS.text(values), directory/'parameters.yaml':parameter_text(human,t.parse_template(template)[0],bindings),
        directory/'bindings.json':t.json_text(bindings), directory/'observed.json':t.json_text(observed)})
    fixed=bindings['stacks']['017']
    vpc=MODELS.model('vpc','EC2.VPC','vpc-app-preview-main',[
        ('Name','`vpc-app-preview-main`','名前'),('VpcId','[PrimaryVpc](#vpc-vpc-app-preview-main)','識別子'),
        ('CidrBlock','`10.10.0.0/24`','アドレス範囲')],'PrimaryVpc')
    vpc={key.replace('resource.001.','resource.027.').replace('row.001-','row.027-'):value for key,value in vpc.items()}
    vpc['desired.resource.027.cfn-logicalId']=fixed+'-PrimaryVpc'
    vpc.update({'observed.row.027-002.property':'EC2.VPC.VpcId','observed.row.027-002.value':'`vpc-'+'1'*17+'`',
                'observed.row.027-002.comment':'識別子'})
    vpc_path=path.with_name('vpc.properties')
    write_fixture_files({vpc_path:MODELS.text(vpc)})
    assert sync_runtime.sync(root,True,'preview','team',services=['vpc','cloudformation-stacks'])==0
    validate_mapping_targets(root,'preview','team',values)
    unit=dict(dict(stack_model(values)[1])['017'])
    document={'Resources':{'PrimaryVpc':{'Type':'AWS::EC2::VPC'}},
              'Outputs':{'VpcId':{'Value':{'Ref':'PrimaryVpc'}}}}
    assert mappings(root,'preview','team',{fixed:(document,{})},[unit])[1][fixed]['PrimaryVpc'][1]=='027'
    assert destroy_plan(root,'preview','team',[fixed],check_scope=False)['owners'][fixed][0]['resource']=='027'
    vpc_bytes={p:p.read_bytes() for p in load_model(vpc_path).files}
    for suffix in ('-changed','','-second'):
        human['parameters']['Suffix']=suffix
        t.save_parameters(path,human)
        current=load_model(path)
        assert current.values['desired.stack.017.name']=='cfn-stack-app-preview-network'+suffix
        assert bound_stack_names(path)[fixed]==current.values['desired.stack.017.name']
        assert directory/'bindings.json' in current.files
        validate_mapping_targets(root,'preview','team',current.values)
        assert sync_runtime.sync(root,True,'preview','team',services=['vpc','cloudformation-stacks'])==0
        assert load_model(vpc_path).values==vpc and all(p.read_bytes()==data for p,data in vpc_bytes.items())
        changed_unit=dict(dict(stack_model(current.values)[1])['017'])
        INPUTS.rejected(lambda:mappings(root,'preview','team',{changed_unit['name']:(document,{})},[changed_unit]),'explicit placement reconciliation')
        INPUTS.rejected(lambda:destroy_plan(root,'preview','team',[changed_unit['name']],False),'explicit placement reconciliation')
        assert destroy_plan(root,'preview','team',[fixed],False)['owners'][fixed][0]['resource']=='027'
        baseline={p:p.read_bytes() for p in (directory/'parameters.yaml',directory/'bindings.json',
                  root/'docs/designs/preview/team/cloudformation-stacks.md',root/'docs/designs/preview/team/vpc.md')}
        t.save_parameters(path,human)
        assert sync_runtime.sync(root,True,'preview','team',services=['vpc','cloudformation-stacks'])==0
        assert all(p.read_bytes()==data for p,data in baseline.items())
    raw=copy.deepcopy(human);raw['parameters']['Suffix']='-MiX--'
    assert t.expand(template,raw,observed,bindings,'preview')[0]['desired.stack.017.name']=='cfn-stack-app-preview-network-MiX--'
    original=(directory/'bindings.json').read_text()
    expected_bound=bound_stack_names(path)
    digest=t.design_source_digest(path)
    reordered=copy.deepcopy(bindings)
    reordered['stacks']=dict(reversed(list(reordered['stacks'].items())))
    reordered['instances']['renamed-instance']=reordered['instances'].pop('network')
    (directory/'bindings.json').write_text(t.json_text(reordered),encoding='utf-8')
    assert load_model(path).values==current.values and bound_stack_names(path)==expected_bound
    assert load_model(path).files[directory/'bindings.json']!=original
    assert t.design_source_digest(path)!=digest
    assert t.affected(root,{(directory/'bindings.json').relative_to(root)})=={('preview','team','cloudformation-stacks')}
    assert sync_runtime.sync(root,True,'preview','team',services=['vpc','cloudformation-stacks'])==0
    (directory/'bindings.json').write_text(original,encoding='utf-8')
    for field,value,phrase in [('999','cfn-stack-app-preview-unknown','exactly'),('017','bad_name','invalid fixed stack'),
                               ('083',fixed,'conflicting'),('017',None,'invalid fixed stack')]:
        bad=copy.deepcopy(bindings);bad['stacks'][field]=value
        INPUTS.rejected(lambda:t.expand(template,human,observed,bad,'preview'),phrase)
    bad=copy.deepcopy(bindings);del bad['stacks']['083']
    INPUTS.rejected(lambda:t.expand(template,human,observed,bad,'preview'),'exactly')
    bad=copy.deepcopy(bindings);bad['stacks']['017']=current.values['desired.stack.083.name']
    INPUTS.rejected(lambda:t.expand(template,human,observed,bad,'preview'),'conflicting')
    no_bindings={'instances':bindings['instances']}
    assert t.expand(template,human,observed,no_bindings,'preview')[0]==current.values
    (directory/'bindings.json').write_text(t.json_text(no_bindings),encoding='utf-8')
    INPUTS.rejected(lambda:markdown_for(root/'docs/designs/preview/team/vpc.md',vpc,root),'undeclared stack')
    INPUTS.rejected(lambda:validate_mapping_targets(root,'preview','team',current.values),'undeclared stack')
    (directory/'bindings.json').write_text(original,encoding='utf-8')
    invalid=dict(vpc);invalid['desired.resource.027.cfn-logicalId']='cfn-stack-app-preview-unknown-PrimaryVpc'
    INPUTS.rejected(lambda:markdown_for(root/'docs/designs/preview/team/vpc.md',invalid,root),'undeclared stack')
    invalid['desired.resource.027.cfn-logicalId']=current.values['desired.stack.017.name']+'-PrimaryVpc'
    INPUTS.rejected(lambda:markdown_for(root/'docs/designs/preview/team/vpc.md',invalid,root),'undeclared stack')
    other=template.with_name('vpc.properties.tpl');other.write_text(template.read_text(),encoding='utf-8')
    INPUTS.rejected(lambda:t.expand(other,human,observed,bindings,'preview'),'belong only')
    yaml=(directory/'parameters.yaml').read_text()
    (directory/'parameters.yaml').unlink()
    legacy={'version':1,'instances':[{'id':identity,**{k:v for k,v in item.items() if k!='labels'},
        'parameters':{'Suffix':human['parameters']['Suffix'],'Environment':'preview'}} for identity,item in bindings['instances'].items()]}
    (directory/'parameters.json').write_text(t.json_text(legacy),encoding='utf-8')
    INPUTS.rejected(lambda:load_model(path),'unsupported JSON')
    INPUTS.rejected(lambda:bound_stack_names(path),'unsupported JSON')
    (directory/'parameters.json').unlink()
    (directory/'parameters.yaml').write_text(yaml,encoding='utf-8')
    INPUTS.rejected(lambda:t.expand(template,human,observed,{'instances':bindings['instances'],'stacks':None},'preview'),'object')
    (directory/'bindings.json').unlink()
    INPUTS.rejected(lambda:bound_stack_names(path),'missing')
    print('Bound Stacks: PASS (Suffix/empty/raw, fixed IDs/placement/observed, generation/save reruns, reorder/rename, strict rejection and execution safety)')


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as directory:
        with redirect_stdout(io.StringIO()) as output:
            check(Path(directory).resolve())
        print(output.getvalue().strip().splitlines()[-1])
