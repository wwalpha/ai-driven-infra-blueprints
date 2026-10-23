"""Explicit service properties for offline checks; no template or input expansion."""
import json

import support.import_model_fixtures as import_fixtures
import support.it_workspace as workspace
from model.sources import json_text
from support.model_sources import write_model


def topology(root, environments):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'project.json').write_text(json_text({'targets': [
        {'environment': env, 'alias': 'team', 'awsAccountId': '111111111111',
         'awsExecutionAccountId': '123456789012' if env in ('dev', 'preview') else '210987654321',
         'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'} for env in environments]}) + '\n')


def authored_service(root, environment, service, resources, *, extra=None):
    values = import_fixtures.service_values(service, list(dict.fromkeys(kind for _, kind, _, _ in resources)))
    for rid, kind, anchor, rows in resources:
        values.update(import_fixtures.resource_values(rid, kind, anchor, 'CREATE', [(prop, raw) for prop, raw, *document in rows]))
        values[f'desired.resource.{rid}.cfn-logicalId'] = 'fixture-Resource' + rid
        for index, (_, _, *document) in enumerate(rows, 1):
            if document:
                values[f'desired.row.{rid}-{index:03d}.document'] = json_text(document[0])
    values['desired.service.identity.lastAllocated'] = json.dumps({kind: max(int(rid) for rid, candidate, _, _ in resources if candidate == kind) for _, kind, _, _ in resources})
    values.update(extra or {})
    path = root / 'model' / environment / 'team' / (service + '.properties')
    write_model(path, values)
    return path


def build_typed_services(root):
    topology(root, ('dev', 'stg'))
    for env in ('dev', 'stg'):
        services = {
            'kms': [('001', 'KMS.Key', 'kms-log-key', [('Enabled', '`true`'), ('PendingWindowInDays', '`7`')]),
                    ('002', 'KMS.Alias', 'kms-alias', [('AliasName', '`alias/log-one`')])],
            'security-group': [('001', 'EC2.SecurityGroup', 'security-group-group', [('SecurityGroupIngress[].FromPort', '`443`')])],
            'route53': [(f'{number:03d}', 'Route53.RecordSet', 'route53-' + name + '-fixture',
                         [('Name', '`fixture.' + name + '`'), ('TTL', '`60`')]) for number, name in enumerate(('record_a', 'record_b'), 1)],
            'iam': [('001', 'IAM.Role', 'iam-service', [('RoleName', '`fixture-role`'),
                    ('AssumeRolePolicyDocument', '[trust](iam/trust.json)', {'Statement': {'Effect': 'Allow',
                      'Principal': {'AWS': '210987654321'}, 'Action': 'sts:AssumeRole'}})])],
            's3': [('001', 'S3.Bucket', 's3-bucket', [('BucketName', '`fixture`'), ('LifecycleConfiguration.Rules[].ExpirationInDays', '`30`')])],
            'cloudtrail': [('001', 'CloudTrail.Trail', 'cloudtrail-trail', [('TrailName', '`fixture`')])],
            'glue': [('001', 'Glue.Job', 'glue-job', [('Name', '`fixture-job`'), ('Timeout', '`30`'),
                     ('SecurityConfiguration', '[glsc-one](#glue-glsc-one)'), ('DefaultArguments', '`{"--job-language":"python"}`')]),
                     ('002', 'Glue.SecurityConfiguration', 'glue-glsc-one', [('Name', '`glsc-one`')])],
            'cloudwatch-logs': [('001', 'Logs.LogGroup', 'cloudwatch-logs-logs', [('LogGroupName', '`/aws/vpc/flow-logs`'),
                                ('RetentionInDays', '`30`'), ('DeletionProtectionEnabled', '`false`')])],
            'lambda': [('001', 'Lambda.Function', 'lambda-function', [('FunctionName', '`fixture`'),
                        ('Architectures', '`["x86_64"]`'), ('MemorySize', '`128`')]),
                       ('002', 'Lambda.Permission', 'lambda-permission', [('Principal', '`events.amazonaws.com`')])],
            'eventbridge': [('001', 'Events.Rule', 'eventbridge-rule', [('Name', '`fixture-rule`'), ('State', '`ENABLED`'),
                ('EventPattern', '[pattern](eventbridge/pattern.json)', {'detail': {'eventName': ['GetObject'],
                    'userIdentity': {'userName': ['fixture']}, 'requestParameters': {'bucketName': ['fixture']}}}),
                ('Targets[].RetryPolicy.MaximumEventAgeInSeconds', '`3600`'), ('Targets[].RetryPolicy.MaximumRetryAttempts', '`3`')]),
                ('002', 'Scheduler.Schedule', 'eventbridge-schedule', [('Name', '`fixture-schedule`'),
                    ('ScheduleExpression', '`cron(0 0 * * ? *)`'), ('ScheduleExpressionTimezone', '`Asia/Tokyo`'),
                    ('Target.RetryPolicy.MaximumEventAgeInSeconds', '`3600`'), ('Target.RetryPolicy.MaximumRetryAttempts', '`3`')])],
            'codepipeline': [('001', 'CodePipeline.Pipeline', 'codepipeline-pipeline', [('Name', '`fixture`'),
                ('Stages[].Name', '`source`'), ('Stages[].Actions[].Name', '`source`'),
                ('Stages[].Actions[].Configuration', '`{"BranchName":"main"}`')])],
        }
        for name, kind in [('config', 'Config.ConfigurationRecorder'), ('data-firehose', 'KinesisFirehose.DeliveryStream'),
                           ('guardduty', 'GuardDuty.Detector'), ('macie', 'Macie.Session'), ('quicksight', 'QuickSight.DataSource'),
                           ('codebuild', 'CodeBuild.Project'), ('ec2', 'EC2.Instance'), ('mwaa', 'MWAA.Environment'),
                           ('transit-gateway', 'EC2.TransitGateway')]:
            services[name] = [('001', kind, name + '-fixture', [('Name', '`fixture`')])]
        for service, resources in services.items():
            extra = {'desired.row.001-004.comment': 'BranchName: ブランチ'} if service == 'codepipeline' else {}
            if service == 'cloudwatch-logs':
                for producer, kind, prop, name in [
                        ('lambda', 'Lambda.Function', 'FunctionName', 'fixture'), ('glue', 'Glue.Job', 'Name', 'fixture-job'),
                        ('iam', 'IAM.Role', 'RoleName', 'fixture-role'), ('codebuild', 'CodeBuild.Project', 'Name', 'fixture'),
                        ('mwaa', 'MWAA.Environment', 'Name', 'fixture'), ('cloudtrail', 'CloudTrail.Trail', 'TrailName', 'fixture')]:
                    key = 'desired.note.producer_' + producer + '.text'
                    extra[key] = name
                    extra.update(import_fixtures.reference_fields('producer_' + producer, key, name, env + '/team/' + producer + '/001',
                                                  kind=kind, prop=kind + '.' + prop))
            authored_service(root, env, service, resources, extra=extra)
        write_model(root / 'model' / env / 'team/cloudformation-stacks.properties', {
            'desired.deployment.maxConcurrentStacks': '2', 'desired.stack.fixture.name': 'fixture',
            'desired.stack.fixture.placementName': 'fixture', 'desired.stack.fixture.template': 'fixture.yaml',
            'desired.stack.fixture.parameters': 'fixture.json', 'desired.stack.fixture.deployOrder': '1'})


def build_input_templates(root):
    # Bundle name retained as test provenance; the contents are explicit properties v2.
    topology(root, ('preview', 'prod'))
    for env, account in [('preview', '123456789012'), ('prod', '210987654321')]:
        authored_service(root, env, 'codecommit', [('017', 'CodeCommit.Repository', 'fixture-codecommit-017', [
            ('RepositoryName', '`fixture`'), ('RepositoryDescription', '`fixture repository description`')])])
        authored_service(root, env, 'security-hub', [('017', 'SecurityHub.Hub', 'fixture-security-hub-017', [
            ('ControlFindingGenerator', '`SECURITY_CONTROL`'), ('EnableDefaultStandards', '`true`')])])
        authored_service(root, env, 's3', [('001', 'S3.Bucket', 'bucket-001', [('BucketName', '`fixture-bucket-001-one`')])])
        key = 'desired.row.017-002.value'
        references = import_fixtures.reference_fields('result', key, 'fixture-bucket-001-one', env + '/team/s3/001',
                                      kind='S3.Bucket', prop='S3.Bucket.BucketName')
        authored_service(root, env, 'athena', [('017', 'Athena.WorkGroup', 'fixture-athena-017', [
            ('Name', '`fixture`'), ('WorkGroupConfiguration.ResultConfiguration.OutputLocation', '`s3://fixture-bucket-001-one/results/`')])], extra=references)
        key = 'desired.row.034-002.document'
        context = {'consumerKey': key, 'pointer': '/Statement/0/Condition/StringEquals/aws:SourceAccount', 'text': account,
                   'occurrence': '1', 'producerKind': 'context', 'producerScope': env + '/team', 'format': 'literal',
                   'labelPolicy': 'none', 'contextProperty': 'executionAccountId'}
        authored_service(root, env, 'sqs', [
            ('017', 'SQS.Queue', 'fixture-sqs-017', [('QueueName', '`fixture-one`')]),
            ('034', 'SQS.QueuePolicy', 'fixture-sqs-034', [('Queues', '[fixture-one](#fixture-sqs-017)'),
                ('PolicyDocument', '[policy](sqs/policy.json)', {'Statement': [{'Effect': 'Allow', 'Action': 'sqs:SendMessage',
                    'Resource': {'Fn::GetAtt': ['HulftRetrievalDetectDlq', 'Arn']},
                    'Condition': {'StringEquals': {'aws:SourceAccount': account}}}]})])],
            extra={'desired.reference.account.' + field: value for field, value in context.items()})
        authored_service(root, env, 'datazone', [(f'{number * 17:03d}', 'DataZone.Domain', f'fixture-datazone-{number * 17:03d}',
            [('Name', f'`fixture-{number}`')]) for number in range(1, 7)])


def typed_services(root):
    workspace.populate('typed_services', root)


def input_templates(root):
    workspace.populate('input_templates', root)
