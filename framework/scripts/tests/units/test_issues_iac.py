
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

import unittest
import json
from unittest.mock import Mock

import issues_iac


class ImportValueResolutionTests(unittest.TestCase):
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
