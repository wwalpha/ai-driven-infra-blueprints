#!/usr/bin/env bash
set -euo pipefail

MODE=""

while (($# > 0)); do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "$MODE" != "local" ]]; then
  echo "--mode must be local" >&2
  exit 2
fi

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "$REPOSITORY_ROOT/scripts/validate-blueprint.py" \
  --repository-root "$REPOSITORY_ROOT"
