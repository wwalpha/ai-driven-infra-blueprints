"""Design JSON projection using the existing CFn schemas and local evaluator."""

from cloudformation_inputs import Blocked
from iac_values import Expression, ResourceReference
from utils.json_format import AwsDocumentError, policy_json, validate_aws_document


def intrinsic(value):
    return isinstance(value, dict) and any(key == 'Ref' or key.startswith('Fn::') for key in value)


def project_document(document, *, evaluate=None, unresolved=None, warnings=None,
                     property_name=None, model_path=None, logical_id=None, template=False, pointer=''):
    """Keep unproven expressions intact; this never certifies AWS API readiness."""
    from utils.cloudformation_format import intrinsic_shape_error, JSON_INTRINSICS
    from iac_evaluation import Evaluation

    warnings = [] if warnings is None else warnings
    bound = evaluate is not None
    if evaluate is None:
        def pending(*args):
            raise Blocked('no confirmed template binding or physical value; not deployed/unresolved')
        evaluator = Evaluation({'': ({}, {}, {})}, {}, lambda *args: {}, pending, pending, True)
        evaluate = lambda value: evaluator.evaluate('', value)

    def fail(pointer, value, reason):
        raise AwsDocumentError(pointer, value, reason)

    def syntax(value, pointer=''):
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
                syntax(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                syntax(child, pointer + '/' + str(index))

    def visit(value, pointer='', operand=False):
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
                visit(argument, pointer + '/' + name.replace('~', '~0').replace('/', '~1'), True)
                return unresolved(value) if unresolved else value
            except ValueError as error:
                fail(pointer, value, str(error))
        if isinstance(value, dict):
            return {key: visit(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'), operand)
                    for key, child in value.items()}
        if isinstance(value, list):
            return [visit(child, pointer + '/' + str(index), operand) for index, child in enumerate(value)]
        if isinstance(value, str) and not operand and not template:
            if value.lstrip().startswith(('{', '[')):
                try:
                    encoded = policy_json(value)
                except ValueError:
                    pass
                else:
                    import json
                    syntax(encoded, pointer)
                    projected = visit(encoded, pointer)
                    return value if projected == encoded else json.dumps(projected, ensure_ascii=False)
            try:
                validate_aws_document(value)
            except AwsDocumentError as error:
                fail(pointer, value, str(error))
        return evaluate(value) if template else value

    if not template:
        syntax(document, pointer)
    return visit(document, pointer)
