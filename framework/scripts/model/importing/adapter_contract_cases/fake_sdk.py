"""Offline SDK request and response fixtures."""

import json
from copy import deepcopy
from typing import Any

from botocore.validate import ParamValidator
from model.importing.contract_fixtures import InvalidFixture, service_model
from utils.aws_sdk import aws_runtime


class FakeCalls:
    def __init__(self, ctx: Any, payload: dict[str, Any]) -> None:
        self.ctx = ctx
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.error: Exception | None = None

    def request(self, api: str, operation: str, inputs: dict[str, Any]) -> None:
        if (api, operation) not in self.ctx.allowed or not operation.startswith(
            ("list_", "get_", "describe_", "batch_get_")
        ):
            raise ValueError("Operation is outside the read-only allowlist")
        model = service_model(api)
        name = aws_runtime().operation_name(model, operation)
        if name is None:
            raise ValueError("Unknown SDK operation")
        shape = model.operation_model(name).input_shape
        if shape is None and inputs:
            raise ValueError("Operation accepts no input parameters")
        errors = ParamValidator().validate(inputs, shape) if shape else None
        if errors and errors.has_errors():
            raise InvalidFixture("Invalid fixture request: " + errors.generate_report())
        self.calls.append((api, operation, inputs))

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        return self.call(api, operation, **inputs)

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        raise ValueError("Unexpected adapter request or scope")

    def response(
        self, api: str, operation: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        model = service_model(api)
        name = aws_runtime().operation_name(model, operation)
        shape = model.operation_model(name).output_shape
        if shape is None and payload:
            raise InvalidFixture("Operation has no SDK output shape")
        errors = ParamValidator().validate(payload, shape) if shape else None
        if errors and errors.has_errors():
            raise InvalidFixture(
                "Invalid fixture response: " + errors.generate_report()
            )
        return payload


class DirectCalls(FakeCalls):
    api = ""
    operation = ""
    inputs: dict[str, Any] = {}
    envelope = ""
    typename = ""
    cloud_properties: dict[str, Any] = {}
    identifier = ""
    duplicate = False

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": self.typename, "Identifier": self.identifier},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": self.identifier,
                        "Properties": json.dumps(self.cloud_properties),
                    }
                },
            )
        if (api, operation, inputs) != (self.api, self.operation, self.inputs):
            raise ValueError(
                "SDK request differs from fixture: " + api + "." + operation
            )
        body = (
            deepcopy(self.payload)
            if self.envelope == "$"
            else {self.envelope: deepcopy(self.payload)}
        )
        return self.response(api, operation, body)


class EC2NetworkCalls(DirectCalls):
    expected_inputs: dict[str, Any] | None = None
    collection = ""

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation) != ("ec2", self.operation) or (
            self.expected_inputs is not None and inputs != self.expected_inputs
        ):
            raise ValueError("EC2 selector or scope differs from fixture")
        return self.response(
            api,
            operation,
            {self.collection: [deepcopy(self.payload)] * (2 if self.duplicate else 1)},
        )
