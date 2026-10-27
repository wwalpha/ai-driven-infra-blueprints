"""Model 検証: naming。"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import design.layout as _dependency_design_layout
import design.layout as _imports_design_layout
from design.catalog import (
    DesignSchemaCatalog,
    selected_properties,
)
from utils.aws_catalogs import catalog_outputs
from utils.aws_mappings import definition_root
from utils.input_cache import memoized
from validation.diagnostics import InputValidationError
from validation.findings import Findings

from model.projection import resource_rows

NAMING_EXEMPT_PROPERTIES = {
    "Config.ConfigurationRecorder.Name",
    "Config.DeliveryChannel.Name",
    "Glue.Connection.ConnectionInput.Name",
    "Glue.Database.DatabaseInput.Name",
    "Glue.Table.TableInput.Name",
    "GuardDuty.Detector.Name",
    "IAM.ManagedPolicy.ManagedPolicyName",
    "IAM.User.UserName",
    "IAM.InstanceProfile.InstanceProfileName",
    "Route53.HostedZone.Name",
    "Route53.RecordSet.Name",
}


@memoized
def naming_rule_files(root: Path, namespace: str | None = None) -> tuple[Path, ...]:
    """共通ルールと指定サービスに索引された命名ルールだけを取得する。"""
    root = definition_root(root)
    path = root / "framework/rules/aws-resource-naming.md"
    files = [path]
    for name, reference in re.findall(
        r"^\| `([A-Za-z0-9]+)` \| \[[^\]]+\]\((aws-resource-naming/[A-Za-z0-9]+\.md)\) \|$",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    ):
        if namespace is None or name == namespace:
            files.append(path.parent / reference)
    return tuple(files)


def naming_target_matches(
    prop: str, targets: set[str], kind: str | None = None
) -> bool:
    """命名対象が宣言された属性パスと一致するか確認する。"""
    normalized = {
        target.removeprefix(kind + ".") if kind else target for target in targets
    }
    return prop in normalized


@memoized
def naming_targets(root: Path, namespace: str | None = None) -> dict[str, set[str]]:
    """命名ルールの表から Resource Type ごとの対象を集める。"""
    targets: dict[str, set[str]] = {}
    for path in naming_rule_files(root, namespace):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if (
                len(cells) in {5, 6}
                and cells[2].startswith("`")
                and re.fullmatch(r"`[^`]+`", cells[4])
            ):
                for kind in re.findall(r"`([^`]+)`", cells[2]):
                    targets.setdefault(kind, set()).add(cells[3].strip("`"))
    return targets


def naming_coverage_errors(
    root: Path,
    kind: str,
    selected: set[str],
    name_tag: bool = False,
    mode: str = "CREATE",
) -> list[str]:
    """CREATE の選択属性に命名ルールがあるか確認し、IMPORT は対象外とする。"""
    if mode not in {"CREATE", "IMPORT"}:
        raise InputValidationError(f"resourceMode must be CREATE or IMPORT: {mode!r}")
    if mode == "IMPORT":
        return []
    targets = naming_targets(root, kind.partition(".")[0])
    expected = selected & set(_dependency_design_layout.resource_name_fields(kind))
    expected.update(
        field
        for field in selected
        if naming_target_matches(field, targets.get(kind, set()), kind)
    )
    if name_tag:
        expected.add("Name tag")
    return [
        f"naming rule missing: {kind}: {field}"
        for field in sorted(expected)
        if kind + "." + field not in NAMING_EXEMPT_PROPERTIES
        and not naming_target_matches(field, targets.get(kind, set()), kind)
    ]


def design_naming_errors(
    root: Path, kind: str, mode: str = "CREATE", name_tag: bool = False
) -> list[str]:
    """設計開始前に選択可能な命名属性とルールの対応を確認する。"""
    # 配置先の StackName はカタログ属性ではなく Model 入力として選択する。
    selected = (
        {"StackName"}
        if kind == "CloudFormation.Stack"
        else set(selected_properties(root, kind))
    )
    if not selected:
        raise ValueError(f"catalog resource type missing: {kind}")
    selected -= {
        field.removeprefix(kind + ".") for field in catalog_outputs(root, kind)
    }
    if name_tag and not selected.intersection(
        {"Tags", "Tags[].Key", "HostedZoneTags", "HostedZoneTags[].Key"}
    ):
        raise InputValidationError(f"Name tag is not selectable: {kind}")
    if kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}:
        selected.add("Name")
    if kind in {"EC2.VPCEndpoint", "EC2.Instance"}:
        name_tag = True
    return naming_coverage_errors(root, kind, selected, name_tag, mode)


def naming_errors(
    root: Path, kind: str, rows: list[list[str]], mode: str = "CREATE"
) -> list[str]:
    """既存の名前確認とスキーマ制約、命名ルールの適用結果を返す。"""
    if kind in {"CodeBuild.Project", "IAM.Role"}:
        field = "RoleName" if kind == "IAM.Role" else "Name"
        names = [
            row[2].strip('`"')
            for row in rows
            if row[1].removeprefix(kind + ".") == field
        ]
        if len(names) != 1:
            return [f"{kind}.{field} must appear exactly once"]
        value = names[0]
        if (
            not value.strip()
            or value.strip().lower()
            in {"unset", "pending", "pending_deploy", "tbd", "n/a", "none", "未確定"}
            or value.startswith("[")
            or "{{" in value
        ):
            return [f"{kind}.{field} must be confirmed and non-empty"]
    catalog = DesignSchemaCatalog(root)
    for field in _imports_design_layout.configured_name_fields(root, kind):
        for row in rows:
            if row[1].removeprefix(kind + ".") == field:
                try:
                    errors = catalog.literal_errors(kind, field, row[2].strip('`"'))
                except KeyError:
                    continue  # 設計専用の名前には対応する provider 属性がない。
                if errors:
                    return errors
    if mode == "IMPORT":
        return []  # IMPORT でも上記の名前確認と provider／schema の検証は適用する。
    outputs = catalog_outputs(root, kind)
    selected = {
        row[1].removeprefix(kind + ".")
        for row in rows
        if kind + "." + row[1].removeprefix(kind + ".") not in outputs
    }
    tag_rows = [
        row
        for row in rows
        if row[1].removeprefix(kind + ".").startswith(("Tags", "HostedZoneTags"))
    ]
    return naming_coverage_errors(
        root,
        kind,
        selected,
        _dependency_design_layout.resource_display_name(kind, tag_rows, root=root)
        is not None,
        mode,
    )


def _callback_check_model_inputs_names(
    _state_check_model_inputs_337: SimpleNamespace,
    definitions: Path,
    findings: Findings,
    values: dict[str, str],
    /,
) -> None:
    """対象 Resource の名前を共通ルールで検証し、診断を集約する。"""
    rows = resource_rows(
        values,
        _state_check_model_inputs_337.identity,
        _state_check_model_inputs_337.resource["resourceType"],
        definitions,
    )
    for error in naming_errors(
        definitions,
        _state_check_model_inputs_337.resource["resourceType"],
        rows,
        _dependency_design_layout.resource_mode(_state_check_model_inputs_337.resource),
    ):
        findings.input_check(
            False,
            findings.source_path,
            error,
            location="desired.resource." + _state_check_model_inputs_337.identity,
        )
