"""Ordinary issue merge, current-run IaC display and atomic scoped publication."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone, timedelta

from issue_gate import unresolved_services
from task_contract import task_path, paths_in, require_writable, registration_lock, safe_path, section, reserved_batches
from validation_scope import active_scope
from validation_cache import input_scope, memoized
from issues_iac import safe_value, same, selected_same


def identifier(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def inventories(root, path):
    if not path.is_file():
        return []
    text = path.read_text(encoding='utf-8')
    if text.strip() and any(number == 'unknown' for number, _ in unresolved_services(root, path)):
        raise ValueError(f'malformed existing report: {path.relative_to(root)}')
    return unresolved_services(root, path)


def markdown_matches(text, pattern):
    result, offset, fence = [], 0, ''
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            fence = '' if fence == marker[1][0] else marker[1][0] if not fence else fence
        elif not fence:
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
    for i, (start, end, heading) in enumerate(starts):
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


def safe_text(text):
    value = safe_value(text)
    value = re.sub(r'(?i)((?:password|secretstring|token|credential)\s*[=:]\s*)[^\s,;]+', r'\1<masked>', value)
    return value.replace('\n', ' ').replace('\r', ' ')


def normal_merge(root, path, environment, directory, services, candidates, additions, resolutions):
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    inventories(root, path)
    preamble, existing = owned_blocks(root, path, old)
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
    return text


def iac_key(item):
    return identifier([item['service'], item['resource'], item['property'], item.get('stack')])


IAC_CATEGORIES = {'difference', 'uncompared', 'error'}


def value_differences(desired, actual, property_name='', *, exact=False, redact=safe_value, reference=None):
    """Display only: use the detector's predicate, then redact the differing leaves."""
    missing = object()
    differences = []
    predicate = (lambda left, right, name: same(left, right)) if exact else selected_same

    def formatted(value):
        if value is missing:
            return '欠落'
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z_$][\w ./$:-]*', value) and value not in {'null', 'true', 'false'}:
            return value
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    def add(path, left, right):
        differences.append({'path': safe_text(path or property_name),
                            'model': formatted(left), 'iac': formatted(right)})

    def child(value, key):
        # A secret property can redact a whole container into one mask.
        return value[key] if isinstance(value, (dict, list)) else value

    def walk(left, right, shown_left, shown_right, path, name):
        if left is missing or right is missing:
            add(path, shown_left, shown_right)
            return
        if reference is None:
            equal = predicate(left, right, name)
        else:
            field = property_name.rsplit('.', 1)[-1]
            typed_path = path if path.startswith(field + '[') else field + ('.' + path if path else '')
            typed_path = re.sub(r'\[\d+\]', '[]', typed_path)
            equal = (same(left, right, reference=reference, path=typed_path) if exact else
                     selected_same(left, right, name, reference=reference, path=typed_path))
        if equal is None or equal:
            return
        if type(left) is not type(right):
            add(path, shown_left, shown_right)
        elif isinstance(left, dict):
            for key in sorted(left.keys() | right.keys() if exact else left.keys()):
                walk(left.get(key, missing), right.get(key, missing),
                     child(shown_left, key) if key in left else missing,
                     child(shown_right, key) if key in right else missing,
                     f'{path}.{key}' if path else key, key)
        elif isinstance(left, list):
            if not exact and name in {'Tags', 'HostedZoneTags'} and all(isinstance(item, dict) and 'Key' in item for item in left):
                model_keys, iac_keys = {}, {}
                for i, item in enumerate(left):
                    model_keys.setdefault(item['Key'], []).append(i)
                for i, item in enumerate(right):
                    if isinstance(item, dict) and item.get('Key') in model_keys:
                        iac_keys.setdefault(item['Key'], []).append(i)
                for key, model_indexes in model_keys.items():
                    iac_indexes = iac_keys.get(key, [])
                    field = f'{path}[Key={formatted(safe_value(key))}]'
                    if len(model_indexes) != 1 or len(iac_indexes) > 1:
                        add(field + '.要素数（キー重複）', len(model_indexes), len(iac_indexes))
                    else:
                        i = model_indexes[0]
                        j = iac_indexes[0] if iac_indexes else None
                        walk(left[i], right[j] if j is not None else missing,
                             child(shown_left, i), child(shown_right, j) if j is not None else missing, field, '')
            else:
                for i in range(max(len(left), len(right))):
                    walk(left[i] if i < len(left) else missing, right[i] if i < len(right) else missing,
                         child(shown_left, i) if i < len(left) else missing,
                         child(shown_right, i) if i < len(right) else missing, f'{path}[{i}]', name)
        else:
            add(path, shown_left, shown_right)

    name = property_name.rsplit('.', 1)[-1]
    walk(desired, actual, redact(desired, property_name), redact(actual, property_name), name if isinstance(desired, list) else '', name)
    return differences


def iac_actions(entries, environment, directory):
    """O(N) grouping by proven cause/repair target/action; unknowns remain separate."""
    groups = {}
    for index, entry in enumerate(entries):
        item = entry['record']
        if item['category'] not in IAC_CATEGORIES:
            continue
        cause = item.get('cause', {})
        path = cause.get('path')
        known_missing = (cause.get('kind') in {'template-missing', 'parameters-missing'} and path
                         and cause.get('relationship') in {'direct', 'stack-input', 'export-search-incomplete', 'legacy-search-incomplete'})
        if known_missing:
            action = 'confirm-create-template' if cause['kind'] == 'template-missing' else 'confirm-stack-parameters'
            key = [environment, directory, cause['kind'], path, action]
            title = Path(path).name + (' のテンプレート未作成' if cause['kind'] == 'template-missing' else ' の入力ファイル欠落')
            classification = 'IaC未実装' if cause['kind'] == 'template-missing' else '設定不一致'
            description = f'{path} が存在しない。'
            remedy = ('CREATE対象と実装要否を確認し、未実装ならModelに従ってテンプレートを作成する。意図的な未実装なら状態を明示して管理する。'
                      if cause['kind'] == 'template-missing' else 'Stack設計のparameters指定と配置先を確認し、必要な入力ファイルを作成・配置する。')
            target, status = path, '要対応'
            if item['category'] in {'uncompared', 'error'}:
                classification, status = '比較未完了', '要調査'
                description = f'{path} の欠落により参照探索を完了できない。設定差分は未確定。'
                remedy = '参照先とExport宣言・探索範囲を確認して再比較する。Model/IaCの修正要否は未確定。'
        elif item['category'] == 'uncompared' and cause.get('kind') == 'import-unresolved':
            target = None
            key = [environment, directory, 'import-unresolved', cause['export']]
            title = f'Export {cause["export"]} の参照解決が未完了'
            classification, status = '比較未完了', '要調査'
            description = '参照先Exportの一意性または値を確認できない。設定差分は未確定。'
            remedy = 'Export/Importの宣言・有効条件・参照先を確認して再比較する。Model/IaCの修正要否は未確定。'
        elif item['category'] == 'difference' and item.get('iac') and item.get('stack') and item['reason'] in {
                'value mismatch', 'property missing', 'resource missing', 'inline CREATE child missing', 'property omitted by AWS::NoValue'}:
            target = item['iac']['path']
            key = [environment, directory, target, item['stack'], item['service'], item['resource'], item['property'], item['reason'], 'sync-model-iac']
            title = f'{item["service"]} / {item["resource"]} / {item["property"]} の' + ('値の不一致' if item['reason'] == 'value mismatch' else '未実装・設定欠落')
            classification, status = 'Model/IaC差分', '要判断'
            description = {'value mismatch': 'ModelとIaCの設定値が一致しない。', 'property missing': 'Modelにある設定がIaCに存在しない。',
                           'resource missing': 'Modelに対応するCREATEリソースがIaCに存在しない。',
                           'inline CREATE child missing': 'Modelに対応する子リソースがIaCに存在しない。',
                           'property omitted by AWS::NoValue': '設定がAWS::NoValueにより省略される。'}[item['reason']]
            remedy = '該当ModelとIaC・適用条件の正しい設定を確認して同期する。修正先の選択には人間の判断が必要。'
        else:
            target = None
            key = [environment, directory, 'unresolved', entry['id'], item['category'], item['reason'], item.get('iac'), entry.get('legacy')]
            title = f'{item["service"]} / {item["resource"]} / {item["property"]} の確認が必要'
            classification, status = ('処理エラー' if item['category'] == 'error' else '比較未完了' if item['category'] == 'uncompared' else '原因未確定'), '要調査'
            description = '原因または対応先を確定できない。'
            remedy = ('Export/Importの参照関係・宣言・有効条件と探索の完了を確認する。直接依存は未確定。'
                      if 'ImportValue' in item['reason'] else '記載した検出理由とModel/IaCの対応・検証ルールを確認し、原因と修正先を特定する。')
        group_id = 'ISSUE-' + identifier(key)
        group = groups.setdefault(group_id, {'id': group_id, 'title': title, 'classification': classification,
                                             'description': description, 'remedy': remedy, 'target': target,
                                             'status': status, 'members': []})
        group['members'].append(index)
        # A direct confirmed omission remains actionable when its dependent
        # unresolved references share the cause, regardless of input ordering.
        if known_missing and item['category'] == 'difference':
            group.update(classification=classification, description=description, remedy=remedy, status=status)
    return sorted(groups.values(), key=lambda group: (group['status'] != '要対応', group['classification'], group['id']))


IAC_CLASSES = ('要対応', '要判断', '比較未完了', '処理エラー', '原因未確定')
MAX_GROUPS = 8
MAX_EXAMPLES = 3
MAX_FIELDS = 1


def brief(value, limit=160):
    value = safe_text(str(value)).replace('|', '／').replace('<', '&lt;').replace('>', '&gt;')
    return value if len(value) <= limit else value[:limit] + '…（全文はartifact）'


def iac_dataset(records, environment, directory, services, display=None):
    """Current-run data only; causal Issue identities are independent of display grouping."""
    scoped = set(services)
    if any(item['service'] not in scoped for item in records):
        raise ValueError('IaC record outside selected services')
    entries = [{'id': iac_key(item), 'record': dict(safe_value(item), reason=safe_text(item['reason']), **{
        key: safe_value(item[key], item.get('property', '')) for key in ('desired', 'actual') if key in item}),
        'record_index': index} for index, item in enumerate(records)]
    entries.sort(key=lambda entry: (entry['record']['service'], entry['id'], identifier(entry['record'])))
    shown = {}
    for entry in entries:
        key = identifier(entry['record'])
        fields = (display or {}).get(key)
        if fields is None:
            continue
        if not isinstance(fields, list) or any(not isinstance(field, dict) or
                any(not isinstance(field.get(name), str) for name in ('path', 'model', 'iac')) for field in fields):
            raise ValueError('malformed IaC value difference display')
        shown[key] = []
        for field in fields:
            safe = {'path': safe_text(field['path'])}
            for side in ('model', 'iac'):
                value = field[side]
                masked = safe_value(value, entry['record']['property'] + '.' + field['path'])
                safe[side] = safe_text(json.dumps(masked) if masked != value else value)
            shown[key].append(safe)
    actions = iac_actions(entries, environment, directory)
    for group in actions:
        group['category'] = (group['status'] if group['status'] in {'要対応', '要判断'} else group['classification'])
    return entries, actions, shown


def iac_summary(records, environment, directory, services, display=None):
    entries, actions, shown = iac_dataset(records, environment, directory, services, display)
    groups = {}
    counts = {category: 0 for category in IAC_CLASSES}
    for action in actions:
        category = action['category']
        counts[category] += 1
        members = [entries[i]['record'] for i in action['members']]
        # One display unit per proven action; prose similarity never merges unknown causes.
        group = groups.setdefault(action['id'], dict(category=category, problem=brief(action['title']),
            cause=brief(action['description']), remedy=action['remedy'], target=action['target'],
            services=sorted({item['service'] for item in members}), stacks=set(), issues=0, records=0, direct=set(), uncompared=0, errors=0,
            cascading=0, examples=[]))
        group['issues'] += 1
        group['records'] += len(members)
        group['direct'].update((item['service'], item['resource'], item.get('stack')) for item in members if item['category'] == 'difference')
        group['stacks'].update(stack for item in members for stack in
                               (item.get('stack'), item.get('cause', {}).get('consumer_stack'), item.get('cause', {}).get('stack')) if stack)
        if not group['stacks']:
            group['stacks'].add('未確定')
        group['uncompared'] += sum(item['category'] == 'uncompared' for item in members)
        group['errors'] += sum(item['category'] == 'error' for item in members)
        group['cascading'] += sum(item.get('cause', {}).get('relationship') in {'export-search-incomplete', 'legacy-search-incomplete'} for item in members)
        for i in sorted(action['members'], key=lambda i: (entries[i]['record'].get('cause', {}).get('relationship') != 'direct', entries[i]['id'], identifier(entries[i]['record']))):
            if len(group['examples']) >= MAX_EXAMPLES:
                break
            item = entries[i]['record']
            example = {name: brief(item[name]) for name in ('service', 'resource', 'property', 'reason')}
            example.update(issue_id=action['id'], record_id=entries[i]['id'])
            if item['category'] == 'difference' and item['reason'] == 'value mismatch':
                fields = shown.get(identifier(item))
                example['fields'] = [{name: brief(field[name]) for name in ('path', 'model', 'iac')} for field in (fields or [])[:MAX_FIELDS]]
                example['omitted_fields'] = max(0, len(fields or []) - MAX_FIELDS)
                example['field_status'] = '検出は不一致。マスク済み値から相違項目を復元できない。' if not fields else ''
            group['examples'].append(example)
    ordered = sorted(groups.values(), key=lambda group: (IAC_CLASSES.index(group['category']), group['services'], group['problem'], group['target'] or '', group['examples'][0]['issue_id']))
    for group in ordered:
        group['direct_resources'] = len(group.pop('direct'))
        stacks = sorted(group['stacks'])
        group['stacks'] = [brief(stack) for stack in stacks[:5]]
        group['omitted_stacks'] = max(0, len(stacks) - 5)
        group['omitted_examples'] = group['records'] - len(group['examples'])
    # Give every present category a representative before filling the bounded list.
    visible = [next(group for group in ordered if group['category'] == category) for category in IAC_CLASSES
               if any(group['category'] == category for group in ordered)]
    visible += [group for group in ordered if group not in visible][:MAX_GROUPS - len(visible)]
    visible.sort(key=lambda group: (IAC_CLASSES.index(group['category']), group['services'], group['problem'], group['examples'][0]['issue_id']))
    visible_ids = {group['examples'][0]['issue_id'] for group in visible}
    raw = {kind: sum(item['category'] == kind for item in records) for kind in ('difference', 'uncompared', 'error', 'matched', 'excluded')}
    return dict(issue_count=len(actions), categories=counts, record_count=len(records), records=raw,
                proven_causes=sum(any((entries[i]['record'].get('cause', {}).get('kind') in {'template-missing', 'parameters-missing'}
                                        and entries[i]['record'].get('cause', {}).get('path')
                                        and entries[i]['record'].get('cause', {}).get('relationship') in {'direct', 'stack-input', 'export-search-incomplete', 'legacy-search-incomplete'})
                                       or entries[i]['record'].get('cause', {}).get('kind') == 'import-unresolved'
                                       for i in action['members']) for action in actions),
                direct_resources=len({(item['service'], item['resource'], item.get('stack')) for item in records if item['category'] == 'difference'}),
                group_count=len(ordered), omitted_groups=max(0, len(ordered) - MAX_GROUPS),
                omitted_issues=len(actions)-sum(group['issues'] for group in visible),
                omitted_records=sum(group['records'] for group in ordered)-sum(group['records'] for group in visible),
                omitted_categories={category: sum(group['issues'] for group in ordered if group not in visible and group['category'] == category)
                                    for category in IAC_CLASSES},
                omitted_record_categories={kind: sum(entries[i]['record']['category'] == kind for action in actions
                                                     if action['id'] not in visible_ids
                                                     for i in action['members']) for kind in ('difference', 'uncompared', 'error')}, groups=visible)


def comparison_status(counts):
    return ('error' if counts['error'] else 'partial' if counts['uncompared'] else
            'differences' if counts['difference'] else 'complete match' if counts['matched'] else 'no compared records')


def iac_report(environment, directory, services, records, display=None, *, stamp=None):
    summary = iac_summary(records, environment, directory, services, display)
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
        f'分類: ' + ' / '.join(f'{category} {count}件' for category, count in summary['categories'].items()),
        f'表示{len(summary["groups"])}／全{summary["issue_count"]}対応単位、未表示{summary["omitted_issues"]}',
        '未表示の分類: ' + ' / '.join(f'{category} {count}件' for category, count in summary['omitted_categories'].items()),
        '未表示の影響: ' + ' / '.join(f'{kind} {count}件' for kind, count in summary['omitted_record_categories'].items()), '']
    for group in summary['groups']:
        target = ('不足入力: ' + brief(Path(group['target']).name) if group['target'] and group['category'] != '要判断' else
                  'Model／IaC（修正先は要判断）' if group['category'] == '要判断' else
                  '未特定（Model／IaC／比較器／不足入力を確認）')
        lines.extend([f'## {group["category"]}: {group["problem"]}',
            f'- 原因: {group["cause"]}', f'- 必要な対応: {group["remedy"]}', f'- 修正対象: {target}',
            f'- 影響範囲: {", ".join(group["services"])}。{group["records"]}レコード / 直接差分 {group["direct_resources"]}リソース / 未比較 {group["uncompared"]}項目 / 処理エラー {group["errors"]}項目'])
        if group['cascading']:
            lines.append(f'- 探索中断: {group["cascading"]}項目。直接Import依存は未確定。')
        for example in group['examples']:
            lines.append(f'対象: {example["service"]} / {example["resource"]} / {example["property"]}: {example["reason"]}')
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
    lines.extend(['詳細: 同じscanの一時artifactを issues_scan.py detail --artifact <path> --section iac_issues で確認し、',
                  '得られたIDを --section iac --issue-id <id> に指定する（--offset / --limit でページ取得）。', ''])
    return '\n'.join(lines)


def save_authority(root, environment, directory, services, filenames, check_write=True):
    prompt = task_path(root)
    text = prompt.read_text(encoding='utf-8')
    scope = active_scope(root)
    selected = {(environment, directory, service) for service in services}
    if not scope or not selected <= scope or '- Task type: `migration`' not in section(text, '## Task contract'):
        raise ValueError('report save requires a running report-only migration with explicit service scope')
    reports = {f'issues/{env}/{target}/{name}' for env, target, _ in scope for name in ('issues.md', 'iac-issues.md', 'diff.md')}
    allowed = paths_in(text, '## Allowed paths')
    permitted = reports | {prompt.relative_to(root).as_posix()}
    if not allowed & reports or not allowed <= permitted or not paths_in(text, '## Modified files') <= permitted:
        raise ValueError('save-only exception does not permit model/IaC/unscoped outputs')
    paths = [safe_path(root, f'issues/{environment}/{directory}/{name}') for name in filenames]
    if any(path.relative_to(root).as_posix() not in allowed for path in paths):
        raise ValueError('report is outside Allowed paths')
    if check_write:
        require_writable(root, set(paths))
    return paths


def atomic_files(contents):
    originals = {path: path.read_bytes() if path.exists() else None for path in contents}
    staged, published = {}, []
    try:
        for path, text in contents.items():
            if text is None:
                staged[path] = None
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
                staged[path] = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
        for path, temporary in staged.items():
            published.append(path)
            if temporary is None:
                path.unlink()
            else:
                os.replace(temporary, path)
    except BaseException:
        for path in reversed(published):
            if staged[path] is not None and staged[path].exists():  # Rename did not consume the staged file.
                continue
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(originals[path])
                os.replace(temporary, path)
        raise
    finally:
        for temporary in staged.values():
            if temporary is not None:
                temporary.unlink(missing_ok=True)


@input_scope
def save(root, environment, directory, services, candidates=(), additions=(), resolutions=(), iac=None, guard=None, display=None, stamp=None):
    names = ['issues.md'] + (['iac-issues.md'] if iac is not None else [])
    outputs = save_authority(root, environment, directory, services, names, check_write=False)
    for _ in reserved_batches(root, {'reports': outputs}):
        # Merge the latest saved service blocks only after acquisition. Keep the
        # existing publication mutex and indivisible report batch; never sleep here.
        with registration_lock(root):
            paths = save_authority(root, environment, directory, services, names)
            contents = {paths[0]: normal_merge(root, paths[0], environment, directory, services, candidates, additions, resolutions)}
            if iac is not None:
                contents[paths[1]] = iac_report(environment, directory, services, iac, display, stamp=stamp)
            if guard:
                guard()  # Check after formatting, immediately before publication; never repeat comparison.
            atomic_files(contents)
    return paths
