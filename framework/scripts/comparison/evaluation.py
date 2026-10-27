"""Connect the shared evaluator to tracked comparison lookups."""

from collections.abc import Hashable
from functools import partial

from iac_evaluation import Evaluation
from json_intrinsics import intrinsic, project_document
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference, unknown_value

from .deferral import ImportReferenceDeferred
from .values import PreparedValue


def evaluator(
    stack_inputs,
    resources,
    property_schema,
    symbol,
    import_value,
    local_comparison,
    resource_schema,
    defer_select=None,
):
    return Evaluation(
        stack_inputs,
        resources,
        property_schema,
        symbol,
        import_value,
        local_comparison,
        resource_schema,
        defer_select,
    )


class SelectedCandidates(list):
    """Project each candidate only for the Model element being compared."""

    def __init__(
        self,
        values,
        desired,
        path,
        evaluate,
        property_name,
        model_path,
        rules,
        locations,
        initial,
    ):
        super().__init__(values)
        self.desired = desired
        self.path = path
        self.evaluate = evaluate
        self.property_name = property_name
        self.model_path = model_path
        self.rules = rules
        self.cache = {}
        self.values = {}
        self.locations = locations
        self.initial = initial
        self.evidence = {}

    def evaluate_cached(self, value):
        identity = id(value)
        if identity not in self.values:
            try:
                result = self.evaluate(value)
            except (Blocked, KeyError, ValueError, TypeError, IndexError) as error:
                self.values[identity] = (value, error, True)
            else:
                self.values[identity] = (value, result, False)
        _, result, failed = self.values[identity]
        if failed:
            raise result
        return result

    def candidate(self, i, j):
        if (i, j) not in self.cache:
            warnings, failures = self.initial[j]
            warnings, failures = list(warnings), list(failures)
            self.cache[i, j] = _visit_actual(
                self[j],
                self.desired[i],
                self.path + "[]",
                self.locations[j],
                self.evaluate_cached,
                False,
                warnings,
                failures,
                self.property_name,
                self.model_path,
                self.rules,
                {},
            )
            self.evidence[i, j] = warnings, failures
        return self.cache[i, j]


def _candidate_root(value, pointer, evaluate):
    while (
        isinstance(value, dict)
        and len(value) == 1
        and isinstance(value.get("Fn::If"), list)
        and len(value["Fn::If"]) == 3
    ):
        argument = value["Fn::If"]
        try:
            index = 1 if evaluate({"Condition": argument[0]}) else 2
        except (Blocked, KeyError, ValueError, TypeError, IndexError) as error:
            return value, pointer, error
        value = argument[index]
        pointer += "/Fn::If/" + str(index)
    return value, pointer, None


def _raise_candidate_error(error, value):
    raise error


def key_integrity(value, *, rule, evaluate, property_name, model_path):
    """Validate input uniqueness independently of selected-attribute comparison."""
    warnings, failures, names = [], [], {}
    value, pointer, error = _candidate_root(value, "", evaluate)
    if error:
        return PreparedValue(
            None, warnings, failures=((property_name, pointer, error),)
        )
    if not isinstance(value, list) or len(value) < 2:
        return PreparedValue(None, warnings)
    key = rule.key
    path = property_name + "[]." + key
    for index, item in enumerate(value):
        item, location, error = _candidate_root(
            item, pointer + "/" + str(index), evaluate
        )
        if error:
            failures.append((path, location, error))
            continue
        start = len(failures)
        candidate = _visit_actual(
            item,
            {key: None},
            property_name + "[]",
            location,
            evaluate,
            False,
            warnings,
            failures,
            property_name,
            model_path,
            {},
            {},
        )
        name = candidate.get(key) if isinstance(candidate, dict) else candidate
        if isinstance(candidate, dict) and key in candidate:
            location += "/" + key.replace("~", "~0").replace("/", "~1")
        if isinstance(name, str):
            if name in names:
                error = ValueError("duplicate input key: " + key)
                error.iac_cause = dict(
                    kind="input-invalid",
                    rule="unique-key",
                    key=key,
                    value=name,
                    pointers=[names[name], location],
                )
                failures.append((path, location, error))
            else:
                names[name] = location
        elif (
            isinstance(name, (Expression, ResourceReference)) and len(failures) == start
        ):
            failures.append(
                (path, location, Blocked("input key uniqueness is unproven"))
            )
    return PreparedValue(None, warnings, failures=tuple(failures))


def project_actual(
    value,
    *,
    evaluate,
    property_name,
    model_path,
    desired=None,
    exact=True,
    rules=None,
    rule_path=None,
):
    """Project selected containers; evaluate each intrinsic with the existing evaluator."""
    warnings, failures = [], []
    projected = _visit_actual(
        value,
        desired,
        rule_path or property_name,
        "",
        evaluate,
        exact,
        warnings,
        failures,
        property_name,
        model_path,
        rules or {},
        {},
    )
    return PreparedValue(projected, warnings, failures=tuple(failures))


def _visit_actual(
    value,
    selected,
    path,
    pointer,
    evaluate,
    exact,
    warnings,
    failures,
    property_name,
    model_path,
    rules,
    evaluated,
):
    if pointer in evaluated:
        return evaluated.pop(pointer)
    try:
        if (
            isinstance(value, dict)
            and len(value) == 1
            and "Fn::If" in value
            and isinstance(value["Fn::If"], list)
            and len(value["Fn::If"]) == 3
        ):
            # Resolve only the selector, so a failed child cannot discard its active siblings.
            argument = value["Fn::If"]
            index = 1 if evaluate({"Condition": argument[0]}) else 2
            return _visit_actual(
                argument[index],
                selected,
                path,
                pointer + "/Fn::If/" + str(index),
                evaluate,
                exact,
                warnings,
                failures,
                property_name,
                model_path,
                rules,
                evaluated,
            )
        if (
            isinstance(value, dict)
            and not isinstance(value, ResourceReference)
            and not intrinsic(value)
        ):
            rule = rules.get(path[:-2]) if path.endswith("[]") else None
            if (
                not exact
                and rule
                and rule.selected == "KEYED"
                and isinstance(selected, list)
            ):
                key = rule.key
                value = dict(value)
                if key in value:
                    key_pointer = (
                        pointer + "/" + key.replace("~", "~0").replace("/", "~1")
                    )
                    value[key] = _visit_actual(
                        value[key],
                        None,
                        path + "." + key,
                        key_pointer,
                        evaluate,
                        True,
                        warnings,
                        failures,
                        property_name,
                        model_path,
                        rules,
                        evaluated,
                    )
                    evaluated[key_pointer] = value[key]
                matches = (
                    [
                        candidate
                        for candidate in selected or []
                        if isinstance(candidate, dict)
                        and key in candidate
                        and key in value
                        and isinstance(value[key], Hashable)
                        and isinstance(candidate[key], Hashable)
                        and not unknown_value(value[key])
                        and not unknown_value(candidate[key])
                        and candidate[key] == value[key]
                    ]
                    if isinstance(selected, list)
                    else []
                )
                selected = matches[0] if len(matches) == 1 else {}
                selected = {**selected, key: value.get(key)}
            projected = {}
            for key, child in value.items():
                if not exact and isinstance(selected, dict) and key not in selected:
                    projected[key] = child
                    continue
                item = _visit_actual(
                    child,
                    selected.get(key) if isinstance(selected, dict) else None,
                    path + "." + key,
                    pointer + "/" + key.replace("~", "~0").replace("/", "~1"),
                    evaluate,
                    exact,
                    warnings,
                    failures,
                    property_name,
                    model_path,
                    rules,
                    evaluated,
                )
                if item != {"$noValue": True}:
                    projected[key] = item
            return projected
        if isinstance(value, list):
            projected = []
            rule = rules.get(path)
            mode = (rule.whole if exact else rule.selected) if rule else "ORDERED"
            if (
                not exact
                and rule
                and rule.keyless_unordered
                and isinstance(selected, list)
                and any(
                    isinstance(item, dict) and rule.key not in item for item in selected
                )
            ):
                locations, initial = [], []
                for index, child in enumerate(value):
                    child, location, error = _candidate_root(
                        child, pointer + "/" + str(index), evaluate
                    )
                    candidate_warnings, candidate_failures = [], []
                    item = _visit_actual(
                        child,
                        {},
                        path + "[]",
                        location,
                        partial(_raise_candidate_error, error) if error else evaluate,
                        False,
                        candidate_warnings,
                        candidate_failures,
                        property_name,
                        model_path,
                        rules,
                        evaluated,
                    )
                    if item != {"$noValue": True}:
                        projected.append(item)
                        locations.append(location)
                        initial.append((candidate_warnings, candidate_failures))
                return SelectedCandidates(
                    projected,
                    selected,
                    path,
                    evaluate,
                    property_name,
                    model_path,
                    rules,
                    locations,
                    initial,
                )
            for index, child in enumerate(value):
                selected_child = (
                    selected[len(projected)]
                    if isinstance(selected, list) and len(projected) < len(selected)
                    else None
                )
                if (
                    mode == "KEYED"
                    and not exact
                    and isinstance(selected, list)
                    and all(
                        isinstance(item, dict) and rule.key in item for item in selected
                    )
                ):
                    selected_child = selected
                item = _visit_actual(
                    child,
                    selected_child,
                    path + "[]",
                    pointer + "/" + str(index),
                    evaluate,
                    exact or mode == "UNORDERED",
                    warnings,
                    failures,
                    property_name,
                    model_path,
                    rules,
                    evaluated,
                )
                if item != {"$noValue": True}:
                    projected.append(item)
            return projected
        return evaluate(value)
    except (Blocked, KeyError, ValueError, TypeError, IndexError) as error:
        failures.append((path, pointer, error))
        if isinstance(error, ImportReferenceDeferred):
            return Expression("Unverified", [])
        if isinstance(error, (Blocked, KeyError)):
            project_document(
                value,
                evaluate=partial(_unavailable_actual, value, error),
                unresolved=lambda _: Expression("Unverified", []),
                template=True,
                warnings=warnings,
                property_name=property_name,
                model_path=model_path,
                pointer=pointer,
            )
        return Expression(
            "Unverified", [value] if isinstance(error, (Blocked, KeyError)) else []
        )


def _unavailable_actual(value, failure, child):
    if child is value:
        raise failure
    return Expression("Unverified", [])
