#!/usr/bin/env python3
"""Copy reusable framework, skills, and root entrypoints into a target repository."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
import tempfile
from itertools import chain
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRAMEWORK_ROOT.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy framework, .agents, AGENTS.md, and README.md from ai-driven-infra-blueprints "
            "to a target repository."
        )
    )
    parser.add_argument("--target", type=Path, required=True)
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

        for source_file in chain(
            FRAMEWORK_ROOT.rglob("*"), (REPOSITORY_ROOT / ".agents").rglob("*"),
            (REPOSITORY_ROOT / name for name in ("AGENTS.md", "README.md")),
        ):
            relative = source_file.relative_to(REPOSITORY_ROOT)
            if ".git" in relative.parts or "__pycache__" in relative.parts or source_file.suffix in {".pyc", ".pyo"}:
                continue
            if source_file.is_symlink():
                raise ValueError(f"Symbolic links are not supported: {relative}")
            if not source_file.is_file():
                continue
            target_relative = relative
            target_file = target / target_relative
            resolved_target_file = target_file.resolve(strict=False)
            if target not in resolved_target_file.parents:
                raise ValueError(f"Target path escapes the repository: {target_relative}")
            if target_file.is_symlink():
                raise ValueError(f"Symbolic links are not supported: {target_relative}")
            if not target_file.exists():
                changed.append((target_relative, source_file, target_file, True))
                continue
            if not target_file.is_file():
                raise ValueError(f"Target path is not a file: {target_relative}")
            if filecmp.cmp(source_file, target_file, shallow=False):
                unchanged += 1
                continue
            changed.append((target_relative, source_file, target_file, False))

        if not args.dry_run:
            with tempfile.TemporaryDirectory() as directory:
                backup_root = Path(directory)
                backups = {}
                for relative, _, target_file, is_new in changed:
                    backup = backup_root / relative
                    if not is_new:
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target_file, backup)
                    backups[target_file] = None if is_new else backup
                written = []
                created_dirs = set()
                try:
                    for _, source_file, target_file, _ in changed:
                        parent = target_file.parent
                        while parent != target and not parent.exists():
                            created_dirs.add(parent)
                            parent = parent.parent
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        written.append(target_file)
                        shutil.copy2(source_file, target_file)
                except OSError as error:
                    rollback_errors = []
                    for target_file in reversed(written):
                        try:
                            backup = backups[target_file]
                            if backup is None:
                                target_file.unlink(missing_ok=True)
                            else:
                                shutil.copy2(backup, target_file)
                        except OSError as rollback_error:
                            rollback_errors.append(f"{target_file}: {rollback_error}")
                    for parent in sorted(created_dirs, key=lambda path: len(path.parts), reverse=True):
                        try:
                            parent.rmdir()
                        except OSError:
                            pass
                    if rollback_errors:
                        raise OSError(f"{error}; rollback failed: {'; '.join(rollback_errors)}") from error
                    raise

        copied = added = 0
        for relative, _, _, is_new in changed:
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
            "scope=framework,.agents,AGENTS.md,README.md "
            "excluded=project.json,docs,infra,model,tasks,tests"
        )
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
