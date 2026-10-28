#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event

import aws_mapping_catalog
import aws_mapping_catalog as _imports_aws_mapping_catalog
import pytest
import utils.aws_mappings as providers
import utils.mapping_runtime as _mapping_runtime
import utils.mapping_types as _mapping_types
from support.aws_mapping_fixtures import (
    BASELINE,
    CHANNEL,
    RECORDER,
    ROOT,
    FrozenInstanceError,
    Path,
    TemporaryDirectory,
    astuple,
    aws_mapping,
    display_rows,
    hashlib,
    input_scope,
    json,
    m,
    module,
    patch,
    sys,
)
from support.pytest_cli import run
from utils.aws_catalogs import Catalogs
from utils.aws_mappings import Mappings, mapping_alias, mappings_for, owners
from utils.aws_schemas import Schemas
from utils.aws_sdk import Sdk
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.input_cache import memo_table

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_payload_selection():
    mapping = aws_mapping.registry(ROOT, "config")
    original_fields = mapping.fields
    role = "arn:aws:iam::123456789012:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig"
    recorder = {
        "name": "recorder-fixture",
        "roleARN": role,
        "recordingGroup": {
            "allSupported": False,
            "includeGlobalResourceTypes": True,
            "resourceTypes": ["AWS::S3::Bucket", "AWS::EC2::VPC"],
            "exclusionByResourceTypes": {"resourceTypes": []},
            "recordingStrategy": {"useOnly": "ALL_SUPPORTED_RESOURCE_TYPES"},
        },
        "recordingMode": {
            "recordingFrequency": "CONTINUOUS",
            "recordingModeOverrides": [
                {
                    "description": "first",
                    "recordingFrequency": "DAILY",
                    "resourceTypes": ["AWS::EC2::VPC"],
                },
                {
                    "description": "second",
                    "recordingFrequency": "CONTINUOUS",
                    "resourceTypes": ["AWS::S3::Bucket"],
                },
            ],
        },
    }
    channel = {
        "name": "channel-fixture",
        "s3BucketName": "fixture-bucket",
        "s3KeyPrefix": "config/",
        "configSnapshotDeliveryProperties": {"deliveryFrequency": "TwentyFour_Hours"},
        "s3KmsKeyArn": "arn:aws:kms:ap-northeast-1:123456789012:key/fixture",
        "snsTopicARN": "arn:aws:sns:ap-northeast-1:123456789012:fixture",
    }

    # Read every catalog leaf, including excluded fields; preserve SDK types/array grouping.
    payloads = {"recorder": recorder, "channel": channel}
    extracted = {
        key: m.select(payloads[prop.field.getter], prop.field.path)
        for key, prop in mapping.properties.items()
    }
    assert extracted[CHANNEL + ".S3KeyPrefix"] == "config/"
    assert (
        extracted[CHANNEL + ".ConfigSnapshotDeliveryProperties.DeliveryFrequency"]
        == "TwentyFour_Hours"
    )
    assert extracted[RECORDER + ".RecordingGroup.AllSupported"] is False
    assert extracted[
        RECORDER + ".RecordingMode.RecordingModeOverrides[].ResourceTypes"
    ] == [["AWS::EC2::VPC"], ["AWS::S3::Bucket"]]
    assert (
        m.select({}, mapping.properties[CHANNEL + ".S3KeyPrefix"].field.path)
        == m.MISSING
    )
    assert m.select({"s3KeyPrefix": None}, "s3KeyPrefix") is None
    assert m.select({"s3KeyPrefix": ""}, "s3KeyPrefix") == ""
    shown = [
        prop.name
        for key, prop in mapping.properties.items()
        if key.startswith(CHANNEL + ".") and prop.show
    ]
    assert shown == ["Name", "S3BucketName"]
    assert mapping.properties[RECORDER + ".RoleARN"].name == "RoleName"
    assert all(
        not prop.show and not prop.include
        for key, prop in mapping.properties.items()
        if key not in original_fields
    )


@input_scope
def check_v3_registry():
    types, supported, identities, getters, apis = set(), set(), 0, 0, []
    properties, definitions, metadata = {}, {}, {}
    paths = sorted((ROOT / "framework/mappings/aws").glob("*.yaml"))
    assert len(paths) == 50
    for path in paths:
        document = aws_mapping.yaml_read(path.read_text(encoding="utf-8"))
        assert type(document["version"]) is int and document["version"] == 3
        mapping = aws_mapping.registry(ROOT, path.stem)
        runtime = aws_mapping.runtime_registry(ROOT, path.stem)
        runtime_properties = _imports_aws_mapping_catalog.runtime_properties
        assert (
            runtime.properties
            == aws_mapping.Registry(
                ROOT, path.stem, document, runtime_properties(ROOT, path.stem, document)
            ).properties
        )
        assert dict(runtime.getters) == dict(mapping.getters)
        assert runtime.identities == mapping.identities
        assert mapping.resource_types == document["resourceTypes"].keys()
        assert not types & mapping.resource_types
        types.update(mapping.resource_types)
        properties[path.stem] = {
            r: v["properties"] for r, v in document["resourceTypes"].items()
        }
        definitions[path.stem] = document["getters"]
        adapter_getters = {
            name: tuple(value["resources"])
            for name, value in mapping.getters.items()
            if value["kind"] == "adapter"
        }
        assert mapping.adapter_resource_types == {
            r for resources in adapter_getters.values() for r in resources
        }
        if path.stem not in m.SERVICES:
            assert not mapping.adapter_resource_types and not mapping.identities
            continue
        adapter = m.service_module(path.stem)
        assert all(
            not hasattr(adapter, name)
            for name in ("RESOURCE_TYPES", "IDENTITIES", "GETTERS")
        )
        metadata[path.stem] = {
            "RESOURCE_TYPES": sorted(mapping.adapter_resource_types),
            "IDENTITIES": {
                r: astuple(value) for r, value in mapping.identities.items()
            },
            "GETTERS": adapter_getters,
            "APIS": sorted(adapter.APIS),
        }
        supported.update(mapping.adapter_resource_types)
        identities += len(mapping.identities)
        getters += len(adapter_getters)
        apis.extend(adapter.APIS)
    assert (
        len(types),
        len(supported),
        identities,
        getters,
        len(apis),
        len(set(apis)),
    ) == (178, 52, 50, 63, 79, 78)
    stack = m.service_module("cloudformation-stacks")
    assert stack.STACK_TYPE == "CloudFormation.Stack"
    assert all(
        not hasattr(stack, name) for name in ("RESOURCE_TYPES", "IDENTITIES", "GETTERS")
    )
    metadata["cloudformation-stacks"] = {
        "RESOURCE_TYPES": ("CloudFormation.Stack",),
        "IDENTITIES": {},
        "APIS": sorted(stack.APIS),
    }
    tgw_properties = {
        "EC2.TransitGateway": {
            "Id",
            "AmazonSideAsn",
            "Description",
            "DnsSupport",
            "DefaultRouteTableAssociation",
            "DefaultRouteTablePropagation",
            "AutoAcceptSharedAttachments",
            "VpnEcmpSupport",
        },
        "EC2.TransitGatewayRouteTable": {
            "TransitGatewayRouteTableId",
            "TransitGatewayId",
        },
        "EC2.TransitGatewayRoute": {
            "TransitGatewayRouteTableId",
            "DestinationCidrBlock",
            "TransitGatewayAttachmentId",
            "Blackhole",
        },
        "EC2.TransitGatewayRouteTableAssociation": {
            "TransitGatewayRouteTableId",
            "TransitGatewayAttachmentId",
        },
        "EC2.TransitGatewayRouteTablePropagation": {
            "TransitGatewayRouteTableId",
            "TransitGatewayAttachmentId",
        },
    }
    assert sum(map(len, tgw_properties.values())) == 18
    baseline_properties = deepcopy(properties)
    for kind, selected in tgw_properties.items():
        actual = properties["ec2"][kind]
        assert {
            name for name, prop in actual.items() if prop["model"]["include"]
        } == selected, kind
        assert {
            name for name, prop in actual.items() if prop["display"]["show"]
        } == selected, kind
        for name in selected:
            assert actual[name]["model"]["include"] is True, (kind, name)
            assert actual[name]["display"]["show"] is True, (kind, name)
            # Restore only the two authorized flags in a test-local copy for the original hash.
            baseline_properties["ec2"][kind][name]["model"]["include"] = False
            baseline_properties["ec2"][kind][name]["display"]["show"] = False
    replication = {
        name: prop
        for name, prop in properties["s3"]["S3.Bucket"].items()
        if name.startswith("ReplicationConfiguration.")
    }
    assert len(replication) == 21
    for name, prop in replication.items():
        assert prop["model"]["include"] is True and prop["display"]["show"] is True
        baseline = baseline_properties["s3"]["S3.Bucket"][name]
        baseline["model"]["include"] = baseline["display"]["show"] = False
    # Environment mappings add CodePipeline SDK fields and expose ECS/Lambda values.
    for values, expected in [
        (
            baseline_properties,
            "756741f1aee199834603331d1ba4a9611fc8660e6da724b4d6a16db05b04c03e",
        ),
        (
            definitions,
            "b611a2bf2ce4b384c2e80b6c63f51646e0f5439789bdeb308878250df095e0c4",
        ),
        (metadata, "6ddf2190bf6c29c9615b5fad44deb27f8b33007f9fd8b4596be89630da10869b"),
    ]:
        assert (
            hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
            == expected
        )
    print(
        "YAML v3/environment baseline: PASS (50 files, 178 types, 52 adapter types, 50 identities, 63 adapter getters; 18 TGW include/show changes explicit; properties/getters/metadata/API sets pinned)"
    )


def _callback_check_registry_cache_cached(root, /):
    first = aws_mapping.registry(root, "config")
    assert aws_mapping.registry(root, "config") is first
    assert first.identities[RECORDER] == aws_mapping.Identity(
        "recorder", "name", None, "Name"
    )
    for mutate in (
        lambda: setattr(first.identities[RECORDER], "id_path", "other"),
        lambda: first.identities.__setitem__(RECORDER, None),
        lambda: first.getters["recorder"].__setitem__("resources", ()),
        lambda: setattr(first, "service", "other"),
    ):
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            mutate()
    assert isinstance(first.getters["recorder"]["resources"], tuple)
    return first


def check_registry_cache():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        cached = (input_scope)(
            _bind_framework_callback(_callback_check_registry_cache_cached, root)
        )
        with (
            patch.object(
                _mapping_types, "yaml_read", wraps=aws_mapping.yaml_read
            ) as read,
            patch.object(
                aws_mapping_catalog,
                "catalog_properties",
                wraps=aws_mapping_catalog.catalog_properties,
            ) as compile,
        ):
            first = cached()
            assert read.call_count == compile.call_count == 1
            assert cached() is not first
            assert read.call_count == compile.call_count == 1
            assert cached().properties is first.properties


def _callback_check_baseline_cached():
    first = aws_mapping.registry(ROOT, "config")
    assert aws_mapping.registry(ROOT, "config") is first


def check_baseline():
    expected = {
        kind + "." + prop: m.Field(
            "recorder" if kind == RECORDER else "channel", path, norm, default
        )
        for kind, props in BASELINE.items()
        for prop, (path, norm, default) in props.items()
    }
    assert {
        key: replace(field, default=field.copy_default())
        for key, field in aws_mapping.registry(ROOT, "config").fields.items()
    } == expected
    cached = (input_scope)(_callback_check_baseline_cached)
    cached()
    for kind, props in BASELINE.items():
        rows = [
            [f"001-{i:03}", kind + "." + prop, "`fixture`", ""]
            for i, prop in enumerate(props, 1)
        ]
        shown = display_rows(kind, rows)
        assert [row[1] for row in shown] == [
            "RoleName" if prop == "RoleARN" else prop for prop in props
        ]
        assert [row[0] for row in shown] == [row[0] for row in rows]
    assert m.normalize(None, False, "typed") is False
    assert m.normalize(None, [], "set") == []
    assert m.normalize(None, ["b", "a"], "set") == ["a", "b"]
    assert m.normalize(None, "bucket-fixture", "name") == "bucket-fixture"


def _callback_check_import_and_owners_are_lazy_read(
    original, reads, /, path, *args, **kwargs
):
    reads.append(path)
    return original(path, *args, **kwargs)


def _callback_check_import_and_owners_are_lazy_obtain(barrier, root, /, _):
    barrier.wait(timeout=10)
    return mappings_for(root)


def check_import_and_owners_are_lazy():
    # A fresh interpreter verifies import side effects without reloading shared state.
    code = """from pathlib import Path
from unittest.mock import patch
with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected read')):
    import utils.aws_mappings
assert not utils.aws_mappings._instances
"""
    subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT / "framework/scripts", check=True
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        original = Path.read_text
        reads = []
        read = _bind_framework_callback(
            _callback_check_import_and_owners_are_lazy_read, original, reads
        )
        barrier = Barrier(8)
        obtain = _bind_framework_callback(
            _callback_check_import_and_owners_are_lazy_obtain, barrier, root
        )
        with (
            patch.object(Path, "read_text", read),
            patch.object(_mapping_types, "yaml_read") as parse,
        ):
            with ThreadPoolExecutor(max_workers=8) as pool:
                providers = list(pool.map(obtain, range(8)))
            assert all(provider is providers[0] for provider in providers)
            assert owners(root) is owners(root)
            assert owners(root)[RECORDER] == "config"
            assert reads == [ROOT / "framework/mappings/aws/owners.json"]
            parse.assert_not_called()
            with pytest.raises(KeyError):
                owners(root)["Unknown.Resource"]
            with pytest.raises(TypeError):
                owners(root)[RECORDER] = "iam"
            for service in ("unknown", "../config", None):
                with pytest.raises(ValueError, match="unknown Mapping service"):
                    providers[0].get(service)
            assert len(reads) == 1


def _callback_check_runtime_cache_read(original, reads, /, path, *args, **kwargs):
    if path.suffix == ".yaml":
        reads.append(path)
    return original(path, *args, **kwargs)


def _callback_check_runtime_cache_scoped(first, root, /):
    assert aws_mapping.runtime_registry(root, "config") is first
    memo_table().clear()
    assert aws_mapping.runtime_registry(root, "config") is first


def check_runtime_cache():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "first"
        other = Path(directory) / "second"
        original = Path.read_text
        reads = []
        read = _bind_framework_callback(
            _callback_check_runtime_cache_read, original, reads
        )
        with (
            patch.object(Path, "read_text", read),
            patch.object(
                _mapping_types, "yaml_read", wraps=aws_mapping.yaml_read
            ) as parse,
            patch.object(
                _mapping_runtime,
                "runtime_properties",
                wraps=_mapping_runtime.runtime_properties,
            ) as compile,
        ):
            provider = mappings_for(root)
            first = provider.get("config")
            assert (
                provider.get(owners(root)[RECORDER])
                is provider.get(owners(root)[CHANNEL])
                is first
            )
            scoped = (input_scope)(
                _bind_framework_callback(
                    _callback_check_runtime_cache_scoped, first, root
                )
            )
            scoped()
            scoped()
            assert parse.call_count == compile.call_count == 1
            assert mappings_for(root).get("iam").service == "iam"
            assert mappings_for(other).get("config") is not first
            assert parse.call_count == 2
            assert compile.call_count == 3
            assert reads == [
                ROOT / "framework/mappings/aws/config.yaml",
                ROOT / "framework/mappings/aws/iam.yaml",
                ROOT / "framework/mappings/aws/config.yaml",
            ]


def _callback_check_parallel_services_parse(original, parsing, /, content):
    parsing.wait(timeout=10)  # Different services must not hold a common lock.
    return original(content)


def _callback_check_parallel_services_get(provider, start, /, number):
    start.wait(timeout=10)
    return provider.get("config" if number % 2 else "iam")


def check_parallel_services():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        provider = mappings_for(root)
        start, parsing = Barrier(8), Barrier(2)
        original = aws_mapping.yaml_read
        parse = _bind_framework_callback(
            _callback_check_parallel_services_parse, original, parsing
        )
        get = _bind_framework_callback(
            _callback_check_parallel_services_get, provider, start
        )
        with (
            patch.object(_mapping_types, "yaml_read", side_effect=parse) as read,
            patch.object(
                _mapping_runtime,
                "runtime_properties",
                wraps=_mapping_runtime.runtime_properties,
            ) as compile,
        ):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(get, range(8)))
            assert read.call_count == compile.call_count == 2
        assert all(item is results[number % 2] for number, item in enumerate(results))


def _callback_check_runtime_full_reuse_obtain(barrier, provider, root, /, number):
    barrier.wait(timeout=10)
    return provider.get("sqs") if number % 2 else aws_mapping.registry(root, "sqs")


def check_runtime_full_reuse():
    with TemporaryDirectory() as directory:
        for order in ("runtime-first", "full-first", "parallel"):
            root = Path(directory) / order
            provider = mappings_for(root)
            barrier = Barrier(8)
            obtain = _bind_framework_callback(
                _callback_check_runtime_full_reuse_obtain, barrier, provider, root
            )
            with patch.object(
                _mapping_types, "yaml_read", wraps=aws_mapping.yaml_read
            ) as parse:
                if order == "runtime-first":
                    runtime, full = (
                        provider.get("sqs"),
                        aws_mapping.registry(root, "sqs"),
                    )
                elif order == "full-first":
                    full, runtime = (
                        aws_mapping.registry(root, "sqs"),
                        provider.get("sqs"),
                    )
                else:
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        results = list(pool.map(obtain, range(8)))
                    runtime, full = results[1], results[0]
                    assert all(results[n] is runtime for n in (1, 3, 5, 7))
                assert parse.call_count == 1
                # Full compilation retains input extraction classification; runtime retains executable fields.
                assert (
                    full.getters == runtime.getters
                    and full.identities == runtime.identities
                )
                key = "SQS.Queue.QueueName"
                assert full.properties[key].field.classification == "local_metadata"
                assert runtime.properties[key].field.classification == "supported"
                assert provider.get("sqs") is runtime


def _callback_check_runtime_failures_read(
    _state_check_runtime_failures_352, /, path, *args, **kwargs
):
    if path.suffix == ".yaml":
        _state_check_runtime_failures_352.reads.append(path)
        if _state_check_runtime_failures_352.fault == "read":
            raise OSError("injected read failure")
    return _state_check_runtime_failures_352.original(path, *args, **kwargs)


def _callback_check_runtime_failures_compile(
    _state_check_runtime_failures_352, /, *args
):
    if _state_check_runtime_failures_352.fault == "runtime":
        raise ValueError("injected runtime failure")
    return _state_check_runtime_failures_352.runtime(*args)


def check_runtime_failures():
    _state_check_runtime_failures_352 = _CallbackState()
    with TemporaryDirectory() as directory:
        for _state_check_runtime_failures_352.fault in ("read", "runtime"):
            root = Path(directory) / _state_check_runtime_failures_352.fault
            provider = mappings_for(root)
            _state_check_runtime_failures_352.original = Path.read_text
            _state_check_runtime_failures_352.reads = []
            read = _bind_framework_callback(
                _callback_check_runtime_failures_read, _state_check_runtime_failures_352
            )
            _state_check_runtime_failures_352.runtime = (
                _mapping_runtime.runtime_properties
            )
            compile = _bind_framework_callback(
                _callback_check_runtime_failures_compile,
                _state_check_runtime_failures_352,
            )
            with (
                patch.object(Path, "read_text", read),
                patch.object(
                    _mapping_types, "yaml_read", wraps=aws_mapping.yaml_read
                ) as parse,
                patch.object(
                    _mapping_runtime, "runtime_properties", side_effect=compile
                ) as build,
            ):
                failure = (
                    OSError
                    if _state_check_runtime_failures_352.fault == "read"
                    else ValueError
                )
                for _ in range(2):
                    with pytest.raises(failure):
                        provider.get("config")
                assert len(_state_check_runtime_failures_352.reads) == 1
                assert parse.call_count == (
                    0 if _state_check_runtime_failures_352.fault == "read" else 1
                )
                assert build.call_count == (
                    1 if _state_check_runtime_failures_352.fault == "runtime" else 0
                )
                if _state_check_runtime_failures_352.fault == "runtime":
                    assert aws_mapping.registry(root, "config").service == "config"
                    assert parse.call_count == 1, (
                        "runtime failure must retain a usable document"
                    )


def _callback_check_full_failure_isolation_failed(catalogs, provider, schemas, sdk, /):
    with pytest.raises(ValueError, match="injected full failure"):
        provider.validated(
            "sns", sdk, schemas, catalogs, aws_mapping_catalog.catalog_properties
        )


def check_full_failure_isolation():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        runtime_provider = mappings_for(root)
        with patch.object(
            _mapping_types, "yaml_read", wraps=aws_mapping.yaml_read
        ) as parse:
            for target in ("sdk_shape", "DesignSchemaCatalog"):
                # Patching validation code changes its lifetime: use fresh instances.
                provider = Mappings(root)
                sdk, schemas, catalogs = Sdk(), Schemas(root), Catalogs(root)
                with patch.object(
                    aws_mapping_catalog,
                    target,
                    side_effect=ValueError("injected full failure"),
                ):
                    failed = _bind_framework_callback(
                        _callback_check_full_failure_isolation_failed,
                        catalogs,
                        provider,
                        schemas,
                        sdk,
                    )
                    input_scope(failed)()
                    runtime = runtime_provider.get("sns")
                    input_scope(failed)()
                    assert runtime_provider.get("sns") is runtime
                fresh = Mappings(root)
                assert (
                    fresh.validated(
                        "sns",
                        Sdk(),
                        Schemas(root),
                        Catalogs(root),
                        aws_mapping_catalog.catalog_properties,
                    ).resource_types
                    == runtime.resource_types
                )
            assert parse.call_count == 1


def check_shared_documents():
    with TemporaryDirectory() as directory:
        first, other = (
            Mappings(Path(directory) / "first"),
            Mappings(Path(directory) / "other"),
        )
        with patch.object(
            _mapping_types, "yaml_read", wraps=aws_mapping.yaml_read
        ) as parse:
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(
                    pool.map(
                        lambda n: (first if n % 2 else other)._document("config"),
                        range(8),
                    )
                )
            assert parse.call_count == 1
            assert first._document("config") is not other._document("config")
            first._document("config")["service"] = "changed"
            assert other._document("config")["service"] == "config"
            fresh = Mappings(Path(directory) / "fresh")
            assert fresh._document("config")["service"] == "config"
            assert parse.call_count == 1
            original_read = providers.input_text
            with patch.object(
                providers,
                "input_text",
                side_effect=lambda path, **kw: original_read(path, **kw) + "\n",
            ):
                changed = Mappings(Path(directory) / "changed")
                assert changed._document("config")["service"] == "config"
            assert parse.call_count == 2, "changed content must be parsed again"
        original = providers.input_text
        # Equal definitions at distinct Framework paths must not share a document.
        with (
            patch.object(
                providers,
                "definition_root",
                return_value=Path(directory) / "framework-owner",
            ),
            patch.object(
                providers,
                "input_text",
                side_effect=lambda path, **kw: original(
                    ROOT / path.relative_to(Path(directory) / "framework-owner"), **kw
                ),
            ),
            patch.object(
                _mapping_types, "yaml_read", wraps=aws_mapping.yaml_read
            ) as parse,
        ):
            distinct = Mappings(Path(directory))
            assert distinct.get("config").root == Path(directory) / "framework-owner"
            assert parse.call_count == 1
        with patch.object(
            _mapping_types,
            "yaml_read",
            side_effect=[
                ValueError("parse failure"),
                aws_mapping.yaml_read(
                    original(ROOT / "framework/mappings/aws/config.yaml")
                ),
            ],
        ) as parse:
            broken = Mappings(Path(directory) / "broken")
            with pytest.raises(ValueError, match="parse failure"):
                broken.get("config")
            assert (
                Mappings(Path(directory) / "healthy").get("config").service == "config"
            )
            for obtain in (
                lambda: broken._document("config"),
                lambda: broken.get("config"),
            ):
                with pytest.raises(ValueError, match="parse failure"):
                    obtain()
            assert parse.call_count == 2


def check_stage_alias():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "source"
        stage = Path(directory) / "stage"
        provider = mappings_for(root)
        with pytest.raises(RuntimeError, match="injected"), mapping_alias(root, stage):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(
                    pool.map(lambda _: mappings_for(stage).get("config"), range(4))
                )
            assert all(item is provider.get("config") for item in results)
            sibling = Path(str(stage) + "-prefix")
            assert mappings_for(sibling) is not provider
            with (
                pytest.raises(ValueError, match="already has a provider"),
                mapping_alias(root, stage),
            ):
                pass
            raise RuntimeError("injected")
        assert mappings_for(stage) is not provider
        with (
            pytest.raises(ValueError, match="already has a provider"),
            mapping_alias(root, stage),
        ):
            pass
        second = Path(directory) / "short-lived"
        with mapping_alias(root, second):
            assert mappings_for(second) is provider
        assert second not in providers._aliases


def _pause_alias_lookup(original, stage, entered, release, root):
    if root == stage:
        entered.set()
        assert release.wait(timeout=10)
    return original(root)


def _change_alias(context, attempted, register):
    attempted.set()
    if register:
        with context:
            pass
    else:
        context.__exit__(None, None, None)


@pytest.mark.parametrize("register", [True, False])
def check_alias_transition_races(register):
    with TemporaryDirectory() as directory:
        root, stage = Path(directory) / "source", Path(directory) / "stage"
        source = mappings_for(root)
        context = mapping_alias(root, stage)
        if not register:
            context.__enter__()
        entered, release, attempted = Event(), Event(), Event()
        lookup = _bind_framework_callback(
            _pause_alias_lookup, providers._lookup_alias_locked, stage, entered, release
        )
        with (
            patch.object(providers, "_lookup_alias_locked", side_effect=lookup),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            request = pool.submit(mappings_for, stage)
            try:
                assert entered.wait(timeout=10)
                transition = pool.submit(_change_alias, context, attempted, register)
                assert attempted.wait(timeout=10)
            finally:
                release.set()
            provider = request.result(timeout=10)
            if register:
                with pytest.raises(ValueError, match="already has a provider"):
                    transition.result(timeout=10)
                assert provider is mappings_for(stage) and provider is not source
            else:
                transition.result(timeout=10)
                assert provider is source
                assert stage not in providers._instances
        assert stage not in providers._aliases
        assert mappings_for(stage) is not source


def check_provider_failure_lifetime():
    with TemporaryDirectory() as directory:
        root, other = Path(directory) / "failed", Path(directory) / "other"
        error, healthy = ValueError("invalid owners"), object()
        with patch.object(
            providers, "Mappings", side_effect=[error, healthy]
        ) as create:
            for _ in range(2):
                with pytest.raises(ValueError, match="invalid owners"):
                    mappings_for(root)
            assert mappings_for(other) is healthy
            assert create.call_count == 2


def check_readonly_defaults():
    # Field is embedded verbatim into standalone audits; it must need no repo imports.
    generator = module("model/audit.py", "model.audit")
    namespace = {}
    exec(
        "from dataclasses import dataclass\nfrom collections.abc import Mapping\n"
        + generator.definitions(
            ROOT / "framework/scripts/model/adapters/aws.py", ["copy_default", "Field"]
        ),
        namespace,
    )
    assert namespace["Field"](default={"nested": (False, 0, None)}).copy_default() == {
        "nested": [False, 0, None]
    }


if __name__ == "__main__":
    raise SystemExit(run(__file__))
