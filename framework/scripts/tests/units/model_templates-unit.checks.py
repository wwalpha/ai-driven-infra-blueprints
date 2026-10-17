#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_templates_fixtures import *

def check_template_syntax(root):
    template = common_shape_template(root)
    original=template.read_text(encoding='utf-8')
    for malformed in (original.replace('/Statement/1','/Statement/-1'),
                      original.replace('/Statement/1','/Statement/01'),
                      original.replace('/Statement/1','/Statement/~2'),
                      original.replace('"pointer":"/Value"','"pointer":null'),
                      original.replace('# choice: desired.row.config.value', '# choice: desired.row.config.value {"parameter":"AlternateAnchor","value":"other"}\n# choice: desired.row.config.value'),
                      original.replace('desired.resource.bucket.logicalId HasLogicalId','desired.resource.bucket.unknown HasLogicalId'),
                      original.replace('HasLogicalId boolean','HasLogicalId string')):
        template.write_text(malformed,encoding='utf-8')
        rejected(lambda:templates.parse_template(template))



def check_publish_callback_rollback(tmp_path):
    path = tmp_path/'view.md'
    path.write_bytes(b'original\r\n')
    called = []
    def finish_import():
        called.append(path.read_bytes())
        raise ValueError('injected completion callback failure')
    with pytest.raises(ValueError, match='completion callback'):
        templates.publish(tmp_path, {path: 'changed\n'}, inputs={}, verify=finish_import)
    assert called == [b'changed\r\n']
    assert path.read_bytes() == b'original\r\n'
    with templates.publication_lock(tmp_path) as journal:
        assert not journal.exists()


def check_generation_transaction_recovery(tmp_path):
    first, created = tmp_path/'view.md', tmp_path/'artifact.json'
    first.write_bytes(b'original\r\n')
    originals = {first: first.read_bytes(), created: None}
    write = Path.write_text
    def interrupted(path, *args, **kwargs):
        result = write(path, *args, **kwargs)
        if path == created:
            raise KeyboardInterrupt()
        return result
    with templates.publication_lock(tmp_path) as journal:
        with patch.object(Path, 'write_text', interrupted), pytest.raises(KeyboardInterrupt):
            templates._publish_transaction(tmp_path, {first: 'changed\n', created: '{}\n'}, (), journal,
                                           originals=originals)
        assert journal.is_file()
    # Recovery precedes the next generation snapshot and its originals/output differences.
    with templates.publication_lock(tmp_path) as journal:
        assert first.read_bytes() == originals[first] and not created.exists()
        assert not journal.exists()
    with templates.publication_lock(tmp_path) as journal:
        with patch.object(Path, 'write_text', side_effect=OSError('injected I/O')), pytest.raises(OSError):
            templates._publish_transaction(tmp_path, {first: 'changed\n'}, (), journal,
                                           originals={first: originals[first]})
        assert first.read_bytes() == originals[first] and not journal.exists()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
