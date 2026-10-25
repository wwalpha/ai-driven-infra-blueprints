"""Mapping Compare checks with SDK-shape fixtures and forbidden network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import socket
from unittest.mock import patch

from aws_mapping import Registry
from aws_mapping_compare import comparison
from aws_mapping_compare import value as mapped_value
from support.validator import load
from utils.input_cache import input_scope

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

checks = __import__("support.check_model_aws_fixtures", fromlist=["m"])

m = checks.m

ROOT = Path(__file__).resolve().parents[4]


def outcome(function):
    try:
        return ("value", function())
    except (m.Unresolved, ValueError, KeyError, TypeError) as error:
        return ("error", type(error).__name__, str(error))


__all__ = [
    "Path",
    "ROOT",
    "Registry",
    "checks",
    "comparison",
    "input_scope",
    "load",
    "m",
    "mapped_value",
    "outcome",
    "patch",
    "socket",
    "sys",
]
