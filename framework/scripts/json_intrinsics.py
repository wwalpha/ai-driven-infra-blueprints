"""Design JSON projection using the existing CFn schemas and local evaluator."""

import json as _imports_json
from functools import partial as _bind_framework_callback

import iac_evaluation as _imports_iac_evaluation
from iac_values import Expression
from utils.cloudformation.format import JSON_INTRINSICS, intrinsic_shape_error
from utils.cloudformation.inputs import Blocked
from utils.json_format import AwsDocumentError, policy_json, validate_aws_document


def intrinsic(value):
    return isinstance(value, dict) and any(key == 'Ref' or key.startswith('Fn::') for key in value)






def _project_document_fail(pointer, value, reason):
    raise AwsDocumentError(pointer, value, reason)


def _project_document_pending(*args):
    raise Blocked('no confirmed template binding or physical value; not deployed/unresolved')


def _recursive_project_document_syntax(fail, /, value, pointer=''):
    if isinstance(value, dict):
        if intrinsic(value):
            for name, argument in value.items():
                if name != 'Ref' and not name.startswith('Fn::'):
                    continue
                if name in JSON_INTRINSICS and len(value) != 1:
                    fail(pointer, value, 'intrinsic must contain exactly one function')
                error = intrinsic_shape_error(name, argument)
                if error:
                    fail(pointer, value, f'invalid {name} structure: {error}')
        for key, child in value.items():
            _recursive_project_document_syntax(fail, child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _recursive_project_document_syntax(fail, child, pointer + '/' + str(index))


def _recursive_project_document_visit(bound, evaluate, fail, logical_id, model_path, property_name, syntax, template, unresolved, warnings, /, value, pointer='', operand=False):
    if intrinsic(value):
        name, argument = next((key, child) for key, child in value.items() if key == 'Ref' or key.startswith('Fn::'))
        try:
            if len(value) != 1:
                raise Blocked('unsupported function/object syntax; unverified')
            result = evaluate(value)
            if (not bound and isinstance(result, Expression)) or result == {'$noValue': True}:
                raise Blocked('local evaluation remains symbolic; resolved AWS value is unproven')
            return result
        except (Blocked, KeyError, TypeError) as error:
            warning = dict(code='json.intrinsic.unresolved', severity='WARNING', function=name,
                           pointer=pointer, property=property_name, model=str(model_path), resource=logical_id,
                           message=f'{name}: JSON Pointer={pointer!r}, Property={property_name}; '
                                   f'unresolved/unverified: {error}')
            if warning not in warnings:
                warnings.append(warning)
            _recursive_project_document_visit(bound, evaluate, fail, logical_id, model_path, property_name, syntax, template, unresolved, warnings, argument, pointer + '/' + name.replace('~', '~0').replace('/', '~1'), True)
            return unresolved(value) if unresolved else value
        except ValueError as error:
            fail(pointer, value, str(error))
    if isinstance(value, dict):
        return {key: _recursive_project_document_visit(bound, evaluate, fail, logical_id, model_path, property_name, syntax, template, unresolved, warnings, child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'), operand)
                for key, child in value.items()}
    if isinstance(value, list):
        return [_recursive_project_document_visit(bound, evaluate, fail, logical_id, model_path, property_name, syntax, template, unresolved, warnings, child, pointer + '/' + str(index), operand) for index, child in enumerate(value)]
    if isinstance(value, str) and not operand and not template:
        if value.lstrip().startswith(('{', '[')):
            try:
                encoded = policy_json(value)
            except ValueError:
                pass
            else:
                json = _imports_json
                syntax(encoded, pointer)
                projected = _recursive_project_document_visit(bound, evaluate, fail, logical_id, model_path, property_name, syntax, template, unresolved, warnings, encoded, pointer)
                return value if projected == encoded else json.dumps(projected, ensure_ascii=False)
        try:
            validate_aws_document(value)
        except AwsDocumentError as error:
            fail(pointer, value, str(error))
    return evaluate(value) if template else value


def _lambda_project_document_evaluate_101(evaluator, /, value):
    return evaluator.evaluate('', value)


def project_document(document, *, evaluate=None, unresolved=None, warnings=None,
                     property_name=None, model_path=None, logical_id=None, template=False, pointer=''):
    """Keep unproven expressions intact; this never certifies AWS API readiness."""
    Evaluation = _imports_iac_evaluation.Evaluation

    warnings = [] if warnings is None else warnings
    bound = evaluate is not None
    if evaluate is None:
        pending = _project_document_pending
        evaluator = Evaluation({'': ({}, {}, {})}, {}, lambda *args: {}, pending, pending, True)
        evaluate = _bind_framework_callback(_lambda_project_document_evaluate_101, evaluator)

    fail = _project_document_fail

    syntax = _bind_framework_callback(_recursive_project_document_syntax, fail)

    visit = _bind_framework_callback(_recursive_project_document_visit, bound, evaluate, fail, logical_id, model_path, property_name, syntax, template, unresolved, warnings)

    if not template:
        syntax(document, pointer)
    return visit(document, pointer)
