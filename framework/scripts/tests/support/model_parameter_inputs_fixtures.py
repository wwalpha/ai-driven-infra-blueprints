"""Offline YAML responsibility, projection, dependency and rejection regression."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model_files import read_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy

import io

import json

from support.model_sources import write_model, write_fixture_files

import shutil

import tempfile

from contextlib import redirect_stdout

from unittest.mock import patch

import model_templates as t

from model_parameter_inputs import yaml_read, parameter_text, schema

from model_files import load_model

from support.model_sources import write_fixture_files as save_files

import sync_runtime

ROOT = Path(__file__).resolve().parents[4]

from support.it_workspace import copy_framework

def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError, KeyError, TypeError) as error:
        assert phrase in str(error), (phrase, str(error))
    else:
        raise AssertionError('invalid input accepted: '+phrase)

def declaration(name, kind='string', **fields):
    return '# parameter: '+name+' '+t.json_text({'type':kind,'description':'入力 '+name,'required':True,**fields})

def fixture(root):
    copy_framework(root / 'framework')
    environments = ['preview', 'prod']
    (root/'project.json').write_text(json.dumps({'projectName':'app','targets':[
        {'environment':env,'alias':alias,'awsAccountId':account,'awsRegion':'ap-northeast-1','iacEngine':'cloudformation'}
        for env in environments for alias,account in [('other','210987654321'),('team','123456789012')]]})+'\n', encoding='utf-8')
    (root/'tasks').mkdir()
    (root/'tasks/active.md').write_text('## Task contract\n- Task type: `migration`\n## Validation scope\n'+
        ''.join('- `'+env+'/team/'+service+'`\n' for env in environments for service in ('vpc','iam'))+
        '## Allowed paths\n- `model/**`\n- `model/parameters/**`\n- `model/templates/**`\n- `docs/designs/**`\n', encoding='utf-8')
    template = root/'model/templates/team/vpc.properties.tpl'
    lines = ['# model-template: 1']
    for kind in ['VPC', 'Subnet']:
        lines += ['# definition: '+kind, declaration('Name',format='literal'),declaration('CidrBlock',format='literal',constraints={'cidr':'ipv4'}),
                  '# internal: Anchor string','# internal: LogicalId string','# internal: Comment string',
                  '# resource: resource','# row: name resource','# row: cidr resource','# row: id resource',
                  '# row: vpc resource' if kind=='Subnet' else '# row: dns resource',
                  'desired.resource.resource.resourceType=EC2.'+kind,'desired.resource.resource.resourceMode=IMPORT',
                  'display.resource.resource.comment=既存説明','desired.resource.resource.anchor=<<Anchor>>','desired.resource.resource.logicalId=<<LogicalId>>',
                  'desired.row.name.property=EC2.'+kind+'.Name','desired.row.name.value=<<Name>>','desired.row.name.comment=名前説明',
                  'desired.row.cidr.property=EC2.'+kind+'.CidrBlock','desired.row.cidr.value=<<CidrBlock>>','desired.row.cidr.comment=<<Comment>>',
                  'desired.row.id.property=EC2.'+kind+'.'+('VpcId' if kind=='VPC' else 'SubnetId'),
                  'desired.row.id.value=[<<LogicalId>>](#<<Anchor_resource>>)','desired.row.id.comment=ID説明']
        if kind=='Subnet':
            lines += [declaration('Vpc','reference',resourceType='EC2.VPC'),'desired.row.vpc.property=EC2.Subnet.VpcId',
                      'desired.row.vpc.value=<<Vpc>>','desired.row.vpc.comment=所属VPC説明']
        else:
            lines += [declaration('EnableDnsSupport','boolean',format='literal'),'desired.row.dns.property=EC2.VPC.EnableDnsSupport',
                      'desired.row.dns.value=<<EnableDnsSupport>>','desired.row.dns.comment=DNS説明']
        lines += ['# end-definition']
    lines += ['# definition: Service','desired.service.vpc.serviceId=vpc','desired.service.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet',
              'display.service.title=# Amazon VPC 詳細設計','# end-definition']
    original='\n'.join(lines)+'\n';write_fixture_files({template:original})
    records={}
    for env in environments:
        suffix='' if env=='prod' else '-one'
        human={'instances':{}};bindings={'instances':{}};observed={'version':1,'values':{}}
        for rid,kind,identity in [('017','VPC','main-vpc'),('042','Subnet','private-a'),('083','Subnet','private-c')]:
            name=('vpc' if kind=='VPC' else 'sbnt')+'-app-'+env+suffix+('' if kind=='VPC' else '-'+identity[-1])
            public={'Name':name,'CidrBlock':'10.10.0.0/23' if kind=='VPC' else '10.10.0.0/25'}
            public.update({'EnableDnsSupport':True} if kind=='VPC' else {'Vpc':'main-vpc'})
            rows={key:rid+'-'+str(n).zfill(3) for n,key in enumerate(['name','cidr','id','vpc' if kind=='Subnet' else 'dns'],1)}
            human['instances'][identity]={'parameters':public}
            bindings['instances'][identity]={'definition':kind,'resources':{'resource':rid},'rows':rows,
                'parameters':{'Anchor':'vpc-'+name,'LogicalId':'existing-'+identity,'Comment':'環境注記 '+env},'labels':{'Vpc':'existing-main-vpc'} if kind=='Subnet' else {}}
            observed['values'].update({'observed.row.'+rows['id']+'.property':'EC2.'+kind+'.'+('VpcId' if kind=='VPC' else 'SubnetId'),
                                      'observed.row.'+rows['id']+'.value':'`'+('vpc-' if kind=='VPC' else 'subnet-')+rid+'0'*14+'`',
                                      'observed.row.'+rows['id']+'.comment':'ID説明'})
            if kind=='Subnet':
                observed['values'].update({'observed.row.'+rows['vpc']+'.property':'EC2.Subnet.VpcId',
                                          'observed.row.'+rows['vpc']+'.value':'vpc-017'+'0'*14,'observed.row.'+rows['vpc']+'.comment':'所属VPC説明'})
        bindings['instances']['service']={'definition':'Service','resources':{},'rows':{},'parameters':{},'labels':{}}
        observed['values'] = {key:value for key,value in observed['values'].items() if key.endswith('.value')}
        values,_,_=t.expand(template,human,observed,bindings,env)
        directory=root/'model/parameters'/env/'team/vpc'
        write_fixture_files({root/'model'/env/'team/vpc.properties':'# Generated Model\n'+''.join(k+'='+v+'\n' for k,v in values.items()),
                    directory/'parameters.yaml':parameter_text(human,t.parse_template(template)[0],bindings),directory/'bindings.json':t.json_text(bindings),
                    directory/'observed.json':t.json_text(observed)})
        records[env]=(human,bindings,suffix)
    return template,environments,records,original

import pytest

from support.pytest_cli import run

@pytest.fixture
def root(tmp_path):
    return tmp_path.resolve()


__all__ = ['Path', 'ROOT', 'copy', 'declaration', 'fixture', 'io', 'json', 'load_model', 'parameter_text', 'patch', 'pytest', 'read_model', 'redirect_stdout', 'rejected', 'root', 'run', 'save_files', 'schema', 'shutil', 'sync_runtime', 'sys', 't', 'tempfile', 'write_fixture_files', 'write_model', 'yaml_read']
