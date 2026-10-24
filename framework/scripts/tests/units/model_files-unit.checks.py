#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from model.files import resource_keys
from support.model_files_fixtures import (
    Path,
    sys,
)
from support.pytest_cli import run

from model import sources

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_cfn_selector():
    text = 'desired.resource.007.resourceType=EC2.VPC\ndesired.resource.007.logicalId=EC2_VPC_001\ndesired.service.identity.lastAllocated={"EC2.VPC":1}\ndesired.resource.007.cfn-logicalId=cfn-stack-app-dev-network-Vpc\n'
    assert resource_keys(text, '007') == resource_keys(text, 'EC2_VPC_001')
    for selector in ('ec2-network', 'cfn-stack-app-dev-network-Vpc'):
        with pytest.raises(ValueError):
            resource_keys(text, selector)



def check_cli_entrypoints():
    scripts = Path(__file__).resolve().parents[2]
    direct = subprocess.run([sys.executable, '-B', str(scripts / 'model/cli.py'), '--help'],
                            capture_output=True, text=True, check=True)
    imported = subprocess.run([sys.executable, '-B', '-c',
                               "import sys; sys.argv[0] = 'cli.py'; from model.cli import main; main(['--help'])"], cwd=scripts,
                              capture_output=True, text=True, check=True)
    assert direct.stdout == imported.stdout
    module = subprocess.run([sys.executable, '-B', '-m', 'model.cli', '--help'], cwd=scripts,
                            capture_output=True, text=True, check=True)
    assert module.stdout == ''  # Preserve the existing module execution contract.


def check_journal_precedes_publication(tmp_path: Path) -> None:
    destination = tmp_path / 'model.properties'
    destination.write_bytes(b'old\r\n')
    record = {'root': str(tmp_path.resolve()), 'originals': {'model.properties': 'b2xkDQo='}}
    calls = Mock()
    with sources.publication_lock(tmp_path) as journal:
        with patch.object(sources, 'atomic_replace_file', wraps=sources.atomic_replace_file) as save, \
                patch.object(sources.sync_files, 'save_files', wraps=sources.sync_files.save_files) as publish:
            calls.attach_mock(save, 'journal')
            calls.attach_mock(publish, 'model')
            sources._publish_transaction(tmp_path, {destination: 'new\n'}, (), journal)
        save.assert_called_once_with(journal, sources.json_text(record), fsync=True, mode=0o666)
        assert [call[0] for call in calls.mock_calls] == ['journal', 'model']
        assert not journal.exists()
    with sources.publication_lock(tmp_path) as journal:
        with patch.object(sources, 'atomic_replace_file', side_effect=OSError('journal save')), \
                patch.object(sources.sync_files, 'save_files') as publish, pytest.raises(OSError, match='journal save'):
            sources._publish_transaction(tmp_path, {destination: 'unpublished'}, (), journal)
        publish.assert_not_called()
        assert not journal.exists()


if __name__ == '__main__':
    raise SystemExit(run(__file__))
