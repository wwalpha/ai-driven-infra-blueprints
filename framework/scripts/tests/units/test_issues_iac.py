
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

import unittest
import json
from unittest.mock import Mock, patch
from types import SimpleNamespace
import tempfile

import issues_iac


def legacy_comparison(root, count=3, services=1, stacks=2):
  """Synthetic legacy Models and real local templates; no consumer inputs."""
  models, documents, units = {}, [{'Resources': {}} for _ in range(stacks)], []
  for number in range(count):
    service, identity = f'service-{number % services}', f'{number:04d}'
    values = models.setdefault(service, {f'desired.service.{service}.serviceId': service})
    values.update({f'desired.resource.{identity}.resourceType': 'Logs.LogGroup',
                   f'desired.resource.{identity}.logicalId': f'Log{number}',
                   f'desired.row.{identity}-001.property': 'Logs.LogGroup.RetentionInDays',
                   f'desired.row.{identity}-001.value': '`7`'})
    documents[number % stacks]['Resources'][f'Log{number}'] = {
        'Type': 'AWS::Logs::LogGroup', 'Properties': {'RetentionInDays': 7}}
  loaded = {}
  for service, values in models.items():
    path = root / 'model/fixture/team' / (service + '.properties')
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(values).encode()
    path.write_bytes(raw)
    loaded[path] = SimpleNamespace(values=values, dependencies={path: raw}, locations={})
  for number, document in enumerate(documents):
    unit = {'name': f'stack{number}', 'template': f'{number}.json', 'parameters': f'{number}.json'}
    units.append((str(number), unit))
    for path, value in [(root / 'infra/cloudformation/templates' / unit['template'], document),
                        (root / 'infra/cloudformation/parameters/fixture/team' / unit['parameters'], [])]:
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(json.dumps(value), encoding='utf-8')
  catalog = issues_iac.DesignSchemaCatalog(Path(__file__).resolve().parents[4])
  target = {'iacEngine': 'cloudformation', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1'}
  with patch('issues_iac.load_target', return_value=target), patch('issues_iac.load_model', side_effect=loaded.__getitem__):
    comparison = issues_iac.Comparison(root, 'fixture', 'team', models, catalog=catalog)
  comparison.templates = lambda: units
  return comparison


class ExplicitIdentityTests(unittest.TestCase):
  def test_missing_mapping_never_searches_legacy_ids(self):
    with tempfile.TemporaryDirectory() as directory:
      comparison = legacy_comparison(Path(directory))
      with patch.object(comparison, 'stack_input', side_effect=AssertionError('implicit CFn search')):
        results = comparison.run()
      self.assertEqual([item['category'] for item in results], ['uncompared'] * 3)
      self.assertTrue(all('explicit cfn-logicalId is required' in item['reason'] for item in results))

  def test_explicit_mapping_and_run_isolation(self):
    with tempfile.TemporaryDirectory() as directory:
      comparison = legacy_comparison(Path(directory))
      for number in range(3):
        key = f'{number:04d}'
        mapping = f'stack{number % 2}-Log{number}'
        comparison.resources['service-0'][key]['cfn-logicalId'] = mapping
        comparison.models['service-0'].values[f'desired.resource.{key}.cfn-logicalId'] = mapping
      self.assertEqual([item['category'] for item in comparison.run()], ['matched'] * 3)
      del comparison.stack_inputs['stack1'][0]['Resources']['Log1']
      comparison.results = []
      self.assertEqual(comparison.run()[1]['reason'], 'resource missing')
      # Changing a Model logicalId never changes the explicit CFn correspondence.
      comparison.resources['service-0']['0000']['logicalId'] = 'Logs_LogGroup_999'
      comparison.results = []
      self.assertEqual(comparison.run()[0]['category'], 'matched')

  def test_duplicate_direct_ownership_and_type_mismatch(self):
    with tempfile.TemporaryDirectory() as directory:
      comparison = legacy_comparison(Path(directory))
      for key in ('0000', '0001'):
        comparison.resources['service-0'][key]['cfn-logicalId'] = 'stack0-Log0'
        comparison.models['service-0'].values[f'desired.resource.{key}.cfn-logicalId'] = 'stack0-Log0'
      self.assertTrue(all('duplicate resource correspondence' in item['reason'] for item in comparison.run()[:2]))
      comparison.resources['service-0']['0001']['cfn-logicalId'] = 'stack1-Log1'
      comparison.models['service-0'].values['desired.resource.0001.cfn-logicalId'] = 'stack1-Log1'
      comparison.resources['service-0']['0001']['resourceType'] = 'SQS.Queue'
      comparison._index = None
      comparison.results = []
      self.assertIn('formal resource type mismatch', comparison.run()[1]['reason'])


class ImportValueResolutionTests(unittest.TestCase):
  def test_codebuild_plaintext_resource_attributes(self):
    # Authored identities and templates only; no consumer inputs or physical identifiers.
    with tempfile.TemporaryDirectory() as directory:
      comparison = issues_iac.Comparison.__new__(issues_iac.Comparison)
      comparison.root = Path(directory)
      comparison.environment, comparison.directory = 'fixture', 'team'
      comparison.catalog = issues_iac.DesignSchemaCatalog(Path(__file__).resolve().parents[4])
      comparison.local_comparison = comparison.reference_models_loaded = True
      comparison.reference_formats, comparison.symbols = {}, {}
      comparison._index = None
      comparison.resources = {'kms': {}, 's3': {}}
      comparison.rows = {'kms': {}, 's3': {}}
      comparison.models = {}
      definitions = {}
      for service, identity, kind, logical in [
          ('kms', '001', 'KMS.Key', 'Key'), ('kms', '002', 'KMS.Alias', 'Alias'),
          ('kms', '003', 'KMS.Key', 'OtherKey'), ('s3', '001', 'S3.Bucket', 'Bucket')]:
        resource = {'resourceType': kind, 'logicalId': kind.replace('.', '_') + '_' + identity, 'cfn-logicalId': 'producer-' + logical}
        if kind == 'KMS.Alias':
          resource['parentReference'] = 'resource://fixture/team/kms/KMS_Key_001'
        comparison.resources[service][identity] = resource
        comparison.rows[service][identity] = []
        definitions[logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
      definitions['Alias']['Properties'] = {'AliasName': 'alias/fixture', 'TargetKeyId': {'Ref': 'Key'}}
      definitions['Bucket']['Properties'] = {'BucketName': 'fixture-bucket'}
      for service, resources in comparison.resources.items():
        comparison.models[service] = SimpleNamespace(values={
            f'desired.resource.{identity}.{key}': value
            for identity, resource in resources.items() for key, value in resource.items()})
      producer = {'Resources': definitions}
      pseudo = {'AWS::Partition': 'aws', 'AWS::Region': 'ap-northeast-1', 'AWS::AccountId': '123456789012'}
      comparison.stack_inputs = {'producer': (producer, {}, pseudo), 'build': ({}, {}, pseudo)}
      comparison.templates = lambda: [('001', {'name': 'producer'})]
      comparison.stack = lambda unit: (Path('producer.yaml'), comparison.stack_inputs['producer'])
      alias_value = {'Fn::Sub': ['arn:${AWS::Partition}:kms:${AWS::Region}:${AWS::AccountId}:${Alias}', {'Alias': {'Ref': 'Alias'}}]}
      comparison.exports = {'key-export': [('producer', {'Fn::GetAtt': ['Key', 'Arn']})],
                            'alias-export': [('producer', alias_value)]}
      comparison.export_failures = []
      prop = 'Environment.EnvironmentVariables[].Value'
      def desired(logical, attribute=None, name='VALUE'):
        ids = {'Key': 'KMS_Key_001', 'Alias': 'KMS_Alias_002', 'OtherKey': 'KMS_Key_003', 'Bucket': 'S3_Bucket_001', 'Missing': 'KMS_Key_999'}
        link = f'resource://fixture/team/{"s3" if logical == "Bucket" else "kms"}/{ids[logical]}'
        value = {'$resource': link, '$attribute': attribute} if attribute else link
        return comparison.desired_value('codebuild', {
            'property': 'CodeBuild.Project.Environment.EnvironmentVariables', 'value': '',
            'document': json.dumps([{'Name': name, 'Type': 'PLAINTEXT', 'Value': value}])}, 'CodeBuild.Project')[0]['Value']
      def equal(left, right):
        return comparison.reference_same(left, right, 'CodeBuild.Project', prop)
      with patch('issues_iac.catalog_outputs', return_value=set()):
        key, alias = desired('Key', 'Arn'), desired('Alias', 'AliasArn')
        for selector in [{'$resource': 'resource://fixture/team/kms/KMS_Key_001'},
                         {'$resource': 'resource://fixture/team/kms/KMS_Key_001', '$attribute': 'Arn'}]:
          policy = {'property': 'IAM.ManagedPolicy.PolicyDocument', 'value': '',
                    'document': json.dumps({'Statement': [{'Resource': selector}]})}
          self.assertEqual(comparison.desired_value('iam', policy, 'IAM.ManagedPolicy')['Statement'][0]['Resource'], key)
        policy['document'] = json.dumps({'Statement': [{'Resource': {**selector, 'extra': 1}}]})
        with self.assertRaises(issues_iac.Blocked):
          comparison.desired_value('iam', policy, 'IAM.ManagedPolicy')
        for model, actual, exported in [
            (key, {'Fn::GetAtt': ['Key', 'Arn']}, 'key-export'), (alias, alias_value, 'alias-export')]:
          self.assertTrue(equal(model, comparison.evaluate('producer', actual)))
          self.assertTrue(equal(model, comparison.evaluate('build', {'Fn::ImportValue': exported})))
          self.assertIsNot(equal(model, exported), True)
        self.assertFalse(equal(key, alias))
        self.assertFalse(equal(key, comparison.evaluate('producer', alias_value)))
        self.assertFalse(equal(key, desired('OtherKey', 'Arn')))
        self.assertFalse(equal(key, desired('Key', 'KeyId')))
        self.assertFalse(equal(alias, desired('Alias', 'AliasName')))
        self.assertTrue(equal(desired('Bucket'), comparison.evaluate('producer', {'Ref': 'Bucket'})))
        self.assertFalse(equal(desired('Bucket'), desired('Bucket', 'Arn')))
        self.assertEqual(desired('Key', 'KeyId', name='KEY_ARN')['$attribute'], 'KeyId')
        for logical, attribute in [('Key', None), ('Alias', None), ('Missing', 'Arn'), ('Key', 'AliasArn')]:
          with self.subTest(logical=logical, attribute=attribute), self.assertRaises((issues_iac.Blocked, KeyError)):
            desired(logical, attribute)
        with self.assertRaises(issues_iac.Blocked):
          comparison.evaluate('build', {'Fn::ImportValue': 'unknown-export'})
        self.assertIsNone(equal(key, issues_iac.Expression('Sub', ['${Unknown}', {}])))
        unknown = issues_iac.Expression('Sub', ['${Unknown}', {}])
        self.assertIsNone(equal(unknown, unknown))
        row = {'property': 'CodeBuild.Project.' + prop, 'value': '`' + json.dumps({
            '$resource': 'resource://fixture/team/kms/KMS_Key_001', '$attribute': 'Arn'}) + '`'}
        self.assertEqual(comparison.desired_value('codebuild', row, 'CodeBuild.Project', context={'Type': 'PLAINTEXT'}), key)
        for selector in [{'$resource': 'resource://fixture/team/kms/KMS_Key_001'},
                         {'$resource': 'key-export', '$attribute': 'Arn'},
                         {'$resource': 'resource://fixture/team/kms/KMS_Key_001', '$attribute': 'Arn', 'extra': 'x'},
                         {'$resource': 'resource://fixture/team/kms/KMS_Key_001', '$attribute': 3}]:
          row['value'] = '`' + json.dumps(selector) + '`'
          with self.subTest(selector=selector), self.assertRaises(issues_iac.Blocked):
            comparison.desired_value('codebuild', row, 'CodeBuild.Project', context={'Type': 'PLAINTEXT'})

  def test_formal_pipeline_membership_and_configuration_context(self):
    comparison = Mock()
    comparison.root = Path(__file__).resolve().parents[4]
    comparison.local_comparison = True
    fields = [
        ('Stages[].Actions[].ActionTypeId.Category', '`Build`'),
        ('Stages[].Actions[].ActionTypeId.Owner', '`AWS`'),
        ('Stages[].Actions[].ActionTypeId.Provider', '`CodeBuild`'),
        ('Stages[].Actions[].ActionTypeId.Version', '`1`'),
        ('Stages[].Actions[].Configuration', '`{"ProjectName":"one","Extra":"two"}`'),
        ('Stages[].Actions[].InputArtifacts[].Name', '`first`'),
        ('Stages[].Actions[].InputArtifacts[].Name', '`second`'),
        ('Stages[].Actions[].Name', '`Build`'),
        ('Stages[].Actions[].ActionTypeId.Category', '`Approval`'),
        ('Stages[].Actions[].Name', '`Approve`'),
        ('Stages[].Name', '`BuildAndApprove`'),
        ('Stages[].Actions[].Name', '`Finish`'),
        ('Stages[].Name', '`Final`'),
    ]
    rows = [(str(i), {'property': 'CodePipeline.Pipeline.' + prop, 'value': value,
                     'comment': 'ProjectName: project / Extra: extra' if prop.endswith('.Configuration') else ''})
            for i, (prop, value) in enumerate(fields)]
    comparison.rows = {'codepipeline': {'001': rows}}
    contexts = []
    def desired_value(service, row, kind, **kwargs):
      value = row['value'].strip('`')
      if row['property'].endswith('.Configuration'):
        contexts.append(kwargs['context'])
        return json.loads(value)
      return value
    comparison.desired_value = desired_value
    comparison.evaluate.side_effect = lambda stack, value: value
    comparison.reference_same.return_value = True
    stages = [
        {'Name': 'BuildAndApprove', 'Actions': [
            {'Name': 'Build', 'ActionTypeId': {'Category': 'Build', 'Owner': 'AWS', 'Provider': 'CodeBuild', 'Version': '1'},
             'Configuration': {'ProjectName': 'one', 'Extra': 'two'}, 'InputArtifacts': [{'Name': 'first'}, {'Name': 'second'}]},
            {'Name': 'Approve', 'ActionTypeId': {'Category': 'Approval'}}]},
        {'Name': 'Final', 'Actions': [{'Name': 'Finish'}]},
    ]
    template = comparison.root / 'infra/cloudformation/templates/fixture.yaml'
    definition = {'Properties': {'Stages': stages}}
    issues_iac.Comparison.compare_rows(comparison, 'codepipeline', '001',
        {'resourceType': 'CodePipeline.Pipeline'}, 'stack', 'Pipeline', template, definition, {})
    self.assertEqual(contexts, [{'ActionTypeId': {'Category': 'Build', 'Owner': 'AWS', 'Provider': 'CodeBuild', 'Version': '1'}}])
    self.assertEqual(comparison.record.call_count, 1)
    self.assertEqual(comparison.record.call_args.args[:5],
                     ('matched', 'codepipeline', '001', 'CodePipeline.Pipeline.Stages', 'equal'))

  def test_api_managed_resource_remains_unverified_in_cloudformation_comparison(self):
    comparison = issues_iac.Comparison.__new__(issues_iac.Comparison)
    comparison.catalog = Mock(api_schemas={'Macie.ClassificationJob': {}})
    comparison.target = {'iacEngine': 'cloudformation'}
    comparison.services = ['macie']
    comparison.resources = {'macie': {'001': {'resourceType': 'Macie.ClassificationJob'}}}
    comparison.results = []
    comparison.load_errors = []
    comparison.reference_unavailable = {}
    comparison.symbols = {}
    comparison.record = lambda *args, **kwargs: comparison.results.append((args, kwargs))
    comparison.templates = lambda: []

    results = comparison.run()

    self.assertEqual(results[0][0][:5], ('uncompared', 'macie', '001', '*', 'CloudFormation unsupported; outside CFn comparison; API implementation status unverified'))

    self.assertEqual(results[0][1]['cause'], {'kind': 'cloudformation-unsupported', 'resource_type': 'Macie.ClassificationJob', 'implementation_status': 'unverified'})

  def test_import_value_ignores_unrelated_incomplete_stack(self):
    comparison = Mock()
    comparison.evaluate.side_effect = lambda stack, value, seen: (
        "KmsAppKeyAlias-p4x8r2" if isinstance(value, dict) else value
    )
    comparison.templates.return_value = [
        (Path("missing.yaml"), {"name": "missing", "template": "missing.yaml"}),
        (Path("kms.yaml"), {"name": "kms", "template": "kms.yaml"}),
    ]
    comparison.stack.side_effect = [
        issues_iac.Blocked("stack input missing: missing.yaml"),
        (
            Path("kms.yaml"),
            (
                {"Outputs": {"Alias": {"Export": {"Name": "KmsAppKeyAlias-p4x8r2"}, "Value": "alias/app"}}},
                {},
                {},
            ),
        ),
    ]
    comparison.exports = None
    comparison.local_comparison = True
    comparison.import_value = issues_iac.Comparison.import_value.__get__(comparison)

    value = comparison.import_value("s3", {"Fn::ImportValue": "KmsAppKeyAlias-p4x8r2"}, frozenset())

    self.assertEqual(value, "alias/app")

  def test_kms_alias_retains_identity_even_with_the_same_parent_key(self):
    comparison = Mock()
    comparison.local_comparison = True
    comparison.resources = {
        "kms": {
            "002": {"resourceType": "KMS.Alias", "parentReference": "[LogKey](#kms-log)"},
            "001": {"resourceType": "KMS.Key", "anchor": "kms-log"},
        }
    }
    comparison.reference_formats = {}
    comparison.reference_forms = lambda kind, path: {"Arn"}

    left = issues_iac.ResourceReference({"$resource": ["kms", "002"], "$attribute": "AliasName"})
    right = issues_iac.ResourceReference({"$resource": ["kms", "001"], "$attribute": "Arn"})

    result = issues_iac.Comparison.reference_same(comparison, left, right, "S3.Bucket", "BucketEncryption")

    self.assertFalse(result)
    self.assertFalse(issues_iac.Comparison.reference_same(comparison, right, left, "S3.Bucket", "BucketEncryption"))
    self.assertTrue(issues_iac.Comparison.reference_same(comparison, right, right, "S3.Bucket", "BucketEncryption"))


if __name__ == "__main__":
  unittest.main()
