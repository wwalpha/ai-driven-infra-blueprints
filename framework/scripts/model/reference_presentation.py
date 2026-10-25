"""Position-bound Resource links for display only; never an execution projection."""

import html
import json
import re
from dataclasses import dataclass
from functools import partial

import json_intrinsics

import model.files as files
import model.identity as identity
import model.projection as projection
import model.references as references
import model.render as render
import model.sources as sources
import model.validation as validation
from model.core import LINK, literal
from model.reference_nodes import nodes, project, receiving_property
from model.reference_values import reference_value


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

    def __init__(self, values, path, root):
        self.values, self.root = values, root
        self.scope = sources.scope_for(
            (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
                ".properties"
            )
        )
        self.resolver = projection.reference_resolver(values, self.scope, root)
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
                    occurrences = tuple(nodes(raw))
                    for node in occurrences:
                        result = reference_value(
                            self.resolver,
                            self.scope,
                            node,
                            field=receiving_property(prop, node.pointer),
                            property_name=prop,
                            context=validation.reference_context_for(
                                values, rid, row, raw, node.pointer, root
                            ),
                        )
                        position = Position(rid, field, node.pointer)
                        self.references[position] = Reference(
                            position,
                            result.value
                            if result.status == "resolved"
                            else result.status,
                            self.link(node) if result.status == "resolved" else None,
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

    def link(self, node):
        try:
            snapshot, number, resource = self.resolver.resolve_logical(
                node.logical_id, self.scope
            )
            name, _, _ = render.resource_presentation(
                snapshot.authoritative,
                number,
                resource,
                self.root,
                scope=snapshot.scope,
            )
            if (
                not name
                or literal(name).lower()
                in {"unset", "unresolved", "pending_deploy", "tbd", "todo", "未確定"}
                or literal(name).startswith("arn:")
            ):
                return None
            identity.display_anchor(resource)
            link = identity.address(
                snapshot.scope, resource, consumer_scope=self.scope, label=literal(name)
            )
            # Reuse the saved-anchor resolver to reject an ambiguous destination.
            self.resolver.resolve(link, self.scope)
            return link
        except (ValueError, KeyError):
            return None

    def node_value(self, row_id, field, node):
        position = Position(row_id, field, node.pointer)
        return self.markers.get(position, self.references[position].value)

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
