"""Reject unresolved environment literals in a decoded Stack input snapshot."""

import re
from functools import partial

from iac_evaluation import Evaluation
from model.environment_values import inspect, mapping_for

from utils.cloudformation.inputs import Blocked, condition_active, resolve_value


class EnvironmentValuePending(Blocked):
    """A Stack-local input wait; independent peers may still execute."""


def _aws_resolved(*args):
    raise Blocked("CloudFormation resolves this reference")


def _substitute(known, match):
    key = match.group(1)
    return (
        str(known[key])
        if key in known and isinstance(known[key], (str, int, float))
        else match.group(0)
    )


def _known(value, evaluate, parameters, pseudo, conditions):
    if isinstance(value, list):
        return [
            _known(child, evaluate, parameters, pseudo, conditions) for child in value
        ]
    if not isinstance(value, dict):
        return value
    if len(value) == 1 and "Fn::If" in value:
        name, yes, no = value["Fn::If"]
        active = resolve_value(
            {"Condition": name}, parameters, pseudo, conditions=conditions
        )
        return _known(yes if active else no, evaluate, parameters, pseudo, conditions)
    if len(value) == 1 and any(key == "Ref" or key.startswith("Fn::") for key in value):
        try:
            return evaluate(value)
        except Blocked:
            if "Fn::Sub" in value:
                argument = value["Fn::Sub"]
                text, variables = (
                    (argument, {}) if isinstance(argument, str) else argument
                )
                known = (
                    parameters
                    | pseudo
                    | {
                        key: _known(child, evaluate, parameters, pseudo, conditions)
                        for key, child in variables.items()
                    }
                )
                text = re.sub(r"\$\{([^}]+)\}", partial(_substitute, known), text)
                remaining = {
                    key: known[key] for key in variables if "${" + key + "}" in text
                }
                return (
                    {"Fn::Sub": [text, remaining]} if remaining else {"Fn::Sub": text}
                )
        return {
            key: _known(child, evaluate, parameters, pseudo, conditions)
            for key, child in value.items()
        }
    return value


def _pending(value):
    if isinstance(value, str):
        return "PENDING_DEPLOY" in value
    if isinstance(value, dict):
        return any(_pending(child) for child in value.values())
    if isinstance(value, list):
        return any(_pending(child) for child in value)
    return False


def validate_environment_inputs(root, template, parameters, target, stack):
    """Read no Models or source files; use the exact already decoded Template/Parameters."""
    pseudo = {
        "AWS::Region": target["awsRegion"],
        "AWS::AccountId": target.get("awsExecutionAccountId", target["awsAccountId"]),
        "AWS::StackName": stack,
    }
    conditions = template.get("Conditions", {})
    evaluator = Evaluation(
        {stack: (template, parameters, pseudo)},
        {},
        _aws_resolved,
        _aws_resolved,
        _aws_resolved,
        False,
        _aws_resolved,
    )
    evaluate = partial(
        _known,
        evaluate=partial(evaluator.evaluate, stack),
        parameters=parameters,
        pseudo=pseudo,
        conditions=conditions,
    )
    for logical_id, resource in template.get("Resources", {}).items():
        kind = resource.get("Type", "").removeprefix("AWS::").replace("::", ".")
        mapping = mapping_for(root, kind)
        if not any(
            item.environment
            for key, item in mapping.items()
            if key.startswith(kind + ".")
        ):
            continue
        if not condition_active(template, parameters, pseudo, resource):
            continue
        for item in inspect(
            kind, kind, resource.get("Properties", {}), mapping, evaluate=evaluate
        ):
            if _pending(item.value):
                raise EnvironmentValuePending(
                    f"unresolved environment PENDING_DEPLOY: Stack={stack}, Resource={logical_id}, JSON Pointer={item.pointer}"
                )
