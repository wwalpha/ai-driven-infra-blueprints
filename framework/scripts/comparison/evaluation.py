"""Connect the shared evaluator to tracked comparison lookups."""
from cloudformation_inputs import Blocked
from iac_evaluation import Evaluation
from iac_values import Expression
from json_intrinsics import project_document

from .values import PreparedValue


def evaluator(stack_inputs, resources, property_schema, symbol, import_value, local_comparison):
    return Evaluation(stack_inputs, resources, property_schema, symbol, import_value, local_comparison)


def project_actual(value, *, evaluate, property_name, model_path):
    warnings = []
    try:
        result = project_document(value, evaluate=evaluate,
            unresolved=lambda value: Expression('Unverified', [value]), template=True,
            warnings=warnings, property_name=property_name, model_path=model_path)
    except (Blocked, KeyError, ValueError, TypeError, IndexError) as error:
        return PreparedValue(None, warnings, error)
    return PreparedValue(result, warnings)
