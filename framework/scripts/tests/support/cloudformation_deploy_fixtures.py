"""Deterministic scheduler and AWS CLI adapter regression checks (no live AWS)."""

import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import base64
import copy
import hashlib
import importlib.util
import io
import json
import shutil
import time
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from threading import Barrier, get_ident
from types import SimpleNamespace
from unittest.mock import patch

import model.format as _imports_model_format
import model.projection as model_projection
import pytest
import sync_views
import utils.aws.client as _imports_utils_aws_client
from deploy import controller as M
from deploy import scheduler
from deploy.s3_delivery import ALGORITHM, KEY
from design.layout import stack_delivery
from model.core import deployment_settings, entries, properties, stack_model
from model.files import read_model
from model.format import JSON_LINK
from model.projection import deployment_bucket
from model.render import markdown_for
from model.sources import model_parts
from support.model_sources import snapshot_model, write_fixture_files, write_model
from support.pytest_cli import run
from support.validator import load
from utils.aws.client import AwsError

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

_production_runtime = M.create_runtime

class Runtime:
    def __init__(self, *args, **kwargs):
        runtime = _production_runtime(*args, **kwargs)
        self.__dict__.update(runtime.__dict__)
        for name, value in runtime.__dict__.items():
            if isinstance(value, partial):
                if hasattr(type(self), name):
                    del self.__dict__[name]
                else:
                    setattr(self, name, partial(value.func, self))

for _name in ('template_arguments', 'prepare_delivery_group', 'repair', 'poll', 'execute', 'load_inputs'):
    setattr(Runtime, _name, getattr(M, _name))


ROOT = Path(__file__).resolve().parents[4]

TARGET = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}

def units(*orders):
    return [{"name": chr(65 + i), "template": "app.yaml", "parameters": chr(97 + i) + ".json", "deployOrder": str(order)}
            for i, order in enumerate(orders)]

def states(units):
    return {unit["name"]: {"status": "NOT_STARTED"} for unit in units}

def rejects(call, text):
    with pytest.raises((ValueError, M.Blocked)) as error:
        call()
    assert text in str(error.value), error.value

class Fake:
    def __init__(self, completions=None, blocked=()):
        self.events, self.running, self.peak = [], set(), 0
        self.completions = {key: list(values) for key, values in (completions or {}).items()}
        self.blocked = set(blocked)

    def prepare(self, unit, state):
        self.events.append(("prepare", unit["name"], unit["template"], unit["parameters"]))
        state["changeSetId"] = "cs-" + unit["name"]
        return "BLOCKED" if unit["name"] in self.blocked else "READY"

    def execute(self, unit, state):
        name = unit["name"]
        self.running.add(name)
        self.peak = max(self.peak, len(self.running))
        self.events.append(("start", name, state["changeSetId"]))

    def poll(self, unit, state):
        name = unit["name"]
        sequence = self.completions.get(name, ["CREATE_COMPLETE"])
        result = sequence.pop(0) if len(sequence) > 1 else sequence[0]
        if result in scheduler.SUCCESS | scheduler.FAILED:
            self.running.remove(name)
        self.events.append(("poll", name, result))
        return result

def starts(fake):
    return [event[1] for event in fake.events if event[0] == "start"]

def finish(units, limit, state, fake):
    for _ in range(10):
        outcome = scheduler.run_group(units, limit, state, fake, sleep=lambda _: None)
        if outcome != "GROUP_COMPLETE":
            return outcome
    raise AssertionError("groups did not complete")

class StubAws(Runtime):
    def __init__(self, exports=(), destructive=False):
        super().__init__(ROOT, "dev", "123456789012", TARGET)
        self.exports, self.calls = list(exports), []
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        for unit in units(10, 10, 10, 10):
            template, parameters = self.paths(unit)
            template.parent.mkdir(parents=True, exist_ok=True)
            parameters.parent.mkdir(parents=True, exist_ok=True)
            template.write_text('Resources: {}')
            parameters.write_text('[]')
        self.change = {"Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE", "Changes": [
            {"ResourceChange": {"LogicalResourceId": "App", "ResourceType": "AWS::S3::Bucket",
                                "Action": "Remove" if destructive else "Add"}}]}

    def prepare_delivery_group(self, units, states):
        pass  # Scheduler/CFn adapter tests replace delivery; DeliveryAws exercises the real barrier.

    def template_arguments(self, unit, state, **kwargs):
        return {'TemplateBody': 'Resources: {}'}

    def aws(self, operation, **arguments):
        self.calls.append((operation, dict(arguments)))
        if operation == 'list_exports':
            return {'Exports': [{'Name': name, 'Value': 'export-value',
                                'ExportingStackId': 'arn:aws:cloudformation:ap-northeast-1:123456789012:stack/External/id'} for name in self.exports]}
        if operation == 'describe_stacks':
            AwsError = _imports_utils_aws_client.AwsError
            raise AwsError('cloudformation', operation, 'ValidationError', stack_absent=True)
        if operation == 'create_change_set':
            return {'Id': 'cs-' + arguments['StackName'], 'StackId': 'stackid-' + arguments['StackName']}
        if operation == 'describe_change_set':
            name = arguments['ChangeSetName'].removeprefix('cs-')
            return json.loads(json.dumps(self.change)) | {'ChangeSetId': 'cs-' + name, 'StackId': 'stackid-' + name}
        if operation == 'list_stack_resources':
            return {'StackResourceSummaries': []}
        if operation in {'execute_change_set', 'validate_template'}:
            return {}
        raise AssertionError(operation)

class DeliveryAws(StubAws):
    template_arguments = Runtime.template_arguments
    prepare_delivery_group = Runtime.prepare_delivery_group

    def __init__(self, root, workdir, destructive=False):
        super().__init__(destructive=destructive)
        self.root, self.workdir = root, workdir
        self.objects, self.region, self.fail = {}, "ap-northeast-1", None
        self.export_values = {}
        self.default_algorithm, self.default_key, self.policy = 'AES256', None, None
        self.key_arn = 'arn:aws:kms:ap-northeast-1:123456789012:key/test-key'
        self.key_state, self.key_enabled = 'Enabled', True
        root.mkdir(parents=True, exist_ok=True)
        project = root / 'project.json'
        if not project.exists():
            project.write_text(json.dumps({'targets': [{'environment': 'dev', **TARGET}]}) + '\n')
        # Fixture-owned authoritative models; no consumer files or live AWS.
        for bucket in ('app-dev-assets', 'app-dev-other'):
            self.add_bucket(bucket)

    def add_bucket(self, bucket, algorithm='AES256', key=None, delegation=False):
        path = self.root / 'model/dev/123456789012/s3.properties'
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = properties(read_model(path)) if path.is_file() else {}
        identities = {r['logicalId']: i for i, r in entries(existing, 'desired.resource.')}
        identity = next((i.split('-')[0] for i, row in entries(existing, 'desired.row.')
                         if row.get('property') == 'S3.Bucket.BucketName' and row.get('value', '').strip('`') == bucket),
                        f'{len(identities) + 1:03d}')
        values = {k: v for k, v in existing.items() if not k.startswith((f'desired.resource.{identity}.', f'desired.row.{identity}-'))}
        values.update({f'desired.resource.{identity}.resourceType': 'S3.Bucket',
                       f'desired.resource.{identity}.logicalId': 'S3_Bucket_' + identity,
                       f'desired.resource.{identity}.anchor': 'resource-S3_Bucket_' + identity,
                       'desired.service.identity.lastAllocated': json.dumps({'S3.Bucket': max(int(identity), len(identities))})})
        if delegation:
            values[f'desired.resource.{identity}.deploymentEncryption'] = 'default'
        rows = [('BucketName', bucket), ('Region', self.region), (ALGORITHM, algorithm)]
        if key:
            rows.append((KEY, key))
        for number, (prop, value) in enumerate(rows, 1):
            values[f'desired.row.{identity}-{number:03d}.property'] = 'S3.Bucket.' + prop
            values[f'desired.row.{identity}-{number:03d}.value'] = value
            values[f'desired.row.{identity}-{number:03d}.comment'] = '合成配置設定'
        write_model(path, '\n'.join(f'{k}={v}' for k, v in values.items()))

    def aws(self, operation, service='cloudformation', **arguments):
        if service == 'cloudformation':
            if operation == 'list_exports' and self.export_values:
                self.calls.append((operation, dict(arguments)))
                return {'Exports': [{'Name': name, 'Value': value,
                    'ExportingStackId': 'arn:aws:cloudformation:ap-northeast-1:123456789012:stack/External/id'} for name, value in self.export_values.items()]}
            return super().aws(operation, **arguments)
        self.calls.append((operation, dict(arguments)))
        if self.fail == operation:
            raise AwsError(service, operation, 'AccessDenied', 403)
        if service == 'kms':
            assert operation == 'describe_key'
            key = arguments['KeyId']
            arn = self.key_arn if key in ('test-key', 'alias/test', self.key_arn) else key if key.startswith('arn:') else self.key_arn.replace('test-key', key)
            return {'KeyMetadata': {'Arn': arn, 'KeyId': arn.split('key/')[-1], 'AWSAccountId': arn.split(':')[4],
                    'KeyState': self.key_state, 'Enabled': self.key_enabled, 'KeyUsage': 'ENCRYPT_DECRYPT', 'KeySpec': 'SYMMETRIC_DEFAULT'}}
        assert arguments['ExpectedBucketOwner'] == TARGET['awsAccountId']
        if operation == 'head_bucket':
            return {}
        if operation == 'get_bucket_encryption':
            default = {'SSEAlgorithm': self.default_algorithm}
            if self.default_key:
                default['KMSMasterKeyID'] = self.default_key
            return {'ServerSideEncryptionConfiguration': {'Rules': [{'ApplyServerSideEncryptionByDefault': default}]}}
        if operation == 'get_bucket_policy':
            if self.policy is None:
                raise AwsError('s3', operation, 'NoSuchBucketPolicy', 404)
            return {'Policy': json.dumps(self.policy)}
        if operation == 'get_bucket_location':
            return {'LocationConstraint': self.region}
        bucket, key = arguments['Bucket'], arguments['Key']
        if operation == 'put_object':
            assert arguments['IfNoneMatch'] == '*'
            if (bucket, key) in self.objects:
                raise AwsError('s3', operation, 'PreconditionFailed', 412)
            data = arguments['Body'].read()
            checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
            assert checksum == arguments['ChecksumSHA256']
            self.objects[bucket, key] = {'ChecksumSHA256': checksum, 'ContentLength': len(data), 'VersionId': 'version+1', 'data': data,
                                      'ServerSideEncryption': arguments.get('ServerSideEncryption', self.default_algorithm)}
            if self.objects[bucket, key]['ServerSideEncryption'] == 'aws:kms':
                self.objects[bucket, key]['SSEKMSKeyId'] = self.key_arn
        if (bucket, key) not in self.objects:
            raise AwsError('s3', operation, 'NotFound', 404)
        return self.objects[bucket, key]


__all__ = ['Runtime', 'subprocess', 'Barrier', 'DeliveryAws', 'Fake', 'M', 'Path', 'ROOT', 'SimpleNamespace', 'StubAws', 'TARGET', 'base64', 'copy', 'deployment_bucket', 'deployment_settings', 'finish', 'get_ident', 'hashlib', 'importlib', 'io', 'json', 'load', 'markdown_for', 'model_projection', 'patch', 'properties', 'pytest', 'read_model', 'redirect_stderr', 'redirect_stdout', 'rejects', 'run', 'scheduler', 'shutil', 'snapshot_model', 'stack_delivery', 'stack_model', 'starts', 'states', 'sync_views', 'sys', 'time', 'units', 'write_fixture_files', 'write_model', 'zipfile']


def remove_model(path):
    for file in model_parts(path):
        file.unlink()
    path.unlink(missing_ok=True)

__all__.append('remove_model')


def observation_contract(root, services):
    files = {'tasks/observation-fixture.md', 'project.json'}
    for service in services:
        source = root / 'model/dev/123456789012' / (service + '.properties')
        files.add(source.relative_to(root).as_posix())
        files.update((source.with_suffix('') / ('part-' + str(number).zfill(3) + '.properties')).relative_to(root).as_posix()
                     for number in (1, 2, 3))
        view = root / 'docs/designs/dev/123456789012' / (service + '.md')
        files.add(view.relative_to(root).as_posix())
        if source.is_file():
            files.update(file.relative_to(root).as_posix() for file in model_parts(source))
            parse = _imports_model_format.parse
            values = {key: value for part in model_parts(source) for key, value in parse(part.read_text()).values.items()}
            for _, row in entries(values, 'desired.row.'):
                if match := JSON_LINK.fullmatch(row['value']):
                    files.add((view.parent / match[1]).relative_to(root).as_posix())
    listed = ''.join('- `' + file + '`\n' for file in sorted(files))
    text = ('## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `update`\n'
            '- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n'
            '## Required changes\n- [R1] Synthetic selected observation\n'
            '## Acceptance checks\n- [R1] `exists:project.json`\n## Validation scope\n')
    text += ''.join('- `dev/123456789012/' + service + '`\n' for service in services)
    for heading in ('Modified files', 'Allowed paths'):
        text += '## ' + heading + '\n' + listed
    return text

__all__.append('observation_contract')
