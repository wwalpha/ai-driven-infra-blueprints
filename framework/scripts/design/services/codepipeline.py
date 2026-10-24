"""design/services/codepipeline.py display and restoration."""

import json
import re

from model.core import LINK, literal
from utils.json_format import policy_json

from design.services.definitions.codepipeline import (
    CODEPIPELINE_CONFIGURATION,
    CODEPIPELINE_STAGE,
)


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
            # Authored stage rows may put Name before or after their action rows.
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
        config = policy_json(literal(value))
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
