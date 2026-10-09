"""Terraform root/module boundaries; Terraform itself retains full syntax validation."""

import json
import re
from pathlib import Path


def root_directory(root, target):
    # Target keys already contain the authoritative alias-or-account directory.
    environment, directory = target
    return module_directory(root, directory).parent / environment


def module_directory(root, directory):
    return root / 'infra' / directory / 'terraform' / 'modules'


def is_configuration(path):
    return path.suffix == '.tf' or path.name.endswith('.tf.json')


def is_terraform_path(path):
    path = Path(path)
    parts = path.parts
    return bool(parts and parts[0] == 'infra' and (
        is_configuration(path) or parts[1:2] == ('terraform',) or parts[2:3] == ('terraform',)))


def placement(path, root):
    parts = path.relative_to(root).parts
    if len(parts) >= 4 and parts[0] == 'infra' and parts[2] == 'terraform':
        directory, environment = parts[1], parts[3]
        if environment == 'modules':
            return directory, None, len(parts) >= (6 if is_configuration(path) else 5)
        return directory, environment, len(parts) == 5 if is_configuration(path) else len(parts) >= 5
    return None, None, False


def files(root):
    return sorted(path for path in (root / 'infra').rglob('*')
                  if path.is_file() and is_terraform_path(path.relative_to(root))
                  and not any(part.startswith('.') for part in path.relative_to(root).parts))


def selected(path, root, scope, findings, changed_modules=()):
    directory, environment, _ = placement(path, root)
    return (scope is None or findings.relative(path) in (findings.file_gate_paths or set())
            or directory in changed_modules
            or any(target == directory and (environment is None or env == environment)
                   for env, target, _ in scope))


def check_placement(root, scope, accounts, template_mode, findings):
    for path in files(root):
        if not template_mode and not selected(path, root, scope, findings):
            continue
        relative = findings.relative(path)
        directory, environment, valid = placement(path, root)
        findings.check_file(not template_mode, path, f'template mode contains terraform implementation: {relative}')
        findings.check_file(valid, path, f'Terraform placement must use target Root or modules/<module>; legacy paths are forbidden: {relative}')
        targets = [key for key in accounts if key[1] == directory and (environment is None or key[0] == environment)]
        findings.check_file(bool(targets), path, f'Terraform target is not defined: {relative}')
        if targets:
            findings.check_file(any(accounts[key]['engine'] == 'terraform' for key in targets), path,
                                f'Terraform is not selected: {relative}')


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
            elif kind == 'resource':
                for resource_type in values:
                    yield kind, resource_type, None
            else:
                yield kind, '', None
        return
    stream = list(tokens(text))
    index = 0
    while index < len(stream):
        kind = stream[index]
        index += 1
        labels = []
        while index < len(stream) and stream[index][0] in {'string', 'identifier'}:
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


def check_configuration(root, scope, accounts, findings, changed_paths=()):
    changed_modules = {}
    for relative in sorted(changed_paths):
        path = root / relative
        directory, environment, valid = placement(path, root)
        if valid and environment is None and (findings.file_gate_paths is None
                                               or relative in findings.file_gate_paths):
            changed_modules.setdefault(directory, []).append(path)
    configurations = [path for path in files(root) if is_configuration(path)]
    active = {path for path in configurations if selected(path, root, scope, findings, changed_modules)}
    directories = {placement(path, root)[0] for path in active}
    calls = {}
    for path in configurations:
        directory, environment, valid = placement(path, root)
        if directory not in directories or (environment is None and path not in active):
            continue
        if not valid or not any(key[1] == directory and (environment is None or key[0] == environment)
                                and value['engine'] == 'terraform' for key, value in accounts.items()):
            continue  # Placement/engine diagnostics belong to common IaC selection.
        expected = module_directory(root.resolve(), directory)
        try:
            for kind, name, source in blocks(path):
                if path in active and environment is not None and kind == 'resource' and name.startswith(('aws_', 'awscc_')):
                    findings.check_file(False, path, f'Terraform AWS resource must be in the target Module, not Root: {findings.relative(path)}')
                elif kind == 'module':
                    local = isinstance(source, str) and (source.startswith(('./', '../')) or Path(source).is_absolute())
                    literal = local and not any(marker in source for marker in ('${', '%{'))
                    # Remote child modules retain Terraform semantics; Root calls own local Modules.
                    if environment is None and isinstance(source, str) and not local:
                        continue
                    if path in active:
                        findings.check_file(literal, path, f'Terraform Module source must be a local literal path: {findings.relative(path)}: {name}')
                    if not literal:
                        continue
                    resolved = (path.parent / source).resolve()
                    if environment is not None and resolved.is_dir() and resolved != expected and resolved.is_relative_to(expected):
                        calls.setdefault((directory, name), []).append((environment, path, resolved))
                    if path not in active:
                        continue
                    gates = [path, *(changed for changed in changed_modules.get(directory, [])
                                     if changed.resolve().is_relative_to(resolved))]
                    for gate in gates:
                        findings.check_file(resolved.is_dir(), gate, f'Terraform Module source does not exist: {findings.relative(path)}: {name}')
                        findings.check_file(resolved != expected and resolved.is_relative_to(expected), gate,
                                            f'Terraform Module source must resolve inside {expected.relative_to(root.resolve())}/<module> for this target: {findings.relative(path)}: {name}')
        except (OSError, ValueError, TypeError, AttributeError) as error:
            if path in active:
                findings.check_file(False, path, f'Terraform configuration cannot be read: {findings.relative(path)}: {error}')
    for (directory, name), references in calls.items():
        if len({env for env, _, _ in references}) < 2 or len({source for _, _, source in references}) < 2:
            continue
        gates = {path for _, path, _ in references if path in active}
        gates.update(changed for changed in changed_modules.get(directory, [])
                     if any(changed.resolve().is_relative_to(source) for _, _, source in references))
        for gate in sorted(gates):
            findings.check_file(False, gate, f'Terraform Module {name} must use the same source across environments for {directory}: '
                                + ', '.join(f'{env}={source.relative_to(root.resolve())}' for env, _, source in references))
