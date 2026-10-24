"""Connect the shared evaluator to tracked comparison lookups."""
from functools import partial

from iac_evaluation import Evaluation
from json_intrinsics import intrinsic, project_document
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference

from .values import PreparedValue


def evaluator(stack_inputs, resources, property_schema, symbol, import_value, local_comparison):
    return Evaluation(stack_inputs, resources, property_schema, symbol, import_value, local_comparison)


def project_actual(value, *, evaluate, property_name, model_path, desired=None, exact=True):
    """Project selected containers; evaluate each intrinsic with the existing evaluator."""
    warnings, failures = [], []
    projected = _visit_actual(value, desired, property_name, '', evaluate, exact, warnings, failures,
                             property_name, model_path)
    return PreparedValue(projected, warnings, failures=tuple(failures))


def _visit_actual(value, selected, path, pointer, evaluate, exact, warnings, failures, property_name, model_path):
    try:
        if (isinstance(value, dict) and len(value) == 1 and 'Fn::If' in value
                and isinstance(value['Fn::If'], list) and len(value['Fn::If']) == 3):
            # Resolve only the selector, so a failed child cannot discard its active siblings.
            argument = value['Fn::If']
            index = 1 if evaluate({'Condition': argument[0]}) else 2
            return _visit_actual(argument[index], selected, path, pointer + '/Fn::If/' + str(index),
                                 evaluate, exact, warnings, failures, property_name, model_path)
        if isinstance(value, dict) and not isinstance(value, ResourceReference) and not intrinsic(value):
            projected = {}
            for key, child in value.items():
                if not exact and isinstance(selected, dict) and key not in selected:
                    projected[key] = child
                    continue
                item = _visit_actual(child, selected.get(key) if isinstance(selected, dict) else None,
                                     path + '.' + key, pointer + '/' + key.replace('~', '~0').replace('/', '~1'),
                                     evaluate, exact, warnings, failures, property_name, model_path)
                if item != {'$noValue': True}:
                    projected[key] = item
            return projected
        if isinstance(value, list):
            projected = []
            for index, child in enumerate(value):
                selected_child = selected[len(projected)] if isinstance(selected, list) and len(projected) < len(selected) else None
                item = _visit_actual(child, selected_child, path + '[]', pointer + '/' + str(index),
                                     evaluate, exact, warnings, failures, property_name, model_path)
                if item != {'$noValue': True}:
                    projected.append(item)
            return projected
        return evaluate(value)
    except (Blocked, KeyError, ValueError, TypeError, IndexError) as error:
        failures.append((path, pointer, error))
        if isinstance(error, (Blocked, KeyError)):
            project_document(value, evaluate=partial(_unavailable_actual, value, error), unresolved=lambda _: Expression('Unverified', []),
                template=True, warnings=warnings, property_name=property_name, model_path=model_path, pointer=pointer)
        return Expression('Unverified', [value] if isinstance(error, (Blocked, KeyError)) else [])


def _unavailable_actual(value, failure, child):
    if child is value:
        raise failure
    return Expression('Unverified', [])
