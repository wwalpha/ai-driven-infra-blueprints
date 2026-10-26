"""Pure Mapping-directed environment value inspection and comparison projection."""

import re
import shlex
from dataclasses import dataclass
from functools import partial

import utils.aws_mappings as aws_mappings
from utils.comparison_rows import put_row
from utils.json_format import strict_json
from utils.mapping_types import EnvironmentDefinition, path_tokens

from model.core import literal


@dataclass(frozen=True)
class EnvironmentValue:
    pointer: str
    value: object
    status: str
    reason: str
    pending_allowed: bool = True


def mapping_for(root, kind):
    service = aws_mappings.owners(root).get(kind)
    return aws_mappings.mappings_for(root).get(service).properties if service else {}


def glue_variables(text):
    """Split only the registered customer arguments, respecting quotes and commas."""
    if not isinstance(text, str):
        raise ValueError("customer environment argument must be a string")
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace, lexer.whitespace_split, lexer.commenters = ",", True, ""
    result, names = [], set()
    for token in lexer:
        name, separator, value = token.lstrip().partition("=")
        if (
            not separator
            or re.fullmatch(r"CUSTOMER_[A-Za-z0-9_]+", name) is None
            or name in names
        ):
            raise ValueError("invalid or duplicate customer environment assignment")
        names.add(name)
        result.append({"Name": name, "Value": value})
    return result


def _pointer(pointer, key):
    return pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")


def state(value, pointer="", pending_allowed=True):
    if value == "PENDING_DEPLOY":
        return EnvironmentValue(
            pointer,
            value,
            "unresolved",
            "dependency identity and deployment state are unknown",
            pending_allowed,
        )
    if isinstance(value, str):
        return EnvironmentValue(
            pointer, value, "resolved", "literal value", pending_allowed
        )
    return EnvironmentValue(
        pointer,
        value,
        "unresolved",
        "requires reference/expression resolution",
        pending_allowed,
    )


def _visit(value, tokens, spec, callback, pointer, context, evaluate=None):
    if evaluate is not None:
        value = evaluate(value)
    if not tokens:
        if spec.encoding == "json":
            if not isinstance(value, str):
                return callback(state(value, pointer))
            decoded = strict_json(value)
            if not isinstance(decoded, list):
                raise ValueError("encoded environment variables must be an array")
            value_key = spec.value_path[-1]
            name_key = "Name" if value_key == "Value" else "name"
            for child in decoded:
                if (
                    not isinstance(child, dict)
                    or not {name_key, value_key} <= child.keys()
                    or child.keys() - {name_key, value_key, spec.type_field}
                ):
                    raise ValueError(
                        "encoded environment entry requires Name and Value fields"
                    )
                if (
                    not isinstance(child[name_key], str)
                    or not child[name_key]
                    or not isinstance(child[value_key], (str, dict))
                ):
                    raise ValueError(
                        "encoded environment Name/Value must be strings or typed Values"
                    )
                if child.get(spec.type_field, "PLAINTEXT") not in {
                    "PLAINTEXT",
                    "PARAMETER_STORE",
                    "SECRETS_MANAGER",
                }:
                    raise ValueError("invalid encoded environment Type")
            leaf = EnvironmentDefinition(
                (), "value", plaintext=spec.plaintext, type_field=spec.type_field
            )
            return _visit(
                decoded, spec.value_path, leaf, callback, pointer, context, evaluate
            )
        if spec.encoding == "glue":
            if not isinstance(value, dict):
                raise ValueError("environment arguments must be an object")
            result = dict(value)
            for key in spec.keys:
                if key in result:
                    argument = (
                        evaluate(result[key]) if evaluate is not None else result[key]
                    )
                    if not isinstance(argument, str):
                        result[key] = callback(state(argument, _pointer(pointer, key)))
                        continue
                    result[key] = _visit(
                        glue_variables(argument),
                        ("[]", "Value"),
                        EnvironmentDefinition((), "value"),
                        callback,
                        _pointer(pointer, key),
                        context,
                        evaluate,
                    )
            return result
        allowed = (
            not spec.plaintext
            or (context or {}).get(spec.type_field, "PLAINTEXT") == "PLAINTEXT"
        )
        return callback(state(value, pointer, allowed))
    token, rest = tokens[0], tokens[1:]
    if token == "[]":
        if not isinstance(value, list):
            if isinstance(value, dict):
                return callback(state(value, pointer))
            raise ValueError("environment path requires an array at " + pointer)
        return [
            _visit(
                child, rest, spec, callback, _pointer(pointer, index), context, evaluate
            )
            for index, child in enumerate(value)
        ]
    if not isinstance(value, dict):
        # Intrinsic/typed references are atomic and evaluated by their existing owner.
        return value
    result = dict(value)
    selected = value.keys() if token == "*" else [token] if token in value else []
    for key in selected:
        result[key] = _visit(
            value[key], rest, spec, callback, _pointer(pointer, key), value, evaluate
        )
    return result


def project(kind, prop, value, mapping, callback, *, context=None, evaluate=None):
    """Copy selected values; decode structured strings only at Mapping-owned paths."""
    short = prop.removeprefix(kind + ".")
    row_path = () if prop == kind else path_tokens(re.sub(r"\[\d+\]", "[]", short))
    result = value
    for key, item in mapping.items():
        spec = item.environment
        if spec is None or not key.startswith(kind + "."):
            continue
        path = path_tokens(key.removeprefix(kind + ".")) + spec.path
        if path[: len(row_path)] == row_path:
            result = _visit(
                result, path[len(row_path) :], spec, callback, "", context, evaluate
            )
    return result


def _collect(result, item):
    result.append(item)
    return item.value


def inspect(kind, prop, value, mapping, *, context=None, evaluate=None):
    result = []
    project(
        kind,
        prop,
        value,
        mapping,
        partial(_collect, result),
        context=context,
        evaluate=evaluate,
    )
    return tuple(result)


def _leaves(value, pointer=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, _pointer(pointer, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, _pointer(pointer, index))
    else:
        yield pointer, value


def pending_errors(kind, prop, value, mapping, *, context=None):
    items = []
    projected = project(
        kind, prop, value, mapping, partial(_collect, items), context=context
    )
    allowed = {
        item.pointer
        for item in items
        if item.value == "PENDING_DEPLOY" and item.pending_allowed
    }
    return tuple(
        pointer
        for pointer, child in _leaves(projected)
        if child == "PENDING_DEPLOY" and pointer not in allowed
    )


def identity(item):
    return item.value


def row_contexts(kind, rows, mapping):
    """Match split Name/Type/Value rows using the existing array grouping rules."""
    tree, result = {}, {}
    for key, item in mapping.items():
        spec = item.environment
        if spec is None or spec.encoding != "value" or spec.path:
            continue
        parent = key.rsplit(".", 1)[0] + "."
        for rid, row in rows:
            prop = re.sub(r"\[\d+\]", "[]", row["property"])
            if prop.startswith(parent) and prop.rsplit(".", 1)[0] + "." == parent:
                field = "Variables[]." + prop.rsplit(".", 1)[1]
                put_row(tree, field, rid if prop == key else literal(row["value"]))
    _contexts(tree, result)
    return result


def _contexts(value, result):
    if isinstance(value, dict):
        if "Value" in value:
            result[value["Value"]] = value
        for child in value.values():
            _contexts(child, result)
    elif isinstance(value, list):
        for child in value:
            _contexts(child, result)


def value_property(kind, prop, mapping):
    """Prove scalar receiving positions, including leaves inside encoded JSON."""
    try:
        receiving = path_tokens(re.sub(r"\[\d+\]", "[]", prop.removeprefix(kind + ".")))
    except ValueError:
        return False
    for key, item in mapping.items():
        spec = item.environment
        if spec is None or spec.encoding == "glue" or not key.startswith(kind + "."):
            continue
        path = path_tokens(key.removeprefix(kind + ".")) + spec.path + spec.value_path
        if len(path) == len(receiving) and all(
            expected == actual or expected == "*"
            for expected, actual in zip(path, receiving, strict=True)
        ):
            return True
    return False
