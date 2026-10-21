"""JSON contracts shared by Model syntax, Policy/IaC readers and projections."""
import hashlib
import json
import math


def unique_object(pairs: list[tuple[str, object]], *, label='policy JSON') -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate {label} key: {key}')
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError(f'invalid JSON constant: {value}')


def _number(raw):
    number = float(raw)
    if not math.isfinite(number):
        raise ValueError('nonfinite JSON number: ' + raw)
    return number


def strict_json(value):
    return json.loads(value, object_pairs_hook=lambda pairs: unique_object(pairs, label='JSON'),
                      parse_constant=invalid_constant, parse_float=_number)


def policy_json(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def document_sha256(content) -> str:
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
