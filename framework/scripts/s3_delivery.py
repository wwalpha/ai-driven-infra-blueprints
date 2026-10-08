"""Model-approved S3 delivery conditions; read checks do not prove write permission."""
import re
import hashlib
import json
from types import SimpleNamespace

from cloudformation_inputs import Blocked
from script_loader import module
from iac_values import strict_json
from model_core import LINK
from policy_tables import literal

ALGORITHM = 'BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm'
KEY = 'BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID'
HEADERS = {'s3:x-amz-server-side-encryption': 'algorithm',
           's3:x-amz-server-side-encryption-aws-kms-key-id': 'requestKey',
           's3:x-amz-server-side-encryption-customer-algorithm': 'customerAlgorithm'}


def fail(category, reason):
    raise Blocked(f'S3_PLACEMENT_{category}: {reason}')


def confirmed(value):
    value = literal(value)
    if not value or value in {'UNSET', 'PENDING_DEPLOY', 'TBD', 'TODO', '未確定'}:
        fail('INDETERMINATE', 'unconfirmed design value')
    return value


def selected(resource, prop):
    rows = resource.rows_for(prop)
    if len(rows) != 1:
        fail('INDETERMINATE', f'{resource.kind}.{prop}: requires one confirmed row')
    return confirmed(rows[0][1]['value'])


def read(backend, operation, *arguments, service='s3api', absent=None):
    try:
        return backend.aws(operation, *arguments, service=service)
    except Exception as error:
        if absent and f'({absent})' in str(error):
            return None
        category = 'READ_DENIED' if any(code in str(error) for code in
            ('AccessDenied', 'Forbidden', '(403)', 'UnauthorizedOperation')) else 'READ_UNCONFIRMED'
        fail(category, f'{service}.{operation}: {error}')


def key_metadata(backend, key):
    if not isinstance(key, str) or not key:
        fail('INDETERMINATE', 'KMS key selector is missing or invalid')
    metadata = read(backend, 'describe-key', '--key-id', key, service='kms').get('KeyMetadata', {})
    if not {'Arn', 'KeyId', 'AWSAccountId', 'KeyState', 'Enabled', 'KeyUsage', 'KeySpec'} <= metadata.keys():
        fail('INDETERMINATE', 'DescribeKey metadata is incomplete')
    arn = metadata.get('Arn', '')
    parts = arn.split(':')
    account = backend.target.get('awsExecutionAccountId', backend.target['awsAccountId'])
    if len(parts) != 6 or parts[2] != 'kms' or not parts[5].startswith('key/'):
        fail('INDETERMINATE', 'DescribeKey did not return a key ARN')
    if parts[3] != backend.target['awsRegion'] or parts[4] != account or metadata.get('AWSAccountId') != account:
        fail('MISMATCH', 'KMS key account/region differs from target')
    if metadata.get('KeyState') != 'Enabled' or metadata.get('Enabled') is not True:
        fail('MISMATCH', 'KMS key is not Enabled')
    if metadata.get('KeyUsage') != 'ENCRYPT_DECRYPT' or metadata.get('KeySpec') != 'SYMMETRIC_DEFAULT':
        fail('MISMATCH', 'KMS key is not compatible with S3 SSE-KMS')
    if metadata.get('KeyId') != parts[5].removeprefix('key/'):
        fail('INDETERMINATE', 'KMS key identity is inconsistent')
    return arn


def referenced_key(backend, resource):
    current = resource.current('KeyId')
    if current:
        return key_metadata(backend, current)
    aliases = [child for child in resource.model.resources if child.kind == 'KMS.Alias'
               and child.spec.get('parentReference') and child.parent().number == resource.number]
    if not aliases:
        fail('INDETERMINATE', 'referenced KMS key has no confirmed KeyId or approved alias; producer must succeed first')
    keys = {key_metadata(backend, selected(alias, 'AliasName')) for alias in aliases}
    if len(keys) != 1:
        fail('MISMATCH', 'approved KMS aliases identify different keys')
    return keys.pop()


def model_conditions(backend, bucket):
    # Reuse the comparator's resource/current/parent/reference resolution, without an SDK client.
    models = {}
    ctx = SimpleNamespace()
    def model(path):
        if path not in models:
            models[path] = module('check-model-aws.py', 'model_aws_compare').Model(ctx, path)
        return models[path]
    ctx.model = model
    path = backend.root / 'model' / backend.environment / backend.directory / 's3.properties'
    try:
        candidates = [r for r in model(path).resources if r.kind == 'S3.Bucket'
                      and any(literal(row['value']) == bucket for _, row in r.rows_for('BucketName'))]
        if len(candidates) != 1:
            fail('INDETERMINATE', 'placement must identify one approved S3 bucket')
        resource = candidates[0]
        selected(resource, 'BucketName')
        if selected(resource, 'Region') != backend.target['awsRegion']:
            fail('MISMATCH', 'designed bucket region differs from target')
        mode = resource.spec.get('deploymentEncryption')
        if mode not in {None, 'default'}:
            fail('INDETERMINATE', 'unsupported deploymentEncryption approval')
        algorithm = selected(resource, ALGORITHM)
        if algorithm not in {'AES256', 'aws:kms'}:
            fail('INDETERMINATE', 'unsupported S3 encryption algorithm')
        request_key = key_arn = None
        key_rows = resource.rows_for(KEY)
        if algorithm == 'AES256' and key_rows:
            fail('INDETERMINATE', 'SSE-S3 design also specifies a KMS key')
        if algorithm == 'aws:kms':
            raw = selected(resource, KEY)
            if LINK.fullmatch(raw):
                referenced = resource.reference(raw)
                if referenced.kind == 'KMS.Alias':
                    parent = referenced.parent()
                    if parent.kind != 'KMS.Key':
                        fail('INDETERMINATE', 'KMS Alias parent is not a Key')
                    key_arn = key_metadata(backend, selected(referenced, 'AliasName'))
                    if referenced_key(backend, parent) != key_arn:
                        fail('MISMATCH', 'KMS Alias does not match its approved parent KeyId')
                elif referenced.kind == 'KMS.Key':
                    key_arn = referenced_key(backend, referenced)
                else:
                    fail('INDETERMINATE', 'encryption reference is not a KMS Key/Alias')
                request_key = key_arn
            else:
                request_key = raw
                key_arn = key_metadata(backend, raw)
        result = {'algorithm': algorithm, 'keyArn': key_arn, 'requestKey': request_key,
                  'mode': mode or 'explicit', 'account': backend.target.get('awsExecutionAccountId', backend.target['awsAccountId']),
                  'region': backend.target['awsRegion']}
        rows = resource.rows_for('BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled')
        if rows:
            value = selected(resource, 'BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled')
            if value not in {'true', 'false'}:
                fail('INDETERMINATE', 'BucketKeyEnabled is not a confirmed boolean')
            result['bucketKeyEnabled'] = value == 'true'
        return result
    except (OSError, ValueError, KeyError) as error:
        fail('INDETERMINATE', f'approved S3 model/reference cannot be resolved: {error}')


def wildcard(value, pattern):
    return re.fullmatch(re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.'), value) is not None


def strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return value
    fail('INDETERMINATE', 'unsupported bucket policy value')


def policy_conditions(policy, bucket, key, conditions):
    """Check encryption clauses only. Unknown applicability is a blocker, not an IAM verdict."""
    if not isinstance(policy, dict) or 'Statement' not in policy:
        fail('INDETERMINATE', 'bucket policy response lacks Statement')
    statements = policy['Statement']
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list):
        fail('INDETERMINATE', 'invalid bucket policy statements')
    partition = 'aws-cn' if conditions['region'].startswith('cn-') else 'aws-us-gov' if conditions['region'].startswith('us-gov-') else 'aws'
    object_arn = f'arn:{partition}:s3:::{bucket}/{key}'
    request = {} if conditions['mode'] == 'default' else conditions
    for statement in statements:
        if not isinstance(statement, dict) or not isinstance(statement.get('Condition', {}), dict):
            fail('INDETERMINATE', 'invalid bucket policy statement')
        clauses = statement.get('Condition', {})
        if not any(isinstance(values, dict) and any(k.lower().startswith('s3:x-amz-server-side-encryption') for k in values) for values in clauses.values()):
            continue  # IAM, transport and non-encryption authorization are left to real PutObject.
        if any(name in statement for name in ('NotAction', 'NotResource', 'NotPrincipal')):
            fail('INDETERMINATE', 'unsupported encryption policy applicability')
        if not any(wildcard('s3:putobject', action.lower()) for action in strings(statement.get('Action'))):
            continue
        resources = strings(statement.get('Resource'))
        if any('${' in value for value in resources):
            fail('INDETERMINATE', 'encryption policy resource variable')
        if not any(wildcard(object_arn, value) for value in resources):
            continue
        unknown, matches = [], []
        for operator, values in clauses.items():
            if not isinstance(values, dict):
                fail('INDETERMINATE', 'invalid encryption policy conditions')
            for header, expected in values.items():
                if header.lower() not in HEADERS:
                    unknown.append(header)
                    continue
                actual = request.get(HEADERS[header.lower()])
                options = strings(expected)
                if any('${' in value for value in options):
                    unknown.append('encryption policy variable')
                    continue
                base = operator.removesuffix('IfExists')
                if base == 'Null' and options in [['true'], ['false']]:
                    match = (actual is None) == (options == ['true'])
                elif base in {'StringEquals', 'StringNotEquals', 'StringLike', 'StringNotLike'}:
                    equal = any(wildcard(actual, value) if 'Like' in base else actual == value
                                for value in options) if actual is not None else False
                    match = not equal if base in {'StringNotEquals', 'StringNotLike'} else equal
                    if operator.endswith('IfExists') and actual is None:
                        match = True
                else:
                    unknown.append(operator)
                    continue
                matches.append(match)
        if False in matches:
            continue
        if statement.get('Principal') not in ('*', {'AWS': '*'}) or unknown or not matches:
            fail('INDETERMINATE', 'encryption policy applicability/conditions unsupported: ' + ', '.join(unknown))
        if statement.get('Effect') == 'Deny':
            fail('MISMATCH', 'bucket policy denies the designed encryption request for this object prefix')
        if statement.get('Effect') != 'Allow':
            fail('INDETERMINATE', 'unsupported encryption policy Effect')


def preflight(backend, bucket, prefix, keys):
    identity = json.dumps([bucket, prefix], separators=(',', ':'))
    reports = backend.session.setdefault('placementPreflight', {})
    try:
        conditions = model_conditions(backend, bucket)
        owner = ['--bucket', bucket, '--expected-bucket-owner', conditions['account']]
        read(backend, 'head-bucket', *owner)
        location = read(backend, 'get-bucket-location', *owner)
        if 'LocationConstraint' not in location:
            fail('INDETERMINATE', 'bucket location response is incomplete')
        region = location['LocationConstraint'] or 'us-east-1'
        if ('eu-west-1' if region == 'EU' else region) != conditions['region']:
            fail('MISMATCH', 'deployment bucket region does not match target')
        encryption = read(backend, 'get-bucket-encryption', *owner)
        rules = encryption.get('ServerSideEncryptionConfiguration', {}).get('Rules', [])
        if len(rules) != 1:
            fail('INDETERMINATE', 'bucket default encryption must have one supported rule')
        default = rules[0].get('ApplyServerSideEncryptionByDefault', {})
        if 'SSEAlgorithm' not in default:
            fail('INDETERMINATE', 'bucket default encryption response is incomplete')
        if default.get('SSEAlgorithm') != conditions['algorithm']:
            fail('MISMATCH', 'bucket default encryption differs from the approved model')
        if conditions['algorithm'] == 'aws:kms':
            key = default.get('KMSMasterKeyID')
            if not key:
                fail('INDETERMINATE', 'bucket default KMS key is not explicit')
            if key_metadata(backend, key) != conditions['keyArn']:
                fail('MISMATCH', 'bucket default KMS key differs from the approved model')
        elif default.get('KMSMasterKeyID'):
            fail('INDETERMINATE', 'SSE-S3 default also contains a KMS key')
        if 'bucketKeyEnabled' in conditions and rules[0].get('BucketKeyEnabled', False) != conditions['bucketKeyEnabled']:
            fail('MISMATCH', 'bucket default BucketKeyEnabled differs from model')
        raw_policy = read(backend, 'get-bucket-policy', *owner, absent='NoSuchBucketPolicy')
        policy = strict_json(raw_policy['Policy']) if raw_policy is not None else {'Statement': []}
        for key in keys:
            policy_conditions(policy, bucket, key, conditions)
        conditions['defaultEncryption'] = rules
        conditions['policyDigest'] = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        previous = backend.session.setdefault('placementConditions', {}).get(identity)
        if previous is not None and previous != conditions:
            fail('CHANGED', 'resolved placement conditions changed in this session; do not resume')
        backend.session['placementConditions'][identity] = conditions
        reports[identity] = {'status': 'READ_CONFIRMED', 'effectiveWritePermission': 'UNCONFIRMED'}
        backend.save()
        return conditions
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        error = Blocked('S3_PLACEMENT_INDETERMINATE: malformed preflight response: ' + str(error))
        reports[identity] = {'status': 'INDETERMINATE', 'reason': str(error)}
        backend.save()
        raise error
    except Blocked as error:
        reports[identity] = {'status': str(error).split(':', 1)[0], 'reason': str(error)}
        backend.save()
        raise


def upload_options(conditions):
    if conditions['mode'] == 'default':
        return []
    result = ['--server-side-encryption', conditions['algorithm']]
    if conditions['requestKey']:
        result += ['--ssekms-key-id', conditions['requestKey']]
    return result


def verify_encryption(current, conditions):
    if current.get('ServerSideEncryption') != conditions['algorithm']:
        fail('MISMATCH', 'existing object encryption differs from approved placement')
    if conditions['keyArn'] and current.get('SSEKMSKeyId') != conditions['keyArn']:
        fail('MISMATCH', 'existing object KMS key differs from approved placement')
