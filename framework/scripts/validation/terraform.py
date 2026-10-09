"""Terraform root/module boundaries; Terraform itself retains full syntax validation."""

import json
import re


def tokens(text):
    """Read HCL tokens, treating comments and template contents as opaque."""
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith(('//', '#'), index):
            end = text.find('\n', index)
            index = len(text) if end < 0 else end + 1
        elif text.startswith('/*', index):
            end = text.find('*/', index + 2)
            if end < 0:
                raise ValueError('unterminated comment')
            index = end + 2
        elif match := re.match(r'<<-?([A-Za-z_][A-Za-z0-9_-]*)[^\S\n]*\n', text[index:]):
            end = re.search(r'^\s*' + re.escape(match[1]) + r'[^\S\n]*(?:\n|$)',
                            text[index + match.end():], re.M)
            if end is None:
                raise ValueError('unterminated heredoc')
            index += match.end() + end.end()
            yield 'literal', ''
        elif text[index] == '"':
            start = index
            index += 1
            # Template expressions can contain their own quoted strings/braces.
            depth = 0
            quoted = False
            while index < len(text):
                char = text[index]
                if char == '\\':
                    index += 2
                    continue
                if not depth and text.startswith(('${', '%{'), index):
                    depth = 1
                    index += 2
                    continue
                if char == '"':
                    if not depth:
                        break
                    quoted = not quoted
                if depth and not quoted:
                    depth += (char == '{') - (char == '}')
                index += 1
            if index >= len(text):
                raise ValueError('unterminated string')
            raw = text[start:index + 1]
            index += 1
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw[1:-1]
            yield 'string', value
        elif match := re.match(r'[A-Za-z_][A-Za-z0-9_-]*', text[index:]):
            index += match.end()
            yield 'identifier', match[0]
        else:
            yield 'symbol', text[index]
            index += 1


def blocks(path):
    text = path.read_text(encoding='utf-8')
    if path.name.endswith('.tf.json'):
        data = json.loads(text)
        for kind, values in data.items():
            if kind == 'module':
                for name, body in values.items():
                    yield kind, name, body.get('source')
            else:
                yield kind, '', None
        return
    stream = list(tokens(text))
    index = 0
    while index < len(stream):
        kind = stream[index]
        index += 1
        labels = []
        while index < len(stream) and stream[index][0] == 'string':
            labels.append(stream[index][1])
            index += 1
        if kind[0] != 'identifier' or index >= len(stream) or stream[index] != ('symbol', '{'):
            raise ValueError('expected top-level HCL block')
        depth, source = 1, None
        index += 1
        while index < len(stream) and depth:
            token = stream[index]
            if depth == 1 and token == ('identifier', 'source') and stream[index + 1:index + 2] == [('symbol', '=')]:
                value = stream[index + 2:index + 3]
                following = stream[index + 3:index + 5]
                boundary = following[:1] == [('symbol', '}')] or (
                    len(following) == 2 and following[0][0] == 'identifier' and following[1] == ('symbol', '='))
                source = value[0][1] if value and value[0][0] == 'string' and boundary else None
            if token[0] == 'symbol':
                depth += (token[1] == '{') - (token[1] == '}')
            index += 1
        if depth:
            raise ValueError('unterminated HCL block')
        yield kind[1], labels[0] if labels else '', source


def check_configuration(root, scope, accounts, findings):
    base = root / 'infra/terraform/environments'
    modules = root / 'infra/terraform/modules'
    for path in sorted(base.rglob('*')):
        if not path.is_file() or not (path.suffix == '.tf' or path.name.endswith('.tf.json')):
            continue
        parts = path.relative_to(base).parts
        if any(part.startswith('.') for part in parts) or len(parts) != 3:
            continue
        target = parts[:2]
        if scope is not None and not any(item[:2] == target for item in scope) and \
                findings.relative(path) not in (findings.file_gate_paths or set()):
            continue
        if target not in accounts or accounts[target]['engine'] != 'terraform':
            continue  # Engine/target diagnostics belong to common IaC selection.
        expected = modules.resolve() / accounts[target]['alias']
        try:
            for kind, name, source in blocks(path):
                if kind == 'resource':
                    findings.check_file(False, path, f'Terraform resource must be in the target Module, not Root: {findings.relative(path)}')
                elif kind == 'module':
                    literal = isinstance(source, str) and source.startswith(('./', '../')) and not any(
                        marker in source for marker in ('${', '%{'))
                    findings.check_file(literal, path, f'Terraform Module source must be a local literal path: {findings.relative(path)}: {name}')
                    if not literal:
                        continue
                    resolved = (path.parent / source).resolve()
                    findings.check_file(resolved.is_dir(), path, f'Terraform Module source does not exist: {findings.relative(path)}: {name}')
                    findings.check_file(resolved == expected, path, f'Terraform Module source must resolve to modules/{accounts[target]["alias"]} for this target: {findings.relative(path)}: {name}')
        except (OSError, ValueError, TypeError, AttributeError) as error:
            findings.check_file(False, path, f'Terraform configuration cannot be read: {findings.relative(path)}: {error}')
