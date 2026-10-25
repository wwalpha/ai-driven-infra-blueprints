"""design/services/glue.py display and restoration."""

import html
import json

from model.core import literal
from utils.json_format import policy_json

from design.common import code
from design.services.definitions.glue import GLUE_ARGUMENT_SOURCE, GLUE_ARGUMENTS


def glue_argument_rows(rows: list[list[str]], kind: str) -> list[list[str]]:
    result = []
    for identity, prop, value, comment in rows:
        if kind != "Glue.Job" or prop not in GLUE_ARGUMENTS:
            result.append([identity, prop, value, comment])
            continue
        arguments = policy_json(literal(value))
        if not isinstance(arguments, dict) or any(
            not isinstance(item, str) for item in arguments.values()
        ):
            raise ValueError(f"Glue.Job.{prop} must be a string object")
        if not arguments:
            result.append([identity, prop, value, comment])
            continue
        source = json.dumps([prop, value, len(arguments)], ensure_ascii=True)
        for char in "|<>":
            source = source.replace(char, f"\\u{ord(char):04x}")
        for offset, (key, item) in enumerate(arguments.items()):
            field = html.escape(
                prop + "[" + json.dumps(key, ensure_ascii=False) + "]", quote=False
            )
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
            if (
                kind != "Glue.Job"
                or not isinstance(source, list)
                or len(source) != 3
                or not all(isinstance(item, str) for item in source[:2])
                or source[0] not in GLUE_ARGUMENTS
                or type(source[2]) is not int
                or not 1 <= source[2] <= len(rows) - index
            ):
                raise ValueError("invalid Glue argument source row or count")
            original = [identity, *source[:2], comment[marker.end() :]]
            expected = glue_argument_rows([original], kind)
            if [row[1:] for row in expected] != [
                row[1:] for row in rows[index : index + source[2]]
            ]:
                raise ValueError(
                    "Glue argument keys, values or comments differ from their source row"
                )
            result.append(original)
            index += source[2]
        else:
            if "<!-- glue-arguments-source:" in comment or (
                kind == "Glue.Job"
                and any(prop.startswith(field + "[") for field in GLUE_ARGUMENTS)
            ):
                raise ValueError("Glue argument display requires a valid source marker")
            result.append(rows[index])
            index += 1
    return result
