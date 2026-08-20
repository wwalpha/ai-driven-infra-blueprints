#!/usr/bin/env python3
"""Check or update the integrity lock for materials/aws."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "materials" / "aws"
METADATA = ROOT / "materials" / "catalog.properties"
MANIFEST = ROOT / "materials" / "catalog.sha256"


def catalog_files() -> list[Path]:
    return sorted(CATALOG_DIR.glob("*.properties"))


def manifest_text(files: list[Path]) -> str:
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}")
    return "\n".join(lines) + "\n"


def property_count(files: list[Path]) -> int:
    return sum(len(path.read_text(encoding="utf-8").splitlines()) for path in files)


def metadata_lines() -> list[str]:
    return METADATA.read_text(encoding="utf-8").splitlines()


def replace_metadata(lines: list[str], values: dict[str, str]) -> str:
    updated = []
    seen = set()
    for line in lines:
        key, separator, _ = line.partition("=")
        if separator and key in values:
            updated.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            updated.append(line)
    missing = values.keys() - seen
    if missing:
        raise ValueError(f"catalog metadata keys missing: {', '.join(sorted(missing))}")
    return "\n".join(updated) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    files = catalog_files()
    expected_manifest = manifest_text(files)
    values = {
        "catalog.fileCount": str(len(files)),
        "catalog.propertyCount": str(property_count(files)),
    }

    if args.write:
        MANIFEST.write_text(expected_manifest, encoding="utf-8")
        METADATA.write_text(replace_metadata(metadata_lines(), values), encoding="utf-8")
        print(f"catalog lock updated: {len(files)} files, {values['catalog.propertyCount']} properties")
        return 0

    metadata = dict(line.split("=", 1) for line in metadata_lines() if "=" in line)
    errors = []
    for key, expected in values.items():
        if metadata.get(key) != expected:
            errors.append(f"{key}: expected {expected}, got {metadata.get(key)}")
    if MANIFEST.read_text(encoding="utf-8") != expected_manifest:
        errors.append("materials/catalog.sha256 does not match materials/aws")
    if errors:
        print("catalog lock: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"catalog lock: PASS ({len(files)} files, {values['catalog.propertyCount']} properties)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
