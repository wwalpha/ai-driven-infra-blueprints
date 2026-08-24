#!/usr/bin/env python3
"""Overwrite files that already exist at the same relative path in a target repo."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET_ROOT = SOURCE_ROOT.parent / "viewcard-code"
PROTECTED_PATHS = {
    Path("scripts/sync-existing-files.py"),
    Path("tasks/active.md"),
}
NEW_FILE_ROOTS = {"copilot", "materials", "prompts", "rules", "scripts"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy changed files from ai-driven-infra-blueprints only when the "
            "same relative file path already exists in the target repository."
        )
    )
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without copying files."
    )
    return parser.parse_args()


def resolve_target(path: Path) -> Path:
    try:
        target = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Target does not exist: {path}") from exc
    if not target.is_dir():
        raise ValueError(f"Target is not a directory: {target}")
    if target == SOURCE_ROOT or target in SOURCE_ROOT.parents or SOURCE_ROOT in target.parents:
        raise ValueError("Source and target must be separate, non-nested directories.")
    return target


def main() -> int:
    args = parse_args()
    try:
        target = resolve_target(args.target)
        changed: list[tuple[Path, Path, Path, bool]] = []
        unchanged = missing = protected = 0

        for source_file in SOURCE_ROOT.rglob("*"):
            relative = source_file.relative_to(SOURCE_ROOT)
            if (
                ".git" in relative.parts
                or "__pycache__" in relative.parts
                or source_file.suffix in {".pyc", ".pyo"}
                or not source_file.is_file()
            ):
                continue
            if relative in PROTECTED_PATHS:
                protected += 1
                continue

            target_file = target / relative
            resolved_target_file = target_file.resolve(strict=False)
            if target not in resolved_target_file.parents:
                raise ValueError(f"Target path escapes the repository: {relative}")
            if not target_file.exists():
                if relative.parts[0] in NEW_FILE_ROOTS:
                    changed.append((relative, source_file, target_file, True))
                else:
                    missing += 1
                continue
            if not target_file.is_file():
                raise ValueError(f"Target path is not a file: {relative}")
            if source_file.is_symlink() or target_file.is_symlink():
                raise ValueError(f"Symbolic links are not supported: {relative}")
            if filecmp.cmp(source_file, target_file, shallow=False):
                unchanged += 1
                continue
            changed.append((relative, source_file, target_file, False))

        copied = added = 0
        for relative, source_file, target_file, is_new in changed:
            if not args.dry_run:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target_file)
            if is_new:
                added += 1
                action = "WOULD ADD" if args.dry_run else "ADDED"
            else:
                copied += 1
                action = "WOULD COPY" if args.dry_run else "COPIED"
            print(f"{action}: {relative.as_posix()}")

        print(
            f"Summary: copied={0 if args.dry_run else copied} "
            f"added={0 if args.dry_run else added} "
            f"pending={len(changed) if args.dry_run else 0} unchanged={unchanged} "
            f"missing_in_target={missing} protected={protected}"
        )
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
