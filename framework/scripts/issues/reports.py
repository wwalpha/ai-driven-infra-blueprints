"""Ordinary issue merge, current-run IaC display and atomic scoped publication."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import task_contract_core as _exports_task_contract_core
from issue_gate import unresolved_services
from task_contract_core import safe_path as safe_path
from utils.input_cache import memoized

from .aggregate import comparison_status, iac_summary
from .records import brief, identifier, safe_text

# Preserve shared fixtures and compatibility exports under their historical names.
status = _exports_task_contract_core.status




def inventories(root, path):
    if not path.is_file():
        return []
    text = path.read_text(encoding='utf-8')
    if text.strip() and any(number == 'unknown' for number, _ in unresolved_services(root, path)):
        raise ValueError(f'malformed existing report: {path.relative_to(root)}')
    return unresolved_services(root, path)


def markdown_matches(text, pattern):
    result, offset, fence = [], 0, None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
        elif marker and (marker[1][0] == '~' or '`' not in marker[2]):
            fence = (marker[1][0], len(marker[1]))
        else:
            match = re.match(pattern, line.rstrip('\r\n'))
            if match:
                result.append((offset, offset + match.end(), match.group(1)))
        offset += len(line)
    return result


def blocks(text):
    """Keep the original preamble and every service block byte-for-byte until merged."""
    starts = markdown_matches(text, r'^### (.+)$')
    preamble = text[:starts[0][0]] if starts else text
    result = []
    for i, (start, _end, heading) in enumerate(starts):
        body = text[start: starts[i + 1][0] if i + 1 < len(starts) else len(text)]
        markers = re.findall(r'<!-- issue-service: ([a-z0-9_-]+) -->', body)
        service = markers[0] if len(set(markers)) == 1 else heading if re.fullmatch(r'[a-z0-9_-]+', heading) else None
        result.append((service, body))
    return preamble, result


def numbered(body):
    starts = markdown_matches(body, r'^ {0,3}(\d+)[.)] +')
    prefix = body[:starts[0][0]] if starts else body
    return prefix, [body[end: starts[i + 1][0] if i + 1 < len(starts) else len(body)].strip()
                    for i, (start, end, number) in enumerate(starts)]


def owned_blocks(root, path, text):
    preamble, sections = blocks(text)
    owners = unresolved_services(root, path) if path.is_file() else []
    offset = len(numbered(preamble)[1])
    result = []
    if offset and len(owners[:offset]) == offset:
        known = {next(iter(services)) for _, services in owners[:offset] if len(services) == 1}
        if len(known) == 1 and all(len(services) == 1 for _, services in owners[:offset]):
            service = next(iter(known))
            markers = markdown_matches(preamble, r'^(<!-- issue-service: [a-z0-9_-]+ -->)$')
            boundary = markers[0][0] if markers else markdown_matches(preamble, r'^ {0,3}(\d+)[.)] +')[0][0]
            result.append((service, f'### {service}\n\n' + preamble[boundary:]))
            preamble = preamble[:boundary]
    for service, body in sections:
        count = len(numbered(body)[1])
        belonging = [services for _, services in owners[offset:offset + count]]
        offset += count
        if service is None and count and len(belonging) == count and all(len(values) == 1 for values in belonging):
            known = set().union(*belonging)
            if len(known) == 1:
                service = next(iter(known))
        result.append((service, body))
    return preamble, result


@memoized
def line_count(path):
    return len(path.read_text(encoding="utf-8").splitlines())


def evidence(root, report, source):
    if not source:
        return ''
    path = safe_path(root, source['path'])
    if not path.is_file():
        return f"`{source['path']}`（ファイルが存在しない）"
    number = source.get('line')
    if number is not None and (type(number) is not int or not 1 <= number <= line_count(path)):
        raise ValueError('invalid evidence line')
    label = source['path'] + (f':{number}' if number else '')
    relative = Path(os.path.relpath(path, report.parent)).as_posix()
    target = '<' + relative + '>' if ' ' in relative else relative
    return f'[{label}]({target})'


def normal_merge(root, path, environment, directory, services, candidates, additions, resolutions):
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    inventories(root, path)
    ordinary, notices = split_notices(old)
    preamble, existing = owned_blocks(root, path, ordinary)
    if not preamble:
        preamble = '# 問題一覧\n\n'
    # Human confirmation/exception prose stays in the original preamble.
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S Asia/Tokyo')
    preamble = re.sub(r'^(更新日時|今回確認した範囲):[^\n]*\n?', '', preamble, flags=re.M)
    preamble = preamble.replace('未解決issueなし', '').rstrip() + f'\n\n更新日時: {stamp}\n今回確認した範囲: {environment}／{directory}／{", ".join(services)}\n\n'
    if not re.search(r'^## ', preamble, re.M):
        preamble += f'## {environment}／{directory}\n\n'
    pending = {service: [] for service in services}
    for record in [*candidates, *additions]:
        service = record.get('service')
        if service not in pending:
            raise ValueError('ordinary issue ownership requires explicit scoped service')
        message = safe_text(record['message']).replace(str(root) + '/', '')
        link = evidence(root, path, record.get('source'))
        content = message + (f' 根拠: {link}。' if link else '')
        marker = identifier([service, record.get('key', message)])
        pending[service].append(content + f' <!-- issue-id: {marker} -->')
    resolutions = {item['id']: item for item in resolutions}
    used = set()
    output = []
    for service, body in existing:
        if service not in pending:
            output.append(body)
            continue
        prefix, items = numbered(body)
        if not re.search(r'^<!-- issue-service: ' + re.escape(service) + r' -->$', prefix, re.M) and not prefix.startswith('### ' + service + '\n'):
            prefix = prefix.rstrip() + f'\n\n<!-- issue-service: {service} -->\n\n'
        kept = []
        for item in items:
            item_id = identifier([service, item])
            decision = resolutions.get(item_id)
            if decision:
                if not decision.get('reason') or not decision.get('evidence'):
                    raise ValueError('resolution needs explicit revalidation evidence and reason')
                used.add(item_id)
            else:
                kept.append(item)  # Absence in a new scan never resolves an issue.
        for item in pending.pop(service):
            marker = re.search(r'<!-- issue-id: (.+?) -->', item).group(1)
            if not any(f'<!-- issue-id: {marker} -->' in current for current in kept):
                kept.append(item)
        if kept:
            output.append(prefix.rstrip() + '\n\n' + '\n\n'.join(f'{i}. {item}' for i, item in enumerate(kept, 1)) + '\n\n')
        elif prefix.strip() != f'### {service}':
            # Keep human prose in an emptied service block, without an empty issue list.
            prose = re.sub(r'^### .*\n|^<!-- issue-service: .*? -->\n?', '', prefix, flags=re.M).strip()
            if prose:
                preamble += prose + '\n\n'
    if used != resolutions.keys():
        raise ValueError('resolution is stale, outside scope or does not identify an existing issue')
    for service, items in pending.items():
        if items:
            output.append(f'### {service}\n\n<!-- issue-service: {service} -->\n\n' +
                          '\n\n'.join(f'{i}. {item}' for i, item in enumerate(items, 1)) + '\n\n')
    text = preamble + ''.join(output)
    if not re.search(r'^\d+\. ', text, re.M):
        text = text.rstrip() + '\n\n未解決issueなし\n'
    return attach_notices(text, notices)


def iac_report(environment, directory, services, records, display=None, *, stamp=None, artifact=None):
    summary = dict(artifact['overview'], index=sorted((group['compact'] for group in artifact['iac_issues']), key=lambda item:item['report_order'])) if artifact is not None else iac_summary(records, environment, directory, services, display, include_index=True)
    counts = summary['records']
    status = comparison_status(counts)
    if stamp and stamp.endswith('Z'):
        stamp = datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S Asia/Tokyo')
    stamp = stamp or datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S Asia/Tokyo')
    lines = ['# model → IaC比較の非阻害結果', '', f'実行日時: {stamp}',
        f'今回指定した範囲: {environment}／{directory}／{", ".join(sorted(set(services)))}',
        f'今回の判定: {status}',
        '今回指定した範囲の結果。対象外Serviceは今回未検証。通常issue gateの停止対象外。',
        f'問題: {summary["issue_count"]}件（原因・必要対応単位）',
        f'影響: 差分 {counts["difference"]}件 / 未比較 {counts["uncompared"]}項目 / 処理エラー {counts["error"]}項目',
        f'元レコード数: {summary["record_count"]}（一致 {counts["matched"]} / 除外 {counts["excluded"]}）',
        '分類: ' + ' / '.join(f'{category} {count}件' for category, count in summary['categories'].items()),
        f'表示{len(summary["groups"])}／全{summary["issue_count"]}対応単位、未表示{summary["omitted_issues"]}',
        '未表示の分類: ' + ' / '.join(f'{category} {count}件' for category, count in summary['omitted_categories'].items()),
        '未表示の影響: ' + ' / '.join(f'{kind} {count}件' for kind, count in summary['omitted_record_categories'].items()), '']
    if summary['comparison_incomplete']:
        lines.extend(['比較途中終了: 収集済みレコードを保持。未実施範囲は未検証であり、一致・修正完了とは扱わない。', ''])
    lines.extend(['## 全Issueの簡易一覧', '',
                  '| Issue ID | 分類 | 原因・問題 | 修正対象 | 必要な操作 | 影響レコード数 | 影響Service |',
                  '| --- | --- | --- | --- | --- | ---: | --- |'])
    for item in summary['index']:
        lines.append('| ' + ' | '.join(brief(value).replace('\n', ' ').replace('\r', ' ') for value in (item['id'], item['category'], item['problem'] + '：' + item['cause'],
                     item['target'] or '未特定・要判断', item['remedy'], item['records'], ', '.join(item['services']))) + ' |')
    lines.extend(['', '## 詳細（最大16グループ）', ''])
    for group in summary['groups']:
        target = ('API専用リソース（実装scopeとAPI実装状態を確認）' if group['category'] == 'CFn非対応・比較対象外' else
                  '不足入力: ' + brief(Path(group['target']).name) if group['target'] and group['category'] != '要判断' else
                  'Model／IaC（修正先は要判断）' if group['category'] == '要判断' else
                  '未特定（Model／IaC／比較器／不足入力を確認）')
        lines.extend([f'### {group["id"]} / {group["category"]}: {group["problem"]}',
            f'- 原因: {group["cause"]}', f'- 必要な対応: {group["remedy"]}', f'- 修正対象: {target}',
            f'- 影響範囲: {", ".join(group["services"])}。{group["records"]}レコード / 直接差分 {group["direct_resources"]}リソース / 未比較 {group["uncompared"]}項目 / 処理エラー {group["errors"]}項目'])
        if group['cascading']:
            lines.append(f'- 探索中断: {group["cascading"]}項目。直接Import依存は未確定。')
        for example in group['examples']:
            lines.append(f'対象: {example["service"]} / {example["resource"]} / {example["property"]}: {example["reason"]}')
            for child in example.get('deferred_children', []):
                lines.append(f"保留原因の子項目: {child['property']} / {child['category']}: {child['reason']}")
            if example.get('omitted_deferred_children'):
                lines.append(f"省略保留原因: {example['omitted_deferred_children']}件（全文はartifact）")
            for field in example.get('reference_diagnostics', []):
                lines.extend(['未比較field: ' + field['path'], '- Model参照: ' + field['model'],
                              '- IaC参照: ' + field['iac'], '- 参照同一性: ' + field['identity'],
                              '- 許容形式: ' + field['allowed_forms'], '- 両側の形式適合性: ' + field['format'],
                              '- 形式／未比較理由: ' + field['reason']])
            if example.get('omitted_reference_fields'):
                lines.append(f'省略参照フィールド: {example["omitted_reference_fields"]}件')
            if 'condition' in example:
                condition = example['condition']
                lines.extend([f"Condition: {condition['condition']} = false",
                    f"Stack／論理ID: {condition['stack']}／{condition['logical']}",
                    'テンプレート位置: ' + condition['template']])
                for value in condition['inputs']:
                    lines.append(f"原因入力: {value['name']} = {value['value']} / 取得元: {value['source']}")
                if condition['omitted_inputs']:
                    lines.append(f"省略原因入力: {condition['omitted_inputs']}件（全文はartifact）")
            if 'fields' in example:
                if example['field_status']:
                    lines.append('相違項目: ' + example['field_status'])
                for field in example['fields']:
                    lines.extend(['相違項目: ' + field['path'], '- Model: ' + field['model'], '- IaC: ' + field['iac']])
                    if field['model'] == field['iac']:
                        lines.append('不一致の検出結果を保持（短縮・マスキングまたはキー重複）。')
                if example['omitted_fields']:
                    lines.append(f'省略相違フィールド: {example["omitted_fields"]}件')
        if group['omitted_examples']:
            lines.append(f'省略代表例: {group["omitted_examples"]}レコード')
        lines.append('')
    lines.extend(['## 全メンバー取得', '',
                  '代表例は修正対象の上限ではない。同じscanの一時artifactから一覧のIssue IDで全メンバーを取得する。',
                  '```console',
                  'python3 framework/scripts/issues_scan.py detail --artifact <path> --section iac --issue-id ISSUE-<id> --offset 0 --limit 50',
                  '```',
                  'offsetを50ずつ進め、total件すべてを確認する。後続の修正タスクは全メンバーを調査・再比較し、未比較を修正完了と扱わない。', ''])
    return '\n'.join(lines)


# Notices are scope-stamped machine output, never Human confirmation material.
NOTICE_MARKER = r'^(<!-- issues-notices:[^ >]+:(?:start|end) -->)[ \t]*$'
WARNING_HEADINGS = ('警告（非ブロッキング）', '参照警告（非ブロッキング）')

def without_notices(text):
    return split_notices(text)[0]


def split_notices(text):
    notices, ordinary, offset = [], [], 0
    markers = markdown_matches(text, NOTICE_MARKER)
    for index, (start, _, marker) in enumerate(markers[:-1]):
        if ':start -->' not in marker:
            continue
        _, end, closing = markers[index + 1]
        if closing != marker.replace(':start -->', ':end -->'):
            continue
        ordinary.append(text[offset:start])
        scope = marker.removeprefix('<!-- issues-notices:').removesuffix(':start -->')
        notices.append((scope, text[start:end]))
        offset = end
    ordinary.append(text[offset:])
    text = ''.join(ordinary)
    ordinary, offset = [], 0
    # Only owned, numbered service blocks end notices; auxiliary headings stay inside.
    service_starts = {start for (start, _, _), (service, body) in
                      zip(markdown_matches(text, r'^### (.+)$'), blocks(text)[1])
                      if service is not None and numbered(body)[1]}
    headings = [(start, end, heading) for start, end, heading in markdown_matches(text, r'^#{1,3} (.+)$')
                if not text.startswith('### ', start) or start in service_starts]
    for index, (start, _, heading) in enumerate(headings):
        if heading not in WARNING_HEADINGS:
            continue
        end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        ordinary.append(text[offset:start])
        notices.append((None, text[start:end].rstrip()))
        offset = end
    ordinary.append(text[offset:])
    return ''.join(ordinary), notices


def attach_notices(text, notices):
    if not notices:
        return text
    ordered = []
    priorities = ('情報', '未検証範囲', '処理エラー（未検証範囲あり）', *WARNING_HEADINGS)
    for scope, block in notices:
        headings = markdown_matches(block, r'^## (.+)$')
        prefix = block[:headings[0][0]] if headings else ''
        closing = block.rfind('\n<!-- issues-notices:') if scope is not None else len(block)
        groups = {}
        for index, (start, _, heading) in enumerate(headings):
            end = headings[index + 1][0] if index + 1 < len(headings) else closing
            priority = priorities.index(heading) + 1 if heading in priorities else 0
            groups.setdefault(priority, []).append(block[start:end].rstrip())
        if len(groups) <= 1:
            ordered.append((next(iter(groups), 0), block))
        else:
            # Each separated portion keeps its scope so later saves replace all of it.
            ordered.extend((priority, prefix + '\n\n'.join(parts) + block[closing:])
                           for priority, parts in groups.items())
    return text.rstrip() + '\n\n' + '\n\n'.join(block for _, block in sorted(ordered, key=lambda item: item[0])) + '\n'

def notice_report(text, environment, directory, services, channels, *, preserve_prior=False):
    scope_id = identifier([environment, directory, sorted(services)])
    text, notices = split_notices(text)
    # Separate mixed scope blocks before replacing diagnostics; reference warnings survive.
    _, notices = split_notices(attach_notices('', notices))
    previous = [block for scope, block in notices if scope == scope_id
                and not markdown_matches(block, r'^## (参照警告（非ブロッキング）)$')]
    retained = list(dict.fromkeys(line for block in previous for line in block.splitlines() if line.startswith('- '))) if preserve_prior else []
    notices = [(scope, block) for scope, block in notices if scope != scope_id or block not in previous]
    lines = [f'<!-- issues-notices:{scope_id}:start -->', f'今回の機械診断scope: {environment}／{directory}／{", ".join(sorted(services))}']
    for channel, heading in [('information', '情報'), ('unverified', '未検証範囲'), ('processing_errors', '処理エラー（未検証範囲あり）'), ('warnings', '警告（非ブロッキング）')]:
        values = channels.get(channel, [])
        if values:
            lines += ['## ' + heading, ''] + ['- ' + safe_text(json.dumps(value, ensure_ascii=False)) for value in values]
    if retained:
        current = set(line for line in lines if line.startswith('- '))
        retained = [line for line in retained if line not in current]
        if retained:
            lines += ['### 前回診断（今回未検証・解消未確認）', *retained]
    lines.append(f'<!-- issues-notices:{scope_id}:end -->')
    return attach_notices(text, [(scope_id, '\n'.join(lines)), *notices])
