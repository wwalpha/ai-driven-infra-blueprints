"""Paired Glue, CodeBuild and CodePipeline row display/restoration."""

import html
import json
import re
from model_core import LINK, literal
from iac_values import unique_object, invalid_constant


CODEBUILD_VARIABLE = "CodeBuild.Project.Environment.Variables."
CODEBUILD_FORMAL_VARIABLE = "CodeBuild.Project.Environment.EnvironmentVariables[]."
CODEBUILD_VARIABLE_TYPE = re.compile(r"^<!-- codebuild-variable-type: (PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER) -->\s*")
CODEPIPELINE_STAGE = re.compile(r"^Stages\[([1-9]\d*)\]\.(?:Actions(?:\[([1-9]\d*)\])?\.)?(.+)$")
CODEPIPELINE_CONFIGURATION = "CodePipeline.Pipeline.Stages[].Actions[].Configuration"


def codebuild_display_row(rows, index, comment):
    block = rows[index:index + 3]
    if [row[1] for row in block] != [CODEBUILD_FORMAL_VARIABLE + field for field in ("Name", "Type", "Value")]:
        raise ValueError("CodeBuild variables require contiguous Name/Type/Value rows")
    name, variable_type, value = [literal(row[2]) for row in block]
    prop = CODEBUILD_VARIABLE + name
    if LINK.fullmatch(block[2][2]):
        value = block[2][2]
        comment = f"<!-- codebuild-variable-type: {variable_type} --> {comment}"
    elif variable_type == "PLAINTEXT":
        value = block[2][2]
    else:
        raise ValueError("CodeBuild non-PLAINTEXT variables require a resource link")
    return [rows[index][0], prop, value, comment]


def codebuild_formal_rows(cells, names):
    name = cells[1].removeprefix(CODEBUILD_VARIABLE)
    if not re.fullmatch(r"[^.\s|]+", name) or name in names:
        raise ValueError(f"invalid or duplicate CodeBuild environment variable name: {name}")
    names.add(name)
    raw = cells[2]
    if len(raw) >= 2 and raw[0] == raw[-1] == "`":
        raw = raw[1:-1]
    marker = CODEBUILD_VARIABLE_TYPE.match(cells[3])
    linked = re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2])
    if cells[2].startswith("[") and "](" in cells[2] and not linked:
        raise ValueError(f"CodeBuild resource variable must use a single resource anchor link: {name}")
    if "<!-- codebuild-variable-type:" in cells[3] and not marker:
        raise ValueError(f"invalid CodeBuild environment variable Type marker: {name}")
    if bool(marker) != bool(linked):
        raise ValueError(f"CodeBuild resource variable requires a link and Type marker: {name}")
    if re.match(r"^(PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER):", raw):
        raise ValueError(f"CodeBuild environment variable must omit the Type prefix: {name}")
    variable_type = marker.group(1) if marker else "PLAINTEXT"
    comment = cells[3][marker.end():] if marker else cells[3]
    value = cells[2] if linked else f"`{raw}`"
    return [[cells[0], CODEBUILD_FORMAL_VARIABLE + field, field_value, comment]
            for field, field_value in (("Name", f"`{name}`"), ("Type", f"`{variable_type}`"), ("Value", value))]


def pipeline_rows(rows: list[list[str]]) -> list[list[str]]:
    action_counts: list[int] = []
    seen_stage: set[str] = set()
    seen_action: set[str] = set()
    result = []
    trailing = []
    ordered = []
    name_last = False
    for row in rows:
        field = row[1]
        if not field.startswith("Stages[]."):
            (trailing if action_counts else result).append(row)
            continue
        if trailing:
            raise ValueError("CodePipeline stage rows must be contiguous")
        field = field.removeprefix("Stages[].")
        action = field.startswith("Actions[].")
        field = field.removeprefix("Actions[].")
        if not action_counts:
            # Catalog order ends each stage with Name; legacy models put it first.
            name_last = action
        if not action_counts or (name_last and "Name" in seen_stage) or (not action and field in seen_stage):
            seen_stage, seen_action = set(), set()
            action_counts.append(0)
        if action:
            if not seen_action or ("[]" not in field and field in seen_action):
                seen_action = set()
                action_counts[-1] += 1
            seen_action.add(field)
        else:
            seen_stage.add(field)
        ordered.append((len(action_counts), action_counts[-1] if action else 0, [row[0], field, *row[2:]]))
    for stage, action, (identity, field, value, comment) in ordered:
        prefix = f"Stages[{stage}]."
        if action:
            prefix += "Actions." if action_counts[stage - 1] == 1 else f"Actions[{action}]."
        if field != "Configuration":
            result.append([identity, prefix + field, value, comment])
            continue
        config = json.loads(literal(value), object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(config, dict) or not config or any(not isinstance(item, str) for item in config.values()):
            raise ValueError("CodePipeline Configuration must be a non-empty string object")
        comments = dict(part.split(": ", 1) for part in comment.split(" / ") if ": " in part)
        if set(comments) != set(config):
            raise ValueError("CodePipeline Configuration requires a comment for each key")
        for key, item in config.items():
            result.append([identity, prefix + "Configuration." + key, item if LINK.fullmatch(item) else f"`{item}`", comments[key]])
    return result + trailing


def pipeline_display_rows(rows: list[list[str]]) -> list[list[str]]:
    """Restore indexed stages/actions and key rows to the selected catalog fields."""
    stages: dict[int, dict[int, bool]] = {}
    configurations: dict[tuple[int, int], dict[str, str]] = {}
    configuration_rows: dict[tuple[int, int], list[str]] = {}
    fields: set[tuple[int, int, str]] = set()
    result = []
    previous_stage = previous_action = 0
    previous_configuration = None
    for row in rows:
        display = row[1].removeprefix("CodePipeline.Pipeline.")
        if not display.startswith("Stages"):
            result.append(row)
            previous_configuration = None
            continue
        match = CODEPIPELINE_STAGE.fullmatch(display)
        if not match:
            raise ValueError("CodePipeline stages must use Stages[N], starting at 1")
        stage = int(match.group(1))
        if stage != previous_stage:
            if stage != len(stages) + 1:
                raise ValueError("CodePipeline stage indexes must be sequential and contiguous")
            stages[stage] = {}
            previous_stage, previous_action = stage, 0
        is_action = display.startswith(f"Stages[{stage}].Actions")
        action = int(match.group(2) or 1) if is_action else 0
        field = match.group(3)
        if is_action and field.startswith("Actions"):
            raise ValueError("CodePipeline actions must use Actions or Actions[N], without []")
        identity_field = stage, action, field
        if "[]" not in field and identity_field in fields:
            raise ValueError(f"duplicate CodePipeline stage/action field: {display}")
        fields.add(identity_field)
        if is_action and action != previous_action:
            if action != len(stages[stage]) + 1:
                raise ValueError("CodePipeline action indexes must be sequential and contiguous per stage")
            stages[stage][action] = bool(match.group(2))
            previous_action = action
        elif is_action and stages[stage][action] != bool(match.group(2)):
            raise ValueError("CodePipeline action index spelling must be consistent")
        row = row.copy()
        row[1] = "CodePipeline.Pipeline.Stages[]." + ("Actions[]." if is_action else "") + field
        if not is_action or not field.startswith("Configuration"):
            result.append(row)
            previous_configuration = None
            continue
        key = field.removeprefix("Configuration.")
        if not field.startswith("Configuration.") or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise ValueError("CodePipeline Configuration must use Configuration.<Key> display rows")
        identity = stage, action
        if identity in configurations and previous_configuration != identity:
            raise ValueError("CodePipeline Configuration key rows must be contiguous per action")
        values = configurations.setdefault(identity, {})
        if key in values:
            raise ValueError(f"duplicate CodePipeline Configuration key: {key}")
        value = row[2]
        linked = re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", value)
        if not linked:
            if len(value) >= 2 and value[0] == value[-1] == "`":
                value = value[1:-1]
            if value.startswith(("{", "[", "!")) or "Fn::" in value or "](" in value or "\n" in value:
                raise ValueError("CodePipeline Configuration value must be a literal or a resource link, without CFN intrinsics")
        values[key] = value
        if identity not in configuration_rows:
            row[1] = CODEPIPELINE_CONFIGURATION
            configuration_rows[identity] = row
            result.append(row)
            row[3] = f"{key}: {row[3]}"
        else:
            configuration_rows[identity][3] += f" / {key}: {row[3]}"
        configuration_rows[identity][2] = "`" + json.dumps(values, ensure_ascii=False, separators=(",", ":")) + "`"
        previous_configuration = identity
    for actions in stages.values():
        if len(actions) > 1 and not all(actions.values()):
            raise ValueError("CodePipeline multiple actions must use Actions[N]")
        if len(actions) == 1 and any(actions.values()):
            raise ValueError("CodePipeline single action must use Actions without an index")
    return result


GLUE_ARGUMENTS = {"DefaultArguments", "NonOverridableArguments"}
GLUE_ARGUMENT_SOURCE = re.compile(r"^<!-- glue-arguments-source: (.+?) --> ")


def glue_argument_rows(rows: list[list[str]], kind: str) -> list[list[str]]:
    from policy_tables import code, literal, unique_object, invalid_constant

    result = []
    for identity, prop, value, comment in rows:
        if kind != "Glue.Job" or prop not in GLUE_ARGUMENTS:
            result.append([identity, prop, value, comment])
            continue
        arguments = json.loads(literal(value), object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(arguments, dict) or any(not isinstance(item, str) for item in arguments.values()):
            raise ValueError(f"Glue.Job.{prop} must be a string object")
        if not arguments:
            result.append([identity, prop, value, comment])
            continue
        source = json.dumps([prop, value, len(arguments)], ensure_ascii=True)
        for char in "|<>":
            source = source.replace(char, f"\\u{ord(char):04x}")
        for offset, (key, item) in enumerate(arguments.items()):
            field = html.escape(prop + "[" + json.dumps(key, ensure_ascii=False) + "]", quote=False)
            field = field.replace("|", "&#124;").replace("`", "&#96;")
            marker = f"<!-- glue-arguments-source: {source} --> " if offset == 0 else ""
            result.append([identity, field, code(item), marker + comment])
    return result


def restored_glue_argument_rows(rows: list[list[str]], kind: str) -> list[list[str]]:
    result, index = [], 0
    while index < len(rows):
        identity, prop, value, comment = rows[index]
        marker = GLUE_ARGUMENT_SOURCE.match(comment)
        if marker:
            source = json.loads(marker[1])
            if (kind != "Glue.Job" or not isinstance(source, list) or len(source) != 3 or
                    not all(isinstance(item, str) for item in source[:2]) or source[0] not in GLUE_ARGUMENTS or
                    type(source[2]) is not int or not 1 <= source[2] <= len(rows) - index):
                raise ValueError("invalid Glue argument source row or count")
            original = [identity, *source[:2], comment[marker.end():]]
            expected = glue_argument_rows([original], kind)
            if [row[1:] for row in expected] != [row[1:] for row in rows[index:index + source[2]]]:
                raise ValueError("Glue argument keys, values or comments differ from their source row")
            result.append(original)
            index += source[2]
        else:
            if "<!-- glue-arguments-source:" in comment or (kind == "Glue.Job" and any(prop.startswith(field + "[") for field in GLUE_ARGUMENTS)):
                raise ValueError("Glue argument display requires a valid source marker")
            result.append(rows[index])
            index += 1
    return result


