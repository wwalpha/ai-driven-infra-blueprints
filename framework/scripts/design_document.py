"""Read-only Markdown snapshots shared within one fixed design validation phase.

Reference views retain validation_scope's selective parsing, including grouped
parents. An index must be discarded or explicitly invalidated after writes;
it never stores validation results or survives an invocation.
"""
from validation_cache import input_is_dir, input_text

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
import re
from threading import RLock

from design_layout import (ANCHOR, expanded_design, expanded_display_rows, resource_heading_lines,
                           resource_logical_ids, resource_modes)
from policy_tables import without_policy_tables
from security_group_tables import security_group_table_lines
from validation_scope import reference_lines


@dataclass(frozen=True)
class DesignView:
    """A selected set of lines; callers treat parser outputs as read-only."""

    lines: tuple[str, ...]
    root: Path | None = field(default=None, repr=False, compare=False)
    bound_anchors: dict[tuple[str, str], str] = field(default_factory=dict, repr=False, compare=False)
    modes: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    _lock: object = field(default_factory=RLock, repr=False, compare=False)

    @cached_property
    def _logical_ids(self) -> dict[tuple[str, str], str]:
        return resource_logical_ids(list(self.lines))

    @property
    def logical_ids(self) -> dict[tuple[str, str], str]:
        with self._lock:
            return self._logical_ids

    @cached_property
    def _expanded(self) -> tuple[tuple[str, ...], dict[str, dict]]:
        lines, children = expanded_design(list(self.lines), logical_ids=self.logical_ids, bound_anchors=self.bound_anchors, root=self.root, modes=self.modes)
        return tuple(lines), children

    @property
    def expanded(self) -> tuple[tuple[str, ...], dict[str, dict]]:
        with self._lock:
            return self._expanded

    @cached_property
    def _display_lines(self) -> tuple[str, ...]:
        return tuple(expanded_display_rows(security_group_table_lines(list(self.lines), self.root), self.root, modes=self.modes))

    @property
    def display_lines(self) -> tuple[str, ...]:
        with self._lock:
            return self._display_lines


@dataclass(frozen=True)
class DesignDocument:
    path: Path
    text: str
    root: Path | None = None
    _views: dict[tuple[frozenset[str] | None, bool], DesignView] = field(default_factory=dict, repr=False, compare=False)
    _parses: dict[tuple[str, ...], DesignView] = field(default_factory=dict, repr=False, compare=False)
    _lock: object = field(default_factory=RLock, repr=False, compare=False)

    @cached_property
    def lines(self) -> tuple[str, ...]:
        return tuple(self.text.splitlines())

    @cached_property
    def anchors(self) -> frozenset[str]:
        return frozenset(ANCHOR.findall(self.text))

    @cached_property
    def visible_text(self) -> str:
        return re.sub(r"<!--.*?-->", "", self.text, flags=re.DOTALL)

    @cached_property
    def projection_source(self) -> DesignView:
        # Identity metadata is checked before stripping policy tables, as in model_for.
        return self._view([line for line in self.lines if not line.startswith(
            ("<!-- resource-mode:", "<!-- resource-entry:", "<!-- cfn-logical-id:"))])

    def _view(self, lines: list[str] | tuple[str, ...]) -> DesignView:
        lines = tuple(lines)
        with self._lock:
            if lines not in self._parses:
                from model_references import bound_resource_anchors
                self._parses[lines] = DesignView(lines, self.root, bound_resource_anchors(self.path)
                                               if any(line.startswith('### ') for line in lines) else {}, self.modes)
            return self._parses[lines]

    @cached_property
    def modes(self):
        model_root = self.path.parents[4] if len(self.path.parents) >= 5 and self.path.parents[2].name == 'designs' and self.path.parents[3].name == 'docs' else None
        values = None
        if model_root is not None:
            from model_templates import load_expansion, source_paths
            model = (model_root / 'model' / self.path.relative_to(model_root / 'docs/designs')).with_suffix('.properties')
            if source_paths(model)[2].is_dir():
                values = load_expansion(model).values
        return resource_modes(self.lines, values)

    @property
    def raw(self) -> DesignView:
        return self._view(self.lines)

    def view(self, fragments: frozenset[str] | None = None, *, projection: bool = False) -> DesignView:
        # Serialize lazy construction only; existing validation workers remain unchanged.
        with self._lock:
            key = fragments, projection
            if key not in self._views:
                if fragments is not None:
                    lines = reference_lines(self.path, fragments, lines=list(self.headings.lines))
                elif projection:
                    lines = without_policy_tables(list(self.projection_source.lines))
                else:
                    lines = resource_heading_lines(list(self.lines))
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

    def get(self, path: Path) -> DesignDocument:
        path = path.resolve()
        with self._lock:
            if path not in self._documents:
                document = DesignDocument(path, input_text(path, encoding="utf-8"), self.root or next(
                    (parent for parent in path.parents if input_is_dir(parent / "framework/mappings/aws")), None))
                # Construct these cheap text views once before sharing across workers.
                document.lines, document.anchors, document.visible_text
                self._documents[path] = document
            return self._documents[path]

    def invalidate(self, path: Path) -> None:
        """Drop every view of a changed file; existing snapshots remain immutable."""
        with self._lock:
            self._documents.pop(path.resolve(), None)
