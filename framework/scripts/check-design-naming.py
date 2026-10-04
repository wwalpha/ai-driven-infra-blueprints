#!/usr/bin/env python3
"""Read-only naming rule preflight; no model or confirmed name is required."""

import argparse
from pathlib import Path
import sys

from model_design import design_naming_errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--resource-type", required=True)
    parser.add_argument("--mode", choices=("CREATE", "IMPORT"), default="CREATE")
    parser.add_argument("--name-tag", action="store_true", help="Check a human-selected optional Name tag")
    args = parser.parse_args()
    try:
        errors = design_naming_errors(args.root, args.resource_type, args.mode, args.name_tag)
    except (OSError, ValueError) as error:
        errors = [str(error)]
    if errors:
        for error in errors:
            print(f"Design naming preflight: FAIL: {error}", file=sys.stderr)
        return 1
    print(f"Design naming preflight: PASS: {args.resource_type} ({args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
