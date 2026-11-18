"""Service-owned capabilities and reference decisions over synthetic resources."""

import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.contracts import ResourceContract
from comparison.methods import OBJECT, SCALAR, RuleSet
from services.contracts import (
    ArnExtension,
    DisplayExtension,
    ProducerReference,
    ReceiverReference,
    ReferenceMode,
    ResourceDefinition,
    ServiceDefinition,
)
from services.reference_engine import ReferenceEngine
from services.registry import ServiceRegistry
from support.pytest_cli import run

TARGET = {"SyntheticKeys.Key": ("Arn", "KeyName")}
IMPORT = ReferenceMode.IMPORT
COMPARISON = ReferenceMode.COMPARISON


def conditional(path, context, mode):
    if path != "Choice.Target":
        return None
    if mode is COMPARISON:
        return {"SyntheticKeys.Key": ("KeyArn",)}
    if context is None:
        return None
    return TARGET if context.get("Kind") == "Key" else {}


def arn_components(properties, evaluate):
    return {"id": evaluate(properties["Name"])}


@pytest.fixture
def keys():
    return ServiceDefinition(
        "test-keys",
        (
            ResourceDefinition(
                "SyntheticKeys.Key",
                producer=ProducerReference(
                    ref_attribute="Id",
                    getatt_attributes=frozenset({"KeyArn"}),
                    arn_attribute="KeyArn",
                    model_attributes={"KeyName": "Name"},
                ),
                arn=ArnExtension(arn_components, ("SyntheticKeys.Key.Name",)),
            ),
        ),
    )


@pytest.fixture
def registry(keys):
    storage = ServiceDefinition(
        "test-storage",
        (
            ResourceDefinition(
                "AWS::SyntheticStorage::Bucket",
                receiver=ReceiverReference(
                    import_properties={
                        "Rules[].Key": {"AWS::SyntheticKeys::Key": ("Arn", "KeyName")},
                        "Recipients[]": TARGET,
                        "Blocked": {},
                        "Choice.Target": {"SyntheticKeys.Key": ("Arn",)},
                    },
                    comparison_properties={
                        "CompareOnly": {"SyntheticKeys.Key": ("KeyArn",)}
                    },
                    contextual=conditional,
                ),
            ),
            ResourceDefinition(
                "SyntheticStorage.Empty",
                producer=ProducerReference(),
                receiver=ReceiverReference(),
            ),
            ResourceDefinition("SyntheticStorage.Plain"),
        ),
    )
    return ServiceRegistry((storage, keys))


def check_registration_and_coverage(registry):
    assert registry.resource("AWS::SyntheticStorage::Bucket").resource_type == (
        "SyntheticStorage.Bucket"
    )
    registry.check_coverage(
        {
            "AWS::SyntheticStorage::Empty": "test-storage",
            "SyntheticKeys.Key": "test-keys",
        }
    )
    with pytest.raises(ValueError, match="wrong owner.*test-storage.*test-keys"):
        registry.check_coverage({"SyntheticKeys.Key": "test-storage"})
    with pytest.raises(ValueError, match="missing ResourceType registration"):
        registry.check_coverage({"SyntheticStorage.Unregistered": "test-storage"})

    assert registry.receiver("SyntheticStorage.Empty") == ReceiverReference()
    assert registry.receiver("SyntheticStorage.Plain") is None
    assert registry.owner("SyntheticStorage.Plain") == "test-storage"
    for lookup in (
        registry.producer,
        registry.receiver,
        registry.comparison_rules,
        registry.design,
        registry.display,
        registry.arn,
    ):
        assert lookup("SyntheticStorage.Plain") is None
        with pytest.raises(KeyError, match="SyntheticStorage.Unregistered"):
            lookup("AWS::SyntheticStorage::Unregistered")


@pytest.mark.parametrize(
    ("definition", "message"),
    [
        (
            ServiceDefinition(
                "test-keys", (ResourceDefinition("SyntheticKeys.Other"),)
            ),
            "duplicate service",
        ),
        (
            ServiceDefinition(
                "different-owner", (ResourceDefinition("AWS::SyntheticKeys::Key"),)
            ),
            "duplicate ResourceType.*test-keys.*different-owner",
        ),
        (
            ServiceDefinition(
                "test-storage", (ResourceDefinition("AWS::SyntheticStorage.Bucket"),)
            ),
            "invalid ResourceType",
        ),
    ],
    ids=("service-name", "canonical-type", "malformed-type"),
)
def check_invalid_registration(keys, definition, message):
    with pytest.raises(ValueError, match=message):
        ServiceRegistry((keys, definition))


@pytest.mark.parametrize(
    ("receiver", "message"),
    [
        (
            ReceiverReference({"Key": {"SyntheticKeys.Key": ("Unknown",)}}),
            "invalid Producer forms",
        ),
        (
            ReceiverReference({"Rules[].Key": TARGET, "Rules[1].Key": TARGET}),
            "duplicate receiving property",
        ),
        (
            ReceiverReference({"Key": {"SyntheticKeys.Key": ()}}),
            "invalid Producer forms",
        ),
    ],
    ids=(
        "missing-form",
        "duplicate-normalized-path",
        "empty-forms",
    ),
)
def check_invalid_receiver_contract(keys, receiver, message):
    resource = ResourceDefinition("SyntheticStorage.Bucket", receiver=receiver)
    with pytest.raises(ValueError, match=message):
        ServiceRegistry((keys, ServiceDefinition("test-storage", (resource,))))


def check_cross_service_reference(registry):
    engine = ReferenceEngine(registry)
    assert engine.ref_attribute("AWS::SyntheticKeys::Key") == "Id"
    assert engine.getatt_attributes("SyntheticKeys.Key") == {"KeyArn"}
    assert engine.arn_attribute("SyntheticKeys.Key") == "KeyArn"
    assert engine.model_attribute("SyntheticKeys.Key", "Arn") == "KeyArn"
    assert engine.model_attribute("SyntheticKeys.Key", "KeyName") == "Name"
    assert engine.getatt_attributes("SyntheticStorage.Bucket") is None
    assert engine.getatt_attributes("SyntheticStorage.Empty") == frozenset()
    assert engine.model_attribute("SyntheticKeys.Key", "Unknown") is None

    receiver = "AWS::SyntheticStorage::Bucket"
    path = "AWS::SyntheticStorage::Bucket.Rules[12].Key"
    assert engine.receiver_forms(receiver, path, mode=IMPORT) == TARGET
    assert (
        engine.allows(receiver, path, "AWS::SyntheticKeys::Key", "Arn", mode=IMPORT)
        is True
    )
    assert (
        engine.allows(receiver, path, "SyntheticKeys.Key", "Id", mode=IMPORT) is False
    )
    assert engine.receiver_forms(receiver, "Recipients", mode=IMPORT) == TARGET
    assert engine.receiver_forms(receiver, path, mode=COMPARISON) is None
    assert engine.receiver_forms(receiver, "CompareOnly", mode=IMPORT) is None
    assert engine.receiver_forms(receiver, "CompareOnly", mode=COMPARISON) == {
        "SyntheticKeys.Key": ("KeyArn",)
    }
    with pytest.raises(ValueError, match="property path must belong"):
        engine.receiver_forms(receiver, "AWS::SyntheticKeys::Key.Id", mode=IMPORT)


def check_denial_and_conditional_override(registry):
    engine = ReferenceEngine(registry)
    kind = "SyntheticStorage.Bucket"
    assert engine.receiver_forms(kind, "Choice.Target", mode=IMPORT) == {
        "SyntheticKeys.Key": ("Arn",)
    }
    assert (
        engine.receiver_forms(
            kind, "Choice.Target", mode=IMPORT, context={"Kind": "Key"}
        )
        == TARGET
    )
    assert (
        engine.receiver_forms(
            kind, "Choice.Target", mode=IMPORT, context={"Kind": "Literal"}
        )
        == {}
    )
    assert engine.receiver_forms(
        kind, "Choice.Target", mode=COMPARISON, context={"Kind": "Literal"}
    ) == {"SyntheticKeys.Key": ("KeyArn",)}
    assert engine.receiver_forms(kind, "Blocked", mode=IMPORT) == {}
    assert (
        engine.allows(kind, "Blocked", "SyntheticKeys.Key", "Arn", mode=IMPORT) is False
    )
    assert (
        engine.allows(kind, "Undeclared", "SyntheticKeys.Key", "Arn", mode=IMPORT)
        is None
    )


def check_unregistered_producer_dependencies(keys):
    missing = {"SyntheticKeys.Unregistered": ("Arn",)}
    hook = Mock(return_value=missing)
    resource = ResourceDefinition(
        "SyntheticStorage.Bucket",
        receiver=ReceiverReference(import_properties={"Key": missing}, contextual=hook),
    )
    registry = ServiceRegistry((keys, ServiceDefinition("test-storage", (resource,))))
    engine = ReferenceEngine(registry)
    assert registry.missing_producers() == {"SyntheticKeys.Unregistered"}
    assert (
        engine.receiver_forms("SyntheticStorage.Bucket", "Choice.Target", mode=IMPORT)
        == missing
    )
    with pytest.raises(KeyError, match="SyntheticKeys.Unregistered"):
        engine.allows(
            "SyntheticStorage.Bucket",
            "Key",
            "SyntheticKeys.Unregistered",
            "Arn",
            mode=IMPORT,
        )


def check_reuses_feature_contracts(keys):
    resource_type = "SyntheticStorage.Bucket"
    resource_contract = ResourceContract(name_tag=True)
    rules = RuleSet(resource_contract)
    rules["Rules[].Name"] = SCALAR
    comparison = Mock(return_value=rules)
    display_hook = Mock(return_value=[["1", "Name", "example", ""]])
    display = Mock(return_value=DisplayExtension(display=display_hook))
    formats = {"SyntheticStorage.Bucket.Policy": "statement"}
    resource = ResourceDefinition(
        resource_type,
        comparison=comparison,
        design={"POLICY_FORMATS": formats},
        display=display,
    )
    registry = ServiceRegistry((keys, ServiceDefinition("test-storage", (resource,))))
    assert registry.design(resource_type)["POLICY_FORMATS"] is formats
    arn = registry.arn("SyntheticKeys.Key")
    assert arn.depends_on == ("Name",)
    assert arn.components({"Name": "example"}, str.upper) == {"id": "EXAMPLE"}
    comparison.assert_not_called()
    display.assert_not_called()

    assert registry.comparison_rules(resource_type) is rules
    assert rules.resource is resource_contract
    assert registry.comparison_property_rule(resource_type, "Rules[0].Name") is SCALAR
    assert (
        registry.comparison_property_rule(resource_type, "Rules[0].NewChild") is OBJECT
    )
    extension = registry.display(resource_type)
    assert extension.display([], resource_type, mode="CREATE") == [
        ["1", "Name", "example", ""]
    ]
    assert extension.restore is None


def check_invalid_feature_declarations():
    resource_type = "SyntheticStorage.Bucket"
    definition = ResourceDefinition(
        resource_type, design={"HIDDEN_PROPERTIES": {"Other.Bucket.Name"}}
    )
    with pytest.raises(ValueError, match="foreign key"):
        ServiceRegistry((ServiceDefinition("test-storage", (definition,)),))
    definition = ResourceDefinition(
        resource_type, comparison=Mock(return_value={}), display=Mock(return_value=())
    )
    registry = ServiceRegistry((ServiceDefinition("test-storage", (definition,)),))
    with pytest.raises(ValueError, match="invalid Comparison rules"):
        registry.comparison_rules(resource_type)
    with pytest.raises(ValueError, match="invalid Display extension"):
        registry.display(resource_type)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
