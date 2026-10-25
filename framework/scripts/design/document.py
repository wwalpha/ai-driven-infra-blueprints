"""Read-only Markdown snapshots shared within one fixed design validation phase.

Reference views retain validation_scope's selective parsing, including grouped
parents. An index must be discarded or explicitly invalidated after writes;
it never stores validation results or survives an invocation.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from threading import RLock
from types import MappingProxyType

import model.display as _model_display
import model.identity as _model_identity
import model.projection as _imports_model_projection
import model.render as _model_render
import model.sources as _imports_model_sources
import model.validation as _model_validation
import validation_scope as _dependency_validation_scope
from utils.aws_mappings import definition_root
from utils.input_cache import input_text, memoized

import design.layout as _dependency_design_layout
import design.services.ec2.security_groups as _dependency_security_group_tables
from design.layout_schema import ANCHOR


@memoized
def model_reference_tables(path, text, values, root):
    """Bind original typed rows only after the actual document matches its Model."""
    source = dict(values)
    if not any(
        item.references for item in _model_display.reference_rows(source).values()
    ):
        return ()
    model_path = (
        path.parents[4] / "model" / path.relative_to(path.parents[4] / "docs/designs")
    ).with_suffix(".properties")
    prohibited = _model_validation.codebuild_reference_errors(model_path, source)
    if prohibited:
        raise ValueError("\n".join(prohibited.values()))
    tables = []
    expected = _model_render.generate_markdown(
        path, source, root, reference_tables=tables
    )
    if text.splitlines() != expected.splitlines():
        raise ValueError("Markdown differs from Model expected display: " + str(path))
    return tuple(tables)


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

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
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
