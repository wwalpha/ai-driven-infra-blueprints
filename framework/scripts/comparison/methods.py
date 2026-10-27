"""Declared typed comparisons and their evidence. No service, Catalog or I/O knowledge."""

from dataclasses import dataclass, field, replace
from functools import partial

from utils.iac_values import (
    Expression,
    ResourceReference,
    array_presence,
    comparison_result,
    same,
    selected_same,
    unknown_value,
    unordered_same,
)

from .contracts import ResourceContract

MISSING = object()


@dataclass(frozen=True)
class Rule:
    whole: str
    selected: str
    key: str | None = None
    custom: object = None
    actual: object = None
    local: bool = False
    reference: object = None
    selected_decision: object = None
    selected_reference: object = None
    forms: frozenset | set | None = None
    form_compare: object = None
    direct_attribute: str | None = None


SCALAR = Rule("SCALAR", "SCALAR")
OBJECT = Rule("OBJECT", "OBJECT")
ORDERED = Rule("ORDERED", "ORDERED")
UNORDERED = Rule("UNORDERED", "UNORDERED")
REFERENCE = Rule("REFERENCE", "REFERENCE")


def keyed(key):
    return Rule("ORDERED", "KEYED", key=key)


def custom(callback, *, local=False):
    return Rule("CUSTOM", "CUSTOM", custom=callback, local=local)


class RuleSet(dict):
    """Index declared method overrides once, without runtime schema acquisition."""

    def __init__(self, resource=None):
        super().__init__()
        self.special = {}
        self.resource = resource or ResourceContract()

    def __setitem__(self, path, rule):
        super().__setitem__(path, rule)
        if {rule.whole, rule.selected} & {"KEYED", "UNORDERED", "CUSTOM"}:
            self.special[path] = rule
        else:
            self.special.pop(path, None)


def properties(
    *, scalars="", objects="", ordered="", references="", tags="", resource=None
):
    """Group declarations only; descendants of containers retain typed recursion."""
    result = RuleSet(resource)
    for names, rule in (
        (scalars, SCALAR),
        (objects, OBJECT),
        (ordered, ORDERED),
        (references, REFERENCE),
        (tags, keyed("Key")),
    ):
        for name in names.split():
            if name in result:
                raise ValueError("duplicate comparison rule: " + name)
            result[name] = rule
    return result


@dataclass(frozen=True)
class Difference:
    path: str
    model: object
    iac: object
    model_pointer: tuple | None = None
    iac_pointer: tuple | None = None


@dataclass(frozen=True)
class CompareOutcome:
    equal: bool | None
    diagnostics: tuple = ()
    equivalent: bool = False
    differences: tuple = ()


EQUAL = CompareOutcome(True)


@dataclass
class _Comparison:
    rules: dict
    reference: object
    local: bool
    negative: dict = field(default_factory=dict)
    proofs: dict = field(default_factory=dict)
    keyed: dict = field(default_factory=dict)
    pairs: set = field(default_factory=set)
    diagnostics: list = field(default_factory=list)
    equivalent: bool = False


def _trace(negative, whole, left, right, path, equal):
    negative[path, id(left), id(right), whole] = equal


def _special(rule, whole, local):
    return (
        rule is not None
        and (not rule.local or local)
        and (rule.whole if whole else rule.selected) in {"KEYED", "UNORDERED", "CUSTOM"}
    )


def _has_special(rules, key, whole, local):
    selected = rules.special if isinstance(rules, RuleSet) else rules
    return any(
        _special(rule, whole, local)
        and (path == key or path.startswith((key + ".", key + "[]")))
        for path, rule in selected.items()
    )


def _detect(state, left, right, path, whole):
    rule = state.rules.get(path, OBJECT)
    scope = whole or rule.whole in {"SCALAR", "REFERENCE"}
    algorithm = same if scope else selected_same
    callback = (
        partial(_decision, state, scope)
        if state.reference is not None
        or _has_special(state.rules, path, scope, state.local)
        else None
    )
    return algorithm(
        left,
        right,
        path=path,
        reference=callback,
        trace=partial(_trace, state.negative, scope),
    )


def compare_values(
    desired,
    actual,
    key,
    *,
    rules,
    whole=False,
    reference=None,
    local=True,
    missing=False,
):
    if key not in rules:
        raise ValueError("Framework comparison rule missing: " + key)
    shown = key if isinstance(desired, list) else ""
    if missing:
        return CompareOutcome(
            False, differences=(Difference(shown, desired, MISSING, (), ()),)
        )
    rule = rules[key]
    scope = whole or rule.whole in {"SCALAR", "REFERENCE"}
    if reference is None and not _has_special(rules, key, scope, local):
        negative = {}
        algorithm = same if scope else selected_same
        equal = algorithm(
            desired, actual, path=key, trace=partial(_trace, negative, scope)
        )
        if equal is True:
            return EQUAL
        state = _Comparison(rules, reference, local, negative=negative)
    else:
        state = _Comparison(rules, reference, local)
        equal = _detect(state, desired, actual, key, scope)
    differences = (
        _evidence(state, desired, actual, key, shown, (), (), scope)
        if equal is False
        else ()
    )
    return CompareOutcome(
        equal, tuple(state.diagnostics), state.equivalent, tuple(differences)
    )


def _decision(state, whole, left, right, path):
    if state.reference is not None:
        outcome = state.reference(left, right, path)
        state.diagnostics.extend(outcome.diagnostics)
        state.equivalent |= outcome.equivalent
        if outcome.equal is not NotImplemented:
            if (
                outcome.equal is False
                and type(left) is type(right)
                and isinstance(left, (dict, list))
            ):
                state.proofs[path, id(left), id(right), whole] = _proof(
                    state, left, right, path, whole, getattr(outcome, "comparisons", ())
                )
            return outcome.equal
    rule = state.rules.get(path)
    if not _special(rule, whole, state.local):
        return NotImplemented
    mode = rule.whole if whole else rule.selected
    if mode == "CUSTOM":
        return rule.custom(left, right)
    if not isinstance(left, list) or not isinstance(right, list):
        return NotImplemented
    if mode == "KEYED":
        return _keyed_same(state, left, right, path, whole, rule.key)
    equal = unordered_same(
        left,
        right,
        path=path,
        reference=partial(_unordered_pair, state),
        trace=partial(_trace, state.negative, True),
    )
    if equal is False and len(left) != len(right):
        # A count mismatch may have needed no candidates; evaluate only missing evidence.
        _, prefix = array_presence(right)
        for a, b in zip(left, right[:prefix], strict=False):
            if (path + "[]", id(a), id(b), True) not in state.pairs:
                _detect(state, a, b, path + "[]", True)
    return equal


def _unordered_pair(state, left, right, path):
    state.pairs.add((path, id(left), id(right), True))
    return _decision(state, True, left, right, path)


def _proof_reference(comparisons, root_left, root_right, root_path, left, right, path):
    if left is root_left and right is root_right and path == root_path:
        return CompareOutcome(NotImplemented)
    for a, b, location, equal in comparisons:
        if a is left and b is right and location == path:
            return CompareOutcome(equal)
    if any(
        isinstance(value, (ResourceReference, Expression)) for value in (left, right)
    ):
        return CompareOutcome(None)
    return CompareOutcome(NotImplemented)


def _proof(state, left, right, path, whole, comparisons):
    # Reuse the resolver's decisions. No reference resolution occurs during evidence extraction.
    nested = _Comparison(
        state.rules,
        partial(_proof_reference, comparisons, left, right, path),
        state.local,
    )
    _detect(nested, left, right, path, whole)
    differences = _evidence(nested, left, right, path, "", (), (), whole)
    return differences or [Difference("", left, right, (), ())]


def _keyed_same(state, left, right, path, whole, key):
    if not all(isinstance(item, dict) and key in item for item in left):
        return NotImplemented
    if any(unknown_value(item[key]) for item in left):
        return None
    model_keys, iac_keys, unknown = {}, {}, 0
    for index, item in enumerate(left):
        model_keys.setdefault(item[key], []).append(index)
    for index, item in enumerate(right):
        if (
            unknown_value(item)
            or isinstance(item, dict)
            and unknown_value(item.get(key))
        ):
            unknown += 1
        elif isinstance(item, dict) and item.get(key) in model_keys:
            iac_keys.setdefault(item[key], []).append(index)
    state.keyed[path, id(left), id(right), whole] = key, model_keys, iac_keys, unknown
    count = sum(len(indexes) for indexes in iac_keys.values())
    membership = (
        False
        if count + unknown < len(left)
        else None
        if unknown
        else count == len(left)
    )
    results = [membership]
    for value, indexes in model_keys.items():
        partners = iac_keys.get(value, [])
        if len(indexes) != 1 or len(partners) > 1:
            results.append(False)
        elif partners:
            results.append(
                _detect(state, left[indexes[0]], right[partners[0]], path + "[]", whole)
            )
    return comparison_result(results)


def _prefix_path(parent, child):
    if isinstance(child, str):
        return (
            parent
            + ("" if not child or child.startswith("[") or not parent else ".")
            + child
        )
    return (_prefix_path(parent, child[0]), *child[1:])


def _evidence(state, left, right, typed, shown, lp, rp, whole):
    key = typed, id(left), id(right), whole
    if key in state.proofs:
        return [
            replace(
                d,
                path=_prefix_path(shown, d.path),
                model_pointer=lp + d.model_pointer
                if d.model_pointer is not None
                else None,
                iac_pointer=rp + d.iac_pointer if d.iac_pointer is not None else None,
            )
            for d in state.proofs[key]
        ]
    if left is MISSING and unknown_value(right):
        return []
    if left is MISSING or right is MISSING:
        return [Difference(shown, left, right, lp, rp)]
    if state.negative.get(key, True) is not False:
        return []
    if key in state.keyed:
        return _keyed_evidence(
            state, left, right, typed, shown, lp, rp, whole, state.keyed[key]
        )
    if type(left) is not type(right):
        return [Difference(shown, left, right, lp, rp)]
    differences = []
    if isinstance(left, dict):
        for name in sorted(left.keys() | right.keys() if whole else left.keys()):
            differences.extend(
                _evidence(
                    state,
                    left.get(name, MISSING),
                    right.get(name, MISSING),
                    typed + "." + name,
                    _path(shown, "." + name) if shown else name,
                    lp + (name,),
                    rp + (name,),
                    whole,
                )
            )
    elif isinstance(left, list):
        known, prefix = array_presence(right)
        if known != len(right) and not known <= len(left) <= len(right):
            differences.append(
                Difference(
                    _path(shown, ".要素数"),
                    len(left),
                    {"min": known, "max": len(right)},
                )
            )
        child_scope = (
            whole
            or _special(state.rules.get(typed), whole, state.local)
            and (state.rules[typed].whole if whole else state.rules[typed].selected)
            == "UNORDERED"
        )
        for index in range(
            max(len(left), len(right)) if known == len(right) else prefix
        ):
            differences.extend(
                _evidence(
                    state,
                    left[index] if index < len(left) else MISSING,
                    right[index] if index < len(right) else MISSING,
                    typed + "[]",
                    _path(shown, f"[{index}]"),
                    lp + (index,),
                    rp + (index,),
                    child_scope,
                )
            )
    else:
        differences.append(Difference(shown, left, right, lp, rp))
    return differences


def _keyed_evidence(state, left, right, typed, shown, lp, rp, whole, correspondence):
    key, model_keys, iac_keys, unknown = correspondence
    differences = []
    if unknown and len(iac_keys) + unknown < len(model_keys):
        differences.append(
            Difference(
                _path(shown, ".要素数"),
                len(model_keys),
                {"min": len(iac_keys), "max": len(iac_keys) + unknown},
            )
        )
    for value, indexes in model_keys.items():
        partners = iac_keys.get(value, [])
        field = shown, key, value
        if len(indexes) != 1 or len(partners) > 1:
            differences.append(
                Difference((field, ".要素数（キー重複）"), len(indexes), len(partners))
            )
        elif not partners and unknown:
            continue
        else:
            i, j = indexes[0], partners[0] if partners else None
            differences.extend(
                _evidence(
                    state,
                    left[i],
                    right[j] if j is not None else MISSING,
                    typed + "[]",
                    field,
                    lp + (i,),
                    rp + (j,) if j is not None else (),
                    whole,
                )
            )
    return differences


def _path(parent, suffix):
    return parent + suffix if isinstance(parent, str) else (parent, suffix)
