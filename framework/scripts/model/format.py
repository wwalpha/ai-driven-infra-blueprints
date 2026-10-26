"""Version 2 properties syntax. Scalars are text; only explicit JSON is parsed."""

import posixpath
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from utils.json_format import strict_json
from validation.diagnostics import InputValidationError

LINKS = re.compile(r"\[([^\]]+)\]\(([^)]*?)#([^)]+)\)")


def link_scope(environment, target, service, filename):
    """Resolve a saved Markdown address lexically inside the registered Model tree."""
    if not filename:
        return "/".join((environment, target, service))
    if filename.startswith("/") or "\\" in filename:
        raise InputValidationError(
            "direct Model reference is outside the Model tree: " + filename
        )
    relative = PurePosixPath(
        posixpath.normpath("/".join((environment, target, filename)))
    )
    if len(relative.parts) != 3 or ".." in relative.parts or relative.suffix != ".md":
        raise InputValidationError(
            "direct Model reference is outside the Model tree: " + filename
        )
    return "/".join((*relative.parts[:2], relative.stem))


FORMAT = "# model-format: 2"
INDEX = "# model-index: 2"
PART = "# part: "
LIMIT = 600
KEY = re.compile(r"[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class Record:
    key: str
    value: str
    start: int
    end: int
    line: int


@dataclass(frozen=True)
class Document:
    text: str
    records: tuple[Record, ...]

    @property
    def values(self):
        return {record.key: record.value for record in self.records}


def json_field(key, value):
    if key.endswith(".document"):
        return value, False
    if (
        key.endswith(".value")
        and value.startswith("`")
        and value[1:].lstrip().startswith(("{", "["))
    ):
        scalar = value[1:-1].strip() if value.endswith("`") else ""
        if re.fullmatch(r"\{\{resolve:[^{}\r\n]+\}\}", scalar) or re.fullmatch(
            r"\[[^\]\r\n]+\]\([^()\r\n]+\)", scalar
        ):
            return (
                None,
                False,
            )  # Existing CFn dynamic references and Markdown links remain scalars.
        return value[1:], True
    return None, False


def _outside_string(value):
    quoted, escaped = False, False
    for char in value:
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
    return not quoted


def input_json(text):
    """Parse a known authoritative JSON field, preserving proven syntax violations."""
    try:
        return strict_json(text)
    except ValueError as error:
        raise InputValidationError(str(error)) from error


def parse(text, *, require_header=True):
    if not isinstance(text, str):
        raise TypeError("properties must be UTF-8 text")
    lines = text.splitlines(keepends=True)
    if require_header and (not lines or lines[0].rstrip("\r\n") != FORMAT):
        raise InputValidationError("Model requires " + FORMAT)
    if any(
        line.startswith(("# model-format:", "# model-index:", PART))
        for line in lines[1:]
    ):
        raise InputValidationError(
            "unexpected Model format/index/part directive in data file"
        )
    result, seen, offset, index = [], set(), 0, 0
    while index < len(lines):
        raw = lines[index]
        line = raw.rstrip("\r\n")
        start, number = offset, index + 1
        offset += len(raw)
        index += 1
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or KEY.fullmatch(key) is None or key in seen:
            raise InputValidationError(
                f"invalid or duplicate model property at line {number}: {key}"
            )
        seen.add(key)
        body, ticked = json_field(key, value)
        if body is not None:
            fragments = []
            current = body
            while current.endswith("\\"):
                if not _outside_string(current[:-1]):
                    raise InputValidationError(
                        f"JSON continuation inside a string: {key}:{number}"
                    )
                fragments.append(current[:-1])
                if index >= len(lines):
                    raise InputValidationError("JSON continuation at EOF: " + key)
                raw = lines[index]
                current = raw.rstrip("\r\n")
                offset += len(raw)
                index += 1
                if not current.strip() or current.lstrip().startswith("#"):
                    raise InputValidationError(
                        "empty/comment JSON continuation: " + key
                    )
            fragments.append(current)
            body = " ".join(fragments)
            if ticked:
                if not body.endswith("`"):
                    raise InputValidationError("missing closing JSON backtick: " + key)
                body = body[:-1]
            parsed = input_json(body)
            if ticked and not isinstance(parsed, (dict, list)):
                raise InputValidationError(
                    "backtick JSON value must be an object or array: " + key
                )
            value = ("`" if ticked else "") + body + ("`" if ticked else "")
        result.append(Record(key, value, start, offset, number))
    return Document(text, tuple(result))


def owner(key, values):
    """One indivisible owning block; reference metadata belongs to its consumer."""
    fields = key.split(".")
    if len(fields) < 3:
        raise InputValidationError("invalid Model key: " + key)
    namespace, kind, identity = fields[:3]
    if namespace == "desired" and kind == "reference":
        consumer = values.get(f"desired.reference.{identity}.consumerKey")
        if consumer is None or consumer.startswith(("observed.", "desired.reference.")):
            raise InputValidationError(
                "reference has no valid consumerKey: " + identity
            )
        return owner(consumer, values)
    if kind in {"service", "deployment"}:
        return kind, "service"
    if kind == "row":
        resource, separator, _ = identity.rpartition("-")
        if not separator or f"desired.resource.{resource}.resourceType" not in values:
            raise InputValidationError("orphan row: " + identity)
        return "resource", resource
    return kind, identity


def validate_blocks(documents):
    values, locations, ownership = {}, {}, {}
    for path, document in documents.items():
        for record in document.records:
            if record.key in values:
                raise InputValidationError(
                    "duplicate Model key across parts: " + record.key
                )
            values[record.key] = record.value
            locations[record.key] = (path, record.line)
    for path, document in documents.items():
        for record in document.records:
            block = owner(record.key, values)
            if ownership.setdefault(block, path) != path:
                raise InputValidationError(
                    "Model block is split across parts: " + "/".join(block)
                )
    return values, locations


def serialize(values):
    """Serialize authoritative fields only, preserving explicit scalar spelling."""
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in values.items()
    ):
        raise ValueError("Model fields must be strings")
    text = (
        FORMAT
        + "\n"
        + "".join(key + "=" + value + "\n" for key, value in values.items())
    )
    if parse(text).values != values:
        raise ValueError("Model fields cannot be serialized losslessly")
    return text


def split(path, values, *, limit=LIMIT):
    """Initial conversion only. A resource larger than the limit owns a whole part."""
    blocks = {}
    for key, value in values.items():
        blocks.setdefault(owner(key, values), {})[key] = value
    if len(serialize(values).splitlines()) <= limit:
        return {path: serialize(values)}
    groups, group = [], {}
    for block in blocks.values():
        if group and len(serialize({**group, **block}).splitlines()) > limit:
            groups.append(group)
            group = {}
        group.update(block)
    if group:
        groups.append(group)
    output = {
        path.with_suffix("") / f"part-{index:03d}.properties": serialize(group)
        for index, group in enumerate(groups, 1)
    }
    output[path] = (
        FORMAT
        + "\n"
        + INDEX
        + "\n"
        + "".join(
            PART + part.relative_to(path.parent).as_posix() + "\n" for part in output
        )
    )
    return output


def patch(document, changes):
    """Patch explicit keys and insert new Row metadata locally, without reflow."""
    result, remaining, cursor = [], dict(changes), 0
    newline = "\r\n" if "\r\n" in document.text else "\n"
    values = {**document.values, **changes}
    insertions = {}
    for key, value in changes.items():
        if key in document.values or value is None:
            continue
        consumer = key
        if key.startswith("desired.reference."):
            consumer = values.get(key.rsplit(".", 1)[0] + ".consumerKey")
            if not consumer:
                raise ValueError("new reference metadata requires its consumerKey")
        fields = consumer.split(".")
        prefix = ".".join(fields[:3]) + "." if len(fields) >= 4 else None
        row = fields[2] if len(fields) >= 4 and fields[1] == "row" else None
        nearby = [
            record.end
            for record in document.records
            if prefix
            and record.key.startswith(prefix)
            or row
            and record.key.startswith(
                ("desired.row." + row + ".", "observed.row." + row + ".")
            )
        ]
        position = max(nearby, default=len(document.text))
        insertions.setdefault(position, []).append(key + "=" + value + newline)
        remaining.pop(key)
    for record in document.records:
        result.append(document.text[cursor : record.start])
        if record.key in remaining:
            value = remaining.pop(record.key)
            if value is not None:
                result.append(record.key + "=" + value + newline)
        else:
            result.append(document.text[record.start : record.end])
        cursor = record.end
        if cursor in insertions:
            if result and not result[-1].endswith(("\r", "\n")):
                result.append(newline)
            result.extend(insertions.pop(cursor))
    result.append(document.text[cursor:])
    for position, lines in insertions.items():
        if position != len(document.text):
            raise ValueError("new Model field insertion has no owning source location")
        if result and result[-1] and not result[-1].endswith(("\r", "\n")):
            result.append(newline)
        result.extend(lines)
    text = "".join(result)
    expected = {key: value for key, value in values.items() if value is not None}
    if parse(text).values != expected:
        raise ValueError("Model edit cannot be represented losslessly")
    return text


JSON_LINK = re.compile(r"^\[[^\]]+\]\(([^)#]+\.json)\)$")

RESOURCE_LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")

REFERENCE_NAME_SUFFIXES = (
    ".Name",
    ".RoleName",
    ".LogGroupName",
    ".BucketName",
    ".AliasName",
    ".GroupName",
    ".InstanceProfileName",
    ".FunctionName",
    ".TrailName",
    ".QueueName",
    ".UserName",
    ".RepositoryName",
)


FORMAT_FIELDS = {"modelFormat": 2, "snapshotVersion": 2, "referenceMeaningVersion": 1}


def require_format(value, version, label):
    expected = {"version": version, **FORMAT_FIELDS}
    if not isinstance(value, dict) or any(
        type(value.get(key)) is not int or value[key] != item
        for key, item in expected.items()
    ):
        raise ValueError(
            "IMPORT " + label + " format is incompatible; requires " + str(expected)
        )
