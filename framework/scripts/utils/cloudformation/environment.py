"""Reject unresolved environment inputs in a decoded Stack snapshot."""

from functools import partial

from iac_evaluation import Evaluation
from model.environment_values import inspect, mapping_for, state

from utils.cloudformation.inputs import Blocked, condition_active
from utils.iac_values import Expression, unknown_value


class EnvironmentValuePending(Blocked):
    """A Stack-local input wait; independent peers may still execute."""


class _EnvironmentEvaluation(Evaluation):
    def evaluate(self, stack, value, seen=frozenset()):
        if isinstance(value, str) and state(value).status == "unresolved":
            return Expression("Unverified", [])
        parameters = self.stack_inputs[stack][1]
        if isinstance(value, dict) and set(value) == {"Ref"}:
            key = value["Ref"]
            if key in parameters:
                return self.evaluate(stack, parameters[key], seen)
        return super().evaluate(stack, value, seen)

    def string_operand(self, value):
        return unknown_value(value) or super().string_operand(value)


def _aws_resolved(*args):
    raise Blocked("CloudFormation resolves this reference")


def _aws_reference(template, stack, logical_id, attribute=None):
    if logical_id not in template.get("Resources", {}):
        raise Blocked(f"undefined CloudFormation resource: {logical_id}")
    # Opaque tokens retain valid AWS references while encoded environment strings are decoded.
    return "${" + logical_id + ("." + attribute if attribute else "") + "}"


def _aws_import(evaluator, stack, value, seen):
    name = evaluator.evaluate(stack, value, seen)
    return "${Fn::ImportValue}" if isinstance(name, str) else name


def _environment_input(evaluator, stack, value):
    if isinstance(value, dict) and any(
        key == "Ref" or key.startswith("Fn::") for key in value
    ):
        return evaluator.evaluate(stack, value)
    return value


def validate_environment_inputs(root, template, parameters, target, stack):
    """Read no Models or source files; use the exact already decoded Template/Parameters."""
    pseudo = {
        "AWS::Region": target["awsRegion"],
        "AWS::AccountId": target.get("awsExecutionAccountId", target["awsAccountId"]),
        "AWS::StackName": stack,
        "AWS::Partition": "${AWS::Partition}",
        "AWS::URLSuffix": "${AWS::URLSuffix}",
        "AWS::StackId": "${AWS::StackId}",
        "AWS::NoValue": {"$noValue": True},
    }
    evaluator = _EnvironmentEvaluation(
        {stack: (template, parameters, pseudo)},
        {},
        _aws_resolved,
        partial(_aws_reference, template),
        _aws_resolved,
        True,
        _aws_resolved,
    )
    evaluator.import_value = partial(_aws_import, evaluator)
    evaluate = partial(_environment_input, evaluator, stack)
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
            if item.status != "resolved" and item.value != {"$noValue": True}:
                raise EnvironmentValuePending(
                    f"unresolved environment PENDING_DEPLOY: Stack={stack}, Resource={logical_id}, JSON Pointer={item.pointer}"
                )
