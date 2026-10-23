"""Compatibility CLI with subcommand-specific runtime imports."""
import argparse
import json
import os
from pathlib import Path
import sys
from .records import safe_text
SELECTOR = "BLUEPRINT_TASK_FILE"

def outside(root, path):
    path = path.resolve()
    if path.is_relative_to(root):
        raise ValueError('scan/review/diagnostics artifacts must be outside the repository')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, default=Path.cwd().resolve())
    parser.add_argument('--task-file')
    commands = parser.add_subparsers(dest='command', required=True)
    scanparser = commands.add_parser('scan')
    scanparser.add_argument('--environment', required=True)
    scanparser.add_argument('--target-directory', required=True)
    scanparser.add_argument('--service', action='append', required=True)
    scanparser.add_argument('--artifact', type=Path, required=True)
    scanparser.add_argument('--fresh', action='store_true')
    scanparser.add_argument('--jobs', type=int, choices=(1, 2, 4), default=4)
    detail = commands.add_parser('detail')
    detail.add_argument('--artifact', type=Path, required=True)
    detail.add_argument('--section', choices=('ordinary', 'naming', 'judgments', 'human_confirmations', 'iac', 'iac_issues', 'machine_diagnostics', 'warnings', 'information', 'unverified', 'processing_errors', 'naming_context', 'cfn_lint', 'lint_coverage'), required=True)
    detail.add_argument('--offset', type=int, default=0)
    detail.add_argument('--limit', type=int, default=50)
    detail.add_argument('--category', choices=('要対応', '要判断', '比較未完了', '処理エラー', '原因未確定'), help='IaC classification filter; applied before pagination')
    detail.add_argument('--issue-id', help='stable ISSUE-<id>; retrieve members from this artifact without comparison')
    saveparser = commands.add_parser('save')
    saveparser.add_argument('--artifact', type=Path, required=True)
    saveparser.add_argument('--review', type=Path, required=True)
    results = commands.add_parser('save-results')
    results.add_argument('--environment', required=True)
    results.add_argument('--target-directory', required=True)
    results.add_argument('--service', action='append', required=True)
    results.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    if args.task_file:
        os.environ[SELECTOR] = args.task_file
    try:
        if args.command == 'scan':
            from .runner import scan
            from .artifact import review_payload, scan_exit_code
            artifact_path = outside(root, args.artifact)
            artifact = scan(root, args.environment, args.target_directory, args.service, fresh=args.fresh, jobs=args.jobs)
            artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            output = review_payload(artifact, artifact_path)
            print(json.dumps(output, ensure_ascii=False))
            return scan_exit_code(artifact)
        if args.command == 'detail':
            from .artifact import detail_payload
            artifact = json.loads(outside(root, args.artifact).read_text(encoding='utf-8'))
            print(json.dumps(detail_payload(artifact, args.section, args.offset, args.limit, args.category, args.issue_id), ensure_ascii=False))
            return 0
        if args.command == 'save':
            from .publication import save_scan
            from .artifact import summary, has_processing_errors
            artifact = json.loads(outside(root, args.artifact).read_text(encoding='utf-8'))
            review = json.loads(outside(root, args.review).read_text(encoding='utf-8'))
            paths = save_scan(root, artifact, review)
        else:
            from .integrity import selected_scope
            from .publication import save
            selected_scope(args.environment, args.target_directory, args.service)
            results = json.loads(outside(root, args.results).read_text(encoding='utf-8'))
            if set(results) - {'issues', 'resolved'}:
                raise ValueError('save-results accepts acquired ordinary results only; no automatic comparison')
            paths = save(root, args.environment, args.target_directory, args.service, additions=results.get('issues', []), resolutions=results.get('resolved', []))
        saved_summary = summary(artifact) if args.command == 'save' else None
        print(json.dumps({'publication_status': 'SAVED', 'validation_status': saved_summary['validation_status'] if saved_summary else 'not_run', 'saved': [path.relative_to(root).as_posix() for path in paths], 'summary': saved_summary if saved_summary else 'acquired results saved; no rescan', 'post_save_validation': 'required: blueprint-loop.py --mode local'}, ensure_ascii=False))
        return 2 if args.command == 'save' and has_processing_errors(artifact) else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Local issues: ERROR: ' + safe_text(str(error)), file=sys.stderr)
        return 2


