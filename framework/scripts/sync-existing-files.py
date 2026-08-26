#!/usr/bin/env python3
"""Copy this repository's reusable framework into a target repository."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRAMEWORK_ROOT.parent
DEFAULT_TARGET_ROOT = REPOSITORY_ROOT.parent / "viewcard-code"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy the reusable framework directory from ai-driven-infra-blueprints "
            "to a target repository."
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
    if (
        target == REPOSITORY_ROOT
        or target in REPOSITORY_ROOT.parents
        or REPOSITORY_ROOT in target.parents
    ):
        raise ValueError("Source and target must be separate, non-nested directories.")
    return target


def main() -> int:
    args = parse_args()
    try:
        target = resolve_target(args.target)
        changed: list[tuple[Path, Path, Path, bool]] = []
        unchanged = 0

        for source_file in FRAMEWORK_ROOT.rglob("*"):
            relative = source_file.relative_to(FRAMEWORK_ROOT)
            if (
                ".git" in relative.parts
                or "__pycache__" in relative.parts
                or source_file.suffix in {".pyc", ".pyo"}
                or not source_file.is_file()
            ):
                continue
            target_relative = Path("framework") / relative
            target_file = target / target_relative
            resolved_target_file = target_file.resolve(strict=False)
            if target not in resolved_target_file.parents:
                raise ValueError(f"Target path escapes the repository: {target_relative}")
            if not target_file.exists():
                changed.append((target_relative, source_file, target_file, True))
                continue
            if not target_file.is_file():
                raise ValueError(f"Target path is not a file: {target_relative}")
            if source_file.is_symlink() or target_file.is_symlink():
                raise ValueError(f"Symbolic links are not supported: {target_relative}")
            if filecmp.cmp(source_file, target_file, shallow=False):
                unchanged += 1
                continue
            changed.append((target_relative, source_file, target_file, False))

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
            "scope=framework"
        )
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
