"""Offline Mapping and Config regressions with synthetic Config data."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from dataclasses import FrozenInstanceError, astuple

import hashlib

from tempfile import TemporaryDirectory

from types import SimpleNamespace

from unittest.mock import patch

import copy

import json

import socket

import aws_mapping

from model.display import display_rows

from model.core import entries

from model.files import load_model

from model.render import resource_table_lines

from model.projection import resource_rows

from script_loader import module

from support.model_sources import write_model

from validation_cache import input_scope

ROOT = Path(__file__).resolve().parents[4]

m = module('model/adapters/aws.py', 'model.adapters.aws')

RECORDER = 'Config.ConfigurationRecorder'

CHANNEL = 'Config.DeliveryChannel'

BASELINE = {
    RECORDER: {
        'Id': ('name', 'typed', m.MISSING),
        'Name': ('name', 'typed', m.MISSING),
        'RecordingGroup.AllSupported': ('recordingGroup.allSupported', 'typed', m.MISSING),
        'RecordingGroup.ExclusionByResourceTypes.ResourceTypes': ('recordingGroup.exclusionByResourceTypes.resourceTypes', 'set', []),
        'RecordingGroup.IncludeGlobalResourceTypes': ('recordingGroup.includeGlobalResourceTypes', 'typed', m.MISSING),
        'RecordingGroup.RecordingStrategy.UseOnly': ('recordingGroup.recordingStrategy.useOnly', 'typed', m.MISSING),
        'RecordingGroup.ResourceTypes': ('recordingGroup.resourceTypes', 'set', []),
        'RecordingMode.RecordingFrequency': ('recordingMode.recordingFrequency', 'typed', m.MISSING),
        'RoleARN': ('roleARN', 'iam_role', m.MISSING),
    },
    CHANNEL: {'Name': ('name', 'typed', m.MISSING), 'S3BucketName': ('s3BucketName', 'name', m.MISSING)},
}


__all__ = ['BASELINE', 'CHANNEL', 'FrozenInstanceError', 'Path', 'RECORDER', 'ROOT', 'SimpleNamespace', 'TemporaryDirectory', 'astuple', 'aws_mapping', 'copy', 'display_rows', 'entries', 'hashlib', 'input_scope', 'json', 'load_model', 'm', 'module', 'patch', 'resource_rows', 'resource_table_lines', 'socket', 'sys', 'write_model']


def mapping_fixture(root, *services):
    """Copy selected static definitions and their pinned validation authorities only."""
    from shutil import copyfile
    index = json.loads((ROOT / 'framework/mappings/aws/owners.json').read_text(encoding='utf-8'))
    owners = {kind: service for kind, service in index.items() if service in services}
    schema = Path('framework/materials/cloudformation-schema/ap-northeast-1')
    schemas = json.loads((ROOT / schema / 'index.json').read_text(encoding='utf-8'))['resourceTypes']
    paths = {Path('framework/mappings/aws') / (service + '.yaml') for service in services}
    paths.add(schema / 'index.json')
    for kind in owners:
        name = kind.replace('.', '_', 1)
        paths.add(Path('framework/materials/aws') / (name + '.properties'))
        paths.add(schema / schemas['AWS::' + kind.replace('.', '::', 1)])
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copyfile(ROOT / relative, target)
    (root / 'framework/mappings/aws/owners.json').write_text(json.dumps(owners), encoding='utf-8')
    return root


__all__ += ['mapping_fixture']
