"""Position-bound Resource links for display only; never an execution projection."""

import html
import json
import re
from dataclasses import dataclass
from functools import partial

import json_intrinsics
from design.services import reference_labels
from design.services.definitions.registry import POLICY_FORMATS
from utils.reference_contracts import ARN_SHAPES

import model.files as files
import model.identity as identity
import model.projection as projection
import model.references as references
import model.render as render
import model.sources as sources
from model.core import LINK, literal
from model.reference_nodes import (
    context_at,
    nodes,
    project,
    receiving_property,
    reference_document,
    resolve,
)


@dataclass(frozen=True)
class Position:
    row_id: str
    source_field: str
    pointer: str


@dataclass(frozen=True)
class Reference:
    position: Position
    value: object
    link: str | None


def input_strings(value):
    """Include decoded JSON strings so authored escapes cannot impersonate markers."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from input_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from input_strings(child)
    elif isinstance(value, str):
        yield value
        raw = literal(value)
        if raw.lstrip().startswith(("{", "[")):
            try:
                decoded = json.loads(raw)
            except ValueError:
                return
            yield from input_strings(decoded)


class Presentation:
    """Carry typed positions through existing, lossless service display transforms."""

    def __init__(
        self, values, path, root, *, reference_values=None, service_presentation=None
    ):
        self.values, self.root = values, root
        self.service_presentation = service_presentation
        self.scope = sources.scope_for(
            (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
                ".properties"
            )
        )
        self.resolver = projection.reference_resolver(
            values if reference_values is None else reference_values, self.scope, root
        )
        self.references = {}
        for rows in files.resource_row_index(values).values():
            for rid, row in rows:
                prop = row["property"]
                for field in ("value", "document"):
                    if field not in row:
                        continue
                    raw, structured = references._json(
                        f"desired.row.{rid}.{field}", row[field]
                    )
                    if not structured:
                        continue
                    resolutions, diagnostics = projection.document_references(
                        raw,
                        resolver=self.resolver,
                        scope=self.scope,
                        property_name=prop,
                        model_key=f"desired.row.{rid}.{field}",
                        context=projection.reference_context_for(
                            values, rid, row, raw, "", root
                        ),
                    )
                    row_nodes = list(nodes(raw, errors=[]))
                    if self.service_presentation:
                        self.service_presentation.validate_references(
                            prop, field, raw, row_nodes, diagnostics
                        )
                    for node in row_nodes:
                        result = resolutions.get(node)
                        position = Position(rid, field, node.pointer)
                        self.references[position] = Reference(
                            position,
                            projection._display_document_value(
                                resolutions, self.resolver, self.scope, root, node
                            ),
                            self.link(
                                node,
                                position=position,
                                field=receiving_property(prop, node.pointer),
                                property_name=prop,
                                context=context_at(
                                    raw,
                                    prop,
                                    node.pointer,
                                    projection.reference_context_for(
                                        values, rid, row, raw, "", root
                                    ),
                                ),
                                result=result,
                            ),
                        )
                    if self.service_presentation:
                        self.service_presentation.require_reference_links(
                            prop,
                            field,
                            row_nodes,
                            [
                                self.references[Position(rid, field, node.pointer)].link
                                for node in row_nodes
                            ],
                            diagnostics,
                        )

        inputs = tuple(input_strings(values)) + tuple(
            ref.link for ref in self.references.values() if ref.link
        )
        prefix = "blueprint-reference-"
        while any(prefix in text for text in inputs):
            prefix += "x"
        self.markers = {
            pos: ref.link[:1] + f"{prefix}{index}-" + ref.link[1:]
            for index, (pos, ref) in enumerate(self.references.items())
            if ref.link
        }
        self.tokens = tuple(
            f"{prefix}{index}-"
            for index, ref in enumerate(self.references.values())
            if ref.link
        )
        self.marker_links = {
            variant: self.references[pos].link
            for pos, marker in self.markers.items()
            for variant in (marker, html.escape(marker, quote=False))
        }

    def link(self, node, *, position, result=None, **contract):
        try:
            snapshot, number, resource, _ = resolve(
                node, self.scope, self.resolver, **contract
            )
            terminal = next(
                (
                    part
                    for part in reversed(node.pointer.split("/"))
                    if not part.isdigit()
                ),
                "",
            )
            policy_document = (
                position.source_field == "document"
                and POLICY_FORMATS.get(contract.get("property_name"))
                in {"statement", "wrapped-statement"}
            )
            policy_resource = policy_document and terminal in {
                "Resource",
                "NotResource",
            }
            if (
                snapshot.scope == self.scope
                and number == position.row_id.rpartition("-")[0]
                and not policy_resource
            ):
                return None
            name, _, _ = render.resource_presentation(
                snapshot.authoritative,
                number,
                resource,
                self.root,
                scope=snapshot.scope,
                projection=True,
            )
            displayed = projection._display_document_value(
                {node: result}, self.resolver, self.scope, self.root, node
            )
            kind = resource["resourceType"]
            attribute = projection.reference_attribute(kind, node.attribute)
            field = projection.RETURN_ATTRIBUTE_PROPERTIES.get(
                (kind, attribute), attribute
            )
            identifiers = projection.identifier_outputs(self.root).get(kind, ())
            shape = ARN_SHAPES.get(kind)
            components = shape[0] if shape else ()
            components = (components,) if isinstance(components, str) else components
            identifier_arn = (
                shape is not None
                and attribute == projection.reference_attribute(kind, "Arn")
                and any(kind + "." + part in identifiers for part in components)
                and not (
                    policy_document
                    and result is not None
                    and result.status == "resolved"
                    and name not in {None, kind, resource["logicalId"]}
                )
            )
            if (kind + "." + field in identifiers or identifier_arn) and isinstance(
                displayed, str
            ):
                name = displayed
            name = reference_labels.select(
                self.values,
                position,
                node,
                self.scope,
                self.resolver,
                resource,
                attribute,
                name,
                displayed,
            )
            if self.service_presentation:
                name = self.service_presentation.reference_label(
                    contract.get("property_name"),
                    position.source_field,
                    name,
                    displayed,
                    snapshot,
                    number,
                )
            if (
                not name
                or literal(name).lower()
                in {"unset", "unresolved", "tbd", "todo", "未確定"}
                or literal(name).startswith("arn:")
                and (result is None or result.status != "resolved")
            ):
                return None
            identity.display_anchor(resource)
            link = identity.address(
                snapshot.scope, resource, consumer_scope=self.scope, label=literal(name)
            )
            identity.select_anchor(
                identity.anchor_index(snapshot.authoritative), resource["anchor"], node
            )
            return link
        except (ValueError, KeyError):
            return None

    def node_value(self, row_id, field, node):
        position = Position(row_id, field, node.pointer)
        reference = self.references.get(position)
        return self.markers.get(
            position,
            reference.value if reference is not None else reference_document(node),
        )

    def document(self, row_id, field, baseline):
        selected = [
            ref
            for pos, ref in self.references.items()
            if (pos.row_id, pos.source_field) == (row_id, field) and ref.link
        ]
        if not selected:
            return baseline
        key = f"desired.row.{row_id}.{field}"
        raw, _ = references._json(key, self.values[key])
        prop = self.values[f"desired.row.{row_id}.property"]
        projected = projection.execution_document(
            raw, self.root, property_name=prop, scope=self.scope
        )
        marked = project(projected, partial(self.node_value, row_id, field))
        marked = reference_labels.document(
            self.values,
            row_id,
            field,
            raw,
            marked,
            selected,
            self.markers,
            self.scope,
            self.resolver,
        )
        if any(
            (pos.row_id, pos.source_field) == (row_id, field)
            and "/Fn::" in pos.pointer
            and ref.link
            for pos, ref in self.references.items()
        ):
            return marked
        # Display links are not policy/runtime values and must not enter those validators.
        return json_intrinsics.project_document(
            marked, property_name=prop, model_path=self.scope.path
        )

    def rows(self, rows):
        result = []
        for rid, prop, value, comment in rows:
            if any(
                pos.row_id == rid and pos.source_field == "value" and ref.link
                for pos, ref in self.references.items()
            ):
                marked = self.document(rid, "value", None)
                text = (
                    marked
                    if isinstance(marked, str)
                    else json.dumps(marked, ensure_ascii=False)
                )
                value = text if LINK.fullmatch(text) else "`" + text + "`"
            result.append([rid, prop, value, comment])
        return result

    def cell(self, original, marked):
        original_parts = re.split(r"(<!--.*?-->)", original)
        marked_parts = re.split(r"(<!--.*?-->)", marked)
        if len(original_parts) != len(marked_parts):
            raise ValueError("reference presentation changed comment structure")
        return "".join(
            self.unmark(displayed)
            if source.startswith("<!--")
            else self.fragment(displayed)
            if any(marker in displayed for marker in self.marker_links)
            else source
            for source, displayed in zip(original_parts, marked_parts, strict=True)
        )

    def unmark(self, value):
        for token in self.tokens:
            value = value.replace(token, "")
        return value

    def fragment(self, value):
        pattern = "(" + "|".join(map(re.escape, self.marker_links)) + ")"
        result = []
        for span in re.split(r"(`[^`]*`|<code>.*?</code>)", value):
            if not any(marker in span for marker in self.marker_links):
                result.append(span)
                continue
            opening, closing = (
                ("`", "`")
                if span.startswith("`") and span.endswith("`")
                else ("<code>", "</code>")
                if span.startswith("<code>") and span.endswith("</code>")
                else ("", "")
            )
            body = span[len(opening) : -len(closing)] if closing else span
            result.append(
                "".join(
                    self.marker_links[part]
                    if part in self.marker_links
                    else opening + part + closing
                    if part
                    else ""
                    for part in re.split(pattern, body)
                )
            )
        return "".join(result)

    def lines(self, baseline, marked):
        if len(baseline) != len(marked):
            raise ValueError("reference presentation changed display structure")
        result = []
        for original, displayed in zip(baseline, marked, strict=True):
            if not original.startswith("|"):
                result.append(original)
                continue
            cells = displayed.split("|")
            original_cells = original.split("|")
            if len(cells) != len(original_cells):
                raise ValueError("reference presentation changed table structure")
            result.append(
                "|".join(
                    self.cell(source, cell)
                    for source, cell in zip(original_cells, cells, strict=True)
                )
            )
        return result
