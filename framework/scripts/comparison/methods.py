"""Declared typed comparisons and their evidence. No service, Catalog or I/O knowledge."""

from collections.abc import Hashable
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
    unordered_matching,
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
    reference_context: bool = False
    selected_decision: object = None
    selected_reference: object = None
    forms: frozenset | set | None = None
    form_compare: object = None
    direct_attribute: str | None = None
    singleton: bool = False
    keyless_unordered: bool = False


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
    candidate_failures: tuple = ()
    candidate_warnings: tuple = ()


EQUAL = CompareOutcome(True)


@dataclass
class _Comparison:
    rules: dict
    reference: object
    local: bool
    negative: dict = field(default_factory=dict)
    proofs: dict = field(default_factory=dict)
    keyed: dict = field(default_factory=dict)
    unordered: dict = field(default_factory=dict)
    diagnostics: list = field(default_factory=list)
    contexts: dict = field(default_factory=dict)
    equivalent: bool = False
    candidate_failures: list = field(default_factory=list)
    candidate_warnings: list = field(default_factory=list)


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
        equal,
        tuple(state.diagnostics),
        state.equivalent,
        tuple(differences),
        tuple(state.candidate_failures),
        tuple(state.candidate_warnings),
    )


def _decision(state, whole, left, right, path):
    rule = state.rules.get(path)
    if (
        rule
        and rule.reference_context
        and rule.whole == "OBJECT"
        and isinstance(left, dict)
        and isinstance(right, dict)
    ):
        for key in left.keys() & right.keys():
            state.contexts[path + "." + key, id(left[key]), id(right[key])] = left
        return NotImplemented
    if state.reference is not None:
        context = state.contexts.get((path, id(left), id(right)))
        outcome = (
            state.reference(left, right, path, context=context)
            if context is not None
            and any(isinstance(value, ResourceReference) for value in (left, right))
            else state.reference(left, right, path)
        )
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
    original_left, original_right = left, right
    if rule.singleton:
        if isinstance(left, str) and isinstance(right, list):
            left = [left]
        elif isinstance(right, str) and isinstance(left, list):
            right = [right]
    if not isinstance(left, list) or not isinstance(right, list):
        return NotImplemented
    if mode == "KEYED":
        if (
            not whole
            and rule.keyless_unordered
            and any(isinstance(item, dict) and rule.key not in item for item in left)
        ):
            return _keyless_same(state, left, right, path, rule.key)
        return _keyed_same(state, left, right, path, whole, rule.key)
    evidence = []
    equal = unordered_same(
        left,
        right,
        path=path,
        reference=partial(_decision, state, True),
        trace=partial(_trace, state.negative, True),
        evidence=lambda matrix, owners: evidence.append((matrix, owners)),
    )
    if equal is False and original_left is left and original_right is right:
        pairs = []
        known, _ = array_presence(right)
        if not evidence and rule.key and not known <= len(left) <= len(right):
            left_keys, right_keys = {}, {}
            for items, keys in ((left, left_keys), (right, right_keys)):
                for index, item in enumerate(items):
                    value = item.get(rule.key) if isinstance(item, dict) else None
                    if isinstance(value, str):
                        keys.setdefault(value, []).append(index)
            for value, indexes in left_keys.items():
                partners = right_keys.get(value, [])
                if len(indexes) == len(partners) == 1:
                    i, j = indexes[0], partners[0]
                    _detect(state, left[i], right[j], path + "[]", True)
                    pairs.append((i, j))
        state.unordered[path, id(left), id(right), whole] = (
            evidence[0] if evidence else (None, pairs)
        )
    return equal


def _proof_reference(
    comparisons, root_left, root_right, root_path, left, right, path, *, context=None
):
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


def _candidate_same(state, left, right, path):
    start = len(state.diagnostics)
    equivalent = state.equivalent
    result = (
        None
        if unknown_value(left) or unknown_value(right)
        else _detect(state, left, right, path, False)
    )
    details = tuple(state.diagnostics[start:]), state.equivalent and not equivalent
    del state.diagnostics[start:]
    state.equivalent = equivalent
    return result, details


def _keyless_same(state, left, right, path, key):
    matrix = [[False] * len(right) for _ in left]
    projected = {}
    details = {}
    for i, item in enumerate(left):
        for j, candidate in enumerate(right):
            actual = right.candidate(i, j) if hasattr(right, "candidate") else candidate
            projected[i, j] = actual
            matrix[i][j], details[i, j] = _candidate_same(
                state, item, actual, path + "[]"
            )
            if len(unordered_matching(matrix[: i + 1])) == i + 1:
                break
    owners = unordered_matching(matrix)
    if len(owners) != len(left):
        for i, item in enumerate(left):
            for j, candidate in enumerate(right):
                if (i, j) in projected:
                    continue
                actual = (
                    right.candidate(i, j) if hasattr(right, "candidate") else candidate
                )
                projected[i, j] = actual
                matrix[i][j], details[i, j] = _candidate_same(
                    state, item, actual, path + "[]"
                )
        owners = unordered_matching(matrix)
    possible = unordered_matching(matrix, allow_unknown=True)
    equal = (
        True
        if len(owners) == len(left)
        else None
        if len(possible) == len(left)
        else False
    )
    named = [item.get(key) for item in left if isinstance(item, dict) and key in item]
    actual_names = [
        right.key_value(j, key)
        if hasattr(right, "key_value")
        else item.get(key)
        if isinstance(item, dict)
        else item
        for j, item in enumerate(right)
    ]
    unknown_names = [
        j
        for j, name in enumerate(actual_names)
        if unknown_value(name) or not isinstance(name, Hashable)
    ]
    if equal is True and unknown_names:
        equal = None
    if any(
        names.count(name) > 1
        for names in (named, actual_names)
        for name in names
        if isinstance(name, str)
    ):
        equal = False
    selected = owners if equal is not None else possible
    if equal is None and hasattr(right, "evidence"):
        clean_matrix = [
            [
                result if not right.evidence.get((i, j), ((), ()))[1] else False
                for j, result in enumerate(row)
            ]
            for i, row in enumerate(matrix)
        ]
        clean = unordered_matching(clean_matrix, allow_unknown=True)
        selected = clean if len(clean) == len(left) else possible
        for j, i in selected.items():
            warnings, failures = right.evidence.get((i, j), ((), ()))
            state.candidate_warnings.extend(warnings)
            state.candidate_failures.extend(failures)
        for j in unknown_names:
            warnings, failures = right.key_evidence[j]
            state.candidate_warnings.extend(warnings)
            state.candidate_failures.extend(failures)
    for j, i in selected.items():
        diagnostics, equivalent = details[i, j]
        state.diagnostics.extend(diagnostics)
        state.equivalent |= equivalent
    if equal is False:
        state.unordered[path, id(left), id(right), False] = (matrix, owners, projected)
    return equal


def _keyed_same(state, left, right, path, whole, key):
    if any(unknown_value(item) for item in left):
        return None
    if not all(isinstance(item, dict) and key in item for item in left):
        return NotImplemented
    if any(
        unknown_value(item[key]) or not isinstance(item[key], Hashable) for item in left
    ):
        return None
    model_keys, iac_keys, unknown = {}, {}, 0
    for index, item in enumerate(left):
        model_keys.setdefault(item[key], []).append(index)
    for index, item in enumerate(right):
        if (
            unknown_value(item)
            or isinstance(item, dict)
            and unknown_value(item.get(key))
            or isinstance(item, dict)
            and key in item
            and not isinstance(item[key], Hashable)
        ):
            unknown += 1
        elif isinstance(item, dict) and key in item and isinstance(item[key], Hashable):
            iac_keys.setdefault(item[key], []).append(index)
    state.keyed[path, id(left), id(right), whole] = key, model_keys, iac_keys, unknown
    count = sum(len(iac_keys.get(value, [])) for value in model_keys)
    extra = whole and (
        any(value not in model_keys for value in iac_keys)
        or len(right) - unknown > len(left)
    )
    membership = (
        False
        if extra or count + unknown < len(left)
        else None
        if unknown
        else count == len(left) and (not whole or len(right) == len(left))
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
    if whole and any(len(indexes) > 1 for indexes in iac_keys.values()):
        results.append(False)
    return comparison_result(results)


def _prefix_path(parent, child):
    if isinstance(child, str):
        return _path(
            parent,
            ("" if not child or child.startswith("[") or not parent else ".") + child,
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
    if key in state.unordered:
        return _unordered_evidence(
            state, left, right, typed, shown, lp, rp, state.unordered[key]
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
    if whole:
        for value, indexes in iac_keys.items():
            if value not in model_keys:
                for j in indexes:
                    differences.append(
                        Difference(
                            (shown, key, value), MISSING, right[j], None, rp + (j,)
                        )
                    )
        for j, item in enumerate(right):
            if (isinstance(item, dict) and key not in item) or (
                not isinstance(item, dict) and not unknown_value(item)
            ):
                differences.append(
                    Difference(
                        _path(shown, f"[IaC:{j}]"), MISSING, item, None, rp + (j,)
                    )
                )
    return differences


def _keyless_evidence(state, left, right, typed, shown, lp, rp, evidence):
    matrix, owners, projected = evidence
    matched = set(owners.values())
    paired = set(owners)
    differences = []
    candidates = {}
    key = state.rules[typed].key
    for i, item in enumerate(left):
        if i in matched or any(result is None for result in matrix[i]):
            continue
        name = item.get(key) if isinstance(item, dict) else None
        partners = (
            [
                j
                for j, candidate in enumerate(right)
                if isinstance(projected[i, j], dict)
                and projected[i, j].get(key) == name
            ]
            if name is not None
            else []
        )
        if len(partners) == 1 and partners[0] not in owners:
            j = partners[0]
            paired.add(j)
            if hasattr(right, "candidate"):
                right[j] = projected[i, j]
            differences.extend(
                _evidence(
                    state,
                    item,
                    projected[i, j],
                    typed + "[]",
                    (shown, key, name),
                    lp + (i,),
                    rp + (j,),
                    False,
                )
            )
        else:
            differences.append(
                Difference(_path(shown, f"[{i}]"), item, MISSING, lp + (i,), None)
            )
            for j in range(len(right)):
                if j not in owners and (i, j) in projected:
                    candidates.setdefault(j, projected[i, j])
    for j, candidate in candidates.items():
        if j in paired:
            continue
        if hasattr(right, "candidate"):
            right[j] = candidate
        differences.append(
            Difference(
                _path(shown, f"[IaC候補:{j}（対応・差分未確定）]"),
                MISSING,
                candidate,
                None,
                rp + (j,),
            )
        )
    return differences or [Difference(shown, left, right, lp, rp)]


def _unordered_evidence(state, left, right, typed, shown, lp, rp, evidence):
    matrix, owners = evidence[:2]
    if len(evidence) == 3:
        return _keyless_evidence(state, left, right, typed, shown, lp, rp, evidence)
    if matrix is None:
        known, _ = array_presence(right)
        if known <= len(left) <= len(right):
            return [Difference(shown, left, right, lp, rp)]
        actual_count = (
            len(right) if known == len(right) else {"min": known, "max": len(right)}
        )
        differences = [Difference(_path(shown, ".要素数"), len(left), actual_count)]
        for i, j in owners:
            differences.extend(
                _evidence(
                    state,
                    left[i],
                    right[j],
                    typed + "[]",
                    _path(shown, f"[{i}]"),
                    lp + (i,),
                    rp + (j,),
                    True,
                )
            )
        return differences
    matched_left = set(owners.values())
    matched_right = set(owners)
    differences = []
    key = state.rules.get(typed, UNORDERED).key
    left_sids = [
        item.get(key) if key and isinstance(item, dict) else None for item in left
    ]
    right_sids = [
        item.get(key) if key and isinstance(item, dict) else None for item in right
    ]
    for i, sid in enumerate(left_sids):
        if (
            i not in matched_left
            and isinstance(sid, str)
            and left_sids.count(sid) == 1
            and right_sids.count(sid) == 1
        ):
            j = right_sids.index(sid)
            if j not in matched_right:
                matched_left.add(i)
                matched_right.add(j)
                differences.extend(
                    _evidence(
                        state,
                        left[i],
                        right[j],
                        typed + "[]",
                        _path(shown, f"[{i}]"),
                        lp + (i,),
                        rp + (j,),
                        True,
                    )
                )
    for i, item in enumerate(left):
        if i not in matched_left and not any(value is None for value in matrix[i]):
            differences.append(
                Difference(_path(shown, f"[{i}]"), item, MISSING, lp + (i,), None)
            )
    for j, item in enumerate(right):
        if (
            j not in matched_right
            and not unknown_value(item)
            and not any(row[j] is None for row in matrix)
        ):
            differences.append(
                Difference(_path(shown, f"[IaC:{j}]"), MISSING, item, None, rp + (j,))
            )
    return differences


def _path(parent, suffix):
    return parent + suffix if isinstance(parent, str) else (parent, suffix)
