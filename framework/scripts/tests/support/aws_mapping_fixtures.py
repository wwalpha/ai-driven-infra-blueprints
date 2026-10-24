"""Offline Mapping and Config regressions with synthetic Config data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import copy
import hashlib
import json
import socket
from dataclasses import FrozenInstanceError, astuple
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import aws_mapping
from model.core import entries
from model.display import display_rows
from model.files import load_model
from model.projection import resource_rows
from model.render import resource_table_lines
from support.model_sources import write_model
from utils.input_cache import input_scope
from utils.script_loader import module

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

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
