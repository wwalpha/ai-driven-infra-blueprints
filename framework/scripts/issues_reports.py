"""Conservative scoped report merge under a short shared lock, with atomic publication."""
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


IAC_DATA = r'<!-- iac-report-data: (.+) -->'
IAC_CATEGORIES = {'difference', 'uncompared', 'error'}


def value_differences(desired, actual, property_name='', *, exact=False, redact=safe_value):
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
        if predicate(left, right, name):
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


def mismatch_lines(item, display):
    lines = [f'- 不一致箇所: {item["service"]} / {item["resource"]} / {item["property"]}']
    differences = display.get(identifier(item))
    if differences is None:
        differences = value_differences(item.get('desired'), item.get('actual'), item['property'])
        # Legacy/masked records have no pre-redaction field evidence. Never infer equality.
        lines.append('- 相違項目の確認範囲: 保存済みのマスク済み値のみ。秘匿項目・比較方式は特定できない。')
    if not differences:
        lines.append('- 相違項目: 特定不可（検出結果は不一致。保存済み値からは復元できない）')
    for difference in differences:
        lines.append('- 相違項目: ' + difference['path'])
        for label, key in [('Model', 'model'), ('IaC', 'iac')]:
            value = safe_text(difference[key])
            fence = '`' * (max((len(run) for run in re.findall(r'`+', value)), default=0) + 1)
            lines.append(f'  - {label}: {fence} {value} {fence}')
        if difference['model'] == difference['iac']:
            lines.append('  - 不一致の検出結果を保持（マスキングまたはキー重複により表示値だけでは判別不可）。')
    return lines


def iac_state(text, environment, directory, display=None):
    """Read lossless data from this report; migrate old items without inferring causes."""
    found = re.findall(IAC_DATA, text)
    if found:
        if len(found) != 1:
            raise ValueError('malformed IaC report data')
        data = json.loads(found[0])
        if data.get('version') != 1 or data.get('scope') != [environment, directory]:
            raise ValueError('malformed IaC report scope/version')
        for entry in data['entries']:
            record = entry['record']
            if entry['id'] != iac_key(record) or type(entry['retained']) is not bool:
                raise ValueError('malformed IaC record identity/state')
        if display is not None:
            display.update(data.get('value_differences', {}))
        # Keep additions anywhere in the human-facing report, including action blocks.
        generated = set(data['generated_line_ids'])
        annotations, context = [], ''
        for line in re.sub(IAC_DATA, '', text).splitlines():
            if line.startswith('## ISSUE-'):
                context = line.partition(':')[0].removeprefix('## ')
            elif line.startswith('## '):
                context = ''
            if line.strip() and identifier(line) not in generated:
                annotations.append(f'【{context}】 {line}' if context else line)
        return data['entries'], list(dict.fromkeys([*data['annotations'], *annotations]))
    preamble, existing = blocks(text)
    if text.strip() and (not existing or any(service is None for service, _ in existing)
                         or len({service for service, _ in existing}) != len(existing)):
        raise ValueError('malformed existing IaC service blocks')
    generated = ('# model → IaC比較の非阻害結果', '通常issue gateの停止対象外。', '更新日時:',
                 '今回確認した範囲:', '今回の判定:', '未比較範囲はservice block', '保持未確認:')
    annotations = [line for line in preamble.splitlines() if line.strip() and not line.startswith(generated)]
    result = []
    for service, body in existing:
        annotation, items = numbered(body)
        annotation = re.sub(r'^### .*\n|^<!-- issue-service: .*? -->\n?', '', annotation, flags=re.M)
        annotations.extend(f'【{service}】 {line}' for line in annotation.splitlines() if line.strip() and line != '今回の差分・未比較なし。')
        for item in items:
            marker = re.search(r'<!-- iac-id: ([a-f0-9]{20}) -->', item)
            if not marker:
                raise ValueError('malformed IaC item: missing stable identity')
            content = re.sub(r'^未確認（今回の比較では解消を確定していない）: ', '', item)
            match = re.match(r'(差分|未比較|処理error): (.+?) / (.+?) / (.+?): (.*)', content, re.S)
            if not match:
                raise ValueError('malformed legacy IaC diagnostic')
            category, resource, prop, stack, reason = match.groups()
            record = {'service': service, 'resource': resource, 'property': prop,
                      'stack': None if stack == '未確定stack' else stack,
                      'category': {'差分': 'difference', '未比較': 'uncompared', '処理error': 'error'}[category],
                      'reason': reason.split('; model=', 1)[0]}
            if iac_key(record) != marker[1]:
                raise ValueError('malformed legacy IaC identity')
            result.append({'id': marker[1], 'record': record, 'legacy': content,
                           'retained': content != item})
    return result, list(dict.fromkeys(annotations))


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
            classification, status = ('処理エラー' if item['category'] == 'error' else '原因未確定'), '要調査'
            description = '原因または対応先を確定できない。'
            remedy = ('Export/Importの参照関係・宣言・有効条件と探索の完了を確認する。直接依存は未確定。'
                      if 'ImportValue' in item['reason'] else '記載した検出理由とModel/IaCの対応・検証ルールを確認し、原因と修正先を特定する。')
        group_id = 'ISSUE-' + identifier(key)
        group = groups.setdefault(group_id, {'id': group_id, 'title': title, 'classification': classification,
                                             'description': description, 'remedy': remedy, 'target': target,
                                             'status': status, 'members': []})
        group['members'].append(index)
    return sorted(groups.values(), key=lambda group: (group['status'] != '要対応', group['classification'], group['id']))


@input_scope
def iac_merge(root, path, environment, directory, services, records, display=None):
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    if old.strip() and not old.startswith('# model → IaC比較の非阻害結果\n'):
        raise ValueError('malformed existing IaC report')
    saved_display = {}
    previous, annotations = iac_state(old, environment, directory, saved_display)
    display = {**saved_display, **(display or {})}
    # Keep report storage subject to the existing value/message redaction policy too.
    records = [dict(safe_value(item), reason=safe_text(item['reason']), **{
        key: safe_value(item[key], item.get('property', '')) for key in ('desired', 'actual') if key in item})
        for item in records]
    scoped = set(services)
    if any(item['service'] not in scoped for item in records):
        raise ValueError('IaC record outside selected services')
    active, uncertain = set(), set()
    for item in records:
        if item['category'] in IAC_CATEGORIES:
            active.add(iac_key(item))
        if item['category'] in {'uncompared', 'error'}:
            uncertain.add(iac_key(item))
    entries = []
    for entry in previous:
        item = entry['record']
        if item['service'] not in scoped:
            entries.append(entry)
        elif item['category'] in IAC_CATEGORIES and (entry['id'] not in active or
                entry['id'] in uncertain and item['category'] == 'difference'):
            entries.append(dict(entry, retained=True))
    entries.extend({'id': iac_key(item), 'record': item, 'retained': False} for item in records)
    # Canonical order keeps IDs/membership/order independent of service and record input order.
    entries.sort(key=lambda entry: (entry['record']['service'], entry['id'], entry['retained'], identifier(entry)))
    # Apply the publication mask to the display side-channel as well as original records.
    for entry in entries:
        key = identifier(entry['record'])
        if key not in display:
            continue
        if not isinstance(display[key], list) or any(not isinstance(field, dict) or
                any(not isinstance(field.get(name), str) for name in ('path', 'model', 'iac')) for field in display[key]):
            raise ValueError('malformed IaC value difference display')
        fields = []
        for field in display[key]:
            shown = {'path': safe_text(field['path'])}
            for side in ('model', 'iac'):
                value = field[side]
                masked = safe_value(value, entry['record']['property'] + '.' + field['path'])
                shown[side] = safe_text(json.dumps(masked) if masked != value else value)
            fields.append(shown)
        display[key] = fields
    actions = iac_actions(entries, environment, directory)
    current = [entry['record'] for entry in entries if not entry['retained']]
    counts = {category: sum(item['category'] == category for item in current) for category in ('difference', 'uncompared', 'error')}
    retained = sum(entry['retained'] for entry in entries)
    status = 'error' if counts['error'] else 'partial' if counts['uncompared'] or retained else 'differences' if counts['difference'] else 'complete match'
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S Asia/Tokyo')
    lines = ['# model → IaC比較の非阻害結果', '', '通常issue gateの停止対象外。', '',
             f'更新日時: {stamp}', f'今回確認した範囲: {environment}／{directory}／{", ".join(sorted(scoped))}',
             f'今回の判定: {status}; 差分 {counts["difference"]}件; 未比較 {counts["uncompared"]}件; 処理error {counts["error"]}件', '',
             '## サマリー', '', f'- 独立Issue数: {len(actions)}',
             f'- 対応が必要なIssue数: {sum(group["status"] == "要対応" for group in actions)}',
             f'- 人間の判断が必要なIssue数: {sum(group["status"] in {"要判断", "要調査"} for group in actions)}',
             f'- 比較未完了のIssue数: {sum(any(entries[i]["record"]["category"] in {"uncompared", "error"} or entries[i]["retained"] for i in group["members"]) for group in actions)}',
             f'- 元レコード数: 差分 {counts["difference"]} / 未比較 {counts["uncompared"]} / 処理エラー {counts["error"]}',
             f'- 保持未確認: {retained}件（今回差分件数とは別）', '',
             '件数は保存済み全Serviceの現行結果。今回確認した範囲外の結果は再確認していない。',
             '元レコード・既存iac-id・各Issueとの対応は末尾の機械読取用データに全件保持。', '']
    for group in actions:
        members = [entries[i] for i in group['members']]
        diagnostic = [entry['record'] for entry in members]
        value_mismatch = all(item['category'] == 'difference' and item['reason'] == 'value mismatch' for item in diagnostic)
        sources = set()
        representatives = {}
        for entry in members:
            item = entry['record']
            role = item['category'], item.get('cause', {}).get('relationship', '')
            if role not in representatives or representatives[role]['retained'] and not entry['retained']:
                representatives[role] = entry
        examples = sorted(representatives.values(), key=lambda entry: (entry['record'].get('cause', {}).get('relationship') != 'direct', entry['retained'], entry['id']))[:3]
        for entry in examples:
            item = entry['record']
            if value_mismatch:
                continue
            for source in [*item.get('model_sources', [item.get('model')])[:3], item.get('iac')]:
                if source:
                    if entry['retained'] or item['service'] not in scoped:
                        sources.add(f'`{source["path"]}`（保存済み根拠・今回未再確認）')
                    else:
                        sources.add(evidence(root, path, source))
        service_names = sorted({item['service'] for item in diagnostic})
        stacks = sorted({item.get('stack') or item.get('cause', {}).get('consumer_stack') or item.get('cause', {}).get('stack') for item in diagnostic} - {None})
        direct = {(item['service'], item['resource'], item.get('stack')) for item in diagnostic if item['category'] == 'difference'}
        cascading = sum(item.get('cause', {}).get('relationship') == 'export-search-incomplete' for item in diagnostic)
        legacy_cascading = sum(item.get('cause', {}).get('relationship') == 'legacy-search-incomplete' for item in diagnostic)
        lines.extend([f'## {group["id"]}: {safe_text(group["title"])}', '',
                      *(f'<!-- issue-service: {service} -->' for service in service_names), '',
                      f'- 状態: {"保持未確認（今回の比較では解消を確定していない） / " if any(entry["retained"] for entry in members) else ""}{group["status"]}',
                      f'- 分類: {group["classification"]}', f'- 環境: {environment}/{directory}',
                      f'- 原因: {safe_text(group["description"])}', f'- 必要な対応: {group["remedy"]}',
                      *([] if value_mismatch else [f'- 修正対象: {"`" + group["target"] + "`" if group["target"] else "未確定（調査して決める）"}' + ("（IaC側の候補。Model側も根拠から確認して決める）" if group["status"] == "要判断" else "")]),
                      f'- 影響: 元レコード {len(members)}件 / 直接差分 {len(direct)}リソース / 比較未完了 {sum(item["category"] in {"uncompared", "error"} for item in diagnostic)}項目',
                      f'- 影響Service: {", ".join(service_names)}',
                      f'- 影響Stack: {", ".join(stacks[:5]) or "未確定"}' + (f' ほか{len(stacks)-5}件' if len(stacks) > 5 else '')])
        if cascading or legacy_cascading:
            lines.append(f'- 連鎖影響: 全Export探索の中断に関連する未比較 {cascading}項目 / 旧識別方式の候補探索中断 {legacy_cascading}項目。欠落Stackへの直接Import依存は未確定。')
        if sources:
            lines.append('- 根拠（代表例）: ' + '; '.join(sorted(sources)))
        for entry in examples:
            item = entry['record']
            if item['category'] == 'difference' and item['reason'] == 'value mismatch':
                lines.extend(mismatch_lines(item, display))
                continue
            reason = safe_text(item['reason']).replace(str(root) + '/', '')
            lines.append(f'- 代表的な検出: {item["service"]} / {item["resource"]} / {item["property"]}: {reason}')
            if item['category'] == 'difference' and (item.get('desired') is not None or item.get('actual') is not None):
                values = safe_text(f'model={json.dumps(item.get("desired"), ensure_ascii=False)}; IaC={json.dumps(item.get("actual"), ensure_ascii=False)}')
                lines.append('- 値（代表例）: ' + (values[:240] + '…（全体は元レコード）' if len(values) > 240 else values))
        lines.append('')
    if not actions:
        lines.extend(['今回の差分・未比較なし。', ''])
    data = {'version': 1, 'scope': [environment, directory], 'entries': entries,
            'actions': [{'id': group['id'], 'members': group['members']} for group in actions],
            'annotations': annotations, 'generated_line_ids': sorted({identifier(line) for line in lines if line.strip()})}
    data['value_differences'] = {identifier(entry['record']): display[identifier(entry['record'])]
                               for entry in entries if identifier(entry['record']) in display}
    if annotations:
        lines.extend(['## 保持した注記', '', *annotations, ''])
        data['generated_line_ids'].append(identifier('## 保持した注記'))
    # Necessary persistence only: no duplicated full diagnostic values in visible Markdown.
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e')
    return '\n'.join(lines) + f'\n<!-- iac-report-data: {payload} -->\n'


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
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
                staged[path] = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
        for path, temporary in staged.items():
            os.replace(temporary, path)
            published.append(path)
    except OSError:
        for path in reversed(published):
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
            temporary.unlink(missing_ok=True)


@input_scope
def save(root, environment, directory, services, candidates=(), additions=(), resolutions=(), iac=None, guard=None, display=None):
    names = ['issues.md'] + (['iac-issues.md'] if iac is not None else [])
    outputs = save_authority(root, environment, directory, services, names, check_write=False)
    for _ in reserved_batches(root, {'reports': outputs}):
        # Merge the latest saved service blocks only after acquisition. Keep the
        # existing publication mutex and indivisible report batch; never sleep here.
        with registration_lock(root):
            paths = save_authority(root, environment, directory, services, names)
            contents = {paths[0]: normal_merge(root, paths[0], environment, directory, services, candidates, additions, resolutions)}
            if iac is not None:
                contents[paths[1]] = iac_merge(root, paths[1], environment, directory, services, iac, display)
            if guard:
                guard()  # Check after formatting, immediately before publication; never repeat comparison.
            atomic_files(contents)
    return paths
