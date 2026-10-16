"""P5 independent display fixtures; never copy consumer Models or use AWS."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from tempfile import TemporaryDirectory

import copy

import json

import shutil

import socket

from unittest.mock import patch

import yaml

from aws_mapping_display import projection, ROOT, selected_rows

from design_layout import resource_anchor

from model_core import properties, entries

from model_design import markdown_for

from model_projection import model_for

from sync_views import validate_views

from support.model_sources import write_model, snapshot_model

def fixture(service, kind, name, rows):
    values = {f'desired.service.{service}.serviceId': service,
              f'desired.service.{service}.ownedCatalogResourceTypes': kind,
              'display.service.title': '# 独立した表示fixture',
              'desired.resource.007.resourceType': kind,
              'desired.resource.007.logicalId': 'Fixture',
              'desired.resource.007.anchor': resource_anchor(service, name, kind),
              'desired.resource.007.resourceMode': 'IMPORT',
              'display.resource.007.comment': '表示設定を検証するresource'}
    for number, (prop, value) in enumerate(rows, 11):
        key = f'desired.row.007-{number:03d}'
        values.update({key + '.property': kind + '.' + prop, key + '.value': value, key + '.comment': '独立fixtureの設定値'})
    return values

def change(root, service, kind, prop, **display):
    path = root / 'framework/mappings/aws' / (service + '.yaml')
    document = yaml.safe_load(path.read_text(encoding='utf-8'))
    document['resourceTypes'][kind]['properties'][prop]['display'].update(display)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding='utf-8')


__all__ = ['Path', 'ROOT', 'TemporaryDirectory', 'change', 'copy', 'entries', 'fixture', 'json', 'markdown_for', 'model_for', 'patch', 'projection', 'properties', 'resource_anchor', 'selected_rows', 'shutil', 'snapshot_model', 'socket', 'sys', 'validate_views', 'write_model', 'yaml']
