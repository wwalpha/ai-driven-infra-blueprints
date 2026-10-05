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
from task_contract import task_path, paths_in, require_writable, registration_lock, safe_path, section
from validation_scope import active_scope
from validation_cache import input_scope, memoized
from issues_iac import safe_value


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


def iac_merge(root, path, environment, directory, services, records):
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    if old.strip() and not old.startswith('# model → IaC比較の非阻害結果\n'):
        raise ValueError('malformed existing IaC report')
    preamble, existing = blocks(old)
    if old.strip() and (not existing or any(service is None for service, _ in existing) or len({service for service, _ in existing}) != len(existing)):
        raise ValueError('malformed existing IaC service blocks')
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S Asia/Tokyo')
    prefix = ('# model → IaC比較の非阻害結果\n\n通常issue gateの停止対象外。\n\n' +
              f'更新日時: {stamp}\n今回確認した範囲: {environment}／{directory}／{", ".join(services)}\n')
    counts = {category: sum(item['category'] == category for item in records) for category in ('difference', 'uncompared', 'error')}
    status = 'error' if counts['error'] else 'partial' if counts['uncompared'] else 'differences' if counts['difference'] else 'complete match'
    prefix += f'今回の判定: {status}; 差分 {counts["difference"]}件; 未比較 {counts["uncompared"]}件; 処理error {counts["error"]}件\n未比較範囲はservice blockの未比較項目に記載。\n\n'
    pending = {service: [item for item in records if item['service'] == service] for service in services}
    output, retained = [], 0
    for service, body in existing:
        if service not in pending:
            output.append(body)
            continue
        annotation, olditems = numbered(body)
        annotation = re.sub(r'^### .*\n|^<!-- issue-service: .*? -->\n?', '', annotation, flags=re.M).strip()
        annotation = annotation.replace('今回の差分・未比較なし。', '').strip()
        current = pending[service]
        activekeys = {iac_key(item) for item in current if item['category'] in {'difference', 'uncompared', 'error'}}
        uncertainkeys = {iac_key(item) for item in current if item['category'] in {'uncompared', 'error'}}
        kept = []
        for item in olditems:
            match = re.search(r'<!-- iac-id: ([a-f0-9]{20}) -->', item)
            if not match:
                raise ValueError('malformed IaC item: missing stable identity')
            original_item = re.sub(r'^未確認（今回の比較では解消を確定していない）: ', '', item)
            if match.group(1) not in activekeys or (match.group(1) in uncertainkeys and original_item.startswith('差分:')):
                # Keep old differences until explicit repair/revalidation; comparison loss is not resolution.
                kept.append('未確認（今回の比較では解消を確定していない）: ' + original_item)
                retained += 1
        pending[service] = (current, kept, annotation)
    for service, content in pending.items():
        records_for_service, kept, annotation = content if isinstance(content, tuple) else (content, [], '')
        items = kept[:]
        for item in records_for_service:
            if item['category'] not in {'difference', 'uncompared', 'error'}:
                continue
            category = {'difference': '差分', 'uncompared': '未比較', 'error': '処理error'}[item['category']]
            values = f"model={json.dumps(item.get('desired'), ensure_ascii=False)}; IaC={json.dumps(item.get('actual'), ensure_ascii=False)}"
            links = '; '.join(filter(None, [*(evidence(root, path, source) for source in item.get('model_sources', [item.get('model')])), evidence(root, path, item.get('iac'))]))
            message = safe_text(f'{category}: {item["resource"]} / {item["property"]} / {item.get("stack") or "未確定stack"}: {item["reason"]}; {values}').replace(str(root) + '/', '')
            items.append(message + (f' 根拠: {links}' if links else '') + f' <!-- iac-id: {iac_key(item)} -->')
        output.append(f'### {service}\n\n<!-- issue-service: {service} -->\n\n' +
                      (annotation + '\n\n' if annotation else '') +
                      ('\n\n'.join(f'{i}. {item}' for i, item in enumerate(items, 1)) if items else '今回の差分・未比較なし。') + '\n\n')
    if retained:
        prefix = prefix.replace(f'今回の判定: {status}', '今回の判定: partial (保持未確認あり)')
        prefix += f'保持未確認: {retained}件（今回差分件数とは別）。\n\n'
    # Preserve human prose if a report has acquired annotations outside generated sections.
    generated = ('# model → IaC比較の非阻害結果', '通常issue gateの停止対象外。', '更新日時:', '今回確認した範囲:', '今回の判定:', '未比較範囲はservice block', '保持未確認:')
    extras = [line for line in preamble.splitlines() if line.strip() and not line.startswith(generated)]
    return prefix + ''.join(line + '\n' for line in extras) + ''.join(output)


def save_authority(root, environment, directory, services, filenames):
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
def save(root, environment, directory, services, candidates=(), additions=(), resolutions=(), iac=None, guard=None):
    names = ['issues.md'] + (['iac-issues.md'] if iac is not None else [])
    # Existing portable registration lock is outside the repository and fail-closed.
    # All report writers through this entrypoint share it; callers retry a busy save.
    with registration_lock(root):
        paths = save_authority(root, environment, directory, services, names)
        contents = {paths[0]: normal_merge(root, paths[0], environment, directory, services, candidates, additions, resolutions)}
        if iac is not None:
            contents[paths[1]] = iac_merge(root, paths[1], environment, directory, services, iac)
        if guard:
            guard()  # Check after formatting, immediately before publication; never repeat comparison.
        atomic_files(contents)
    return paths
