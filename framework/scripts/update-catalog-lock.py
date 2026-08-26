#!/usr/bin/env python3
"""Check or update the integrity lock for framework/materials/aws."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "framework" / "materials" / "aws"
METADATA = ROOT / "framework" / "materials" / "catalog.properties"
MANIFEST = ROOT / "framework" / "materials" / "catalog.sha256"
IDENTIFIER_OUTPUT = "IDENTIFIER_OUTPUT"


def catalog_files() -> list[Path]:
    return sorted(CATALOG_DIR.glob("*.properties"))


def manifest_text(files: list[Path]) -> str:
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}")
    return "\n".join(lines) + "\n"


def catalog_counts(files: list[Path]) -> tuple[int, int]:
    property_count = 0
    identifier_output_count = 0
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            _, separator, value = line.partition("=")
            if not separator or value not in {"", IDENTIFIER_OUTPUT}:
                raise ValueError(f"invalid catalog line: {path}:{number}: {line}")
            property_count += value == ""
            identifier_output_count += value == IDENTIFIER_OUTPUT
    return property_count, identifier_output_count


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
    try:
        property_count, identifier_output_count = catalog_counts(files)
    except ValueError as error:
        print(f"catalog lock: FAIL\n- {error}")
        return 1
    values = {
        "catalog.schemaVersion": "2",
        "catalog.fileCount": str(len(files)),
        "catalog.propertyCount": str(property_count),
        "catalog.identifierOutputCount": str(identifier_output_count),
    }

    if args.write:
        MANIFEST.write_text(expected_manifest, encoding="utf-8")
        METADATA.write_text(replace_metadata(metadata_lines(), values), encoding="utf-8")
        print(
            f"catalog lock updated: {len(files)} files, {property_count} properties, "
            f"{identifier_output_count} identifier outputs"
        )
        return 0

    metadata = dict(line.split("=", 1) for line in metadata_lines() if "=" in line)
    errors = []
    for key, expected in values.items():
        if metadata.get(key) != expected:
            errors.append(f"{key}: expected {expected}, got {metadata.get(key)}")
    if MANIFEST.read_text(encoding="utf-8") != expected_manifest:
        errors.append("framework/materials/catalog.sha256 does not match framework/materials/aws")
    if errors:
        print("catalog lock: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"catalog lock: PASS ({len(files)} files, {property_count} properties, "
        f"{identifier_output_count} identifier outputs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
