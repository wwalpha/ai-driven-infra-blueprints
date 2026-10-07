"""Shared local CloudFormation input decoding and intrinsic evaluation (no AWS calls)."""
import json
import math
import re
from decimal import Decimal, InvalidOperation


class Blocked(RuntimeError):
    pass


def resolve_value(value, parameters, pseudo, exports=None, conditions=None):
    """Resolve the same explicit inputs for imports and artifact destinations."""
    def resolve(value, seen=frozenset()):
        if isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, list):
            return [resolve(part, seen) for part in value]
        if not isinstance(value, dict) or len(value) != 1:
            raise Blocked("cannot resolve ImportValue expression")
        key, argument = next(iter(value.items()))
        if key == "Condition":
            if not isinstance(argument, str) or argument in seen or argument not in (conditions or {}):
                raise Blocked(f"unresolved or cyclic Condition: {argument}")
            result = resolve(conditions[argument], seen | {argument})
            if type(result) is not bool:
                raise Blocked(f"non-boolean Condition: {argument}")
            return result
        if key == "Fn::If" and isinstance(argument, list) and len(argument) == 3:
            active = resolve({"Condition": argument[0]}, seen)
            return resolve(argument[1 if active else 2], seen)
        if key == "Fn::Equals" and isinstance(argument, list) and len(argument) == 2:
            left, right = resolve(argument, seen)
            return any(isinstance(left, kind) and isinstance(right, kind) and left == right
                       for kind in (str, bool, int, float)) and isinstance(left, bool) == isinstance(right, bool)
        if key in {"Fn::And", "Fn::Or", "Fn::Not"} and isinstance(argument, list):
            operands = resolve(argument, seen)
            if (all(type(part) is bool for part in operands) and
                    (len(operands) == 1 if key == "Fn::Not" else 2 <= len(operands) <= 10)):
                return not operands[0] if key == "Fn::Not" else all(operands) if key == "Fn::And" else any(operands)
            raise Blocked(f"invalid condition operands: {key}")
        if key == "Fn::ImportValue" and exports is not None:
            name = resolve(argument, seen)
            if name in exports:
                return exports[name]
            raise Blocked(f"unresolved artifact bucket export: {name}")
        if key == "Ref" and argument in parameters | pseudo:
            return (parameters | pseudo)[argument]
        if key == "Fn::Join" and isinstance(argument, list) and len(argument) == 2:
            delimiter, parts = resolve(argument, seen)
            if isinstance(delimiter, str) and isinstance(parts, list) and all(isinstance(part, str) for part in parts):
                return delimiter.join(parts)
            raise Blocked("invalid Join operands")
        if key == "Fn::Sub":
            text, variables = (argument, {}) if isinstance(argument, str) else argument
            substitutions = parameters | pseudo | {key: resolve(val, seen) for key, val in variables.items()}
            def replace(match):
                key = match.group(1)
                if key.startswith("!"):
                    return "${" + key[1:] + "}"
                if key not in substitutions:
                    raise Blocked(f"unresolved ImportValue variable: {key}")
                return substitutions[key]
            return re.sub(r"\$\{([^}]+)\}", replace, text)
        raise Blocked(f"unsupported ImportValue expression: {key}")
    return resolve(value)


def checked_parameters(document, inputs):
    """Validate and type explicit comparison inputs without retrieving AWS values."""
    definitions = document.get("Parameters", {})
    if not isinstance(definitions, dict):
        raise ValueError("invalid parameter declarations")
    if not all(set(item) == {"ParameterKey", "ParameterValue"} for item in inputs):
        raise ValueError("invalid explicit stack parameters")
    supplied = {item["ParameterKey"]: item["ParameterValue"] for item in inputs}
    if supplied.keys() - definitions.keys():
        raise ValueError("undeclared stack parameter")
    values = {}
    def number(raw, key):
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise ValueError(f"invalid Number parameter: {key}")
        try:
            value = Decimal(str(raw))
        except InvalidOperation as error:
            raise ValueError(f"invalid Number parameter: {key}") from error
        if not value.is_finite():
            raise ValueError(f"invalid Number parameter: {key}")
        result = int(value) if value == value.to_integral_value() else float(value)
        if isinstance(result, float) and not math.isfinite(result):
            raise ValueError(f"invalid Number parameter: {key}")
        return result
    for key, definition in definitions.items():
        if not isinstance(definition, dict) or not isinstance(definition.get("Type"), str):
            raise ValueError(f"invalid parameter declaration: {key}")
        if key not in supplied and "Default" not in definition:
            raise ValueError(f"required parameter missing: {key}")
        raw = supplied.get(key, definition.get("Default"))
        kind = definition["Type"]
        if kind.startswith("AWS::SSM::Parameter::"):
            raise Blocked(f"SSM parameter requires external resolution: {key}")
        is_list = kind == "CommaDelimitedList" or kind.startswith("List<")
        if is_list:
            if not isinstance(raw, str):
                raise ValueError(f"invalid list parameter: {key}")
            items = [item.strip() for item in raw.split(",")]
        else:
            items = [raw]
        if kind == "Number" or kind == "List<Number>":
            items = [number(item, key) for item in items]
        elif kind in {"String", "CommaDelimitedList"} or kind.startswith(("AWS::", "List<AWS::")):
            if any(isinstance(item, bool) or not isinstance(item, (str, int, float)) for item in items):
                raise ValueError(f"invalid String parameter: {key}")
            items = [str(item) for item in items]
        else:
            raise ValueError(f"unsupported parameter type: {key}")
        if "AllowedValues" in definition:
            allowed = definition["AllowedValues"]
            if not isinstance(allowed, list):
                raise ValueError(f"invalid AllowedValues: {key}")
            allowed = [number(item, key) for item in allowed] if kind in {"Number", "List<Number>"} else [str(item) for item in allowed]
            if any(item not in allowed for item in items):
                raise ValueError(f"parameter violates AllowedValues: {key}")
        for item in items:
            if "AllowedPattern" in definition:
                try:
                    valid = isinstance(item, str) and re.fullmatch(definition["AllowedPattern"], item) is not None
                except re.error as error:
                    raise Blocked(f"AllowedPattern cannot be evaluated locally: {key}") from error
                if not valid:
                    raise ValueError(f"parameter violates AllowedPattern: {key}")
            for constraint, measured, minimum in (("MinLength", len(item) if isinstance(item, str) else None, True),
                                                   ("MaxLength", len(item) if isinstance(item, str) else None, False),
                                                   ("MinValue", item if type(item) in (int, float) else None, True),
                                                   ("MaxValue", item if type(item) in (int, float) else None, False)):
                if constraint in definition:
                    limit = number(definition[constraint], key)
                    if measured is None or (measured < limit if minimum else measured > limit):
                        raise ValueError(f"parameter violates {constraint}: {key}")
        values[key] = items if is_list else items[0]
    return values


def load_template_inputs(template, parameter_file, *, strict_parameters=False, document=None):
    try:
        from cfnlint.decode import decode
    except ImportError as error:
        raise Blocked("cfn-lint Python runtime is required for template decoding") from error
    if document is None:
        document, errors = decode(str(template))
        if errors or not isinstance(document, dict) or document.get("Transform"):
            raise Blocked("invalid/transform template; inputs must be resolvable locally")
    if strict_parameters:
        from policy_tables import unique_object, invalid_constant
        inputs = json.loads(parameter_file.read_text(encoding="utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
    else:
        inputs = json.loads(parameter_file.read_text(encoding="utf-8"))
    if not isinstance(inputs, list) or not all(isinstance(item, dict) and isinstance(item.get("ParameterKey"), str)
                                             and isinstance(item.get("ParameterValue"), str) for item in inputs):
        raise (ValueError if strict_parameters else Blocked)("parameter file must contain explicit stack-specific ParameterKey/ParameterValue entries")
    if len({item["ParameterKey"] for item in inputs}) != len(inputs):
        raise (ValueError if strict_parameters else Blocked)("duplicate parameter key")
    if strict_parameters:
        return document, checked_parameters(document, inputs)
    defaults = {key: str(value["Default"]) for key, value in document.get("Parameters", {}).items() if "Default" in value}
    return document, defaults | {item["ParameterKey"]: item["ParameterValue"] for item in inputs}


def condition_active(document, parameters, pseudo, definition):
    return "Condition" not in definition or resolve_value(
        {"Condition": definition["Condition"]}, parameters, pseudo, conditions=document.get("Conditions", {}))


def output_value(document, parameters, pseudo, value):
    # Select conditional branches without resolving resource Ref/GetAtt to physical values.
    while isinstance(value, dict) and "Fn::If" in value:
        argument = value["Fn::If"]
        if len(value) != 1 or not isinstance(argument, list) or len(argument) != 3:
            raise Blocked("invalid Fn::If expression")
        selected = resolve_value({"Condition": argument[0]}, parameters, pseudo, conditions=document.get("Conditions", {}))
        value = argument[1 if selected else 2]
    return value


def load_target(root, environment, directory):
    """Reuse topology validation without invoking credential checks or any AWS operation."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("mapping_context", Path(__file__).with_name("check-deploy-context.py"))
    context = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(context)
    try:
        return context.load_target(root, environment, directory if directory.isdigit() else None,
                                   None if directory.isdigit() else directory)
    except context.DeployContextError as error:
        raise ValueError(str(error)) from error
