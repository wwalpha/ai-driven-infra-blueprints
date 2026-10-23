"""Pure record identities, masking and field differences."""
import hashlib
import json
import re
from iac_values import safe_value, same, selected_same

def identifier(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def safe_text(text):
    value = safe_value(text)
    value = re.sub(r'(?i)((?:password|secretstring|token|credential)\s*[=:]\s*)[^\s,;]+', r'\1<masked>', value)
    return value.replace('\n', ' ').replace('\r', ' ')


def iac_key(item):
    return identifier([item['service'], item['resource'], item['property'], item.get('stack')])


def condition_disabled(item):
    cause = item.get('cause', {})
    return (item['category'] == 'difference' and cause.get('kind') == 'condition-disabled'
            and cause.get('result') is False)


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


def brief(value, limit=160):
    value = safe_text(str(value)).replace('|', '／').replace('<', '&lt;').replace('>', '&gt;')
    return value if len(value) <= limit else value[:limit] + '…（全文はartifact）'


def redacted(self, value, prop=''):
    value = safe_value(value, prop)
    if prop in {'id','service','resource','resourceType','resourceMode','property','stack','code','naming_context_id','job_id','diagnostic_id','scope'}:
        return value
    if isinstance(value, str) and any(secret in value for secret in self.sensitive_values if secret):
        return '<masked sensitive parameter>'
    if isinstance(value, dict):
        return {key: self.redacted(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [self.redacted(item, prop) for item in value]
    return value


def record(self, category, service, identity, prop, reason, desired=None, actual=None, stack=None, source=None, template=None, cause=None):
    self.results.append({'category': category, 'service': service, 'resource': identity,
                         'property': prop, 'reason': reason, 'desired': self.redacted(desired, prop),
                         'actual': self.redacted(actual, prop), 'stack': stack,
                         'model': source or self.source(service, f'desired.resource.{identity}.resourceType'),
                         'iac': template})
    if cause:
        self.results[-1]['cause'] = self.redacted(cause)


