"""Read-only Markdown snapshots shared within one fixed design validation phase.

Reference views retain validation_scope's selective parsing, including grouped
parents. An index must be discarded or explicitly invalidated after writes;
it never stores validation results or survives an invocation.
"""

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from functools import cached_property
from pathlib import Path
from threading import RLock
from types import MappingProxyType

import model.display as _model_display
import model.files as _model_files
import model.format as _model_format
import model.identity as _model_identity
import model.projection as _imports_model_projection
import model.render as _model_render
import model.sources as _imports_model_sources
import model.validation as _model_validation
import validation_scope as _dependency_validation_scope
from model.core import ReferenceResolutionError
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
    normalized = text.splitlines()
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
        markers = [_array_display.SOURCE.match(row[3]) for row in (saved, wanted)]
        if all(markers):
            try:
                before, after = [json.loads(marker[1]) for marker in markers]
            except ValueError:
                continue
            if (
                isinstance(before, list)
                and isinstance(after, list)
                and len(before) == len(after) == 3
                and before[0] == after[0]
                and before[2] == after[2]
                and before[1] == saved[2]
                and after[1] == wanted[2]
            ):
                normalized[number] = normalized[number].replace(
                    markers[0][0], markers[1][0], 1
                )
    other = normalized != expected.splitlines()
    if other:
        wanted = expected.splitlines()
        identities = _dependency_design_layout.resource_logical_ids(wanted)
        counts = Counter()
        for tag, start, end, first, last in SequenceMatcher(
            a=normalized, b=wanted, autojunk=False
        ).get_opcodes():
            if tag == "equal":
                continue
            # Adjacent changed lines are not evidence of a shared root cause.
            for offset in range(max(end - start, last - first)):
                anchor = next(
                    (
                        match[1]
                        for line in reversed(wanted[: first + offset])
                        if (match := ANCHOR.fullmatch(line)) and match[1] in identities
                    ),
                    "",
                )
                saved = (
                    text.splitlines()[start + offset] if start + offset < end else ""
                )
                display = wanted[first + offset] if first + offset < last else ""
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


@memoized
def model_reference_tables(path, text, values, root):
    """Bind original typed rows only after the actual document matches its Model."""
    source = dict(values)
    if not source:
        return ()
    model_path = (
        path.parents[4] / "model" / path.relative_to(path.parents[4] / "docs/designs")
    ).with_suffix(".properties")
    findings = Findings(path.parents[4])
    prohibited = _model_validation.codebuild_reference_errors(
        model_path, source, findings=findings
    )
    if prohibited:
        raise FindingsError(findings)
    if not any(
        item.references for item in _model_display.reference_rows(source).values()
    ):
        return ()
    if path.stem == "codebuild":
        try:
            _dependency_design_layout.expanded_display_rows(
                text.splitlines(),
                root,
                modes=_dependency_design_layout.resource_modes(
                    text.splitlines(), source
                ),
            )
        except ReferenceResolutionError:
            pass  # Only a Model-matched table may validate unavailable typed values below.
    tables = []
    expected = _model_render.generate_markdown(
        path, source, root, reference_tables=tables
    )
    if text.splitlines() != expected.splitlines():
        require_saved_identity(text, expected)
        raise DisplayMismatchError(path, text, expected)
    tables = [
        _security_group_reference_table(table, expected, root)
        if table.resources[0].kind == "EC2.SecurityGroup"
        else table
        for table in tables
    ]
    return tuple(tables)


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
        for index, line in enumerate(block):
            if line.startswith(("# ", "## ")):
                block = block[:index]
                break
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
    scope = _imports_model_sources.scope_for(
        (
            path.parents[4]
            / "model"
            / path.relative_to(path.parents[4] / "docs/designs")
        ).with_suffix(".properties")
    )
    parents = {}
    for identity, resource in resources.items():
        if resource["resourceType"] not in GROUPED:
            continue
        address = _model_identity.parse_reference(
            resource.get("parentReference"), scope
        )
        if address[:3] != (scope.environment, scope.target, scope.service):
            raise ValueError("grouped parent is outside this Model: " + identity)
        if address[3] not in anchors:
            raise ValueError("grouped parent ownership unavailable: " + identity)
        parents[identity] = anchors[address[3]]
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


def model_resource_reference_tables(path, text, values, root):
    """Recover renderer-proven Resource bodies; suffix integrity is document-wide."""
    source = dict(values)
    resources, groups = model_resource_groups(path, source)
    lines = text.splitlines()
    blocks = resource_blocks(_dependency_design_layout.resource_heading_lines(lines))
    saved = {}
    for block in blocks:
        identities = _dependency_design_layout.resource_logical_ids(block)
        if len(identities) != 1:
            raise ValueError("Resource/Row display ownership unavailable: " + str(path))
        anchor, logical_id = next(iter(identities.items()))
        if anchor in saved:
            raise ValueError("duplicate saved Resource anchor: " + anchor)
        saved[anchor] = (logical_id, block)
    owned = {key: _model_format.owner(key, source) for key in source}
    results = []
    for parent, members in groups.items():
        resource = resources[parent]
        anchor = _model_identity.display_anchor(resource)
        selected = {
            key: value
            for key, value in source.items()
            if not key.startswith("desired.note.")
            and (owned[key][0] != "resource" or owned[key][1] in members)
        }
        try:
            model_path = (
                path.parents[4]
                / "model"
                / path.relative_to(path.parents[4] / "docs/designs")
            ).with_suffix(".properties")
            findings = Findings(path.parents[4])
            prohibited = _model_validation.codebuild_reference_errors(
                model_path, selected, findings=findings
            )
            if prohibited:
                raise FindingsError(findings)
            tables = []
            expected = _model_render.generate_markdown(
                path, selected, root, reference_tables=tables, reference_values=source
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
            matches_body = actual == wanted
            if anchor == next(reversed(saved)) and actual[
                len(wanted) : len(wanted) + 1
            ] == [""]:
                # Prove the entire rendered body; leave suffix ownership to document validation.
                matches_body = actual[: len(wanted)] == wanted
            if not matches_body:
                saved_text, expected_text = (
                    "\n".join(actual),
                    "\n".join(wanted),
                )
                require_saved_identity(saved_text, expected_text)
                raise DisplayMismatchError(path, saved_text, expected_text)
            normalized = []
            for table in tables:
                if table.resources[0].kind == "EC2.SecurityGroup":
                    table = _security_group_reference_table(table, expected, root)
                normalized.append(table)
            results.append((anchor, tuple(normalized), None))
        except (OSError, ValueError) as error:
            results.append((anchor, None, error))
    if set(saved) != {_model_identity.display_anchor(resources[rid]) for rid in groups}:
        raise ValueError("Markdown Resource groups differ from Model: " + str(path))
    return results


def _security_group_reference_table(table, document, root):
    """Match the parser's existing horizontal-rule normalization, including sources."""
    start = document.index(f'<a id="{table.anchor}"></a>')
    table_start = document.index("\n".join(table.expected), start)
    table_end = table_start + len("\n".join(table.expected))
    normalized = []
    for rows in (table.expected, table.baseline, table.semantic):
        candidate = document[:table_start] + "\n".join(rows) + document[table_end:]
        lines = _dependency_security_group_tables.security_group_table_lines(
            candidate.splitlines(), root
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
        return MappingProxyType(dict(values)) if values is not None else None

    @cached_property
    def modes(self):
        return _dependency_design_layout.resource_modes(self.lines, self.model_values)

    @cached_property
    def reference_tables(self):
        if not self.check_display:
            return ()
        return model_reference_tables(
            self.path,
            self.text,
            tuple((self.model_values or {}).items()),
            self.root or definition_root(self.path.parent),
        )

    @property
    def raw(self) -> DesignView:
        return self._view(self.lines)

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
                        list(self.lines)
                    )
                self._views[key] = self._view(lines)
            return self._views[key]

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
                    source=MappingProxyType(dict(values))
                    if values is not None
                    else None,
                )
                # Construct these cheap text views once before sharing across workers.
                _ = document.lines, document.anchors, document.visible_text
                self._documents[path] = document
            document = self._documents[path]
            if values is not None and dict(document.model_values or {}) != dict(values):
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
