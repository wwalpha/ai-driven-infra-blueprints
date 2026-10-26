"""Reference discovery from raw properties; never a Model quality verdict."""

import re
from types import MappingProxyType

from utils.json_format import strict_json

import model.identity as identity
from model.core import structural_entries
from model.format import KEY, PART, parse
from model.reference_nodes import nodes

TYPED = re.compile(r'"\$modelRef"\s*:')


def extract(snapshot, *, strict=False):
    links, logical, errors = set(), set(), {}
    for key, value in snapshot.authoritative.items():
        if not key.startswith(
            ("desired.row.", "desired.resource.")
        ) or not key.endswith((".value", ".document", ".parentReference")):
            continue
        diagnostics = candidates(value, snapshot.scope, links, logical, strict=strict)
        if diagnostics:
            errors[key] = diagnostics
    for number, spec in structural_entries(
        snapshot.authoritative, "desired.reference."
    ):
        scope = spec.get("producerScope", "")
        if scope:
            links.add(scope)
        if (
            not scope
            or not spec.get("consumerKey")
            or not spec.get("producerKind")
            or spec.get("producerKind") == "resource"
            and not spec.get("producerLogicalId")
            or spec.get("producerKind") == "stack"
            and not spec.get("producerId")
        ):
            errors.setdefault(
                spec.get("consumerKey", "desired.reference." + number), []
            ).append(
                {
                    "message": "incomplete declared producer reference",
                    "kind": "declaration",
                    **({"producerScope": scope} if scope else {}),
                    **(
                        {"targetLogicalId": spec["producerLogicalId"]}
                        if spec.get("producerLogicalId")
                        else {}
                    ),
                    **(
                        {"attribute": spec["property"].split(".", 2)[-1]}
                        if spec.get("property")
                        else {}
                    ),
                }
            )
    return links, logical, errors


def candidates(value, scope, links, logical, *, strict=False, uncertain=False):
    diagnostics = []
    for token in identity.reference_tokens(value):
        try:
            address = identity.parse_reference(token[0], scope)
        except ValueError as error:
            if strict:
                raise
            # These addresses cannot resolve to any producer in the Model tree.
            diagnostics.append(
                {"message": str(error), "kind": "link", "outsideModel": True}
            )
        else:
            links.add("/".join(address[:3]))
            if uncertain:
                diagnostics.append(
                    {
                        "message": "reference in unreadable or duplicate property",
                        "kind": "link",
                        "producerScope": "/".join(address[:3]),
                        "anchor": address[3],
                    }
                )
    raw = value.strip("`")
    for node in nodes(raw, errors=diagnostics):
        logical.add(node.logical_id)
        if uncertain:
            diagnostics.append(
                {
                    "message": "reference in unreadable or duplicate property",
                    "kind": "typed",
                    "targetLogicalId": node.logical_id,
                    "attribute": node.attribute,
                }
            )
    if TYPED.search(raw) or raw.lstrip().startswith(("{", "[")) and "\\u" in raw:
        try:
            strict_json(raw)
        except ValueError:
            diagnostics.append(
                {"message": "cannot parse JSON reference candidates", "kind": "typed"}
            )
    return diagnostics


def recover(base):
    """Recover independent records; uncertain candidates retain a blocking diagnostic."""
    values, errors = {}, {}
    for path, text in base.files.items():
        for line in text.splitlines():
            if (
                line.startswith(PART)
                and base.scope.path.parent / line[len(PART) :] not in base.files
            ):
                errors.setdefault(str(path), []).append(
                    {
                        "message": "reference candidates unavailable in missing Model part: "
                        + line[len(PART) :],
                        "kind": "unknown",
                    }
                )
        fragments = []
        for line in text.splitlines():
            if not fragments and (not line.strip() or line.startswith("#")):
                continue
            fragments.append(line)
            if line.endswith("\\"):
                continue
            raw = "\n".join(fragments)
            fragments = []
            recover_record(raw, path, base.scope, values, errors)
        if fragments:
            recover_record("\n".join(fragments), path, base.scope, values, errors)
    return base._replace(
        authoritative=MappingProxyType(values), values=MappingProxyType(values)
    ), errors


def recover_record(raw, path, scope, values, errors):
    if not raw.strip() or raw.startswith("#"):
        return
    key, separator, value = raw.partition("=")
    try:
        records = parse(raw, require_header=False).values
    except ValueError:
        records = {}
    if not records or any(key in values for key in records):
        diagnostics = candidates(
            value if separator else raw, scope, set(), set(), uncertain=True
        )
        if key.startswith("desired.reference."):
            diagnostics.append(
                {"message": "unreadable declared reference", "kind": "declaration"}
            )
        if diagnostics:
            errors.setdefault(key if separator else str(path), []).extend(diagnostics)
        if (
            separator
            and KEY.fullmatch(key)
            and key not in values
            and len(key.split(".")) >= 4
        ):
            values[key] = value.replace("\\\n", " ")
    else:
        values.update(records)


def possible(error, scope, scopes, identifiers):
    """Conservative shared scope/identity filter; attribute changes are checked later."""
    if error.get("outsideModel"):
        return False
    producer = error.get("producerScope")
    for address in scopes:
        parts = tuple(address.split("/"))
        if producer and tuple(producer.split("/")) != parts[: len(producer.split("/"))]:
            continue
        if (
            not producer
            and error.get("kind") not in {"link", "unknown"}
            and parts[:2] != (scope.environment, scope.target)
        ):
            continue
        logical = error.get("targetLogicalId")
        if not logical or not identifiers or (*parts[:2], logical) in identifiers:
            return True
    return False
