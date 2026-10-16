"""Invert only provable input substitutions; keep all other template expressions intact."""
import copy
import json
from pathlib import Path

from model_core import literal
from model_parameter_inputs import edit_instances, check_type
from model_templates import bound_definition, resolve, template_document, template_document_text, variables


def parameter_edit(original, wanted):
    """Patch changed input nodes only; keep unrelated comments, ordering and spelling."""
    import yaml
    from model_parameter_inputs import yaml_read
    before = yaml_read(original)
    changes = []
    def equal(left, right):
        return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
    def line_start(index):
        return original.rfind('\n', 0, index) + 1
    def edit(node, old, new):
        if equal(old, new):
            return
        if isinstance(old, dict) and isinstance(new, dict) and old and new and not node.flow_style:
            nodes = {key.value: (key, value) for key, value in node.value}
            for name, (key, value) in nodes.items():
                if name in new:
                    edit(value, old[name], new[name])
                else:
                    start = line_start(key.start_mark.index)
                    end = value.end_mark.index
                    end = line_start(end) if not original[line_start(end):end].strip() else original.find('\n', end)
                    end = len(original) if end < 0 else end + (original[end:end+1] == '\n')
                    changes.append((start, end, ''))
            added = {name: value for name, value in new.items() if name not in old}
            if added:
                end = node.end_mark.index
                if not original[line_start(end):end].strip():
                    end = line_start(end)
                prefix = '' if end == 0 or original[end-1] == '\n' else '\n'
                text = prefix + ''.join(' ' * node.start_mark.column + json.dumps(name, ensure_ascii=False) + ': '
                                       + json.dumps(value, ensure_ascii=False) + '\n' for name, value in added.items())
                changes.append((end, end, text))
        else:
            text = json.dumps(new, ensure_ascii=False)
            if isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and not node.flow_style:
                text += '\n' + ' ' * node.end_mark.column
            changes.append((node.start_mark.index, node.end_mark.index, text))
    edit(yaml.compose(original), before, wanted)
    result = original
    last = len(original) + 1
    for start, end, text in sorted(changes, reverse=True):
        if end > last:
            raise ValueError('IMPORT input edit has overlapping YAML source spans')
        result = result[:start] + text + result[end:]
        last = start
    if not equal(yaml_read(result), wanted):
        raise ValueError('IMPORT input edit cannot preserve unrelated YAML values')
    return result


def equivalent(left, right):
    if left == right:
        return True
    left, right = literal(left), literal(right)
    if left == right:
        return True
    try:
        a, b = json.loads(left), json.loads(right)
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except (ValueError, TypeError):
        return False


def render(key, raw, context):
    if key.endswith('.document') or raw.startswith('`{') or raw.startswith('`['):
        return template_document_text(key, resolve(template_document(key, raw), context, structured=True))
    return resolve(raw, context)


def optional_plan(definitions, parameters, bindings, values):
    """Activate an existing instance-local optional row only when its inputs are unambiguous."""
    from model_core import entries
    parameters, bindings = copy.deepcopy(parameters), copy.deepcopy(bindings)
    mapped = {row for binding in bindings.values() for row in binding['rows'].values()}
    for rid, row in entries(values, 'desired.row.'):
        if rid in mapped:
            continue
        candidates = []
        matched = False
        for instance, binding in bindings.items():
            definition = definitions[binding['definition']]
            for local, owner in definition.rows.items():
                base = 'desired.row.' + local + '.'
                selector = definition.optional.get(base + 'property')
                if local in binding['rows'] or binding['resources'].get(owner) != rid.rpartition('-')[0] or not selector:
                    continue
                if definition.values[base + 'property'] != row['property']:
                    continue
                matched = True
                spec = definition.parameters[selector]
                if spec.get('source') or spec.get('internal') or any(definition.optional.get(base + leaf) != selector for leaf in ('value', 'comment')):
                    continue
                if any(selector in variables(text) for text in definition.values.values()) or selector in definition.optional_json.values() or any(
                        flag == selector for _, _, flag in definition.choices):
                    continue
                # A selector with effects beyond this row requires a separate explicit plan.
                if {key for key, flag in definition.optional.items() if flag == selector} != {base + leaf for leaf in ('property', 'value', 'comment')}:
                    continue
                raw = definition.values[base + 'value']
                names = variables(raw)
                supplied = {selector: True}
                if names:
                    if len(names) != 1:
                        continue
                    name = next(iter(names))
                    input_spec = definition.parameters.get(name, {})
                    if input_spec.get('source') or input_spec.get('internal') or input_spec.get('type') == 'reference' or literal(raw) != '<<' + name + '>>':
                        continue
                    # Never reuse a name already constraining another destination.
                    if any(name in variables(text) for key, text in definition.values.items() if key != base + 'value'):
                        continue
                    value = literal(row['value'])
                    if input_spec['type'] != 'string':
                        value = json.loads(value)
                    check_type(input_spec, value, name)
                    supplied[name] = value
                elif not equivalent(raw, row['value']):
                    continue
                if variables(definition.values[base + 'comment']):
                    continue
                candidates.append((instance, local, supplied, definition.values[base + 'comment']))
        if len(candidates) > 1:
            raise ValueError('IMPORT conflict: ambiguous optional row definition')
        if matched and not candidates:
            raise ValueError('IMPORT conflict: optional row cannot be activated without uncertain effects')
        if candidates:
            instance, local, supplied, comment = candidates[0]
            parameters['instances'].setdefault(instance, {'parameters': {}})['parameters'].update(supplied)
            bindings[instance]['rows'][local] = rid
            values['desired.row.' + rid + '.comment'] = comment
    return parameters, bindings


def input_plan(template, definitions, parameters, bindings, expansion, values, environment, promotions=None):
    """Check every use, including CREATE, excluded rows and JSON, before returning edits."""
    parameters = copy.deepcopy(parameters)
    instances, _ = edit_instances(template, parameters, {'instances': bindings}, definitions, environment)
    instances = instances['instances']
    contexts = {item['id']: {**item['parameters'], **{'Id_' + k: v for k, v in item['resources'].items()}} for item in instances}
    selected = {item['id']: bound_definition(definitions[item['definition']], item['parameters']) for item in instances}
    for item in instances:
        context = contexts[item['id']]
        for local in item['resources']:
            context['Anchor_' + local] = resolve(selected[item['id']].values[f'desired.resource.{local}.anchor'], context)
    proposals = {}

    def propose(trace, name, value):
        info = trace.get('inputs', {}).get(name)
        if not info or info['source'] not in {'instance', 'service'} or info['type'] == 'reference':
            raise ValueError('IMPORT conflict: immutable reference/internal/consumer input')
        if Path(trace['sourceFile']).parent != Path(trace['bindingFile']).parent:
            raise ValueError('IMPORT conflict: input provenance is outside the selected source directory')
        spec = definitions[trace['definition']].parameters[name]
        check_type(spec, value, name)
        target = (None if info['source'] == 'service' else trace['instance'], name)
        if target in proposals and (type(proposals[target]) is not type(value) or proposals[target] != value):
            raise ValueError('IMPORT conflict: inconsistent AWS values for shared variable ' + name)
        proposals[target] = value

    def invert(raw, wanted, trace):
        if isinstance(raw, dict):
            if not isinstance(wanted, dict) or raw.keys() != wanted.keys():
                raise ValueError('IMPORT conflict: JSON shape cannot be inverted')
            for key in raw:
                invert(raw[key], wanted[key], trace)
        elif isinstance(raw, list):
            if not isinstance(wanted, list) or len(raw) != len(wanted):
                raise ValueError('IMPORT conflict: JSON shape cannot be inverted')
            for a, b in zip(raw, wanted):
                invert(a, b, trace)
        elif isinstance(raw, str) and variables(raw):
            names = variables(raw)
            # Registered consumer context is fixed, so it need not become an inverse input.
            fixed = {name for name in names if trace.get('inputs', {}).get(name, {}).get('source') == 'consumer.environment'}
            if len(names - fixed) == 1:
                for name in fixed:
                    raw = raw.replace('<<' + name + '>>', contexts[trace['instance']][name])
                names = variables(raw)
            if len(names) != 1:
                raise ValueError('IMPORT conflict: combined variables cannot be uniquely inverted')
            name = next(iter(names))
            token = '<<' + name + '>>'
            if raw == token:
                info = trace.get('inputs', {}).get(name, {})
                if isinstance(wanted, str) and info.get('type') not in {None, 'string', 'reference'}:
                    wanted = json.loads(wanted)
                propose(trace, name, wanted)
            elif isinstance(wanted, str) and raw.count(token) == 1:
                prefix, suffix = raw.split(token)
                if not wanted.startswith(prefix) or not wanted.endswith(suffix) or len(wanted) < len(prefix) + len(suffix):
                    raise ValueError('IMPORT conflict: expression does not match AWS value')
                propose(trace, name, wanted[len(prefix):len(wanted)-len(suffix) if suffix else None])
            else:
                raise ValueError('IMPORT conflict: expression cannot be uniquely inverted')
        elif raw != wanted:
            raise ValueError('IMPORT conflict: fixed JSON node changed beside a variable')

    pending = []
    for key, trace in expansion.provenance.items():
        if key not in values or not key.startswith('desired.row.') or not key.endswith(('.value', '.document')) or 'definition' not in trace:
            continue
        raw = selected[trace['instance']].values[trace['key']]
        if equivalent(expansion.values[key], values[key]):
            continue
        if not variables(raw):
            if promotions is not None:
                promotions.add(key)
            continue
        pending.append((key, trace, raw))
    # Simple destinations constrain shared fragments before checking combined expressions.
    pending.sort(key=lambda item: len(variables(item[2])))
    for key, trace, raw in pending:
        context = dict(contexts[trace['instance']])
        context.update({name: value for (owner, name), value in proposals.items() if owner in {None, trace['instance']}})
        if equivalent(render(trace['key'], raw, context), values[key]):
            continue
        previous = dict(proposals)
        try:
            if key.endswith('.document') or raw.startswith(('`{', '`[')):
                invert(template_document(trace['key'], raw), template_document(trace['key'], values[key]), trace)
            else:
                invert(literal(raw), literal(values[key]), trace)
        except (ValueError, TypeError):
            if promotions is None:
                raise
            proposals = previous
            promotions.add(key)
    if promotions is not None:
        # Reject side effects before applying any inverse substitution.
        rejected = set()
        for key, trace in expansion.provenance.items():
            if 'definition' not in trace or trace.get('derivedFrom') or key.startswith('observed.'):
                continue
            uses = {(owner, name) for owner, name in proposals
                    if name in trace.get('parameters', []) and owner in {None, trace['instance']}}
            if not uses:
                continue
            context = dict(contexts[trace['instance']])
            context.update({name: proposals[owner, name] for owner, name in uses})
            if key not in values or not equivalent(render(trace['key'], selected[trace['instance']].values[trace['key']], context), values[key]):
                rejected.update(uses)
        for target in rejected:
            del proposals[target]
        for key, trace, raw in pending:
            if any(name in variables(raw) and owner in {None, trace['instance']} for owner, name in rejected):
                promotions.add(key)
    for (owner, name), value in proposals.items():
        if owner is None:
            parameters.setdefault('parameters', {})[name] = value
            for context in contexts.values():
                if name in context:
                    context[name] = value
        else:
            parameters['instances'][owner]['parameters'][name] = value
            contexts[owner][name] = value
    for key, trace in expansion.provenance.items():
        if key not in values or 'definition' not in trace or trace.get('derivedFrom') or key.startswith('observed.'):
            continue
        affected = any(name in trace.get('parameters', []) and owner in {None, trace['instance']} for owner, name in set(proposals))
        if affected:
            raw = selected[trace['instance']].values[trace['key']]
            if not equivalent(render(trace['key'], raw, contexts[trace['instance']]), values[key]):
                raise ValueError('IMPORT conflict: variable update affects an unconfirmed or CREATE destination: ' + key)
    return parameters, selected
