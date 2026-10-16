#!/usr/bin/env python3
"""API-only comparison stays partial; implementation type resolution still fails."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
from collections import Counter
import json
import subprocess
import tempfile
from unittest.mock import patch

from design_catalog import DesignSchemaCatalog
from issues_iac import Comparison
from issues_reports import iac_summary, iac_report
from issues_scan import main, summary
from support.validator import load

ROOT = Path(__file__).resolve().parents[4]


def main_checks():
    fixtures = load('issues_scan.checks', 'api_only_scan_fixtures')
    with tempfile.TemporaryDirectory(prefix='issues-api-only-') as temporary:
        root = Path(temporary) / 'project'
        fixtures.fixture(root, services=('s3',))
        baseline = Comparison(root, 'dev', '123456789012', ['s3']).run()
        assert baseline and any(item['category'] == 'matched' for item in baseline), baseline
        assert all(item['category'] in {'matched', 'excluded'} for item in baseline), baseline
        baseline_counts = Counter(item['category'] for item in baseline)
        catalog = DesignSchemaCatalog(root)
        for kind in catalog.api_schemas:
            comparison = Comparison(root, 'dev', '123456789012', ['s3'])
            comparison.resources['s3']['002'] = {'resourceType': kind}
            records = comparison.run()
            api = next(item for item in records if item['resource'] == '002')
            assert api['category'] == 'uncompared', api
            assert api['cause'] == {'kind': 'cloudformation-unsupported', 'resource_type': kind,
                                    'implementation_status': 'unverified'}, api
            stats = iac_summary(records, 'dev', '123456789012', ['s3'])
            assert stats['records'] == dict(difference=0, uncompared=1, error=0,
                                           matched=baseline_counts['matched'], excluded=baseline_counts['excluded']), stats
            assert stats['categories']['CFn非対応・比較対象外'] == 1, stats
            assert stats['categories']['処理エラー'] == stats['categories']['原因未確定'] == 0
            assert stats['proven_causes'] == 1
            artifact = dict(iac=records, ordinary=[], judgments=[], naming={'names': []})
            assert summary(artifact)['iac_status'] == 'partial'
            for selected in (records, [api]):
                report = iac_report('dev', '123456789012', ['s3'], selected)
                assert '今回の判定: partial' in report
                assert 'CFn非対応・比較対象外' in report and 'API側の実装状態は未確認' in report
                assert '完了' in report and '実装scope' in report
                assert 'complete match' not in report and '## 処理エラー' not in report
            try:
                catalog.cloudformation_type(kind)
            except ValueError as error:
                assert 'implementation remains incomplete if this resource is in scope' in str(error)
            else:
                raise AssertionError('API resource accepted as implemented CFn')
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'framework/scripts/design_catalog.py'),
                                     '--repository-root', str(root), '--cloudformation-type', kind],
                                    capture_output=True, text=True)
            assert result.returncode == 1 and 'CloudFormation unsupported' in result.stdout, result
            cli_exit(root, Path(temporary), artifact, 0)

        for resource in ({'resourceType': 'Macie.Unknown'}, {}, {'resourceType': []}):
            comparison = Comparison(root, 'dev', '123456789012', ['s3'])
            comparison.resources['s3']['002'] = resource
            records = comparison.run()
            failure = next(item for item in records if item['resource'] == '002')
            assert failure['category'] == 'error' and failure.get('cause', {}).get('kind') != 'cloudformation-unsupported', failure
            assert iac_summary(records, 'dev', '123456789012', ['s3'])['categories']['処理エラー'] == 1
            artifact = dict(iac=records, ordinary=[], judgments=[], naming={'names': []})
            assert summary(artifact)['iac_status'] == 'error'
            cli_exit(root, Path(temporary), artifact, 2)

        template_path = root / 'infra/cloudformation/templates/shared.yaml'
        original = template_path.read_text(encoding='utf-8')
        template = json.loads(original)
        template['Resources']['Bucket']['Properties']['VersioningConfiguration']['Status'] = 'Suspended'
        template_path.write_text(json.dumps(template), encoding='utf-8')
        records = Comparison(root, 'dev', '123456789012', ['s3']).run()
        assert sum(item['category'] == 'difference' for item in records) == 1, records
        artifact = dict(iac=records, ordinary=[], judgments=[], naming={'names': []})
        assert summary(artifact)['iac_status'] == 'differences'
        cli_exit(root, Path(temporary), artifact, 0)
        template_path.write_text(original, encoding='utf-8')

        # Unexpected decoder/I/O failures cannot be relabelled as known API-only.
        comparison = Comparison(root, 'dev', '123456789012', ['s3'])
        with patch.object(comparison, 'stack', side_effect=ValueError('broken template input')):
            records = comparison.run()
        assert records and all(item['category'] == 'error' for item in records), records
        artifact = dict(iac=records, ordinary=[], judgments=[], naming={'names': []})
        cli_exit(root, Path(temporary), artifact, 2)

        # Authoritative input parse failure must survive comparison and aggregation.
        with patch('issues_iac.load_model', side_effect=ValueError('broken model input')):
            comparison = Comparison(root, 'dev', '123456789012', ['s3'])
        records = comparison.run()
        assert records and all(item['category'] == 'error' for item in records), records
        assert summary(dict(iac=records))['iac_status'] == 'error'
        artifact = dict(iac=baseline, ordinary=[], judgments=[], naming={'names': []})
        assert summary(artifact)['iac_status'] == 'complete match'
        cli_exit(root, Path(temporary), artifact, 0)
    print('API-only IaC classification: PASS (API/unknown/broken/CFn counts, CLI exits, implementation rejection)')


def cli_exit(root, temporary, artifact, expected):
    before = copy.deepcopy(artifact)
    with patch('issues_scan.scan', return_value=artifact), patch('issues_scan.review_payload', return_value={}), \
         patch('sys.argv', ['issues_scan.py', '--repository-root', str(root), 'scan', '--environment', 'dev',
                            '--target-directory', '123456789012', '--service', 's3',
                            '--artifact', str(temporary / 'scan.json')]):
        assert main() == expected
    assert artifact == before
    assert json.loads((temporary / 'scan.json').read_text(encoding='utf-8')) == artifact


if __name__ == '__main__':
    from support.model_sources import catalog_display
    with catalog_display():
        main_checks()
