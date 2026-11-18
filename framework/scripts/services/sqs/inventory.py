"""sqs IMPORT acquisition."""

import re
from typing import Any
from urllib.parse import urlparse

from contracts.target import AWS_REGION_KEY
from model.importing.sdk_inventory import account_for, identifier, record
from utils.aws_sdk import aws_runtime
from utils.json_format import policy_json


def queue_policies(ctx: Any, parents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    account = account_for(ctx)
    records = []
    region = ctx.target[AWS_REGION_KEY]
    resolver = aws_runtime().sdk_session().get_component("endpoint_resolver")
    endpoint = resolver.construct_endpoint("sqs", region)
    if (
        not endpoint
        or endpoint.get("endpointName") != region
        or region not in resolver.get_available_endpoints("sqs", endpoint["partition"])
    ):
        raise ValueError("SQS endpoint is unknown for target region")
    partition = endpoint["partition"]
    hosts = {endpoint["hostname"]}
    dual = resolver.construct_endpoint(
        "sqs", region, partition_name=partition, use_dualstack_endpoint=True
    )
    if dual:
        hosts.add(dual["hostname"])
    # Only concrete regional FIPS variants establish SQS support; defaults are templates.
    if partition == "aws" and any(
        variant.get("tags") == ["fips"] and "{" not in variant.get("hostname", "")
        for variant in endpoint.get("variants", [])
    ):
        for dualstack in (False, True):
            resolved = resolver.construct_endpoint(
                "sqs",
                region,
                partition_name=partition,
                use_fips_endpoint=True,
                use_dualstack_endpoint=dualstack,
            )
            if resolved:
                hosts.add(resolved["hostname"])
    # AWS documents HTTPS legacy endpoints only for these Regions.
    legacy_regions = {
        "us-east-1",
        "us-east-2",
        "us-west-1",
        "us-west-2",
        "ap-south-1",
        "ap-northeast-1",
        "ap-northeast-2",
        "ap-northeast-3",
        "ap-southeast-1",
        "ap-southeast-2",
        "ca-central-1",
        "eu-central-1",
        "eu-west-1",
        "eu-west-2",
        "eu-west-3",
        "eu-north-1",
        "sa-east-1",
    }
    if partition == "aws" and region in legacy_regions:
        hosts.add(endpoint.get("sslCommonName"))
    if partition == "aws-cn" and region in {"cn-north-1", "cn-northwest-1"}:
        hosts.add(f"{region}.queue.amazonaws.com")
    hosts = {
        host
        for host in hosts
        if isinstance(host, str) and "{" not in host and "}" not in host
    }
    for parent in parents:
        if parent.get("kind") != "SQS.Queue":
            raise ValueError("QueuePolicy requires acquired Queue parents")
        url = parent.get("cloudProperties", {}).get("QueueUrl")
        url = identifier(url)
        parsed = urlparse(url)
        if (
            parsed.geturl() != url
            or parsed.scheme != "https"
            or parsed.netloc not in hosts
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(
                r"/" + account + r"/[A-Za-z0-9_-]{1,80}(?:\.fifo)?", parsed.path
            )
            or len(parsed.path.rsplit("/", 1)[-1]) > 80
        ):
            raise ValueError("SQS queue is outside target scope")
        response = ctx.call(
            "sqs", "get_queue_attributes", QueueUrl=url, AttributeNames=["Policy"]
        )
        # A successful Policy-only read may omit the optional Attributes map.
        attributes = response.get("Attributes", {})
        if not isinstance(attributes, dict):
            raise ValueError("Invalid SQS attributes")
        if "Policy" not in attributes:
            continue
        policy = policy_json(attributes["Policy"])
        if not isinstance(policy, dict):
            raise ValueError("Invalid SQS queue policy")
        value = record(
            "SQS.QueuePolicy",
            {"Queues[]": [url]},
            {"policy": {"Queues": [url], "Policy": policy}},
            selectors={"Queues[]": [url]},
        )
        value["structureStatus"] = "unresolved"
        value["structureReason"] = (
            "AWS does not retain the original QueuePolicy queue grouping; explicitly confirm a single-queue structure or exclude this candidate"
        )
        records.append(value)
    return records
