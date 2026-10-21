"""Deterministic scheduler and AWS CLI adapter regression checks (no live AWS)."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from support.model_sources import snapshot_model

from model.files import read_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model, write_fixture_files

import pytest

from support.pytest_cli import run

import copy

from deployment import scheduler

import sync_views

import model.projection as model_projection

import importlib.util

import json

import hashlib

import base64

import zipfile

import io

import shutil

import time

from threading import Barrier, get_ident

from contextlib import redirect_stdout, redirect_stderr

from support.validator import load

from unittest.mock import patch

from types import SimpleNamespace

from model.render import markdown_for

from model.projection import deployment_bucket

from model.core import stack_model, deployment_settings, properties

from design_layout import stack_delivery

M = load('cloudformation-deploy')

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

class StubAws(M.AwsBackend):
    def __init__(self, exports=(), destructive=False):
        super().__init__(ROOT, "dev", "123456789012", TARGET)
        self.exports, self.calls = list(exports), []
        self.change = {"Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE", "Changes": [
            {"ResourceChange": {"LogicalResourceId": "App", "ResourceType": "AWS::S3::Bucket",
                                "Action": "Remove" if destructive else "Add"}}]}

    def prepare_delivery_group(self, units, states):
        pass  # Scheduler/CFn adapter tests replace delivery; DeliveryAws exercises the real barrier.

    def template_arguments(self, unit, state):
        return ["--template-body", "file://" + str(self.paths(unit)[0])]

    def aws(self, operation, *arguments):
        self.calls.append((operation, arguments))
        if operation == "list-exports":
            return {"Exports": [{"Name": name} for name in self.exports]}
        if operation == "describe-stacks":
            raise M.Blocked("Stack does not exist")
        if operation == "create-change-set":
            return {"Id": "cs-" + arguments[1]}
        if operation == "describe-change-set":
            return json.loads(json.dumps(self.change))
        if operation == "execute-change-set":
            return {}
        if operation == "validate-template":
            return {}
        raise AssertionError(operation)

class DeliveryAws(StubAws):
    template_arguments = M.AwsBackend.template_arguments
    prepare_delivery_group = M.AwsBackend.prepare_delivery_group

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
        from model.core import entries
        identities = {r['logicalId']: i for i, r in entries(existing, 'desired.resource.')}
        identity = next((i.split('-')[0] for i, row in entries(existing, 'desired.row.')
                         if row.get('property') == 'S3.Bucket.BucketName' and row.get('value', '').strip('`') == bucket),
                        f'{len(identities) + 1:03d}')
        values = {k: v for k, v in existing.items() if not k.startswith((f'desired.resource.{identity}.', f'desired.row.{identity}-'))}
        values.update({f'desired.resource.{identity}.resourceType': 'S3.Bucket',
                       f'desired.resource.{identity}.logicalId': bucket,
                       f'desired.resource.{identity}.anchor': 's3-' + bucket})
        if delegation:
            values[f'desired.resource.{identity}.deploymentEncryption'] = 'default'
        from s3_delivery import ALGORITHM, KEY
        rows = [('BucketName', bucket), ('Region', self.region), (ALGORITHM, algorithm)]
        if key:
            rows.append((KEY, key))
        for number, (prop, value) in enumerate(rows, 1):
            values[f'desired.row.{identity}-{number:03d}.property'] = 'S3.Bucket.' + prop
            values[f'desired.row.{identity}-{number:03d}.value'] = value
            values[f'desired.row.{identity}-{number:03d}.comment'] = '合成配置設定'
        write_model(path, '\n'.join(f'{k}={v}' for k, v in values.items()))

    def aws(self, operation, *arguments, service="cloudformation"):
        if service == "cloudformation":
            if operation == "list-exports" and self.export_values:
                self.calls.append((operation, arguments))
                return {"Exports": [{"Name": name, "Value": value} for name, value in self.export_values.items()]}
            return super().aws(operation, *arguments)
        self.calls.append((operation, arguments))
        if self.fail == operation:
            raise M.Blocked("simulated S3 permission/upload failure")
        if service == 'kms':
            assert operation == 'describe-key'
            key = arguments[arguments.index('--key-id') + 1]
            arn = self.key_arn if key in ('test-key', 'alias/test', self.key_arn) else key if key.startswith('arn:') else self.key_arn.replace('test-key', key)
            return {'KeyMetadata': {'Arn': arn, 'KeyId': arn.split('key/')[-1], 'AWSAccountId': arn.split(':')[4],
                    'KeyState': self.key_state, 'Enabled': self.key_enabled, 'KeyUsage': 'ENCRYPT_DECRYPT', 'KeySpec': 'SYMMETRIC_DEFAULT'}}
        assert arguments[arguments.index("--expected-bucket-owner") + 1] == TARGET["awsAccountId"]
        if operation == 'head-bucket':
            return {}
        if operation == 'get-bucket-encryption':
            default = {'SSEAlgorithm': self.default_algorithm}
            if self.default_key:
                default['KMSMasterKeyID'] = self.default_key
            return {'ServerSideEncryptionConfiguration': {'Rules': [{'ApplyServerSideEncryptionByDefault': default}]}}
        if operation == 'get-bucket-policy':
            if self.policy is None:
                raise M.Blocked('(NoSuchBucketPolicy)')
            return {'Policy': json.dumps(self.policy)}
        if operation == "get-bucket-location":
            return {"LocationConstraint": self.region}
        bucket, key = (arguments[arguments.index(flag) + 1] for flag in ("--bucket", "--key"))
        if operation == "put-object":
            assert arguments[arguments.index("--if-none-match") + 1] == "*"
            if (bucket, key) in self.objects:
                raise M.Blocked("(PreconditionFailed)")
            data = Path(arguments[arguments.index("--body") + 1]).read_bytes()
            checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
            assert checksum == arguments[arguments.index("--checksum-sha256") + 1]
            self.objects[bucket, key] = {"ChecksumSHA256": checksum, "ContentLength": len(data), "VersionId": "version+1", "data": data,
                                      'ServerSideEncryption': arguments[arguments.index('--server-side-encryption') + 1] if '--server-side-encryption' in arguments else self.default_algorithm}
            if self.objects[bucket, key]['ServerSideEncryption'] == 'aws:kms':
                self.objects[bucket, key]['SSEKMSKeyId'] = self.key_arn
        if (bucket, key) not in self.objects:
            raise M.Blocked("(404)")
        return self.objects[bucket, key]


__all__ = ['Barrier', 'DeliveryAws', 'Fake', 'M', 'Path', 'ROOT', 'SimpleNamespace', 'StubAws', 'TARGET', 'base64', 'copy', 'deployment_bucket', 'deployment_settings', 'finish', 'get_ident', 'hashlib', 'importlib', 'io', 'json', 'load', 'markdown_for', 'model_projection', 'patch', 'properties', 'pytest', 'read_model', 'redirect_stderr', 'redirect_stdout', 'rejects', 'run', 'scheduler', 'shutil', 'snapshot_model', 'stack_delivery', 'stack_model', 'starts', 'states', 'sync_views', 'sys', 'time', 'units', 'write_fixture_files', 'write_model', 'zipfile']


def remove_model(path):
    from model.sources import model_parts
    for file in model_parts(path):
        file.unlink()
    path.unlink(missing_ok=True)

__all__.append('remove_model')


def observation_contract(root, services):
    files = {'tasks/observation-fixture.md'}
    from model.sources import model_parts
    from model.core import entries
    from model.projection import JSON_LINK
    for service in services:
        source = root / 'model/dev/123456789012' / (service + '.properties')
        files.add(source.relative_to(root).as_posix())
        files.update((source.with_suffix('') / ('part-' + str(number).zfill(3) + '.properties')).relative_to(root).as_posix()
                     for number in (1, 2, 3))
        view = root / 'docs/designs/dev/123456789012' / (service + '.md')
        files.add(view.relative_to(root).as_posix())
        if source.is_file():
            files.update(file.relative_to(root).as_posix() for file in model_parts(source))
            from model.format import parse
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
