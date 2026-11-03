"""Static, schema-checked SDK responses; execution remains in domain test functions."""

from pathlib import Path
from unittest import TestCase

import boto3
import pytest
from botocore.config import Config
from botocore.stub import Stubber
from botocore.validate import validate_parameters
from support.fixture_cases import _identifier


class SdkCase:
    def __init__(self, data, tmp_path, monkeypatch):
        monkeypatch.setattr("socket.socket.connect", network_forbidden)
        empty = Path(tmp_path) / "empty-aws-config"
        empty.write_text("", encoding="utf-8")
        for name in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
            monkeypatch.setenv(name, str(empty))
        for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
        self.context = tuple(data["context"])
        self.clients, self.stubbers, self.services = {}, {}, {}
        for name, definition in data["clients"].items():
            if not _identifier(name) or definition.keys() != {"service", "region"}:
                raise ValueError("invalid SDK client definition")
            service, region = definition["service"], definition["region"]
            # shortcut: one client per service, add context selection for a multi-region case.
            if service in self.services:
                raise ValueError("ambiguous SDK client service")
            session = boto3.Session(
                aws_access_key_id="synthetic",
                aws_secret_access_key="synthetic",
                region_name=region,
            )
            TestCase().assertEqual(session.get_credentials().access_key, "synthetic")
            client = session.client(
                service, config=Config(retries={"total_max_attempts": 1})
            )
            self.clients[name], self.stubbers[name] = client, Stubber(client)
            self.services[service] = name
        if not self.clients:
            raise ValueError("SDK clients must not be empty")
        for step in data["steps"]:
            if step.keys() not in (
                {"client", "operation", "params", "response"},
                {"client", "operation", "params", "error"},
            ):
                raise ValueError("SDK step requires exactly one response or error")
            if step["client"] not in self.clients:
                raise ValueError("unknown SDK client")
            client = self.clients[step["client"]]
            operation = client.meta.method_to_api_mapping.get(step["operation"])
            if operation is None:
                raise ValueError("unknown SDK operation")
            shape = client.meta.service_model.operation_model(operation).input_shape
            if shape is not None:
                validate_parameters(step["params"], shape)
            elif step["params"]:
                raise ValueError("SDK operation accepts no parameters")
            stubber = self.stubbers[step["client"]]
            if "response" in step:
                stubber.add_response(
                    step["operation"], step["response"], step["params"]
                )
            else:
                error = step["error"]
                if (
                    error.keys() != {"code", "message", "http_status"}
                    or type(error["code"]) is not str
                    or type(error["message"]) is not str
                    or type(error["http_status"]) is not int
                ):
                    raise ValueError("invalid SDK error definition")
                stubber.add_client_error(
                    step["operation"],
                    service_error_code=error["code"],
                    service_message=error["message"],
                    http_status_code=error["http_status"],
                    expected_params=step["params"],
                )

    def __enter__(self):
        for stubber in self.stubbers.values():
            stubber.activate()
        return self

    def __exit__(self, error_type, error, traceback):
        try:
            if error_type is None:
                self.finish()
        finally:
            for stubber in self.stubbers.values():
                stubber.deactivate()

    def client(self, context, service, **options):
        if tuple(context) != self.context:
            raise ValueError("SDK context differs from the declared request")
        if service not in self.services:
            raise ValueError("undeclared SDK client")
        client = self.clients[self.services[service]]
        if len(context) > 1 and context[1] != client.meta.region_name:
            raise ValueError("SDK client region differs from request context")
        return client

    def finish(self):
        for stubber in self.stubbers.values():
            stubber.assert_no_pending_responses()


def network_forbidden(*args, **kwargs):
    pytest.fail("SDK case attempted network access", pytrace=False)
