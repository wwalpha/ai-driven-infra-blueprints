"""Model 検証: naming。"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import design.layout as _dependency_design_layout
import design.layout as _imports_design_layout
from design.catalog import (
    DesignSchemaCatalog,
    selected_properties,
)
from utils.aws_catalogs import catalog_outputs
from utils.aws_mappings import definition_root
from utils.input_cache import input_context, memoized
from validation.diagnostics import InputValidationError
from validation.findings import Findings

from model.core import literal
from model.projection import design_target, resource_rows

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


def value_available(value: object, shown: object) -> bool:
    """Require an unmasked literal before claiming a name's checks are complete."""
    raw = literal(value) if isinstance(value, str) else None
    return (
        isinstance(raw, str)
        and bool(raw.strip())
        and raw.lower()
        not in {
            "unresolved",
            "unset",
            "tbd",
            "todo",
            "pending_deploy",
            "未確定",
        }
        and not any(token in raw for token in ("${", "{{", "<masked"))
        and not raw.startswith(("[", "{"))
        and shown == value
    )


def provider_naming_errors(
    kind: str, field: str, value: str, conditions: dict[str, str | None] | None = None
) -> list[str]:
    """Retain explicit AWS constraints not represented by every provider schema."""
    if (kind, field) == ("S3.Bucket", "BucketName") and (
        not 3 <= len(value) <= 63
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", value)
    ):
        return ["S3 BucketName must be lowercase and 3–63 characters"]
    if (kind, field) == ("SQS.Queue", "QueueName") and (
        len(value) > 80 or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.fifo)?", value)
    ):
        return ["SQS QueueName has invalid characters or exceeds 80 characters"]
    if (kind, field) == ("KMS.Alias", "AliasName") and (
        not value.startswith("alias/") or value.startswith("alias/aws/")
    ):
        return ["KMS AliasName must use alias/ and exclude reserved alias/aws/"]
    if (kind, field) in {("SQS.Queue", "QueueName"), ("SNS.Topic", "TopicName")}:
        fifo = (conditions or {}).get(
            "FifoQueue" if kind == "SQS.Queue" else "FifoTopic"
        )
        if (
            fifo is True or isinstance(fifo, str) and fifo.lower() == "true"
        ) and not value.endswith(".fifo"):
            return ["FIFO names must end with .fifo"]
    return []


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
        for kind, target, _ in naming_rule_rows(path.read_text(encoding="utf-8")):
            targets.setdefault(kind, set()).add(target)
    return targets


def naming_rule_rows(text: str) -> Iterator[tuple[str, str, str]]:
    """Read the same naming tables used by the coverage check."""
    for kind, target, pattern, _ in naming_rules(text):
        yield kind, target, pattern


def naming_rules(text: str) -> Iterator[tuple[str, str, str, str]]:
    """Optional applicability column distinguishes obligations from alternatives."""
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if (
            len(cells) in {5, 6}
            and cells[2].startswith("`")
            and re.fullmatch(r"`[^`]+`(?:\s*<br>\s*`[^`]+`)*", cells[4])
        ):
            for kind in re.findall(r"`([^`]+)`", cells[2]):
                for pattern in re.findall(r"`([^`]+)`", cells[4]):
                    scope = (
                        cells[5]
                        if len(cells) == 6 and cells[5] in {"alternative", "prefix"}
                        else "mandatory"
                    )
                    yield kind, cells[3].strip("`"), pattern, scope


@memoized
def parsed_naming_rules(text: str) -> tuple[tuple[str, str, str, str], ...]:
    """Parse a naming rule text once per input context."""
    return tuple(naming_rules(text))


class NamingRuleIndex:
    """Immutable rules parsed once from a Scan naming context."""

    def __init__(self, context):
        index = {}
        errors = {}
        with input_context():
            for namespace, entries in context.get("rules", {}).items():
                if namespace == "common":
                    continue
                try:
                    for entry in entries:
                        text = entry["text"]
                        for kind, target, pattern, scope in parsed_naming_rules(text):
                            key = (namespace, kind, target.removeprefix(kind + "."))
                            index.setdefault(key, []).append((pattern, scope))
                except (KeyError, TypeError, AttributeError) as error:
                    errors[namespace] = (type(error), error.args)
        self._rules = MappingProxyType(
            {key: tuple(value) for key, value in index.items()}
        )
        self._errors = MappingProxyType(errors)

    def get(self, kind, prop):
        namespace = kind.partition(".")[0]
        if namespace in self._errors:
            error, args = self._errors[namespace]
            raise error(*args)
        return self._rules.get((namespace, kind, prop), ())


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


def resolve_target_suffix(view: Path, root: Path) -> str | None:
    """対象ターゲットを解決し、設定された suffix を返す。"""
    target = design_target(view, root)
    if not target:
        raise InputValidationError(f"IAM RoleName target cannot be resolved: {view}")
    return target.get("suffix")


def check_iam_role_suffix(role_name: str, expected_suffix: str | None) -> list[str]:
    """RoleName の末尾が対象ターゲットの suffix と一致するか検証する。"""
    ending = "Role" + ("-" + expected_suffix if expected_suffix is not None else "")
    # purpose と suffix の境界は PascalCase と固定の Role で判別する。
    if re.fullmatch(r".+-[A-Z][A-Za-z0-9]*" + re.escape(ending), role_name):
        return []
    return [
        f"IAM.Role.RoleName suffix mismatch: actual={role_name!r}, "
        f"expected suffix={expected_suffix!r}; expected ending={ending!r}"
    ]


def validate_resource_naming_suffix(
    kind: str, mode: str, rows: list[list[str]], view: Path, root: Path
) -> list[str]:
    """CREATE の IAM Role にだけ対象ターゲットの suffix 検証を適用する。"""
    if kind != "IAM.Role" or mode != "CREATE":
        return []
    role_name = next(
        row[2].strip('`"')
        for row in rows
        if row[1].removeprefix(kind + ".") == "RoleName"
    )
    return check_iam_role_suffix(role_name, resolve_target_suffix(view, root))


def naming_errors(
    root: Path,
    kind: str,
    rows: list[list[str]],
    mode: str = "CREATE",
    view: Path | None = None,
    project_root: Path | None = None,
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
                if errors := provider_naming_errors(
                    kind,
                    field,
                    row[2].strip('`"'),
                    {
                        entry[1].removeprefix(kind + "."): entry[2].strip('`"')
                        for entry in rows
                    },
                ):
                    return errors
    if mode == "IMPORT":
        return []  # IMPORT でも上記の名前確認と provider／schema の検証は適用する。
    if view is not None and project_root is not None:
        if errors := validate_resource_naming_suffix(
            kind, mode, rows, view, project_root
        ):
            return errors
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
        _state_check_model_inputs_337.view,
        findings.canonical_root,
    ):
        findings.input_check(
            False,
            findings.source_path,
            error,
            location="desired.resource." + _state_check_model_inputs_337.identity,
        )
