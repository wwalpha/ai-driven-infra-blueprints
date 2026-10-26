"""Prove diagnostic ownership from explicit scope and canonical service sources."""

import re
from pathlib import Path

from validation.diagnostics import service_scope


def resolve(root, diagnostic, scope):
    root = root.resolve()
    explicit = diagnostic.service
    if explicit is not None and (
        not isinstance(explicit, tuple)
        or len(explicit) != 3
        or any(
            not isinstance(part, str)
            or not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", part)
            for part in explicit
        )
    ):
        return dict(status="unresolved", owner=None, evidence="invalid explicit owner")
    source = diagnostic.source_path
    path_owner = service_scope(root, source)
    if source is not None:
        path = Path(source)
        path = root / path if not path.is_absolute() else path
        if (
            (path_owner is not None and not path.is_relative_to(root.resolve()))
            or ".." in path.parts
            or any(
                part.is_symlink()
                for part in (path, *path.parents)
                if part.is_relative_to(root)
            )
        ):
            return dict(
                status="unresolved", owner=None, evidence="noncanonical source path"
            )
    if explicit is not None and path_owner is not None and explicit != path_owner:
        return dict(
            status="unresolved",
            owner=None,
            evidence="explicit owner conflicts with source path",
        )
    owners = set(diagnostic.affected_services)
    if len(owners) > 1 and explicit is None and path_owner is None:
        return dict(
            status="unresolved", owner=None, evidence="multiple affected services"
        )
    owner = explicit or path_owner
    if owner is None:
        return dict(
            status="unresolved",
            owner=None,
            evidence="no single service source or explicit owner",
        )
    return dict(
        status="assigned" if owner in scope else "outside",
        owner=owner,
        evidence="explicit owner and source path"
        if explicit and path_owner
        else "explicit owner"
        if explicit
        else "service source path",
    )
