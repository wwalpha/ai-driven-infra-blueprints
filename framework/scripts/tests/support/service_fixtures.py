"""Small authored service authorities for offline regression, never consumer copies."""
from pathlib import Path
import json
from model_templates import json_text
from support.model_sources import write_fixture_files, write_model


def input_spec(kind='string', **fields):
    return {'type': kind, 'description': '検証用入力', 'required': True, **fields}


def service(root, name, definitions, *, shared=None, environments=('dev', 'stg'), alias='team'):
    """Each definition supplies one resource and explicit input/row expectations."""
    shared = shared or {}
    lines = ['# model-template: 1']
    for key, (value, spec) in shared.items():
        lines.append('# input: '+key+' '+json_text(spec))
    bindings, human = {'instances': {}}, {'instances': {}}
    for number, (identity, kind, rows, inputs) in enumerate(definitions, 1):
        rid = f'{number:03d}'
        lines += ['# definition: '+identity, '# resource: resource']
        literal_inputs = {key for key in inputs if any(row[1]=='`<<'+key+'>>`' for row in rows)}
        for key, (value, spec) in inputs.items():
            spec = {**spec, 'format':'literal'} if key in literal_inputs else spec
            lines.append('# parameter: '+key+' '+json_text(spec))
        lines += [f'desired.resource.resource.resourceType={kind}',
                  f'desired.resource.resource.anchor={name}-{identity}']
        row_bindings = {}
        for index, row in enumerate(rows, 1):
            prop, value, *document = row
            if value.startswith('`<<') and value.endswith('>>`') and value[3:-3] in literal_inputs:
                value = value[1:-1]
            local = 'row'+str(index)
            row_bindings[local] = rid+f'-{index:03d}'
            lines += ['# row: '+local+' resource', f'desired.row.{local}.property={kind}.{prop}',
                      f'desired.row.{local}.value={value}', f'desired.row.{local}.comment='+('BranchName: ブランチ' if prop.endswith('.Configuration') else '検証用設定')]
            if document:
                lines.append(f'desired.row.{local}.document='+json_text(document[0]))
        unused = {key:'<<'+key+'>>' for key in inputs if not any('<<'+key+'>>' in line for line in lines)}
        if unused:
            lines.append('desired.note.'+identity+'.document='+json_text({'Statement':[], **unused}))
        lines += ['# end-definition']
        bindings['instances'][identity] = {'definition': identity, 'resources': {'resource': rid},
                                           'rows': row_bindings, 'parameters': {}}
        if inputs:
            human['instances'][identity] = {'parameters': {key: value for key, (value, _) in inputs.items()}}
    if shared:
        human['parameters'] = {key: value for key, (value, _) in shared.items()}
    template = root/'model/templates'/alias/(name+'.properties.tpl')
    output = {template: '\n'.join(lines)+'\n'}
    for env in environments:
        directory = root/'model/parameters'/env/alias/name
        output.update({directory/'parameters.yaml': json_text(human)+'\n',
                       directory/'bindings.json': json_text(bindings)+'\n'})
    write_fixture_files(output)
    return template


def build_typed_services(root):
    integer, boolean, string = input_spec('integer'), input_spec('boolean'), input_spec()
    service(root, 'kms', [('log-key', 'KMS.Key', [('Enabled','`<<Enabled>>`'), ('PendingWindowInDays','`<<PendingWindowInDays>>`')],
        {'Enabled':(True,boolean), 'PendingWindowInDays':(7,integer)}),
        ('alias', 'KMS.Alias', [('AliasName','`alias/log<<AliasSuffix>>`')], {})], shared={'AliasSuffix':('-one',string)})
    service(root, 'security-group', [('group','EC2.SecurityGroup', [('SecurityGroupIngress[].FromPort','`<<RuleFromPort>>`')], {'RuleFromPort':(443,integer)})])
    service(root, 'route53', [(identity,'Route53.RecordSet', [('Name','`<<SnowflakeAccountLocator>>.'+identity+'`'), ('TTL','`<<TtlSeconds>>`')], {'TtlSeconds':(60,integer)}) for identity in ('record_a','record_b')], shared={'SnowflakeAccountLocator':('fixture',string)})
    template=root/'model/templates/team/route53.properties.tpl'
    template.write_text(template.read_text().replace('anchor=route53-record_a','anchor=route53-record_a-<<SnowflakeAccountLocator>>').replace('anchor=route53-record_b','anchor=route53-record_b-<<SnowflakeAccountLocator>>'),encoding='utf-8')
    trust = {'Statement': {'Effect':'Allow','Principal':{'AWS':'<<TrustedAccountId>>'},'Action':'sts:AssumeRole'}}
    service(root, 'iam', [('service','IAM.Role',[('RoleName','`fixture-role`'),('AssumeRolePolicyDocument','[trust](iam/trust.json)',trust)],
                         {'UseStgIdentityCenterTrust':(False,boolean)})], shared={'TrustedAccountId':('210987654321',string)})
    service(root, 's3', [('bucket','S3.Bucket',[('BucketName','`fixture`'),('LifecycleConfiguration.Rules[].ExpirationInDays','`<<ExpirationDays>>`')], {'ExpirationDays':(30,integer)})])
    service(root, 'cloudtrail', [('trail','CloudTrail.Trail',[('TrailName','`fixture`')],{})])
    arguments = {'--job-language':'python'}
    service(root, 'glue', [
        ('job','Glue.Job',[('Name','`fixture-job`'),('Timeout','`30`'),
            ('SecurityConfiguration','[glsc<<Suffix>>](#glue-glsc<<Suffix>>)'),('DefaultArguments','`'+json_text(arguments)+'`')],{}),
        ('security','Glue.SecurityConfiguration',[('Name','`glsc<<Suffix>>`')],{})],
        shared={'Suffix':('-one',input_spec(constraints={'pattern':'^-[a-z0-9-]+$'}))})
    template=root/'model/templates/team/glue.properties.tpl'
    template.write_text(template.read_text().replace('anchor=glue-security','anchor=glue-glsc<<Suffix>>'),encoding='utf-8')
    producers = ('lambda','glue','iam','codebuild','mwaa','cloudtrail')
    log_rows = [('LogGroupName','`/aws/vpc/flow-logs`'),('RetentionInDays','`30`'),('DeletionProtectionEnabled','`false`')]
    # Name references deliberately cover each producer service's fixed identity.
    declarations = [('logs','Logs.LogGroup',log_rows,{})]
    template = service(root,'cloudwatch-logs',declarations)
    text = template.read_text(encoding='utf-8')
    for producer in producers:
        text = text.replace('# resource: resource', '# reference: Producer_'+producer.replace('-','_')+' '+json_text(
            {'service':producer,'resource':'001','resourceType':{'lambda':'Lambda.Function','glue':'Glue.Job','iam':'IAM.Role',
             'codebuild':'CodeBuild.Project','mwaa':'MWAA.Environment','cloudtrail':'CloudTrail.Trail'}[producer],'format':'name'})+'\n# resource: resource',1)
    text = text.replace('# end-definition','desired.note.producers.document='+json_text({producer:'<<Producer_'+producer.replace('-','_')+'>>' for producer in producers})+'\n# end-definition')
    template.write_text(text,encoding='utf-8')
    service(root,'lambda',[('function','Lambda.Function',[('FunctionName','`fixture`'),('Architectures','`["x86_64"]`'),('MemorySize','`<<MemorySize>>`')], {'MemorySize':(128,integer)}),
                           ('permission','Lambda.Permission',[('Principal','`events.amazonaws.com`')],{})])
    retry=[('RetryPolicy.MaximumEventAgeInSeconds','`3600`'),('RetryPolicy.MaximumRetryAttempts','`3`')]
    service(root,'eventbridge',[
        ('rule','Events.Rule',[('Name','`fixture-rule`'),('State','`ENABLED`'),('EventPattern','[pattern](eventbridge/pattern.json)',
            {'detail':{'eventName':['GetObject'],'userIdentity':{'userName':['fixture']},'requestParameters':{'bucketName':['fixture']}}}),
            ('Targets[].RetryPolicy.MaximumEventAgeInSeconds','`3600`'),('Targets[].RetryPolicy.MaximumRetryAttempts','`3`')],{'Enabled':(True,boolean)}),
        ('schedule','Scheduler.Schedule',[('Name','`fixture-schedule`'),('ScheduleExpression','`cron(0 0 * * ? *)`'),('ScheduleExpressionTimezone','`Asia/Tokyo`'),
            *[('Target.'+p,v) for p,v in retry]],{})])
    service(root,'codepipeline',[('pipeline','CodePipeline.Pipeline',[('Name','`fixture`'),('Stages[].Name','`source`'),
        ('Stages[].Actions[].Name','`source`'),('Stages[].Actions[].Configuration','`{"BranchName":"<<SourceBranch>>"}`')], {'SourceBranch':('main',string)})])
    for name,kind in [('config','Config.ConfigurationRecorder'),('data-firehose','KinesisFirehose.DeliveryStream'),('guardduty','GuardDuty.Detector'),
                      ('macie','Macie.Session'),('quicksight','QuickSight.DataSource'),('codebuild','CodeBuild.Project'),('ec2','EC2.Instance'),
                      ('mwaa','MWAA.Environment'),('transit-gateway','EC2.TransitGateway')]:
        service(root,name,[('fixture',kind,[('Name','`<<FixtureName>>`')], {'FixtureName':('fixture',string)})])
    service(root,'cloudformation-stacks',[('stack','CloudFormation.Stack',[],{})], shared={'MaxConcurrentStacks':(2,input_spec('integer',constraints={'minimum':1}))})
    template=root/'model/templates/team/cloudformation-stacks.properties.tpl'
    text=template.read_text().replace('# end-definition','desired.deployment.maxConcurrentStacks=<<MaxConcurrentStacks>>\ndesired.stack.fixture.name=fixture\ndesired.stack.fixture.template=fixture.yaml\ndesired.stack.fixture.parameters=fixture.json\ndesired.stack.fixture.deployOrder=1\n# end-definition')
    text = '\n'.join(line for line in text.splitlines() if not line.startswith(('# resource:', 'desired.resource.'))) + '\n'
    template.write_text(text,encoding='utf-8')
    for env in ('dev','stg'):
        bindings=root/'model/parameters'/env/'team/cloudformation-stacks/bindings.json'
        value=json.loads(bindings.read_text());value['instances']['stack']['resources']={};value['stacks']={'fixture':'fixture'};bindings.write_text(json_text(value),encoding='utf-8')


def build_input_templates(root):
    string, boolean = input_spec(), input_spec('boolean')
    service(root,'codecommit',[('repository','CodeCommit.Repository',[('RepositoryName','`fixture`'),('RepositoryDescription','`<<Description>>`')], {'Description':('fixture',string)})])
    service(root,'security-hub',[('hub','SecurityHub.Hub',[('ControlFindingGenerator','`SECURITY_CONTROL`'),('EnableDefaultStandards','`true`')],{})])
    service(root,'athena',[('component_workgroup','Athena.WorkGroup',[('Name','`fixture`'),('WorkGroupConfiguration.ResultConfiguration.OutputLocation','<<ResultBucket>>')],{})])
    template=root/'model/templates/team/athena.properties.tpl'
    template.write_text(template.read_text().replace('# resource: resource','# reference: ResultBucket '+json_text({'service':'s3','resource':'001','resourceType':'S3.Bucket','format':'name'})+'\n# resource: resource'),encoding='utf-8')
    service(root,'sqs',[('component_queue','SQS.Queue',[('QueueName','`fixture<<Suffix>>`')],{}),
        ('component_policy','SQS.QueuePolicy',[('Queues','[017](#fixture-sqs-017)'),('PolicyDocument','[policy](sqs/policy.json)', {'Statement':[{'Effect':'Allow','Action':'sqs:SendMessage',
        'Resource':{'Fn::GetAtt':['HulftRetrievalDetectDlq','Arn']},'Condition':{'StringEquals':{'aws:SourceAccount':'<<SourceAccountId>>'}}}]})],{})],shared={'Suffix':('-one',input_spec(constraints={'pattern':'^-[a-z0-9-]+$'}))})
    template=root/'model/templates/team/sqs.properties.tpl'
    template.write_text(template.read_text().replace('# resource: resource','# internal: Anchor string\n# resource: resource').replace('desired.resource.resource.anchor=sqs-component_queue','desired.resource.resource.anchor=<<Anchor>>').replace('desired.resource.resource.anchor=sqs-component_policy','desired.resource.resource.anchor=<<Anchor>>').replace('# model-template: 1','# model-template: 1\n# input: SourceAccountId {"type": "string", "description": "実行account", "required": true, "source": "consumer.executionAccountId"}'),encoding='utf-8')
    service(root,'datazone',[(f'group_{n}','DataZone.Domain',[('Name',f'`fixture-{n}`')],{}) for n in range(1,7)])


def typed_services(root):
    from support.it_workspace import populate
    populate("typed_services", root)


def input_templates(root):
    from support.it_workspace import populate
    populate("input_templates", root)
