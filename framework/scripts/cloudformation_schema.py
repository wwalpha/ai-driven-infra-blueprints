#!/usr/bin/env python3
"""Check or refresh the CloudFormation provider schemas used by this blueprint."""

import argparse
from pathlib import Path

from utils.cloudformation import schema


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        schema.refresh(args.repository_root)
    errors = schema.snapshot_errors(args.repository_root)
    if errors:
        print("CloudFormation schema snapshot: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"CloudFormation schema snapshot: PASS ({len(schema.material_files(args.repository_root))} resource types)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
