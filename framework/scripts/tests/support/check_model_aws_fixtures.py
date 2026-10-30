"""Offline AWS CLI and SDK/mapping regressions. All network access is forbidden.

Synthetic SDK responses and test-created Models are the only regression inputs. Missing boto3 is a failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import copy
import importlib.util
import io
import json
import os
import socket
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from model.files import read_model
from support.model_sources import write_model
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import boto3
from botocore.stub import Stubber
from model.adapters import aws as m
from model.files import model_file_contents
from model.importing.contract_fixtures import (
    ACCOUNT,
    PATCHES,
    TARGET,
    SchemaClient,
    SchemaOffline,
    remove_tokens,
    sdk_response,
    service_model,
    set_path,
    shape_value,
)

COUNT = 0


def check(condition, message):
    global COUNT
    assert condition, message
    COUNT += 1


def expect(error_type, function):
    with pytest.raises(error_type):
        function()
    check(True, "expected rejection")


STACK_MODEL = "desired.stack.001.name=fixture\ndesired.stack.001.template=a.yaml\ndesired.stack.001.parameters=a.json\ndesired.stack.001.deployOrder=1\ndesired.deployment.maxConcurrentStacks=1\n"


class Offline(m.Context):
    def __init__(self, root, fault=None, target=TARGET):
        session = boto3.Session(
            aws_access_key_id="offline",
            aws_secret_access_key="offline",
            region_name=TARGET["awsRegion"],
        )
        super().__init__(root, target, session)
        self.stubbers, self.fault = {}, fault
        self.request_count = 0

    def client(self, service):
        client = super().client(service)
        if service not in self.stubbers:
            self.stubbers[service] = Stubber(client)
            self.stubbers[service].activate()
        return client

    def queue(self, service, operation, inputs):
        client = self.client(service)
        stub = self.stubbers[service]
        fault = (
            self.fault.get((service, operation))
            if isinstance(self.fault, dict)
            else self.fault
        )
        if fault:
            stub.add_client_error(
                operation,
                service_error_code="ResourceNotFoundException"
                if fault == "missing"
                else "AccessDeniedException",
                expected_params=inputs,
            )
        else:
            response = sdk_response(
                client.meta.service_model, service, operation, self.egress
            )
            stub.add_response(operation, response, expected_params=inputs)
        self.request_count += 1

    def call(self, service, operation, *, _deadline=None, **inputs):
        if (service, operation) not in self.allowed or (
            not self.verified and service != "sts"
        ):
            return super().call(service, operation, _deadline=_deadline, **inputs)
        key = (service, operation, m.stable(inputs))
        if key not in self.cache:
            self.queue(service, operation, inputs)
        return super().call(service, operation, _deadline=_deadline, **inputs)

    def pages(self, service, operation, **inputs):
        client = self.client(service)
        key = (service, operation, "pages", m.stable(inputs))
        if (
            key not in self.cache
            and client.can_paginate(operation)
            and not (service == "cloudformation" and operation in m.READ_RATES)
        ):
            self.queue(service, operation, inputs)
        return super().pages(service, operation, **inputs)

    def finish(self):
        for stub in self.stubbers.values():
            stub.assert_no_pending_responses()


class FakeResource:
    def __init__(self, ctx, service, kind, prop=None, desired="fixture"):
        self.ctx, self.kind, self.number = ctx, kind, "001"
        self.module = m.service_module(service)
        self.spec = {"resourceType": kind, "logicalId": "fixture", "anchor": "fixture"}
        self.rows = (
            [
                (
                    "001-001",
                    {"property": prop, "value": "`fixture`", "comment": "fixture"},
                )
            ]
            if prop
            else []
        )
        self.desired = desired
        self.model = SimpleNamespace(
            path=ctx.root
            / "model"
            / ctx.target["environment"]
            / ctx.target["directory"]
            / (service + ".properties"),
            service=service,
            resources=[self],
            values={},
            locations={
                "desired.row.001-001.value": {
                    "file": "/offline/fixture.properties",
                    "line": 1,
                }
            },
        )
        self.egress = kind.endswith("Egress")
        ctx.egress = self.egress

    def value(self, prop, norm="typed"):
        return {
            "AwsAccountId": ACCOUNT,
            "CatalogId": ACCOUNT,
            "Type": "A",
            "Action": "lambda:InvokeFunction",
            "Principal": "s3.amazonaws.com",
            "SourceAccount": ACCOUNT,
        }.get(prop, "fixture")

    def current(self, prop):
        return "fixture"

    def rows_for(self, prop):
        if prop == "Queues[]":
            return [
                ("001-001", {"property": self.kind + ".Queues[]", "value": "fixture"})
            ]
        return []

    def optional(self, prop, default=None, norm="typed"):
        if self.kind == "Route53.RecordSet" and prop == "SetIdentifier":
            return "fixture"
        return default

    def parent(self):
        return self

    def identity(self, mode="id"):
        return "fixture"

    def parse(self, row, norm="typed"):
        return "fixture" if row["property"].endswith("Queues[]") else self.desired


REPRESENTATIVES = {
    "athena": ("Athena.WorkGroup", "Description", "fixture"),
    "cloudtrail": ("CloudTrail.Trail", "TrailName", "fixture"),
    "cloudwatch-logs": ("Logs.LogGroup", "LogGroupName", "fixture"),
    "codebuild": ("CodeBuild.Project", "Name", "fixture"),
    "codecommit": ("CodeCommit.Repository", "RepositoryName", "fixture"),
    "codepipeline": ("CodePipeline.Pipeline", "Name", "fixture"),
    "config": ("Config.ConfigurationRecorder", "Name", "fixture"),
    "data-firehose": (
        "KinesisFirehose.DeliveryStream",
        "DeliveryStreamName",
        "fixture",
    ),
    "datazone": ("DataZone.Project", "DomainIdentifier", "fixture"),
    "ec2": ("EC2.Instance", "InstanceType", "a1.medium"),
    "eventbridge": ("Events.Rule", "Name", "fixture"),
    "glue": ("Glue.Job", "Name", "fixture"),
    "guardduty": (
        "GuardDuty.Detector",
        "FindingPublishingFrequency",
        "FIFTEEN_MINUTES",
    ),
    "iam": ("IAM.Role", "RoleName", "fixture"),
    "kms": ("KMS.Key", "Description", "fixture"),
    "lake-formation": ("LakeFormation.Resource", "HybridAccessEnabled", True),
    "lambda": ("Lambda.Function", "FunctionName", "fixture"),
    "macie": ("Macie.ClassificationJob", "name", "fixture"),
    "mwaa": ("MWAA.Environment", "Name", "fixture"),
    "quicksight": ("QuickSight.DataSource", "Name", "fixture"),
    "route53": ("Route53.HostedZone", "Name", "fixture"),
    "s3": ("S3.Bucket", "BucketName", "fixture"),
    "secrets-manager": ("SecretsManager.Secret", "Name", "fixture"),
    "security-hub": ("SecurityHub.Hub", "AutoEnableControls", True),
    "security-group": ("EC2.SecurityGroup", "GroupDescription", "fixture"),
    "sqs": ("SQS.Queue", "MessageRetentionPeriod", 604800),
    "transit-gateway": (
        "EC2.TransitGatewayVpcAttachment",
        "TransitGatewayId",
        "fixture",
    ),
    "vpc": ("EC2.VPC", "CidrBlock", "fixture"),
    "vpc-endpoint": ("EC2.VPCEndpoint", "ServiceName", "fixture"),
}


def acquired(value):
    # Optional array members may be absent; [MISSING] is still not an acquired value.
    return (
        any(acquired(item) for item in value)
        if isinstance(value, list)
        else value != m.MISSING
    )


def model_text(
    kind,
    rows,
    number="001",
    logical="fixture",
    anchor="fixture",
    metadata="",
    allocation=True,
):
    text = (
        f"desired.resource.{number}.resourceType={kind}\ndesired.resource.{number}.anchor={anchor}\ndesired.resource.{number}.logicalId={kind.replace('.', '_')}_{int(number):03d}\n"
        + metadata
    )
    if allocation:
        text += (
            "desired.service.identity.lastAllocated="
            + json.dumps({kind: int(number)})
            + "\n"
        )
    for index, (prop, value) in enumerate(rows, 1):
        text += f"desired.row.{number}-{index:03d}.property={prop}\ndesired.row.{number}-{index:03d}.value={value}\ndesired.row.{number}-{index:03d}.comment=fixture\n"
    return text


@pytest.fixture(autouse=True)
def offline_network():
    with patch.object(
        socket.socket,
        "connect",
        side_effect=AssertionError("network is forbidden in offline checks"),
    ):
        yield


__all__ = [
    "SchemaOffline",
    "SchemaClient",
    "service_model",
    "sdk_response",
    "ACCOUNT",
    "COUNT",
    "ExitStack",
    "FakeResource",
    "Offline",
    "PATCHES",
    "Path",
    "REPRESENTATIVES",
    "STACK_MODEL",
    "SimpleNamespace",
    "Stubber",
    "TARGET",
    "acquired",
    "boto3",
    "check",
    "copy",
    "expect",
    "importlib",
    "io",
    "json",
    "m",
    "model_file_contents",
    "model_text",
    "offline_network",
    "os",
    "patch",
    "pytest",
    "read_model",
    "redirect_stderr",
    "redirect_stdout",
    "remove_tokens",
    "run",
    "set_path",
    "shape_value",
    "socket",
    "sys",
    "write_model",
]


def _batch_checks_cli(arguments):
    stdout, stderr = (io.StringIO(), io.StringIO())
    with (
        patch.object(sys, "argv", ["check-model-aws.py", *arguments]),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        try:
            code = m.main()
        except SystemExit as error:
            code = error.code
    return (
        code,
        json.loads(stdout.getvalue()) if stdout.getvalue() else None,
        stderr.getvalue(),
    )
