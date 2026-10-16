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

from model_display import display_rows

from model_core import entries

from model_files import load_model

from model_design import resource_table_lines

from model_references import resource_rows

from model_templates import expand

from script_loader import module

from support.model_sources import write_model

from validation_cache import input_scope

ROOT = Path(__file__).resolve().parents[4]

m = module('check-model-aws.py', 'model_aws_compare')

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


__all__ = ['BASELINE', 'CHANNEL', 'FrozenInstanceError', 'Path', 'RECORDER', 'ROOT', 'SimpleNamespace', 'TemporaryDirectory', 'astuple', 'aws_mapping', 'copy', 'display_rows', 'entries', 'expand', 'hashlib', 'input_scope', 'json', 'load_model', 'm', 'module', 'patch', 'resource_rows', 'resource_table_lines', 'socket', 'sys', 'write_model']
