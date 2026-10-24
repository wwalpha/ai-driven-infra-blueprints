"""Declared artifact placement, immutable execution copies and group delivery barrier."""
import base64
import copy
import json
import re
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlencode

from cloudformation_inputs import Blocked, condition_active, resolve_value
from model.core import ARTIFACT_PROPERTIES

from deploy.s3_delivery import preflight, upload_options, verify_encryption


def placement(root, environment, directory, target, session, save, aws, connection=None):
    return SimpleNamespace(root=root, environment=environment, directory=directory, target=target,
                           session=session, save=save, aws=aws, connection=connection)


def source_path(root, artifact):
    path = (root / artifact['source']).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_relative_to((root / 'infra/cloudformation/artifacts').resolve()) or not path.is_file():
        raise Blocked(f"artifact source is missing or escapes its directory: {artifact['source']}")
    if artifact['property'] in {'Code', 'Content'} and (path.suffix != '.zip' or not zipfile.is_zipfile(path)):
        raise Blocked('Lambda artifact must be a prebuilt ZIP file')
    return path


def object_identity(placement, obj):
    return (placement.connection, obj['bucket'], obj['key'],
            placement.target.get('awsExecutionAccountId', placement.target['awsAccountId']),
            obj.get('version') if obj.get('consumeVersion') else None)


def head_object(placement, obj, boundary):
    identity = object_identity(placement, obj)
    heads = boundary.setdefault('heads', {})
    if identity not in heads:
        arguments = {'Bucket': obj['bucket'], 'Key': obj['key'], 'ExpectedBucketOwner': identity[3],
                     'ChecksumMode': 'ENABLED'}
        if identity[4]:
            arguments['VersionId'] = identity[4]
        heads[identity] = placement.aws('head_object', service='s3', **arguments)
    return heads[identity]


def verify_object(placement, obj, boundary=None):
    boundary = {} if boundary is None else boundary
    conditions = preflight(placement, obj['bucket'], obj['prefix'], [obj['key']], boundary)
    if 'encryption' not in obj or conditions != obj['encryption']:
        raise Blocked('S3_PLACEMENT_CHANGED: object placement conditions changed')
    current = head_object(placement, obj, boundary)
    if current.get('ChecksumSHA256') != obj['checksum'] or current.get('ContentLength') != obj['size']:
        raise Blocked('S3 artifact checksum/size changed; upload or execution blocked')
    if obj.get('consumeVersion') and current.get('VersionId') != obj.get('version'):
        raise Blocked('S3 artifact version changed')
    verify_encryption(current, conditions)
    return current


def upload(placement, file_digest, path, bucket, prefix, boundary, *, consume_version=False):
    digest = file_digest(path)
    obj = {'bucket': bucket, 'key': prefix + digest + path.suffix, 'prefix': prefix,
           'checksum': base64.b64encode(bytes.fromhex(digest)).decode(), 'size': path.stat().st_size}
    obj['encryption'] = preflight(placement, bucket, prefix, [obj['key']], boundary)
    uploaded = boundary.setdefault('uploaded', {})
    key = (placement.connection, bucket, obj['key'], digest)
    if key in uploaded:
        result = dict(uploaded[key])
        result['consumeVersion'] = consume_version and bool(result.get('version'))
        return result
    try:
        current = verify_object(placement, obj, boundary)
    except Blocked as error:
        if getattr(error, 'code', None) not in {'NoSuchKey', 'NotFound', '404'} or getattr(error, 'http_status', None) not in {None, 404}:
            raise
        # Retry only conditionally; an unknown response is resolved by a fresh HEAD.
        for attempt in range(3):
            try:
                with path.open('rb') as stream:
                    placement.aws('put_object', service='s3', Bucket=bucket, Key=obj['key'], Body=stream,
                        ExpectedBucketOwner=placement.target.get('awsExecutionAccountId', placement.target['awsAccountId']),
                        IfNoneMatch='*', ChecksumAlgorithm='SHA256', ChecksumSHA256=obj['checksum'],
                        **upload_options(obj['encryption']))
                put_error = None
            except Blocked as error:
                put_error = error
                if (getattr(error, 'code', None) not in {'PreconditionFailed', 'ConditionalRequestConflict',
                        'RequestTimeout', 'ReadTimeoutError', 'ConnectTimeoutError', 'EndpointConnectionError',
                        'ConnectionClosedError', 'OperationDeadlineExceeded'}
                        and getattr(error, 'http_status', None) not in {409, 412}):
                    raise
            finally:
                heads = boundary.setdefault('heads', {})
                for identity in list(heads):
                    if identity[:3] == (placement.connection, bucket, obj['key']):
                        del heads[identity]
            try:
                current = verify_object(placement, obj, boundary)
                break
            except Blocked as error:
                if not put_error or getattr(error, 'code', None) not in {'404', 'NoSuchKey', 'NotFound'} or getattr(error, 'http_status', None) not in {None, 404}:
                    raise
                if getattr(put_error, 'http_status', None) == 412 or getattr(put_error, 'code', None) == 'PreconditionFailed' or attempt == 2:
                    raise put_error from error
                time.sleep(0.1 * (attempt + 1))
    if current.get('VersionId') not in {None, 'null'}:
        obj['version'] = current['VersionId']
        pinned = dict(obj, consumeVersion=True)
        boundary.setdefault('heads', {})[object_identity(placement, pinned)] = current
    # Post-PUT fresh HEAD already verified current content, checksum, size and encryption.
    uploaded[key] = dict(obj)
    obj['consumeVersion'] = consume_version and bool(obj.get('version'))
    return obj


def artifact_bindings(target, unit, document, parameters, exports):
    pseudo = {'AWS::AccountId': target.get('awsExecutionAccountId', target['awsAccountId']),
              'AWS::Region': target['awsRegion'], 'AWS::StackName': unit['name']}
    bindings = []
    values = {name: entry['Value'] for name, entry in exports.items()}
    for artifact in unit.get('artifacts', []):
        resource = document['Resources'][artifact['resource']]
        if not condition_active(document, parameters, pseudo, resource):
            continue
        container = resource['Properties']
        parts = artifact['property'].split('.')
        for part in parts[:-1]:
            container = container[part]
        value = container[parts[-1]]
        fields = ARTIFACT_PROPERTIES[(resource['Type'], artifact['property'])]
        if fields:
            if not isinstance(value, dict) or not {fields[0], fields[1]} <= value.keys():
                raise Blocked('artifact property must already declare its S3 bucket and key')
            bucket = resolve_value(value[fields[0]], parameters, pseudo, values)
            key = resolve_value(value[fields[1]], parameters, pseudo, values)
        else:
            uri = resolve_value(value, parameters, pseudo, values)
            match = re.fullmatch(r's3://([^/]+)/(.+)', uri)
            if not match:
                raise Blocked('artifact property must declare an S3 URI')
            bucket, key = match.groups()
        if bucket != artifact['bucket'] or not key.startswith(artifact['keyPrefix']):
            raise Blocked('artifact bucket/keyPrefix differs from the approved template')
        bindings.append((artifact, container, parts[-1], fields))
    return bindings


def prepare_delivery_group(placement, units, states, templates, workdir, paths, input_digest,
                           file_digest, check_imports, exports_for):
    boundary = {}
    pending = [unit for unit in units if states[unit['name']]['status'] not in {'RUNNING', 'SUCCESS'}]
    exports_for(pending, boundary)
    for unit in pending:
        check_imports(unit, boundary=boundary)
        template_arguments(placement, unit, states[unit['name']], templates[unit['name']], paths(unit)[0],
                           workdir, input_digest, file_digest, boundary, stage_only=True)
    for unit in pending:
        template_arguments(placement, unit, states[unit['name']], templates[unit['name']], paths(unit)[0],
                           workdir, input_digest, file_digest, boundary)


def template_arguments(placement, unit, state, template_data, template_path, workdir,
                       input_digest_for, file_digest, boundary, stage_only=False):
    document, parameters = template_data
    exports = boundary.get('exports', {})
    # Resolve again against this document copy. Mutable containers never cross templates.
    document = copy.deepcopy(document)
    bindings = artifact_bindings(placement.target, unit, document, parameters, exports)
    imports = {name: {key: entry[key] for key in ('Value', 'ExportingStackId')} for name, entry in exports.items()
               if name in boundary.get('importNames', {}).get(unit['name'], set())}
    if state.get('delivery'):
        record = state['delivery']
        if record['imports'] != imports:
            raise Blocked('required Export destination/value/producer changed; existing delivery cannot execute')
        if input_digest_for(unit) != record['inputDigest']:
            raise Blocked('prepared deployment inputs changed')
        path, objects = Path(record['path']), record['objects']
        if file_digest(path) != record['templateSha256']:
            raise Blocked('prepared deployment template changed')
        for obj in objects:
            verify_object(placement, obj, boundary)
        if record.get('arguments'):
            return {'TemplateBody': path.read_text(encoding='utf-8')} if record['arguments'] == {'inline': True} else record['arguments']
        input_digest = record['inputDigest']
    else:
        path, objects, input_digest = template_path, [], input_digest_for(unit)
        if bindings:
            if workdir is None:
                raise Blocked('artifact packaging requires the external deployment session directory')
            for artifact, container, prop, fields in bindings:
                obj = upload(placement, file_digest, source_path(placement.root, artifact), artifact['bucket'],
                             artifact['keyPrefix'], boundary, consume_version=bool(fields))
                objects.append(obj)
                if fields:
                    container[prop][fields[1]] = obj['key']
                    container[prop].pop(fields[2], None)
                    if obj.get('version'):
                        container[prop][fields[2]] = obj['version']
                else:
                    container[prop] = f"s3://{obj['bucket']}/{obj['key']}"
            workdir.mkdir(parents=True, exist_ok=True)
            path = workdir / (unit['name'] + '.json')
            path.write_text(json.dumps(document, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    size = path.stat().st_size
    if size > 1024 * 1024:
        raise Blocked('template exceeds the 1 MiB CloudFormation limit')
    record = {'inputDigest': input_digest, 'path': str(path), 'templateSha256': file_digest(path),
              'objects': objects, 'imports': imports}
    state['delivery'] = record
    placement.save()
    if stage_only:
        return {}
    arguments = {'TemplateBody': path.read_text(encoding='utf-8')}
    if size > 51200:
        if not unit.get('templateBucket') or not unit.get('templateKeyPrefix'):
            raise Blocked('large template requires designed TemplateBucket and TemplateKeyPrefix')
        obj = upload(placement, file_digest, path, unit['templateBucket'], unit['templateKeyPrefix'], boundary, consume_version=True)
        objects.append(obj)
        suffix = 'amazonaws.com.cn' if placement.target['awsRegion'].startswith('cn-') else 'amazonaws.com'
        url = f"https://s3.{placement.target['awsRegion']}.{suffix}/{obj['bucket']}/{quote(obj['key'], safe='/')}"
        if obj.get('version'):
            url += '?' + urlencode({'versionId': obj['version']})
        arguments = {'TemplateURL': url}
    if input_digest_for(unit) != input_digest:
        raise Blocked('deployment inputs changed while preparing artifacts')
    # Do not persist TemplateBody (may contain NoEcho defaults or other sensitive inputs).
    record['arguments'] = arguments if 'TemplateURL' in arguments else {'inline': True}
    placement.save()
    return arguments
