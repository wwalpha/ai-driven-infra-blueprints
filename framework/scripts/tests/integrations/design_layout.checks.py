#!/usr/bin/env python3
"""Saved Config Model → generated service-role display → read-only Validator."""

import sys
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support.design_layout_fixtures import (
    json,
    model_core,
    reference_design,
    run,
    sync_runtime,
    write_model,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_config_firehose_references(tmp_path):
    _state_check_config_firehose_references_654 = _CallbackState()
    design = reference_design
    directory = tmp_path / "case-1"
    directory.mkdir()
    _state_check_config_firehose_references_654.root = directory
    (_state_check_config_firehose_references_654.root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "test",
                "targets": [
                    {
                        "environment": "dev",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    path = (
        _state_check_config_firehose_references_654.root
        / "docs/designs/dev/123456789012/config.md"
    )
    path.parent.mkdir(parents=True)
    source = (
        design(
            "config",
            "Config.ConfigurationRecorder",
            [
                ("Id", "`PENDING_DEPLOY`"),
                ("RoleName", "`AWSServiceRoleForConfig`"),
            ],
        )
        .replace(
            '<a id="config-resource">',
            '<!-- resource-logical-id: ConfigRecorder -->\n<a id="config-configuration-recorder-recorder">',
        )
        .replace("ConfigurationRecorder: Resource", "ConfigurationRecorder: recorder")
    )
    path.write_text(source, encoding="utf-8")
    values = model_core.properties("""# Synthetic authoritative Model fixture.
desired.service.config.serviceId=config
desired.service.config.ownedCatalogResourceTypes=Config.ConfigurationRecorder
desired.resource.001.resourceType=Config.ConfigurationRecorder
desired.resource.001.logicalId=Config_ConfigurationRecorder_001
desired.resource.001.anchor=resource-Config_ConfigurationRecorder_001
desired.resource.001.cfn-logicalId=fixture-ConfigRecorder
desired.service.identity.lastAllocated={"Config.ConfigurationRecorder":1}
desired.row.001-001.property=Config.ConfigurationRecorder.Id
desired.row.001-001.value=[Config_ConfigurationRecorder_001](config.md#resource-Config_ConfigurationRecorder_001)
desired.row.001-001.comment=設定する属性
observed.row.001-001.property=Config.ConfigurationRecorder.Id
observed.row.001-001.value=`PENDING_DEPLOY`
observed.row.001-001.comment=設定する属性
desired.row.001-002.property=Config.ConfigurationRecorder.RoleARN
desired.row.001-002.value=`AWSServiceRoleForConfig`
desired.row.001-002.comment=設定する属性
desired.row.001-003.property=Config.ConfigurationRecorder.Name
desired.row.001-003.value=`recorder`
desired.row.001-003.comment=記録するrecorderの名前
""")
    values.update(
        {
            "display.service.title": "# Config 詳細設計",
            "display.resource.001.label": "recorder",
            "display.resource.001.comment": "AWSリソースの設定を記録するrecorder",
        }
    )
    model_path = (
        _state_check_config_firehose_references_654.root
        / "model/dev/123456789012/config.properties"
    )
    model_path.parent.mkdir(parents=True)
    write_model(
        model_path, "".join(f"{key}={value}\n" for key, value in values.items())
    )
    write_model(
        model_path.with_name("cloudformation-stacks.properties"),
        {
            "desired.stack.001.name": "fixture",
            "desired.stack.001.placementName": "fixture",
            "desired.stack.001.template": "fixture.yaml",
            "desired.stack.001.parameters": "fixture.json",
            "desired.stack.001.deployOrder": "1",
            "display.stack.001.comment": "合成Stack",
        },
    )
    path.unlink()
    assert (
        sync_runtime.sync(
            _state_check_config_firehose_references_654.root,
            True,
            "dev",
            "123456789012",
        )
        == 0
    )
    assert "| RoleName | `AWSServiceRoleForConfig` |" in path.read_text(
        encoding="utf-8"
    )
    assert (
        sync_runtime.sync(
            _state_check_config_firehose_references_654.root,
            False,
            "dev",
            "123456789012",
        )
        == 0
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
