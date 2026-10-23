"""P5 independent display fixtures; never copy consumer Models or use AWS."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json
import shutil
import socket
from tempfile import TemporaryDirectory
from unittest.mock import patch

from model.render import markdown_for
from support.model_sources import snapshot_model, write_model
from sync_views import validate_views
from utils.layout_schema import resource_anchor

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def fixture(service, kind, name, rows):
    values = {f'desired.service.{service}.serviceId': service,
              f'desired.service.{service}.ownedCatalogResourceTypes': kind,
              'display.service.title': '# 独立した表示fixture',
              'desired.resource.007.resourceType': kind,
              'desired.resource.007.anchor': resource_anchor(service, name, kind),
              'desired.resource.007.logicalId': kind.replace('.', '_') + '_001',
              'desired.service.identity.lastAllocated': json.dumps({kind: 1}),
              'desired.resource.007.resourceMode': 'IMPORT',
              'display.resource.007.comment': '表示設定を検証するresource'}
    for number, (prop, value) in enumerate(rows, 11):
        key = f'desired.row.007-{number:03d}'
        values.update({key + '.property': kind + '.' + prop, key + '.value': value, key + '.comment': '独立fixtureの設定値'})
    return values


__all__ = ['Path', 'TemporaryDirectory', 'fixture', 'json', 'markdown_for', 'patch', 'resource_anchor', 'shutil', 'snapshot_model', 'socket', 'sys', 'validate_views', 'write_model']
