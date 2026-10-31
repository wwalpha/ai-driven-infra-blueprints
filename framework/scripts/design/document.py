"""Read-only Markdown snapshots shared within one fixed design validation phase.

Reference views retain validation_scope's selective parsing, including grouped
parents. An index must be discarded or explicitly invalidated after writes;
it never stores validation results or survives an invocation.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from functools import cached_property
from pathlib import Path
from threading import RLock

import model.display as _model_display
import model.files as _model_files
import model.format as _model_format
import model.identity as _model_identity
import model.projection as _imports_model_projection
import model.references as _model_references
import model.render as _model_render
import model.sources as _imports_model_sources
import validation_scope as _dependency_validation_scope
from model.core import SnapshotValues
from model.reference_nodes import parse
from task_contract_core import task_read_scope
from utils.aws_mappings import definition_root
from utils.input_cache import input_text, memoized
from validation.diagnostics import stable_id
from validation.findings import Findings, FindingsError

import design.array_display as _array_display
import design.layout as _dependency_design_layout
import design.services.ec2.security_groups as _dependency_security_group_tables
from design.layout_schema import (
    ANCHOR,
    CHILD,
    GROUPED,
    HEADER,
    RESOURCE,
    SavedIdentityError,
)
from design.services.definitions.codebuild import CODEBUILD_FORMAL_VARIABLE


class DisplayMismatchError(ValueError):
    """Saved presentation differs; positions are independent of validation routes."""

    def __init__(self, path, text, expected):
        self.positions, self.other_changes = display_differences(text, expected)
        super().__init__("Markdown differs from Model expected display: " + str(path))


def _display_rows(document):
    anchor, logical = "", ""
    identities = _dependency_design_layout.resource_logical_ids(document.splitlines())
    counts, result = Counter(), {}
    for number, line in enumerate(document.splitlines()):
        if match := ANCHOR.fullmatch(line):
            anchor = match[1]
            logical = identities.get(anchor, logical)
        cells = [
            cell.strip() for cell in re.findall(r"((?:\\.|[^\\|])*)\|", line.strip())
        ][1:]
        if len(cells) != 4 or not cells[0].isdigit():
            continue
        counts[anchor, cells[1]] += 1
        key = anchor, logical, cells[1], counts[anchor, cells[1]]
        result[key] = number, cells
    return result


def display_differences(text, expected):
    saved_rows, expected_rows = _display_rows(text), _display_rows(expected)
    saved_lines, expected_lines = text.splitlines(), expected.splitlines()
    normalized = list(saved_lines)
    positions = []
    for key in sorted(saved_rows.keys() & expected_rows.keys()):
        number, saved = saved_rows[key]
        _, wanted = expected_rows[key]
        if saved[2] == wanted[2]:
            continue
        anchor, logical, prop, occurrence = key
        positions.append(
            dict(
                resourceLogicalId=logical,
                anchor=anchor,
                property=prop,
                occurrence=occurrence,
                location=f"{anchor}/{prop}/{occurrence}",
                savedDisplay=saved[2],
                expectedDisplay=wanted[2],
            )
        )
        normalized[number] = normalized[number].replace(
            "| " + saved[2] + " |", "| " + wanted[2] + " |", 1
        )
    other = normalized != expected_lines
    if other:
        identities = _dependency_design_layout.resource_logical_ids(expected_lines)
        anchors, anchor = [], ""
        for line in expected_lines:
            anchors.append(anchor)
            if (match := ANCHOR.fullmatch(line)) and match[1] in identities:
                anchor = match[1]
        anchors.append(anchor)
        counts = Counter()
        for tag, start, end, first, last in SequenceMatcher(
            a=normalized, b=expected_lines, autojunk=False
        ).get_opcodes():
            if tag == "equal":
                continue
            # Adjacent changed lines are not evidence of a shared root cause.
            for offset in range(max(end - start, last - first)):
                anchor = anchors[min(first + offset, len(expected_lines))]
                saved = saved_lines[start + offset] if start + offset < end else ""
                display = (
                    expected_lines[first + offset] if first + offset < last else ""
                )
                token = stable_id([anchor, saved, display])
                counts[token] += 1
                positions.append(
                    dict(
                        resourceLogicalId=identities.get(anchor, ""),
                        anchor=anchor,
                        property="$document",
                        occurrence=counts[token],
                        location=f"{anchor}/document/{token}/{counts[token]}",
                        savedDisplay=saved,
                        expectedDisplay=display,
                    )
                )
    return sorted(positions, key=lambda item: item["location"]), other


def _saved_identity(document):
    lines = document.splitlines()
    children, headings, anchor = [], [], ""
    for line in lines:
        if match := ANCHOR.fullmatch(line):
            anchor = match[1]
        if match := CHILD.match(line):
            children.append((anchor, *match.groups()))
        if match := RESOURCE.fullmatch(line):
            headings.append((anchor, match[1]))
    return (
        _dependency_design_layout.resource_logical_ids(lines),
        sorted(children),
        sorted(headings),
    )


def require_saved_identity(text, expected):
    if _saved_identity(text) != _saved_identity(expected):
        raise SavedIdentityError(
            "Markdown Resource logicalId/anchor/ownership differs from Model"
        )


def _task_root(path, text, values, root, **kwargs):
    return _imports_model_sources.design_project_root(path) if values else None


@task_read_scope(root=_task_root)
@memoized
def model_reference_tables(path, text, values, root, *, check_document=True):
    """Prepare Model expectations; parsers bind formal rows after table equality."""
    source = values if isinstance(values, SnapshotValues) else SnapshotValues(values)
    if not source:
        return ()
    snapshots = _model_display.reference_rows(source).values()
    if not any(
        (check_document and item.references)
        or item.kind != "EC2.SecurityGroup"
        and any(
            (
                row[1] in _dependency_design_layout.LINKED_LIST_PROPERTIES
                or re.search(
                    r"\[(?:[1-9]\d*)?\]",
                    _array_display.array_template(row[1], item.kind, root),
                )
            )
            and (check_document or not row[1].startswith(CODEBUILD_FORMAL_VARIABLE))
            for row in item.rows
        )
        for item in snapshots
    ):
        return ()
    expected, tables = _model_reference_display(path, source, root)
    if text.splitlines() != expected.splitlines():
        require_saved_identity(text, expected)
        if check_document:
            raise DisplayMismatchError(path, text, expected)
    tables = _normalized_reference_tables(tables, expected, root)
    if not check_document:
        # A skipped document check never grants authority to mismatched table values.
        saved = resource_blocks(
            _dependency_security_group_tables.security_group_table_lines(
                _dependency_design_layout.resource_heading_lines(
                    resource_lines(text, source)
                ),
                root,
            )
        )
        tables = [
            table
            for table in tables
            if any(
                f'<a id="{table.anchor}"></a>' in block
                and any(
                    tuple(block[start : start + len(table.expected)]) == table.expected
                    and (
                        start + len(table.expected) == len(block)
                        or not block[start + len(table.expected)].startswith("|")
                    )
                    for start, line in enumerate(block)
                    if line == HEADER
                )
                for block in saved
            )
        ]
    return tuple(tables)


def _model_reference_display(
    path: Path,
    source: SnapshotValues,
    root: Path,
    *,
    reference_values: SnapshotValues | None = None,
) -> tuple[str, tuple[_model_display.ReferenceTable, ...]]:
    model_path = (
        path.parents[4] / "model" / path.relative_to(path.parents[4] / "docs/designs")
    ).with_suffix(".properties")
    findings = Findings(path.parents[4])
    if _model_references.codebuild_reference_errors(
        model_path, source, findings=findings
    ):
        raise FindingsError(findings)
    tables: list[_model_display.ReferenceTable] = []
    expected = _model_render.generate_markdown(
        path, source, root, reference_tables=tables, reference_values=reference_values
    )
    return expected, tuple(tables)


def _normalized_reference_tables(
    tables: tuple[_model_display.ReferenceTable, ...],
    expected: str,
    root: Path,
    *,
    reference_scope: tuple[Path, frozenset[str]] | None = None,
) -> tuple[_model_display.ReferenceTable, ...]:
    return tuple(
        _security_group_reference_table(
            table, expected, root, reference_scope=reference_scope
        )
        if table.resources[0].kind == "EC2.SecurityGroup"
        else table
        for table in tables
    )


def _resource_selections(
    source: SnapshotValues, groups: Mapping[str, set[str]]
) -> dict[str, SnapshotValues]:
    owned = {key: _model_format.owner(key, source) for key in source}
    parents = {
        member: parent for parent, members in groups.items() for member in members
    }
    selections: dict[str, dict[str, str]] = {parent: {} for parent in groups}
    for key, value in source.items():
        if key.startswith("desired.note."):
            continue
        if owned[key][0] == "resource":
            parent = parents.get(owned[key][1])
            targets = () if parent is None else (parent,)
        else:
            targets = groups
        for parent in targets:
            selections[parent][key] = value
    return {parent: SnapshotValues(values) for parent, values in selections.items()}


def resource_lines(text, values):
    """Exclude only the complete service suffix proven by the existing renderer."""
    lines = text.splitlines()
    notes = _model_render.service_note_markdown(values or {})
    suffix = (notes + "\n").splitlines()[1:]
    if notes and lines[-len(suffix) :] == suffix:
        return lines[: -len(suffix)]
    return lines


def resource_blocks(lines):
    """Keep saved Resource sections intact, including their identity metadata."""
    starts = []
    for index, line in enumerate(lines):
        if RESOURCE.fullmatch(line):
            start = index
            while start and (
                not lines[start - 1].strip()
                or ANCHOR.fullmatch(lines[start - 1])
                or lines[start - 1].startswith("<!-- resource-logical-id:")
            ):
                start -= 1
            starts.append(start)
    blocks = []
    for start, end in zip(starts, [*starts[1:], len(lines)], strict=False):
        block = lines[start:end]
        while block and not block[0]:
            block = block[1:]
        while block and not block[-1]:
            block = block[:-1]
        blocks.append(block)
    return blocks


def model_resource_groups(path, source):
    """Use Model ownership and grouped-parent addresses, never diagnostic prose."""
    _model_identity.resource_index(source)
    _model_files.resource_row_index(source)
    resources = dict(_model_display.entries(source, "desired.resource."))
    if not resources:
        raise ValueError("Resource ownership unavailable")
    anchors = {}
    for identity, resource in resources.items():
        anchor = _model_identity.display_anchor(resource)
        if anchor in anchors:
            raise ValueError("duplicate Model Resource anchor: " + anchor)
        anchors[anchor] = identity
    parents = {}
    for identity, resource in resources.items():
        if resource["resourceType"] not in GROUPED:
            continue
        parent = parse(resource.get("parentReference"))
        candidates = [
            rid
            for rid, item in resources.items()
            if item["logicalId"] == parent.logical_id
        ]
        if len(candidates) != 1:
            raise ValueError("grouped parent ownership unavailable: " + identity)
        parents[identity] = candidates[0]
    groups = {}
    for identity in resources:
        parent = identity
        seen = set()
        while parent in parents:
            if parent in seen:
                raise ValueError("cyclic grouped parent ownership: " + identity)
            seen.add(parent)
            parent = parents[parent]
        groups.setdefault(parent, set()).add(identity)
    return resources, groups


@task_read_scope(root=_task_root)
def model_resource_reference_tables(path, text, values, root):
    """Recover complete Resource displays after separating a proven service suffix."""
    source = values if isinstance(values, SnapshotValues) else SnapshotValues(values)
    resources, groups = model_resource_groups(path, source)
    lines = resource_lines(text, source)
    notes = _model_render.service_note_markdown(source)
    notes_separated = lines != text.splitlines()
    blocks = resource_blocks(_dependency_design_layout.resource_heading_lines(lines))
    saved = {}
    for block in blocks:
        identities = _dependency_design_layout.resource_logical_ids(block)
        if len(identities) != 1:
            if not identities and saved:
                # Keep an unowned heading in the preceding body instead of losing all recovery.
                next(reversed(saved.values()))[1].extend(["", *block])
                continue
            raise ValueError("Resource/Row display ownership unavailable: " + str(path))
        anchor, logical_id = next(iter(identities.items()))
        if anchor in saved:
            raise ValueError("duplicate saved Resource anchor: " + anchor)
        saved[anchor] = (logical_id, block)
    selections = _resource_selections(source, groups)
    results = []
    for parent in groups:
        resource = resources[parent]
        anchor = _model_identity.display_anchor(resource)
        selected = selections[parent]
        try:
            expected, tables = _model_reference_display(
                path, selected, root, reference_values=source
            )
            expected_blocks = resource_blocks(
                _dependency_design_layout.resource_heading_lines(expected.splitlines())
            )
            if (
                len(expected_blocks) != 1
                or anchor not in saved
                or saved[anchor][0] != resource["logicalId"]
            ):
                raise ValueError(
                    "Markdown Resource logicalId/anchor differs from Model: " + anchor
                )
            actual, wanted = saved[anchor][1], expected_blocks[0]
            if actual != wanted:
                if notes and anchor == next(reversed(saved)) and not notes_separated:
                    if actual[: len(wanted)] == wanted:
                        raise ValueError(
                            "Service note/Resource display boundary unavailable: "
                            + anchor
                        )
                    if notes:
                        # Report proven body differences without attributing an unknown suffix.
                        actual = actual[: len(wanted)]
                saved_text, expected_text = (
                    "\n".join(actual),
                    "\n".join(wanted),
                )
                require_saved_identity(saved_text, expected_text)
                raise DisplayMismatchError(path, saved_text, expected_text)
            results.append(
                (anchor, _normalized_reference_tables(tables, expected, root), None)
            )
        except (OSError, ValueError) as error:
            results.append((anchor, None, error))
    if set(saved) != {_model_identity.display_anchor(resources[rid]) for rid in groups}:
        raise ValueError("Markdown Resource groups differ from Model: " + str(path))
    return results


def _security_group_reference_table(
    table: _model_display.ReferenceTable,
    document: str,
    root: Path,
    *,
    reference_scope: tuple[Path, frozenset[str]] | None = None,
) -> _model_display.ReferenceTable:
    """Match the parser's existing horizontal-rule normalization, including sources."""
    start = document.index(f'<a id="{table.anchor}"></a>')
    table_start = document.index("\n".join(table.expected), start)
    table_end = table_start + len("\n".join(table.expected))
    normalized = []
    for rows in (table.expected, table.baseline, table.semantic):
        candidate = document[:table_start] + "\n".join(rows) + document[table_end:]
        lines = candidate.splitlines()
        if reference_scope is not None:
            path, fragments = reference_scope
            # Apply the same parent/child selection before expanding every Model projection.
            lines = _dependency_validation_scope.reference_lines(
                path,
                fragments,
                lines=_dependency_design_layout.resource_heading_lines(lines),
            )
        lines = _dependency_security_group_tables.security_group_table_lines(
            lines, root
        )
        anchor = lines.index(f'<a id="{table.anchor}"></a>')
        first = lines.index(HEADER, anchor)
        last = first + 2
        while last < len(lines) and lines[last].startswith("|"):
            last += 1
        normalized.append(tuple(lines[first:last]))
    return replace(
        table, expected=normalized[0], baseline=normalized[1], semantic=normalized[2]
    )


def _require_reference_tables(
    path: Path,
    lines: tuple[str, ...],
    tables: tuple[_model_display.ReferenceTable, ...],
    root: Path,
) -> None:
    normalized = _dependency_security_group_tables.security_group_table_lines(
        list(lines), root
    )
    blocks = resource_blocks(normalized)
    for table in tables:
        block = next(
            (block for block in blocks if f'<a id="{table.anchor}"></a>' in block), []
        )
        start = next(
            (index for index, line in enumerate(block) if line == HEADER), len(block)
        )
        end = start + 1
        while end < len(block) and block[end].startswith("|"):
            end += 1
        actual = tuple(block[start:end])
        if actual != table.expected:
            # Preserve canonical display diagnostics even when dependent link semantics cannot run.
            prefix = [
                f"<!-- resource-logical-id: {table.resources[0].logical_id} -->",
                f'<a id="{table.anchor}"></a>',
                f"### {table.resources[0].kind}: reference",
            ]
            raise DisplayMismatchError(
                path,
                "\n".join([*prefix, *actual]),
                "\n".join([*prefix, *table.expected]),
            )


@dataclass(frozen=True)
class DesignView:
    """A selected set of lines; callers treat parser outputs as read-only."""

    lines: tuple[str, ...]
    root: Path | None = field(default=None, repr=False, compare=False)
    bound_anchors: dict[tuple[str, str], str] = field(
        default_factory=dict, repr=False, compare=False
    )
    modes: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    reference_tables: tuple = field(default=(), repr=False, compare=False)
    document: object = field(default=None, repr=False, compare=False)
    _lock: object = field(default_factory=RLock, repr=False, compare=False)

    @cached_property
    def _logical_ids(self) -> dict[str, str]:
        return resource_logical_ids(list(self.lines))

    @property
    def logical_ids(self) -> dict[str, str]:
        with self._lock:
            return self._logical_ids

    @cached_property
    def _expanded(self) -> tuple[tuple[str, ...], dict[str, dict]]:
        lines, children = expanded_design(
            list(self.lines),
            logical_ids=self.logical_ids,
            bound_anchors=self.bound_anchors,
            root=self.root,
            modes=self.modes,
            reference_tables=self.semantic_reference_tables,
        )
        return tuple(lines), children

    @property
    def expanded(self) -> tuple[tuple[str, ...], dict[str, dict]]:
        with self._lock:
            return self._expanded

    @cached_property
    def _display_lines(self) -> tuple[str, ...]:
        return tuple(
            _dependency_design_layout.expanded_display_rows(
                _dependency_security_group_tables.security_group_table_lines(
                    list(self.lines), self.root
                ),
                self.root,
                modes=self.modes,
                reference_tables=self.semantic_reference_tables,
            )
        )

    @property
    def display_lines(self) -> tuple[str, ...]:
        with self._lock:
            return self._display_lines

    @property
    def semantic_reference_tables(self):
        return (
            self.document.reference_tables
            if self.document is not None
            else self.reference_tables
        )


@dataclass(frozen=True)
class DesignDocument:
    path: Path
    text: str
    root: Path | None = None
    _views: dict[frozenset[str] | None, DesignView] = field(
        default_factory=dict, repr=False, compare=False
    )
    _reference_views: dict[tuple[str, ...], DesignView] = field(
        default_factory=dict, repr=False, compare=False
    )
    _parses: dict[tuple[str, ...], DesignView] = field(
        default_factory=dict, repr=False, compare=False
    )
    _lock: object = field(default_factory=RLock, repr=False, compare=False)

    source: Mapping[str, str] | None = field(default=None, repr=False, compare=False)
    check_display: bool = True

    @cached_property
    def lines(self) -> tuple[str, ...]:
        return tuple(self.text.splitlines())

    @cached_property
    def resource_lines(self) -> tuple[str, ...]:
        return tuple(resource_lines(self.text, self.model_values))

    @cached_property
    def anchors(self) -> frozenset[str]:
        return frozenset(ANCHOR.findall(self.text))

    @cached_property
    def visible_text(self) -> str:
        return re.sub(r"<!--.*?-->", "", self.text, flags=re.DOTALL)

    def _view(self, lines: list[str] | tuple[str, ...]) -> DesignView:
        lines = tuple(lines)
        with self._lock:
            if lines not in self._parses:
                bound_resource_anchors = (
                    _imports_model_projection.bound_resource_anchors
                )
                self._parses[lines] = DesignView(
                    lines,
                    self.root,
                    bound_resource_anchors(self.path)
                    if self.model_values is None
                    and any(line.startswith("### ") for line in lines)
                    else {
                        (
                            resource["resourceType"],
                            resource["logicalId"],
                        ): _model_identity.display_anchor(resource)
                        for _, resource in _model_display.entries(
                            self.model_values or {}, "desired.resource."
                        )
                    },
                    self.modes,
                    document=self,
                )
            return self._parses[lines]

    @cached_property
    def model_values(self):
        model_root = (
            self.path.parents[4]
            if len(self.path.parents) >= 5
            and self.path.parents[2].name == "designs"
            and self.path.parents[3].name == "docs"
            else None
        )
        values = self.source
        if values is None and model_root is not None:
            load_model = _imports_model_sources.load_model
            model_exists = _imports_model_sources.model_exists
            model = (
                model_root
                / "model"
                / self.path.relative_to(model_root / "docs/designs")
            ).with_suffix(".properties")
            if model_exists(model):
                values = load_model(model).values
        return (
            (values if isinstance(values, SnapshotValues) else SnapshotValues(values))
            if values is not None
            else None
        )

    @cached_property
    def modes(self):
        return _dependency_design_layout.resource_modes(
            self.resource_lines, self.model_values
        )

    @cached_property
    def reference_tables(self):
        return model_reference_tables(
            self.path,
            self.text,
            tuple((self.model_values or {}).items()),
            self.root or definition_root(self.path.parent),
            check_document=self.check_display,
        )

    @property
    def raw(self) -> DesignView:
        return self._view(self.resource_lines)

    def view(self, fragments: frozenset[str] | None = None) -> DesignView:
        # Serialize lazy construction only; existing validation workers remain unchanged.
        with self._lock:
            key = fragments
            if key not in self._views:
                if fragments is not None:
                    lines = _dependency_validation_scope.reference_lines(
                        self.path, fragments, lines=list(self.headings.lines)
                    )
                else:
                    lines = _dependency_design_layout.resource_heading_lines(
                        list(self.resource_lines)
                    )
                self._views[key] = self._view(lines)
            return self._views[key]

    def reference_view(self, fragments: frozenset[str]) -> DesignView:
        """Bind only referenced Resource tables to this immutable saved snapshot."""
        with self._lock:
            lines = tuple(
                _dependency_validation_scope.reference_lines(
                    self.path,
                    fragments,
                    lines=_dependency_design_layout.resource_heading_lines(
                        list(self.resource_lines)
                    ),
                )
            )
            if lines not in self._reference_views:
                root = self.root or definition_root(self.path.parent)
                source = self.model_values
                selected = source
                tables: tuple[_model_display.ReferenceTable, ...] = ()
                if source:
                    anchors = set(ANCHOR.findall("\n".join(lines)))
                    identities = {
                        identity
                        for identity, resource in _model_display.entries(
                            source, "desired.resource."
                        )
                        if _model_identity.display_anchor(resource) in anchors
                    }
                    selected = _resource_selections(source, {"reference": identities})[
                        "reference"
                    ]
                    # Ownership checks and rendering see only the selected group, including parents.
                    model_resource_groups(self.path, selected)
                    expected, tables = _model_reference_display(
                        self.path, selected, root, reference_values=source
                    )
                    tables = _normalized_reference_tables(
                        tables, expected, root, reference_scope=(self.path, fragments)
                    )
                    _require_reference_tables(self.path, lines, tables, root)
                self._reference_views[lines] = DesignView(
                    lines,
                    root,
                    bound_anchors={
                        (
                            resource["resourceType"],
                            resource["logicalId"],
                        ): _model_identity.display_anchor(resource)
                        for _, resource in _model_display.entries(
                            selected or {}, "desired.resource."
                        )
                    },
                    modes=_dependency_design_layout.resource_modes(
                        list(lines), selected
                    ),
                    reference_tables=tables,
                )
            return self._reference_views[lines]

    @property
    def headings(self) -> DesignView:
        return self.view()


class DesignIndex:
    """Path -> immutable text snapshot; explicitly scoped to a read-only phase."""

    def __init__(self, root: Path | None = None, *, check_display=True) -> None:
        self.root = root
        self.check_display = check_display
        self._documents: dict[Path, DesignDocument] = {}
        self._lock = RLock()

    def get(
        self, path: Path, *, text: str | None = None, values=None
    ) -> DesignDocument:
        path = path.resolve()
        with self._lock:
            if path not in self._documents:
                document = DesignDocument(
                    path,
                    input_text(path, encoding="utf-8") if text is None else text,
                    self.root or definition_root(path.parent),
                    check_display=self.check_display,
                    source=(
                        values
                        if isinstance(values, SnapshotValues)
                        else SnapshotValues(values)
                    )
                    if values is not None
                    else None,
                )
                # Construct these cheap text views once before sharing across workers.
                _ = document.lines, document.anchors, document.visible_text
                self._documents[path] = document
            document = self._documents[path]
            if values is not None and (document.model_values or {}) != values:
                raise ValueError("DesignIndex cannot mix Model snapshots: " + str(path))
            return document

    def invalidate(self, path: Path) -> None:
        """Drop every view of a changed file; existing snapshots remain immutable."""
        with self._lock:
            self._documents.pop(path.resolve(), None)


def expanded_design(
    lines: list[str],
    *,
    normalized: bool = False,
    logical_ids: dict[tuple[str, str], str] | None = None,
    bound_anchors: dict[tuple[str, str], str] | None = None,
    root: Path | None = None,
    modes=None,
    reference_tables=(),
):
    return _dependency_design_layout.expanded_design(
        lines,
        normalized=normalized,
        logical_ids=logical_ids,
        bound_anchors=bound_anchors,
        root=root,
        modes=modes,
        reference_tables=reference_tables,
    )


def resource_logical_ids(lines: list[str]):
    return _dependency_design_layout.resource_logical_ids(lines)
